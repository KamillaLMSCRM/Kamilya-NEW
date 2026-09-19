import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason


def _lesson_and_facts():
    facts = {
        "oak": SourceFact(
            "oak", "Коллекция Альфа", "материал", "Дуб",
            "doc_id=collections;source_revision=r1;section=alpha",
        ),
        "opening": SourceFact(
            "opening", "Коллекция Альфа", "открывание", "Push-to-open",
            "doc_id=collections;source_revision=r1;section=alpha",
        ),
    }
    return LessonDraft(
        "lesson-alpha", "Коллекции", "Альфа", "Подбирать материалы",
        "", tuple(facts), (), 1,
    ), facts


class _CompletionClient:
    def __init__(self, *, truncate_batches: bool = True):
        self.requests = []
        self.truncate_batches = truncate_batches

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        task = request["task"]
        if task == "assessment_generate":
            axes = request["axes"]
            # Deliberately return only one axis from the batch.  Completion must
            # request only the exact missing axis, retaining server truth.
            if self.truncate_batches and len(axes) > 1:
                axes = axes[:1]
            payload = {"questions": [
                {
                    "axis_id": axis["axis_id"],
                    "prompt": f"Каково значение {axis['attribute']}?",
                    "distractors": ["Другой вариант", "Неподходящий вариант"],
                }
                for axis in axes
            ]}
        elif task == "assessment_review":
            payload = {"reviews": [
                {
                    "question_id": question["question_id"],
                    "question_supported": True,
                    "educational": True,
                    "explanation_supported": True,
                    "options_distinct": True,
                    "options": [
                        {
                            "index": index,
                            "answers_question": True,
                            "correct": index == 0,
                            "plausible_error": index > 0,
                            "contradicted_by_source": index > 0,
                            "same_practical_task": True,
                        }
                        for index in range(len(question["options"]))
                    ],
                }
                for question in request["questions"]
            ]}
        elif task == "assessment_constraints":
            facts_by_id = {fact["fact_id"]: fact for fact in request["facts"]}
            payload = {
                "rules": [
                    {
                        "fact_id": fact_id,
                        "quote": facts_by_id[fact_id]["value"],
                        "kind": "attribute",
                    }
                    for fact_id in {
                        fact_id
                        for question in request["questions"]
                        for fact_id in question["evidence_fact_ids"]
                    }
                ],
                "reviews": [
                    {
                        "question_id": question["question_id"],
                        "reason": "fixture",
                        "distinct_errors": True,
                        "options": [
                            {
                                "index": index,
                                "relation": "entailed" if index == 0 else "contradicted",
                                "invented_constraint": False,
                                "realistic_error": True,
                            }
                            for index in range(len(question["options"]))
                        ],
                    }
                    for question in request["questions"]
                ],
            }
        else:
            raise AssertionError(f"unexpected task: {task}")
        return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1)


@pytest.mark.asyncio
async def test_completion_audits_each_requested_axis_and_supplements_only_missing_ids():
    lesson, facts = _lesson_and_facts()
    client = _CompletionClient()

    result = await generate_block_assessment([lesson], facts, client)

    outcomes = result.audit["axis_outcomes"]
    assert {outcome["axis_id"] for outcome in outcomes} == {
        request_axis["axis_id"]
        for request in client.requests
        if request["task"] == "assessment_generate" and len(request["axes"]) == 2
        for request_axis in request["axes"]
    }
    assert {outcome["state"] for outcome in outcomes} == {"retained"}
    assert result.audit["retained_count"] == 2
    assert result.audit["omitted_count"] == 0
    assert result.audit["uncovered_count"] == 0
    assert result.audit["terminal_status"] == "completed"
    assert all(outcome["attempt_counts"]["replacement"] <= 1 for outcome in outcomes)

    targeted = [
        request for request in client.requests
        if request["task"] == "assessment_generate" and len(request["axes"]) == 1
    ]
    assert len(targeted) == 1
    supplemented_axis = targeted[0]["axes"][0]
    initial_axes = next(
        request["axes"] for request in client.requests
        if request["task"] == "assessment_generate" and len(request["axes"]) == 2
    )
    assert supplemented_axis["axis_id"] == initial_axes[1]["axis_id"]
    assert {(question.fact_id, question.correct_answer, question.evidence_fact_ids)
            for question in result.questions} == {
        ("oak", "Дуб", ("oak",)),
        ("opening", "Push-to-open", ("opening",)),
    }


@pytest.mark.asyncio
async def test_semantic_rejection_is_omitted_after_one_model_repair_without_padding():
    lesson, facts = _lesson_and_facts()

    class _RejectingClient(_CompletionClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_review":
                self.requests.append(request)
                payload = {"reviews": [
                    {
                        "question_id": question["question_id"],
                        "question_supported": True,
                        "educational": True,
                        "explanation_supported": True,
                        "options_distinct": True,
                        "options": [
                            {
                                "index": index,
                                "answers_question": index == 0,
                                "correct": index == 0,
                                "plausible_error": index > 0,
                                "contradicted_by_source": index > 0,
                                "same_practical_task": True,
                            }
                            for index in range(len(question["options"]))
                        ],
                    }
                    for question in request["questions"]
                ]}
                return SimpleNamespace(
                    value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1,
                )
            if request["task"] == "assessment_repair":
                self.requests.append(request)
                return SimpleNamespace(
                    value=parser(json.dumps({"questions": []})), attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = _RejectingClient()
    result = await generate_block_assessment([lesson], facts, client)

    assert result.questions == ()
    assert {outcome["state"] for outcome in result.audit["axis_outcomes"]} == {"omitted"}
    assert result.audit["omitted_count"] == 2
    assert result.audit["terminal_status"] == "completed_with_warnings"
    assert result.audit["coverage"]["requires_review"] is False
    assert {block["outcome"] for block in result.audit["block_outcomes"]} == {
        "quality_omitted",
    }
    assert all(outcome["reason"].startswith("option_")
               for outcome in result.audit["axis_outcomes"])
    assert all(outcome["attempt_counts"]["model_repair"] == 1
               for outcome in result.audit["axis_outcomes"])
    assert [request["task"] for request in client.requests].count("assessment_repair") == 2


@pytest.mark.asyncio
async def test_provider_failure_stays_uncovered_and_requires_review():
    lesson, facts = _lesson_and_facts()

    class _UnavailableReviewer(_CompletionClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_review":
                self.requests.append(request)
                raise AllProvidersFailedError(
                    "fixture", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE],
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = _UnavailableReviewer()
    result = await generate_block_assessment([lesson], facts, client)

    assert result.questions == ()
    assert {outcome["state"] for outcome in result.audit["axis_outcomes"]} == {"uncovered"}
    assert {outcome["reason"] for outcome in result.audit["axis_outcomes"]} == {
        "assessment_provider_or_validation_unavailable",
    }
    assert result.audit["omitted_count"] == 0
    assert result.audit["uncovered_count"] == 2
    assert result.audit["terminal_status"] == "review_required"
    assert all(outcome["failure_kind"] == "provider_or_contract"
               for outcome in result.audit["axis_outcomes"])
    assert not any(request["task"] == "assessment_repair" for request in client.requests)


@pytest.mark.asyncio
async def test_single_constraint_failure_is_omitted_when_neighbor_covers_topic():
    lesson, facts = _lesson_and_facts()

    class _OneConstraintUnavailable(_CompletionClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_constraints":
                if len(request["questions"]) > 1:
                    self.requests.append(request)
                    raise AllProvidersFailedError(
                        "fixture", [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                    )
                if "opening" in request["questions"][0]["evidence_fact_ids"]:
                    self.requests.append(request)
                    raise AllProvidersFailedError(
                        "fixture", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE],
                    )
            if request["task"] == "assessment_repair":
                self.requests.append(request)
                return SimpleNamespace(
                    value=parser(json.dumps({"questions": []})), attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    result = await generate_block_assessment(
        [lesson], facts, _OneConstraintUnavailable(),
    )

    assert {question.fact_id for question in result.questions} == {"oak"}
    outcomes = {
        outcome["primary_fact_id"]: outcome
        for outcome in result.audit["axis_outcomes"]
    }
    assert outcomes["oak"]["state"] == "retained"
    assert outcomes["opening"]["state"] == "omitted"
    assert outcomes["opening"]["reason"] == "provider_review_unavailable_redundant_axis"
    assert outcomes["opening"]["failure_kind"] == "provider_or_contract"
    assert result.audit["uncovered_count"] == 0
    assert result.audit["omitted_count"] == 1
    assert result.audit["terminal_status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_axis_gets_at_most_one_targeted_replacement_without_padding():
    lesson, facts = _lesson_and_facts()

    class _PartialFallbackClient(_CompletionClient):
        def __init__(self):
            super().__init__()
            self.singleton_calls = 0

        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_generate" and len(request["axes"]) > 1:
                self.requests.append(request)
                raise AllProvidersFailedError(
                    "fixture", [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                )
            if request["task"] == "assessment_generate":
                self.requests.append(request)
                self.singleton_calls += 1
                axis = request["axes"][0]
                payload = {"questions": [] if self.singleton_calls > 1 else [{
                    "axis_id": axis["axis_id"],
                    "prompt": f"Каково значение {axis['attribute']}?",
                    "distractors": ["Другой вариант", "Неподходящий вариант"],
                }]}
                return SimpleNamespace(
                    value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = _PartialFallbackClient()
    result = await generate_block_assessment([lesson], facts, client)

    singleton_axis_ids = [
        request["axes"][0]["axis_id"]
        for request in client.requests
        if request["task"] == "assessment_generate" and len(request["axes"]) == 1
    ]
    assert len(singleton_axis_ids) == len(set(singleton_axis_ids))
    omitted = next(
        outcome for outcome in result.audit["axis_outcomes"]
        if outcome["state"] == "omitted"
    )
    assert omitted["reason"] == "no_admissible_candidate"
    assert omitted["attempt_counts"]["replacement"] == 1
    assert result.audit["terminal_status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_empty_authorship_is_an_omission_not_an_unassessable_source_axis():
    lesson, facts = _lesson_and_facts()

    class _EmptyAuthor(_CompletionClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_generate":
                self.requests.append(request)
                return SimpleNamespace(
                    value=parser(json.dumps({"questions": []})), attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    result = await generate_block_assessment([lesson], facts, _EmptyAuthor())

    assert result.questions == ()
    assert {outcome["state"] for outcome in result.audit["axis_outcomes"]} == {"omitted"}
    assert {outcome["reason"] for outcome in result.audit["axis_outcomes"]} == {
        "no_admissible_candidate",
    }
    assert result.audit["unassessable_count"] == 0
    assert result.audit["terminal_status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_skipped_source_fact_is_reported_as_unassessable() -> None:
    lesson, facts = _lesson_and_facts()
    facts["uncertain"] = SourceFact(
        "uncertain", "Коллекция Альфа", "размер", "[UNREADABLE_SIZE]",
        "doc_id=collections;source_revision=r1;section=alpha",
        confidence=0.4,
        uncertainty="ocr_unreadable",
    )
    lesson = LessonDraft(
        lesson.lesson_id,
        lesson.module_title,
        lesson.title,
        lesson.objective,
        lesson.content,
        (*lesson.fact_ids, "uncertain"),
        lesson.supporting_fact_ids,
        lesson.duration_minutes,
    )

    result = await generate_block_assessment([lesson], facts, _CompletionClient())

    unassessable = [
        outcome for outcome in result.audit["axis_outcomes"]
        if outcome["state"] == "unassessable"
    ]
    assert len(unassessable) == 1
    assert unassessable[0]["primary_fact_id"] == "uncertain"
    assert unassessable[0]["reason"] == "no_stable_assessment_axis"
    assert result.audit["unassessable_count"] == 1
    assert result.audit["terminal_status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_density_cap_classifies_every_assessable_axis_without_padding() -> None:
    fact_names = ("material", "opening", "rooms", "warranty")
    facts = {
        name: SourceFact(
            name,
            "Коллекция Альфа",
            name,
            value,
            "doc_id=collections;source_revision=r1;section=alpha",
        )
        for name, value in zip(
            fact_names,
            ("Дуб", "Push-to-open", "Гостиная", "24 месяца"),
            strict=True,
        )
    }
    lesson = LessonDraft(
        "lesson-four-axes", "Коллекции", "Альфа", "Различать характеристики",
        "", fact_names, (), 2,
    )

    result = await generate_block_assessment([lesson], facts, _CompletionClient())

    outcomes = result.audit["axis_outcomes"]
    assert len(outcomes) == 4
    assert result.audit["derived_axes"] == 4
    assert result.audit["requested_axes"] == 3
    assert sum(outcome["state"] == "retained" for outcome in outcomes) == 3
    omitted = [outcome for outcome in outcomes if outcome["state"] == "omitted"]
    assert len(omitted) == 1
    assert omitted[0]["reason"] == "assessment_density_limit"
    assert result.audit["contract_coverage"] == {
        "policy": "assessment-contract-v1",
        "assessable_contract_count": 4,
        "classified_contract_count": 4,
        "retained_contract_count": 3,
        "omitted_contract_count": 1,
        "unassessable_source_count": 0,
        "uncovered_contract_count": 0,
        "audit_incomplete": False,
    }
    assert result.audit["terminal_status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_multi_scope_spreadsheet_lesson_round_robins_three_axes_without_padding() -> None:
    fact_specs = (
        ("alpha_material", "Коллекция Альфа", "материал", "Дуб", "alpha"),
        ("alpha_opening", "Коллекция Альфа", "открывание", "Push-to-open", "alpha"),
        ("beta_rooms", "Коллекция Бета", "помещения", "Гостиная", "beta"),
        ("beta_warranty", "Коллекция Бета", "гарантия", "24 месяца", "beta"),
    )
    facts = {
        fact_id: SourceFact(
            fact_id,
            subject,
            attribute,
            value,
            f"doc_id=collections;source_revision=r1;section={section}",
        )
        for fact_id, subject, attribute, value, section in fact_specs
    }
    lesson = LessonDraft(
        "lesson-multi-scope",
        "Коллекции",
        "Сравнение коллекций",
        "Различать характеристики коллекций",
        "",
        tuple(facts),
        (),
        2,
    )
    client = _CompletionClient(truncate_batches=False)

    result = await generate_block_assessment([lesson], facts, client)

    author_requests = [
        request for request in client.requests if request["task"] == "assessment_generate"
    ]
    assert [
        [axis["source_claim"] for axis in request["axes"]]
        for request in author_requests
    ] == [["Дуб", "Push-to-open"], ["Гостиная"]]
    assert {question.fact_id for question in result.questions} == {
        "alpha_material", "alpha_opening", "beta_rooms",
    }
    assert len(result.questions) == 3
    omitted = {
        outcome["primary_fact_id"]: outcome
        for outcome in result.audit["axis_outcomes"]
        if outcome["state"] == "omitted"
    }
    assert omitted["beta_warranty"]["reason"] == "assessment_density_limit"
    assert result.audit["coverage"]["requires_review"] is False
    assert result.audit["terminal_status"] == "completed_with_warnings"


@pytest.mark.asyncio
async def test_incomplete_answer_is_omitted_without_model_repair() -> None:
    fact = SourceFact(
        "rounding", "Ставка", "правило округления",
        "Число округляется до десятых долей следующим образом",
        "doc_id=rules;source_revision=r1;section=rate",
    )
    lesson = LessonDraft(
        "lesson-rounding", "Правила", "Расчёт ставки", "Применять округление",
        "", (fact.fact_id,), (), 1,
    )
    client = _CompletionClient()

    result = await generate_block_assessment(
        [lesson], {fact.fact_id: fact}, client,
    )

    assert result.questions == ()
    assert not any(
        request["task"] == "assessment_repair" for request in client.requests
    )
    assert result.audit["axis_outcomes"][0]["state"] == "omitted"
    assert result.audit["axis_outcomes"][0]["reason"] == "incomplete_correct_answer"
    assert result.audit["uncovered_count"] == 0
    assert result.audit["terminal_status"] == "completed_with_warnings"
