"""Deterministic replay for bounded operational answer-domain repair."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine import semantic_assessment
from app.modules.ai.evidence_engine.assessment_axes import materialize_assessment
from app.modules.ai.evidence_engine.models import (
    AssessmentAxis,
    AuthoredAssessment,
    LessonDraft,
    SourceFact,
)
from app.modules.ai.evidence_engine.quality import (
    answer_containment_option_indices,
    answer_length_repair_targets,
)
from app.modules.ai.evidence_engine.semantic_assessment import (
    _axis_author_payload,
    generate_block_assessment,
)

NOTICE_KEY = "сменный эксперт-оценщик обязан сразу поставить в известность АУП РД."
SIGNING_KEY = "подписывает залоговый билет с отметкой о согласовании"
SIGNING_DRIFT = (
    "Составляет акт несоответствия стандартам по выдаче микрокредитов.",
    "Берет с эксперта-оценщика объяснительную и обязательство.",
)
SIGNING_AMBIGUOUS = (
    "Подписывает залоговый билет с отметкой.",
    "Подписывает залоговый билет без уточнения отметки.",
)
SIGNING_REPAIR = (
    "Отказывается подписывать залоговый билет с отметкой о согласовании",
    "подписывает залоговый билет без отметки о согласовании",
)
NOTICE_DISTRACTORS = (
    "Отдел аудита — после составления акта.",
    "Регионального руководителя — на следующий день.",
)


def _axis(
    kind: str,
    *,
    block_id: str = "block",
    lesson_id: str | None = None,
) -> AssessmentAxis:
    if kind == "notice":
        axis_id = "axis-notice"
        default_lesson_id = "lesson-notice"
        fact_id = "fact-notice"
        subject = "Уведомление о сомнениях"
        prompt = (
            "Кого и когда сменный эксперт-оценщик обязан поставить в известность "
            "при условии «Если имущество вызывает сомнения»?"
        )
        key = NOTICE_KEY
    else:
        axis_id = "axis-signing"
        default_lesson_id = "lesson-signing"
        fact_id = "fact-signing"
        subject = "Подписание согласования"
        prompt = (
            "Какое действие в отношении «залоговый билет с отметкой о согласовании» "
            "выполняет «согласовавшее лицо» при условии "
            "«Если уполномоченное лицо согласовывает операцию»?"
        )
        key = SIGNING_KEY
    return AssessmentAxis(
        axis_id=axis_id,
        lesson_id=lesson_id or default_lesson_id,
        semantic_block_id=block_id,
        primary_fact_id=fact_id,
        evidence_fact_ids=(fact_id,),
        subject=subject,
        attribute="порядок действия",
        required_prompt=prompt,
        correct_value=key,
        normalized_correct_value=key.casefold(),
        eligible_distractor_fact_ids=(),
        axis_kind="rule_value",
        source_context="Синтетическая категория",
    )


def _fixture(*, combined: bool = False) -> tuple[list[LessonDraft], dict[str, SourceFact]]:
    facts = {
        "fact-notice": SourceFact(
            "fact-notice",
            "Операционные правила",
            "порядок действия",
            NOTICE_KEY,
            "doc_id=synthetic;section=operational",
        ),
        "fact-signing": SourceFact(
            "fact-signing",
            "Операционные правила",
            "порядок действия",
            SIGNING_KEY,
            "doc_id=synthetic;section=operational",
        ),
    }
    separate_lessons = [
        LessonDraft(
            "lesson-notice",
            "Синтетические правила",
            "Уведомление",
            "Выбрать адресата и срок",
            NOTICE_KEY,
            ("fact-notice",),
            (),
            1,
        ),
        LessonDraft(
            "lesson-signing",
            "Синтетические правила",
            "Подписание",
            "Выбрать действие с документом",
            SIGNING_KEY,
            ("fact-signing",),
            (),
            1,
        ),
    ]
    if not combined:
        return separate_lessons, facts
    return [
        LessonDraft(
            "lesson-operational",
            "Синтетические правила",
            "Операционные действия",
            "Выбрать адресата, срок и действие с документом",
            f"{NOTICE_KEY}\n{SIGNING_KEY}",
            ("fact-notice", "fact-signing"),
            (),
            1,
        ),
    ], facts


def _request_key(request: dict) -> str:
    if request["task"] in {"assessment_generate", "assessment_repair"}:
        return request["axes"][0]["source_claim"]
    return request["questions"][0]["options"][0]


def _request_domain(request: dict) -> dict | None:
    if request["task"] in {"assessment_generate", "assessment_repair"}:
        return request["axes"][0]["answer_domain"]
    return request["questions"][0]["answer_domain"]


class ReplayClient:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.requests: list[dict] = []
        self.offered: list[tuple[str, str, tuple[str, ...]]] = []

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        task = request["task"]

        if task in {"assessment_generate", "assessment_repair"}:
            questions = []
            for axis in request["axes"]:
                if axis["source_claim"] == NOTICE_KEY:
                    assert task == "assessment_generate"
                    distractors = NOTICE_DISTRACTORS
                elif task == "assessment_repair":
                    distractors = SIGNING_REPAIR
                elif self.mode == "local_recovery" and len(request["axes"]) > 1:
                    distractors = SIGNING_DRIFT
                elif self.mode == "local_recovery":
                    distractors = SIGNING_REPAIR
                else:
                    distractors = SIGNING_AMBIGUOUS
                self.offered.append((task, axis["axis_id"], tuple(distractors)))
                questions.append({
                    "axis_id": axis["axis_id"],
                    "prompt": axis["required_prompt"],
                    "distractors": list(distractors),
                })
            payload = {
                "questions": questions,
            }
        elif task == "assessment_review":
            rows = []
            for question in request["questions"]:
                ambiguous = any(option in SIGNING_AMBIGUOUS for option in question["options"])
                rows.append({
                    "question_id": question["question_id"],
                    "question_supported": True,
                    "educational": True,
                    "explanation_supported": True,
                    "options_distinct": True,
                    "options": [{
                        "index": index,
                        "answers_question": True,
                        "correct": index == 0,
                        "plausible_error": index > 0 and not ambiguous,
                        "contradicted_by_source": index > 0 and not ambiguous,
                        "same_practical_task": True,
                    } for index in range(len(question["options"]))],
                })
            payload = {"reviews": rows}
        else:
            facts_by_id = {fact["fact_id"]: fact for fact in request["facts"]}
            fact_ids = tuple(dict.fromkeys(
                fact_id
                for question in request["questions"]
                for fact_id in question["evidence_fact_ids"]
            ))
            payload = {
                "rules": [{
                    "fact_id": fact_id,
                    "quote": facts_by_id[fact_id]["value"],
                    "kind": "required",
                } for fact_id in fact_ids],
                "reviews": [{
                    "question_id": question["question_id"],
                    "reason": "Synthetic source-bound truth check.",
                    "distinct_errors": True,
                    "options": [{
                        "index": index,
                        "relation": "entailed" if index == 0 else "contradicted",
                        "invented_constraint": False,
                        "realistic_error": index > 0,
                    } for index in range(len(question["options"]))],
                } for question in request["questions"]],
            }

        value = parser(json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(
            value=value,
            attempt_count=1,
            failure_reasons=(),
            model_id="synthetic-replay",
        )


@pytest.mark.asyncio
async def test_r22_off_domain_drift_gets_one_existing_axis_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lessons, facts = _fixture(combined=True)

    def derive(lesson, selected_facts, *, block_id):
        selected_ids = {fact.fact_id for fact in selected_facts}
        candidates = (
            _axis("notice", block_id=block_id, lesson_id=lesson.lesson_id),
            _axis("signing", block_id=block_id, lesson_id=lesson.lesson_id),
        )
        return tuple(
            axis
            for axis in candidates
            if axis.primary_fact_id in selected_ids
        )

    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", derive)
    client = ReplayClient("local_recovery")

    result = await generate_block_assessment(lessons, facts, client)

    assert {question.correct_answer for question in result.questions} == {
        NOTICE_KEY,
        SIGNING_KEY,
    }
    assert result.audit["accepted"] == 2
    assert result.audit["repaired"] == 0
    assert result.audit["attempt_counts"]["replacement"] == 1
    assert result.audit["attempt_counts"]["model_repair"] == 0
    assert result.audit["unresolved_quality_signals"] == []
    assert [request["task"] for request in client.requests] == [
        "assessment_generate",
        "assessment_generate",
        "assessment_review",
        "assessment_constraints",
    ]
    assert client.offered == [
        ("assessment_generate", "axis-notice", NOTICE_DISTRACTORS),
        ("assessment_generate", "axis-signing", SIGNING_DRIFT),
        ("assessment_generate", "axis-signing", SIGNING_REPAIR),
    ]

    initial, recovery, review, constraint = client.requests
    initial_domains = {
        axis["source_claim"]: axis["answer_domain"] for axis in initial["axes"]
    }
    signing_domain = initial_domains[SIGNING_KEY]
    notice_domain = initial_domains[NOTICE_KEY]
    assert signing_domain is not None and signing_domain["kind"] == "action_on_object"
    assert notice_domain is not None and notice_domain["kind"] == "recipient_and_timing"
    assert recovery["axes"][0]["source_claim"] == SIGNING_KEY
    assert recovery["axes"][0]["answer_domain"] == signing_domain
    for request in (review, constraint):
        domains = {
            question["options"][0]: question["answer_domain"]
            for question in request["questions"]
        }
        assert domains == {NOTICE_KEY: notice_domain, SIGNING_KEY: signing_domain}
        assert all(option not in SIGNING_DRIFT for question in request["questions"]
                   for option in question["options"])
    assert NOTICE_KEY not in json.dumps(notice_domain, ensure_ascii=False)
    assert SIGNING_KEY not in json.dumps(signing_domain, ensure_ascii=False)
    for request in (review, constraint):
        for question in request["questions"]:
            assert "correct_index" not in question
            assert "correct_answer" not in question


@pytest.mark.asyncio
async def test_in_domain_signing_ambiguity_gets_one_model_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lessons, facts = _fixture()
    signing_lesson = [lesson for lesson in lessons if lesson.lesson_id == "lesson-signing"]

    def derive(lesson, selected_facts, *, block_id):
        assert {fact.fact_id for fact in selected_facts} == {"fact-signing"}
        return (_axis("signing", block_id=block_id),)

    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", derive)
    client = ReplayClient("semantic_repair")

    result = await generate_block_assessment(signing_lesson, facts, client)

    assert [question.correct_answer for question in result.questions] == [SIGNING_KEY]
    assert result.audit["accepted"] == 1
    assert result.audit["repaired"] == 1
    assert result.audit["attempt_counts"]["replacement"] == 0
    assert result.audit["attempt_counts"]["model_repair"] == 1
    assert [request["task"] for request in client.requests] == [
        "assessment_generate",
        "assessment_review",
        "assessment_repair",
        "assessment_review",
        "assessment_constraints",
    ]

    initial, initial_review, repair, repaired_review, constraint = client.requests
    assert tuple(initial_review["questions"][0]["options"][1:]) == SIGNING_AMBIGUOUS
    reasons = set(repair["rejected"][0]["rejection_reasons"])
    assert {
        "option_1:not_plausible_error",
        "option_2:not_plausible_error",
    } <= reasons
    assert "assessment_answer_length_signal" not in reasons
    assert tuple(repaired_review["questions"][0]["options"][1:]) == SIGNING_REPAIR
    domain = initial["axes"][0]["answer_domain"]
    assert initial["axes"][0]["source_claim"] == SIGNING_KEY
    assert repair["axes"][0]["source_claim"] == SIGNING_KEY
    assert domain["kind"] == "action_on_object"
    assert all(_request_domain(request) == domain for request in client.requests)
    for request in (initial_review, repaired_review, constraint):
        for question in request["questions"]:
            assert "correct_index" not in question
            assert "correct_answer" not in question


def test_answer_domain_does_not_bypass_existing_answer_length_guard() -> None:
    axis = _axis("signing")
    domain = _axis_author_payload(axis)["answer_domain"]
    question = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis.axis_id,
            axis.required_prompt,
            (
                "не подписывает залоговый билет с отметкой о согласовании, "
                "а затем передает его другому сотруднику для повторной необязательной проверки",
                "подписывает залоговый билет без отметки о согласовании, "
                "а затем откладывает его ради дополнительной необязательной процедуры",
            ),
        ),
    )

    assert domain is not None and domain["kind"] == "action_on_object"
    assert question is not None
    assert answer_containment_option_indices(question) == (1,)
    assert answer_length_repair_targets([question]) == (question.question_id,)


class ShapeRecoveryClient(ReplayClient):
    def __init__(self, defect: str, *, recovery_fails: bool = False) -> None:
        super().__init__("shape_recovery")
        self.defect = defect
        self.recovery_fails = recovery_fails
        self.generate_count = 0

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        if request["task"] != "assessment_generate":
            return await super().ainvoke_validated(messages, parser, **kwargs)
        self.requests.append(request)
        self.generate_count += 1
        axis = request["axes"][0]
        bad = self.generate_count == 1 or self.recovery_fails
        if self.defect == "empty":
            rows = []
        else:
            distractors = NOTICE_DISTRACTORS
            if bad and self.defect == "containment":
                distractors = ("АУП РД.", NOTICE_DISTRACTORS[1])
            elif bad:
                distractors = (
                    "Отдел планирования — через два рабочих дня, после завершения внутренней сверки документов и подготовки дополнительного письменного сообщения.",
                    "Дежурный руководитель — через неделю, после получения итогового отчёта, рассмотрения приложенных материалов и очередного общего совещания.",
                )
            rows = [{"axis_id": axis["axis_id"], "prompt": axis["required_prompt"],
                     "distractors": list(distractors)}]
        return SimpleNamespace(value=parser(json.dumps({"questions": rows}, ensure_ascii=False)),
                               attempt_count=1, failure_reasons=(), model_id="synthetic-replay")


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["containment", "length"])
async def test_deterministic_author_shape_is_recovered_before_paying_for_blind_reviews(monkeypatch, defect):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (_axis("notice", block_id=block_id),))
    client = ShapeRecoveryClient(defect)
    result = await generate_block_assessment(lessons, facts, client)
    assert [question.correct_answer for question in result.questions] == [NOTICE_KEY]
    assert [request["task"] for request in client.requests] == [
        "assessment_generate", "assessment_generate", "assessment_review", "assessment_constraints",
    ]
    assert result.audit["attempt_counts"]["replacement"] == 1
    assert result.audit["attempt_counts"]["model_repair"] == 0
    feedback = client.requests[1]["rejected"][0]
    expected = "answer_value_contains_or_is_contained_in_key" if defect == "containment" else "assessment_answer_length_signal"
    assert any(expected in reason for reason in feedback["rejection_reasons"])
    assert client.requests[1]["axes"][0]["source_claim"] == NOTICE_KEY
    assert all(tuple(request["questions"][0]["options"][1:]) == NOTICE_DISTRACTORS
               for request in client.requests if request["task"] in {"assessment_review", "assessment_constraints"})


@pytest.mark.asyncio
async def test_pre_review_recovery_is_once_and_explicit_empty_author_response_still_has_no_padding(monkeypatch):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (_axis("notice", block_id=block_id),))
    client = ShapeRecoveryClient("containment", recovery_fails=True)
    result = await generate_block_assessment(lessons, facts, client)
    assert not result.questions
    assert [request["task"] for request in client.requests] == ["assessment_generate", "assessment_generate"]
    assert result.audit["attempt_counts"]["replacement"] == 1
    assert result.audit["attempt_counts"]["model_repair"] == 0
    assert result.audit["attempt_counts"]["authored"] == 2
    outcome = next(row for row in result.audit["axis_outcomes"] if row["axis_id"] == "axis-notice")
    assert "answer_value_contains_or_is_contained_in_key" in outcome["reason"]
    assert result.audit["block_outcomes"][0]["outcome"] == "quality_omitted"
    empty = ShapeRecoveryClient("empty")
    empty_result = await generate_block_assessment(lessons, facts, empty)
    assert not empty_result.questions
    assert [request["task"] for request in empty.requests] == ["assessment_generate"]
    assert empty_result.audit["block_outcomes"][0]["outcome"] == "no_assessable_questions"
    empty_outcome = next(row for row in empty_result.audit["axis_outcomes"] if row["axis_id"] == "axis-notice")
    assert empty_outcome["reason"] == "no_admissible_candidate"


@pytest.mark.asyncio
async def test_replaced_source_peer_provenance_records_both_initial_and_retained_origin(monkeypatch):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (_axis("notice", block_id=block_id),))

    def source_peer(axis, lesson, source):
        return materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt,
            ("АУП РД.", NOTICE_DISTRACTORS[1])))

    monkeypatch.setattr(semantic_assessment, "_source_peer_table_candidate", source_peer)
    client = ReplayClient("shape_recovery")
    result = await generate_block_assessment(lessons, facts, client)
    assert [question.correct_answer for question in result.questions] == [NOTICE_KEY]
    outcome = next(row for row in result.audit["axis_outcomes"] if row["axis_id"] == "axis-notice")
    assert outcome["initial_candidate_origin"] == "source_peer_table"
    assert outcome["candidate_origin"] == "provider_replacement"
    assert outcome["attempt_counts"]["authored"] == 2


@pytest.mark.asyncio
async def test_shape_defective_model_repair_never_reaches_another_blind_review(monkeypatch):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-signing"]
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (_axis("signing", block_id=block_id),))

    class DefectiveRepair(ReplayClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] != "assessment_repair":
                return await super().ainvoke_validated(messages, parser, **kwargs)
            self.requests.append(request)
            axis = request["axes"][0]
            row = {"axis_id": axis["axis_id"], "prompt": axis["required_prompt"], "distractors": [
                "не подписывает залоговый билет с отметкой о согласовании", SIGNING_REPAIR[1],
            ]}
            return SimpleNamespace(value=parser(json.dumps({"questions": [row]}, ensure_ascii=False)),
                                   attempt_count=1, failure_reasons=(), model_id="synthetic-replay")

    client = DefectiveRepair("semantic_repair")
    result = await generate_block_assessment(lessons, facts, client)
    assert not result.questions
    assert [request["task"] for request in client.requests] == [
        "assessment_generate", "assessment_review", "assessment_repair",
    ]
    assert result.audit["attempt_counts"]["model_repair"] == 1
    assert result.audit["attempt_counts"]["replacement"] == 0
    assert any(row["stage"] == "model_repair" for row in result.audit["pre_review_rejections"])


@pytest.mark.asyncio
async def test_unknown_domain_still_rejects_deterministic_shape_before_both_truth_reviews(monkeypatch):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    axis = semantic_assessment.replace(_axis("notice"), required_prompt="Кого и когда уведомляют о сомнении?")
    assert _axis_author_payload(axis)["answer_domain"] is None
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (semantic_assessment.replace(axis, semantic_block_id=block_id),))
    client = ShapeRecoveryClient("length")
    result = await generate_block_assessment(lessons, facts, client)
    assert len(result.questions) == 1 and result.questions[0].correct_answer == NOTICE_KEY
    assert [request["task"] for request in client.requests] == [
        "assessment_generate", "assessment_generate", "assessment_review", "assessment_constraints",
    ]
    assert all(question["answer_domain"] is None for request in client.requests
               for question in request.get("questions", []))


@pytest.mark.asyncio
async def test_bad_extra_distractor_is_pruned_only_with_two_remaining_wrong_choices_before_reviews(monkeypatch):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (_axis("notice", block_id=block_id),))

    class ExtraBadOption(ReplayClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] != "assessment_generate":
                return await super().ainvoke_validated(messages, parser, **kwargs)
            self.requests.append(request)
            axis = request["axes"][0]
            row = {"axis_id": axis["axis_id"], "prompt": axis["required_prompt"],
                   "distractors": ["АУП РД.", *NOTICE_DISTRACTORS]}
            return SimpleNamespace(value=parser(json.dumps({"questions": [row]}, ensure_ascii=False)),
                                   attempt_count=1, failure_reasons=(), model_id="synthetic-replay")

    client = ExtraBadOption("local_prune")
    result = await generate_block_assessment(lessons, facts, client)
    assert len(result.questions) == 1 and len(result.questions[0].options) == 3
    assert result.questions[0].correct_answer == NOTICE_KEY
    assert "АУП РД." not in result.questions[0].options
    assert [request["task"] for request in client.requests] == [
        "assessment_generate", "assessment_review", "assessment_constraints",
    ]
    assert result.audit["removed_distractors"] == 1
    assert result.audit["attempt_counts"]["deterministic_repair"] == 1
    assert result.audit["attempt_counts"]["replacement"] == 0
    assert result.audit["attempt_counts"]["model_repair"] == 0


@pytest.mark.asyncio
async def test_unsupported_immutable_executor_shape_is_terminal_without_paid_replacement(monkeypatch):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    prompt = "Кем выполняется именно предварительное согласование по телефону для «Операции категории»?"
    axis = semantic_assessment.replace(_axis("notice"), correct_value="комиссией",
        normalized_correct_value="комиссией", required_prompt=prompt)
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (semantic_assessment.replace(axis, semantic_block_id=block_id),))

    class UnsupportedRole:
        def __init__(self):
            self.tasks = []

        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            self.tasks.append(request["task"])
            assert self.tasks == ["assessment_generate"], "immutable defect cannot reach a recovery or review"
            row = {"axis_id": axis.axis_id, "prompt": prompt,
                   "distractors": ["руководителем", "никем: согласование не требуется"]}
            return SimpleNamespace(value=parser(json.dumps({"questions": [row]}, ensure_ascii=False)),
                                   attempt_count=1, failure_reasons=(), model_id="synthetic-replay")

    client = UnsupportedRole()
    result = await generate_block_assessment(lessons, facts, client)
    assert not result.questions and client.tasks == ["assessment_generate"]
    record = next(row for row in result.audit["axis_outcomes"] if row["axis_id"] == axis.axis_id)
    assert record["state"] == "omitted" and record["reason"] == "preliminary_executor_role_shape_unsupported"
    assert record["attempt_counts"]["replacement"] == record["attempt_counts"]["model_repair"] == 0
    assert result.audit["attempt_counts"]["replacement"] == result.audit["attempt_counts"]["model_repair"] == 0


class ResidualShapeClient(ReplayClient):
    def __init__(self, outcome="accepted"):
        super().__init__("semantic_repair")
        self.outcome = outcome
        self.notice_generations = 0

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        task = request["task"]
        if task in {"assessment_generate", "assessment_repair"}:
            self.requests.append(request)
            rows = []
            for axis in request["axes"]:
                if axis["source_claim"] == NOTICE_KEY:
                    if task == "assessment_generate":
                        self.notice_generations += 1
                        if self.notice_generations > 1 and self.outcome == "empty":
                            continue
                        variant = ("Передать" if self.notice_generations == 1 or self.outcome == "identical"
                                   else "Отложить")
                        choices = (variant + " уведомление службе контроля после повторной плановой проверки " * 4,
                                   variant + " уведомление руководителю после завершения следующей рабочей смены " * 4)
                    else:
                        assert request["rejected"][0]["primary_fact_id"] == "fact-notice"
                        assert request["rejected"][0]["fact_ids"] == ["fact-notice"]
                        choices = ("Ожидать " * 30, "Передавать " * 30) if self.outcome == "bad_repair" else NOTICE_DISTRACTORS
                else:
                    choices = SIGNING_REPAIR if task == "assessment_repair" else SIGNING_AMBIGUOUS
                rows.append({"axis_id": axis["axis_id"], "prompt": axis["required_prompt"],
                             "distractors": list(choices)})
            return SimpleNamespace(value=parser(json.dumps({"questions": rows}, ensure_ascii=False)),
                                   attempt_count=1, failure_reasons=(), model_id="synthetic-replay")
        if task == "assessment_review" and self.outcome in {"semantic_reject", "mixed"}:
            def reject_notice(raw):
                payload = json.loads(raw)
                for row in payload["reviews"]:
                    if row["question_id"] == "semantic-notice":
                        row["educational"] = False
                return parser(json.dumps(payload))
            return await super().ainvoke_validated(messages, reject_notice, **kwargs)
        return await super().ainvoke_validated(messages, parser, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected_repairs", [
    ("accepted", 1), ("bad_repair", 1), ("semantic_reject", 1),
    ("identical", 0), ("empty", 0),
])
async def test_residual_shape_uses_only_unspent_model_repair_before_both_reviews(monkeypatch, outcome, expected_repairs):
    lessons, facts = _fixture()
    lessons = [lesson for lesson in lessons if lesson.lesson_id == "lesson-notice"]
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
                        (_axis("notice", block_id=block_id),))
    client = ResidualShapeClient(outcome)
    result = await generate_block_assessment(lessons, facts, client)
    tasks = [request["task"] for request in client.requests]
    record = next(row for row in result.audit["axis_outcomes"] if row["axis_id"] == "axis-notice")
    assert record["attempt_counts"]["replacement"] == 1
    assert record["attempt_counts"]["model_repair"] == expected_repairs
    assert tasks.count("assessment_repair") == expected_repairs
    if outcome == "accepted":
        assert tasks == ["assessment_generate", "assessment_generate", "assessment_repair",
                         "assessment_review", "assessment_constraints"]
        assert len(result.questions) == result.audit["repaired"] == 1
        assert record["candidate_origin"] == "provider_model_repair_after_replacement"
        assert record["attempt_counts"]["authored"] == 2
        assert not result.audit["unresolved_quality_signals"]
    else:
        assert not result.questions and result.audit["repaired"] == 0
        assert tasks.count("assessment_review") == (1 if outcome == "semantic_reject" else 0)
        assert "assessment_constraints" not in tasks
        if outcome == "identical":
            assert "assessment_replacement_no_progress" in record["reason"]


@pytest.mark.asyncio
async def test_exhausted_pre_review_axis_does_not_consume_another_axes_semantic_repair(monkeypatch):
    lessons, facts = _fixture(combined=True)
    monkeypatch.setattr(semantic_assessment, "derive_assessment_axes", lambda lesson, selected_facts, *, block_id:
        tuple(_axis(kind, block_id=block_id, lesson_id=lesson.lesson_id) for kind in ("notice", "signing")))
    client = ResidualShapeClient("mixed")
    result = await generate_block_assessment(lessons, facts, client)
    records = {row["axis_id"]: row for row in result.audit["axis_outcomes"]}
    assert [question.correct_answer for question in result.questions] == [SIGNING_KEY]
    assert records["axis-notice"]["state"] == "omitted"
    assert records["axis-signing"]["state"] == "retained"
    assert all(records[key]["attempt_counts"]["model_repair"] == 1 for key in ("axis-notice", "axis-signing"))
    assert result.audit["repaired"] == 1
    assert [request["axes"][0]["axis_id"] for request in client.requests if request["task"] == "assessment_repair"] == [
        "axis-notice", "axis-signing"]

