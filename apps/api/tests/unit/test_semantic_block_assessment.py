from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _course_question_identity,
    _value_quote,
    generate_block_assessment,
)
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason

RULE = "Персональные данные нельзя передавать в неразрешённые каналы. Исключений для срочных обращений нет."
ATOMIC_RULE = "Персональные данные нельзя передавать в неразрешённые каналы."
GOOD = "Использовать только разрешённый канал передачи персональных данных."
OPTIONS = [GOOD, "Передать персональные данные через любой канал при срочном обращении.",
           "Передать персональные данные в личный мессенджер, затем удалить сообщение."]
BAD = [GOOD, "Первый ответ подтверждает приём обращения и сообщает следующий шаг.",
       "Эскалация не снимает обязанности следить за результатом."]


@pytest.mark.parametrize(("value", "expected"), [
    (
        "2. Размер ставки не должен превышать предельный размер, определенный актом.",
        "Предельный размер, определенный актом",
    ),
    (
        "3. Правила расчета разрабатываются и утверждаются уполномоченным органом.",
        "Уполномоченным органом",
    ),
    (
        "Основной долг погашается в конце срока, а уплата вознаграждения "
        "осуществляется в момент выдачи микрокредита.",
        "В момент выдачи микрокредита",
    ),
    (
        "График погашения не требуется в случае, если микрокредит погашается "
        "единовременным платежом в конце срока.",
        "Если микрокредит погашается единовременным платежом в конце срока",
    ),
    (
        "Обработка данных прекратится только после исполнения Клиентом всех обязательств.",
        "После исполнения Клиентом всех обязательств",
    ),
    (
        "Ломбард не вправе требовать выплаты вознаграждения, неустойки (штрафов, пени), "
        "начисленных по истечении 90 последовательных календарных дней просрочки исполнения "
        "обязательства по погашению платежа.",
        "Ломбард не вправе требовать выплаты вознаграждения, неустойки (штрафов, пени), "
        "начисленных по истечении 90 последовательных календарных дней просрочки",
    ),
    (
        "Начисление вознаграждения за пользование микрокредитом в период просрочки и/или "
        "пени в случае просрочки исполнения обязательств осуществляется в момент "
        "погашения Клиентом задолженности.",
        "В момент погашения Клиентом задолженности",
    ),
])
def test_server_selects_concise_source_owned_answer_span(value, expected):
    fact = SourceFact("f1", "Правило", "условие", value, "doc_id=d1;section=rules;part=1")
    lesson = LessonDraft("l1", "Правила", "Условия", "Применять условия", "", ("f1",), (), 1)

    axes = derive_assessment_axes(lesson, [fact], block_id="block")

    assert axes[0].correct_value == expected


@pytest.mark.parametrize("marker", [")", "."])
def test_server_atomizes_numbered_source_list_before_authorship(marker: str) -> None:
    value = (
        "Ломбард вправе отказать при наличии оснований: "
        f"1{marker} информация заявителя недостоверна; "
        f"2{marker} имеется непогашенная задолженность; "
        f"3{marker} необходимые документы не представлены."
    )
    fact = SourceFact("f1", "Отказ", "право", value, "doc_id=d1;section=rules;part=1")
    lesson = LessonDraft("l1", "Правила", "Основания отказа", "Применять основания", "", ("f1",), (), 1)

    axes = derive_assessment_axes(lesson, [fact], block_id="block")

    assert axes[0].correct_value.startswith("Да, ")
    assert axes[0].correct_value.endswith(
        "является основанием для отказа в предоставлении микрокредита."
    )
    assert axes[0].required_prompt.startswith("Является ли")
    assert ";" not in axes[0].correct_value
    assert len(axes[0].correct_value) <= 240


def test_server_bounds_long_semicolon_list_to_one_exact_clause() -> None:
    value = (
        "Уведомление считается доставленным одним из следующих способов: "
        "на адрес электронной почты, указанный в договоре; "
        "по месту жительства заказным письмом с уведомлением о вручении; "
        "через мобильное приложение при наличии подтверждения."
    )
    fact = SourceFact("f1", "Уведомление", "условие", value, "doc_id=d1;section=rules;part=1")
    lesson = LessonDraft("l1", "Правила", "Уведомления", "Применять способы", "", ("f1",), (), 1)

    axes = derive_assessment_axes(lesson, [fact], block_id="block")

    assert axes[0].correct_value.casefold() in value.casefold()
    assert ";" not in axes[0].correct_value
    assert len(axes[0].correct_value) <= 240


def test_same_long_source_answer_in_same_document_has_one_course_identity() -> None:
    answer = "В момент погашения Клиентом задолженности"
    facts = {
        "f1": SourceFact(
            "f1", "Начисление", "момент", answer,
            "doc_id=d1;source_revision=r1;section=payments;part=1",
        ),
        "f2": SourceFact(
            "f2", "Обязанности", "момент", answer,
            "doc_id=d1;source_revision=r1;section=rights;part=1",
        ),
    }
    first = QuestionDraft(
        "q1", "l1", "single_choice", "Когда начисляется вознаграждение?",
        (answer, "При выдаче", "Ежемесячно"), answer, answer, "f1",
        evidence_fact_ids=("f1",), semantic_reviewed=True,
    )
    second = replace(
        first, question_id="q2", lesson_id="l2", fact_id="f2",
        prompt="Когда начисляется вознаграждение по залоговому билету?",
        evidence_fact_ids=("f2",),
    )

    assert _course_question_identity(first, facts) == _course_question_identity(second, facts)


def test_short_or_cross_document_answers_keep_distinct_course_identities() -> None:
    facts = {
        "f1": SourceFact(
            "f1", "Обращения", "срок", "15 дней",
            "doc_id=d1;source_revision=r1;section=appeals;part=1",
        ),
        "f2": SourceFact(
            "f2", "Хранение", "срок", "15 дней",
            "doc_id=d1;source_revision=r1;section=storage;part=1",
        ),
        "f3": SourceFact(
            "f3", "Обращения", "срок", "В момент погашения Клиентом задолженности",
            "doc_id=d2;source_revision=r1;section=payments;part=1",
        ),
        "f4": SourceFact(
            "f4", "Начисление", "момент", "В момент погашения Клиентом задолженности",
            "doc_id=d1;source_revision=r1;section=payments;part=1",
        ),
    }
    short = QuestionDraft(
        "q1", "l1", "single_choice", "Каков срок?", ("15 дней", "10 дней", "30 дней"),
        "15 дней", "15 дней", "f1", evidence_fact_ids=("f1",), semantic_reviewed=True,
    )
    same_short = replace(short, question_id="q2", fact_id="f2", evidence_fact_ids=("f2",))
    long_other_doc = replace(
        short, question_id="q3", fact_id="f3",
        correct_answer="В момент погашения Клиентом задолженности",
        evidence_fact_ids=("f3",),
    )
    long_first_doc = replace(
        long_other_doc, question_id="q4", fact_id="f4",
        evidence_fact_ids=("f4",),
    )

    assert _course_question_identity(short, facts) != _course_question_identity(same_short, facts)
    assert _course_question_identity(long_first_doc, facts) != _course_question_identity(
        long_other_doc, facts,
    )


def test_known_attribute_label_does_not_discard_exact_cell_evidence():
    fact = SourceFact("f1", "Коллекция", "Материал фасада", "ЛДСП", "doc_id=d1;section=s1")
    assert _value_quote("Материал фасада: ЛДСП", fact) == "ЛДСП"
    assert _value_quote("ЛДСП", fact) == "ЛДСП"
    assert _value_quote("Материал корпуса: ЛДСП", fact) is None
    assert _value_quote("Материал фасада: МДФ", fact) is None
    assert _value_quote("Материал фасада: ЛДСП не используется", fact) is None
    assert _value_quote("материал фасада: лдсп", fact) == "ЛДСП"
    spaced = replace(fact, value="Светлый   фасад с кромкой")
    assert _value_quote("светлый фасад", spaced) == "Светлый   фасад"


def test_constraint_quote_accepts_only_substantial_exact_ordered_ellipsis() -> None:
    from app.modules.ai.evidence_engine.semantic_assessment import (
        _constraint_quote_is_source_bound,
    )

    fact = SourceFact(
        "f-rule",
        "Залог",
        "запрет",
        "Ломбарду не допускается принятие в залог предметов первой категории; "
        "2) вещей, изъятых из оборота и ограниченных в обороте.",
        "doc_id=d1;section=collateral",
    )

    assert _constraint_quote_is_source_bound(
        "Ломбарду не допускается принятие в залог ... "
        "вещей, изъятых из оборота и ограниченных в обороте.",
        fact,
    )
    assert not _constraint_quote_is_source_bound(
        "вещей, изъятых из оборота и ограниченных в обороте ... "
        "Ломбарду не допускается принятие в залог",
        fact,
    )
    assert not _constraint_quote_is_source_bound(
        "Ломбарду не допускается принятие в залог ... "
        "вещей, разрешённых в свободном обороте.",
        fact,
    )
    assert not _constraint_quote_is_source_bound("Ломбарду ... вещей", fact)


def test_reviewer_rejects_absurd_option_even_if_relevant_and_clearly_false():
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions, _parse_reviews

    lesson, facts = fixture()
    question = _parse_questions(json.dumps({"questions": [candidate()]}),
        lesson_id=lesson.lesson_id, facts=list(facts.values()), maximum=1, block_id="b")[0]
    request = {"questions": [{"question_id": question.question_id, "options": question.options}]}
    response = verdict(request)
    response["reviews"][0]["options"][1]["plausible_error"] = False
    assert _parse_reviews(json.dumps(response), [question]) == {question.question_id: False}


def test_constraint_parser_ignores_extra_bad_rule_when_primary_evidence_is_exact() -> None:
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_constraint_reviews

    lesson, facts = fixture()
    question = QuestionDraft(
        "q", lesson.lesson_id, "single_choice", "Как передавать данные?",
        (ATOMIC_RULE, OPTIONS[1], OPTIONS[2]), ATOMIC_RULE, ATOMIC_RULE, "f1",
        evidence_fact_ids=("f1",), semantic_reviewed=True,
    )
    payload = {
        "rules": [
            {"fact_id": "f1", "quote": ATOMIC_RULE, "kind": "forbidden"},
            {"fact_id": "f1", "quote": "Несуществующая цитата...", "kind": "forbidden"},
        ],
        "reviews": [{
            "question_id": "q",
            "options": [
                {"index": 0, "relation": "entailed", "invented_constraint": False,
                 "realistic_error": False},
                {"index": 1, "relation": "contradicted", "invented_constraint": False,
                 "realistic_error": True},
                {"index": 2, "relation": "contradicted", "invented_constraint": False,
                 "realistic_error": True},
            ],
            "distinct_errors": True,
            "reason": "Проверено по точной цитате.",
        }],
    }

    result = _parse_constraint_reviews(
        json.dumps(payload, ensure_ascii=False), [question], list(facts.values()),
    )

    assert result == {"q": True}


def test_constraint_parser_rejects_when_primary_fact_has_no_exact_rule() -> None:
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_constraint_reviews

    lesson, facts = fixture()
    question = QuestionDraft(
        "q", lesson.lesson_id, "single_choice", "Как передавать данные?",
        (ATOMIC_RULE, OPTIONS[1], OPTIONS[2]), ATOMIC_RULE, ATOMIC_RULE, "f1",
        evidence_fact_ids=("f1",), semantic_reviewed=True,
    )
    payload = {
        "rules": [{
            "fact_id": "f1", "quote": "Несуществующая цитата...", "kind": "forbidden",
        }],
        "reviews": [{
            "question_id": "q",
            "options": [
                {"index": 0, "relation": "entailed", "invented_constraint": False,
                 "realistic_error": False},
                {"index": 1, "relation": "contradicted", "invented_constraint": False,
                 "realistic_error": True},
                {"index": 2, "relation": "contradicted", "invented_constraint": False,
                 "realistic_error": True},
            ],
            "distinct_errors": True,
            "reason": "Нет точной цитаты.",
        }],
    }

    with pytest.raises(ValueError, match="assessment_constraints_evidence"):
        _parse_constraint_reviews(
            json.dumps(payload, ensure_ascii=False), [question], list(facts.values()),
        )


def fixture():
    fact = SourceFact("f1", "Защита данных", "правило", RULE, "doc_id=d1;section=privacy")
    lesson = LessonDraft("l1", "Работа", "Защита персональных данных", "Передавать данные безопасно",
                         RULE, (fact.fact_id,), (), 1)
    return lesson, {fact.fact_id: fact}


def candidate(options=None):
    return {"prompt": "Как передать персональные данные при срочном обращении?",
            "options": options or OPTIONS, "correct_index": 0,
            "explanation": "Срочность обращения не разрешает передачу в неразрешённые каналы.",
            "evidence": [{"fact_id": "f1", "quote": RULE}]}


def verdict(request, *, reject=False):
    return {"reviews": [{"question_id": q["question_id"], "question_supported": True,
                         "educational": True, "explanation_supported": True, "options_distinct": True,
                         "options": [{"index": i, "answers_question": not (reject and i > 0),
                                      "correct": i == 0, "plausible_error": i > 0,
                                      "contradicted_by_source": i > 0, "same_practical_task": True}
                                     for i in range(len(q["options"]))]}
                        for q in request["questions"]]}


class Client:
    def __init__(self, *, bad=False, repair=True, malformed=False, outage=False, empty=False):
        self.requests = []
        self.bad, self.repair, self.malformed, self.outage, self.empty = bad, repair, malformed, outage, empty

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        stage = request["task"]
        if stage == "assessment_constraints":
            assert all("explanation" not in q and "correct_answer" not in q for q in request["questions"])
            facts_by_id = {fact["fact_id"]: fact for fact in request["facts"]}
            required_fact_ids = dict.fromkeys(
                fact_id
                for question in request["questions"]
                for fact_id in question["evidence_fact_ids"]
            )
            payload = {"rules": [
                           {"fact_id": fact_id, "quote": facts_by_id[fact_id]["value"],
                            "kind": "attribute"}
                           for fact_id in required_fact_ids
                       ],
                       "reviews": [{"question_id": q["question_id"], "reason": "Fixture contract", "distinct_errors": True,
                                    "options": [{"index": i, "relation": "entailed" if i == 0 else "contradicted",
                                                 "invented_constraint": False, "realistic_error": True} for i in range(len(q["options"]))]}
                                   for q in request["questions"]]}
        elif stage == "assessment_review":
            assert all("correct_index" not in q and "correct_answer" not in q for q in request["questions"])
            if self.outage:
                raise AllProvidersFailedError("fixture", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE])
            payload = verdict(
                request,
                reject=any(set(BAD[1:]).issubset(set(q["options"])) for q in request["questions"]),
            )
            if self.malformed:
                payload["reviews"][0]["options"].pop()
        else:
            options = BAD if self.bad and (stage != "assessment_repair" or not self.repair) else OPTIONS
            axis = request["axes"][0]
            payload = {"questions": [] if self.empty else [{
                "axis_id": axis["axis_id"],
                "prompt": candidate(options)["prompt"],
                "distractors": options[1:],
            }]}
        try:
            value = parser(json.dumps(payload, ensure_ascii=False))
        except (ValueError, KeyError, TypeError) as exc:
            raise AllProvidersFailedError("fixture", [ValidatedCallFailureReason.VALIDATION_BLOCKED]) from exc
        return SimpleNamespace(value=value, attempt_count=1, failure_reasons=(), model_id="fixture")


@pytest.mark.asyncio
async def test_single_nonnumeric_paragraph_produces_one_question_without_peer_facts():
    lesson, facts = fixture()
    result = await generate_block_assessment([lesson], facts, Client())
    assert len(result.questions) == 1
    assert set(result.questions[0].options) == {ATOMIC_RULE, *OPTIONS[1:]}
    assert result.questions[0].fact_id == "f1"
    assert result.audit["accepted"] == 1
    assert result.audit["repaired"] == 0


@pytest.mark.asyncio
async def test_generation_path_does_not_accept_a_model_selected_correct_key():
    class AdversarialKeyClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_generate":
                self.requests.append(request)
                axis = request["axes"][0]
                payload = {"questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": "Как передавать персональные данные?",
                    "distractors": [
                        "Передать данные через любой канал.",
                        "Передать данные через личный мессенджер.",
                    ],
                    # These legacy fields are malicious noise and must not own truth.
                    "correct_index": 1,
                    "correct_answer": "Передать данные через любой канал.",
                }]}
                return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)),
                                       attempt_count=1)
            return await super().ainvoke_validated(messages, parser, **kwargs)

    lesson, facts = fixture()
    result = await generate_block_assessment([lesson], facts, AdversarialKeyClient())

    assert len(result.questions) == 1
    assert result.questions[0].correct_answer == ATOMIC_RULE
    assert result.questions[0].fact_id == "f1"
    assert result.questions[0].evidence_fact_ids == ("f1",)


@pytest.mark.asyncio
async def test_exact_unrelated_true_options_are_repaired_then_independently_reviewed():
    lesson, facts = fixture()
    client = Client(bad=True)
    result = await generate_block_assessment([lesson], facts, client)
    assert set(result.questions[0].options) == {ATOMIC_RULE, *OPTIONS[1:]}
    assert [r["task"] for r in client.requests] == ["assessment_generate", "assessment_review",
                                                   "assessment_repair", "assessment_review", "assessment_constraints"]
    repair = client.requests[2]
    assert "feedback" not in repair
    assert repair["rejected"][0]["rejection_reasons"] == [
        "option_1:does_not_answer_question", "option_2:does_not_answer_question",
    ]
    assert result.audit["repaired"] == 1


@pytest.mark.asyncio
async def test_constraint_rejection_supplies_trusted_structured_repair_reason():
    class ConstraintRejectingClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] != "assessment_constraints":
                return await super().ainvoke_validated(messages, parser, **kwargs)
            self.requests.append(request)
            payload = {"rules": [{"fact_id": "f1", "quote": RULE, "kind": "forbidden"}],
                       "reviews": [{"question_id": q["question_id"], "reason": "untrusted model prose", "distinct_errors": True,
                                    "options": [{"index": i,
                                                 "relation": "entailed" if i == 0 else "undetermined",
                                                 "invented_constraint": False, "realistic_error": True}
                                                for i in range(len(q["options"]))]}
                                   for q in request["questions"]]}
            return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1)

    lesson, facts = fixture()
    client = ConstraintRejectingClient()
    result = await generate_block_assessment([lesson], facts, client)
    assert result.questions == ()
    repair = next(request for request in client.requests if request["task"] == "assessment_repair")
    assert repair["rejected"][0]["rejection_reasons"] == [
        "constraint_option_1:expected_contradicted_got_undetermined",
        "constraint_option_2:expected_contradicted_got_undetermined",
    ]


@pytest.mark.asyncio
async def test_failed_repair_drops_question_without_quota_padding():
    lesson, facts = fixture()
    client = Client(bad=True, repair=False)
    result = await generate_block_assessment([lesson], facts, client)
    assert result.questions == ()
    assert len(client.requests) == 4
    assert result.audit["dropped"] == 1


@pytest.mark.parametrize("flag", ["malformed", "outage"])
@pytest.mark.asyncio
async def test_missing_or_failed_review_never_admits_questions(flag):
    lesson, facts = fixture()
    result = await generate_block_assessment([lesson], facts, Client(**{flag: True}))
    assert result.questions == ()
    assert result.audit["failures"]


@pytest.mark.asyncio
async def test_one_transient_review_contract_failure_is_retried_once():
    class MalformedOnce(Client):
        def __init__(self):
            super().__init__()
            self.failed = False

        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_review" and not self.failed:
                self.failed = True
                self.requests.append(request)
                raise AllProvidersFailedError(
                    "fixture",
                    [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    lesson, facts = fixture()
    client = MalformedOnce()

    result = await generate_block_assessment([lesson], facts, client)

    assert len(result.questions) == 1
    assert [request["task"] for request in client.requests].count("assessment_review") == 2
    assert result.audit["failures"] == []


@pytest.mark.asyncio
async def test_failed_multi_question_review_falls_back_to_isolated_reviews():
    facts = {
        "f1": SourceFact(
            "f1", "Защита данных", "правило", RULE,
            "doc_id=d1;section=privacy;part=1",
        ),
        "f2": SourceFact(
            "f2", "Защита данных", "срок",
            "Обращение рассматривается в течение 15 дней.",
            "doc_id=d1;section=privacy;part=2",
        ),
    }
    lesson = LessonDraft(
        "l1", "Работа", "Защита персональных данных", "Применять правила",
        "", tuple(facts), (), 2,
    )

    class BatchReviewRejectingClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_review" and len(request["questions"]) > 1:
                self.requests.append(request)
                raise AllProvidersFailedError(
                    "fixture",
                    [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                )
            if request["task"] == "assessment_generate":
                self.requests.append(request)
                rows = [{
                    "axis_id": axis["axis_id"],
                    "prompt": f"Как применяется {axis['attribute']}?",
                    "distractors": ["Другое правило", "Правило не применяется"],
                } for axis in request["axes"]]
                return SimpleNamespace(
                    value=parser(json.dumps({"questions": rows}, ensure_ascii=False)),
                    attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = BatchReviewRejectingClient()
    result = await generate_block_assessment([lesson], facts, client)

    assert len(result.questions) == 2
    assert result.audit["failures"] == []
    review_sizes = [len(request["questions"]) for request in client.requests
                    if request["task"] == "assessment_review"]
    assert review_sizes == [2, 2, 1, 1]


@pytest.mark.asyncio
async def test_failed_multi_axis_authoring_falls_back_to_isolated_axes():
    facts = {
        "f1": SourceFact(
            "f1", "Защита данных", "правило", RULE,
            "doc_id=d1;section=privacy;part=1",
        ),
        "f2": SourceFact(
            "f2", "Защита данных", "срок",
            "Обращение рассматривается в течение 15 дней.",
            "doc_id=d1;section=privacy;part=2",
        ),
    }
    lesson = LessonDraft(
        "l1", "Работа", "Защита персональных данных", "Применять правила",
        "", tuple(facts), (), 2,
    )

    class BatchAuthorRejectingClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_generate" and len(request["axes"]) > 1:
                self.requests.append(request)
                raise AllProvidersFailedError(
                    "fixture",
                    [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                )
            if request["task"] == "assessment_generate" and "15" in request["axes"][0]["source_claim"]:
                self.requests.append(request)
                axis = request["axes"][0]
                payload = {"questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": "В какой срок обрабатывается обращение?",
                    "distractors": ["В течение 30 минут.", "В течение одного часа."],
                }]}
                return SimpleNamespace(
                    value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = BatchAuthorRejectingClient()
    result = await generate_block_assessment([lesson], facts, client)

    assert len(result.questions) == 2
    author_sizes = [len(request["axes"]) for request in client.requests
                    if request["task"] == "assessment_generate"]
    assert author_sizes == [2, 2, 1, 1]


@pytest.mark.asyncio
async def test_failed_multi_question_constraints_keep_isolated_successes():
    facts = {
        "f1": SourceFact(
            "f1", "Защита данных", "правило", RULE,
            "doc_id=d1;section=privacy;part=1",
        ),
        "f2": SourceFact(
            "f2", "Защита данных", "срок",
            "Обращение рассматривается в течение 15 дней.",
            "doc_id=d1;section=privacy;part=2",
        ),
    }
    lesson = LessonDraft(
        "l1", "Работа", "Защита персональных данных", "Применять правила",
        "", tuple(facts), (), 2,
    )

    class BatchConstraintRejectingClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_constraints" and len(request["questions"]) > 1:
                self.requests.append(request)
                raise AllProvidersFailedError(
                    "fixture",
                    [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                )
            if request["task"] == "assessment_generate":
                self.requests.append(request)
                rows = [{
                    "axis_id": axis["axis_id"],
                    "prompt": f"Как применяется {axis['attribute']}?",
                    "distractors": ["Другое правило", "Правило не применяется"],
                } for axis in request["axes"]]
                return SimpleNamespace(
                    value=parser(json.dumps({"questions": rows}, ensure_ascii=False)),
                    attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = BatchConstraintRejectingClient()
    result = await generate_block_assessment([lesson], facts, client)

    assert len(result.questions) == 2
    constraint_sizes = [len(request["questions"]) for request in client.requests
                        if request["task"] == "assessment_constraints"]
    assert constraint_sizes == [2, 2, 1, 1]


@pytest.mark.asyncio
async def test_no_teachable_question_is_not_padded():
    lesson, facts = fixture()
    client = Client(empty=True)
    result = await generate_block_assessment([lesson], facts, client)
    assert result.questions == ()
    assert len(client.requests) == 1
    assert result.audit["block_outcomes"] == [{
        "block_id": result.audit["block_outcomes"][0]["block_id"], "lesson_id": "l1",
        "fact_ids": ["f1"], "candidates": 0, "accepted": 0,
        "outcome": "no_assessable_questions",
    }]


@pytest.mark.asyncio
async def test_partial_rich_block_recovers_only_missing_axes_before_review():
    facts = {
        f"f{index}": SourceFact(
            f"f{index}",
            "Коллекция",
            attribute,
            value,
            f"doc_id=d1;sheet=Коллекции;row=2;column={attribute}",
        )
        for index, (attribute, value) in enumerate((
            ("Назначение", "Для спальни"),
            ("Материал", "МДФ"),
            ("Открывание", "Push-to-open"),
        ), start=1)
    }
    lesson = LessonDraft(
        "l-rich", "Коллекции", "Коллекция", "Подбирать коллекцию",
        "", tuple(facts), (), 2,
    )

    class PartialClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_generate" and len(request["axes"]) > 1:
                self.requests.append(request)
                axis = request["axes"][0]
                payload = {"questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": f"Каково значение «{axis['attribute']}»?",
                    "distractors": ["Другое значение", "Третье значение"],
                }]}
                return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)),
                                       attempt_count=1)
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = PartialClient()
    result = await generate_block_assessment([lesson], facts, client)

    author_requests = [request for request in client.requests
                       if request["task"] == "assessment_generate"]
    assert [len(request["axes"]) for request in author_requests] == [3, 1, 1]
    assert result.audit["requested_axes"] == 3
    assert result.audit["authored_axes"] == 3


@pytest.mark.asyncio
async def test_failed_repair_provider_is_visible_in_audit_not_silent_drop():
    class RepairOutage(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_repair":
                raise AllProvidersFailedError("fixture", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE])
            return await super().ainvoke_validated(messages, parser, **kwargs)

    lesson, facts = fixture()
    result = await generate_block_assessment([lesson], facts, RepairOutage(bad=True))
    assert result.questions == ()
    assert any(row.get("stage") == "assessment_repair" and
               row["reason"] == "assessment_provider_or_validation_unavailable"
               for row in result.audit["failures"])
    assert result.audit["block_outcomes"][0]["outcome"] == "unavailable"


@pytest.mark.asyncio
async def test_block_outcome_reports_final_deduplicated_acceptance_for_coverage_owner():
    lesson, facts = fixture()
    result = await generate_block_assessment([lesson], facts, Client())
    outcome = result.audit["block_outcomes"]
    assert len(outcome) == 1
    assert outcome[0] == {
        "block_id": result.questions[0].semantic_block_id,
        "lesson_id": lesson.lesson_id,
        "fact_ids": ["f1"],
        "candidates": 1,
        "accepted": 1,
        "outcome": "accepted",
    }


@pytest.mark.asyncio
async def test_source_scope_excludes_other_sections_and_supporting_catalog():
    lesson, facts = fixture()
    facts["other"] = SourceFact("other", "Эскалация", "правило", "Обратитесь к руководителю.", "doc_id=d1;section=escalation")
    facts["catalog"] = SourceFact("catalog", "Список", "артикул", "SKU 900", "doc_id=d1;section=catalog")
    lesson = replace(lesson, supporting_fact_ids=("catalog",))
    client = Client()
    result = await generate_block_assessment([lesson], facts, client)
    serialized = json.dumps(client.requests, ensure_ascii=False)
    assert "Обратитесь к руководителю" not in serialized
    assert "SKU 900" not in serialized
    assert "Исключений для срочных обращений нет" in serialized
    # Coverage receives only planned lesson facts, not supporting catalog context.
    assert result.audit["coverage"]["audit_incomplete"] is False
    assert result.audit["coverage"]["required_topic_count"] == 1
    assert result.audit["coverage"]["missing_fact_ids"] == []


@pytest.mark.asyncio
async def test_oversized_block_is_reported_not_silently_truncated():
    lesson, facts = fixture()
    facts["f1"] = replace(facts["f1"], value=RULE * 1000)
    client = Client()
    result = await generate_block_assessment([lesson], facts, client)
    assert not client.requests
    assert result.audit["failures"][0]["reason"] == "assessment_context_too_large"


@pytest.mark.asyncio
async def test_narrative_paragraph_assessment_is_bounded_to_three_atomic_facts():
    lesson, facts = fixture()
    facts["f1"] = replace(facts["f1"], source_locator="doc_id=d1;section=rules;part=1")
    for index in range(2, 6):
        facts[f"f{index}"] = replace(
            facts["f1"],
            fact_id=f"f{index}",
            value=f"Правило {index} требует проверить обращение до передачи.",
            source_locator=f"doc_id=d1;section=rules;part={index}",
        )
    lesson = replace(lesson, fact_ids=tuple(facts))
    client = Client(empty=True)
    result = await generate_block_assessment([lesson], facts, client)
    assert result.audit["blocks"] == 1
    assert len(client.requests) == 1
    assert len(client.requests[0]["facts"]) == 3
    assert len(client.requests[0]["axes"]) == 3
    omitted = [row for row in result.audit["block_outcomes"]
               if row["outcome"] == "density_omitted"]
    assert len(omitted) == 1
    assert len(omitted[0]["fact_ids"]) == 2
    assert result.audit["coverage"]["audit_incomplete"] is False


@pytest.mark.asyncio
async def test_ambiguous_ocr_formula_symbols_are_not_turned_into_questions():
    lesson, facts = fixture()
    facts["f1"] = replace(
        facts["f1"],
        value="0 -период времени со дня выдачи до первой выплаты Заёмщику;",
        source_locator="doc_id=d1;section=formula;part=1",
    )
    lesson = replace(lesson, fact_ids=("f1",))
    client = Client(empty=True)

    result = await generate_block_assessment([lesson], facts, client)

    assert result.questions == ()
    assert client.requests == []
    assert result.audit["blocks"] == 0


@pytest.mark.asyncio
async def test_review_envelope_is_bounded_even_when_source_fits():
    class LongOptions(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            assert request["task"] == "assessment_generate"
            self.requests.append(request)
            row = {
                "axis_id": request["axes"][0]["axis_id"],
                "prompt": candidate()["prompt"],
                "distractors": [f"{i} " + "слово " * 2000 for i in range(2)],
            }
            return SimpleNamespace(value=parser(json.dumps({"questions": [row]})), attempt_count=1)

    lesson, facts = fixture()
    client = LongOptions()
    result = await generate_block_assessment([lesson], facts, client)
    assert result.questions == ()
    assert len(client.requests) == 1
    assert any(x.get("stage") == "assessment_review" and x["reason"] == "assessment_context_too_large"
               for x in result.audit["failures"])
    assert len(result.audit["failures"]) == 1


def test_repair_does_not_require_model_identity_but_retains_primary_fact():
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions

    lesson, facts = fixture()
    original = _parse_questions(json.dumps({"questions": [candidate()]}),
        lesson_id=lesson.lesson_id, facts=list(facts.values()), maximum=1, block_id="b")[0]
    row = candidate()
    row["repair_of"] = "untrusted-and-ignored"
    repaired = _parse_questions(json.dumps({"questions": [row]}), lesson_id=lesson.lesson_id,
        facts=list(facts.values()), maximum=1, block_id="b", repair_targets={original.question_id: original})
    assert repaired[0].question_id == original.question_id

    other = replace(facts["f1"], fact_id="other")
    row["evidence"][0]["fact_id"] = "other"
    with pytest.raises(ValueError, match="assessment_repair_changed_primary_fact"):
        _parse_questions(json.dumps({"questions": [row]}), lesson_id=lesson.lesson_id,
            facts=[*facts.values(), other], maximum=1, block_id="b", repair_targets={original.question_id: original})


def test_repair_parser_rejects_multiple_server_targets():
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions

    lesson, facts = fixture()
    first, second = candidate(), candidate()
    second["prompt"] = "Отменяет ли срочность запрет на передачу данных в личные каналы?"
    originals = _parse_questions(json.dumps({"questions": [first, second]}),
        lesson_id=lesson.lesson_id, facts=list(facts.values()), maximum=2, block_id="b")
    targets = {q.question_id: q for q in originals}
    with pytest.raises(ValueError, match="assessment_repair_single_target"):
        _parse_questions(json.dumps({"questions": [second, first]}), lesson_id=lesson.lesson_id,
            facts=list(facts.values()), maximum=2, block_id="b", repair_targets=targets)


@pytest.mark.asyncio
async def test_multiple_rejections_create_only_singleton_repair_requests():
    class TwoRejectedClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_repair":
                self.requests.append(request)
                axis = request["axes"][0]
                distractors = OPTIONS[1:]
                if request["rejected"][0]["primary_fact_id"] == "f2":
                    distractors = [
                        "Сотрудник обязан звонить клиенту лично.",
                        "Сотрудник обязан отправить письменное уведомление.",
                    ]
                payload = {"questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": request["rejected"][0]["prompt"],
                    "distractors": distractors,
                }]}
                return SimpleNamespace(
                    value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1,
                )
            if request["task"] != "assessment_generate":
                return await super().ainvoke_validated(messages, parser, **kwargs)
            self.requests.append(request)
            rows = [{
                "axis_id": axis["axis_id"],
                "prompt": "Как передавать персональные данные?" if index == 0 else
                    "Отменяет ли срочность запрет на передачу данных в личные каналы?",
                "distractors": BAD[1:],
            } for index, axis in enumerate(request["axes"][:2])]
            return SimpleNamespace(value=parser(json.dumps({"questions": rows},
                                                            ensure_ascii=False)), attempt_count=1)

    lesson, facts = fixture()
    facts["f2"] = replace(facts["f1"], fact_id="f2", value="Срочность не отменяет правило.")
    lesson = replace(lesson, fact_ids=("f1", "f2"))
    client = TwoRejectedClient(bad=True)
    result = await generate_block_assessment([lesson], facts, client)
    repairs = [request for request in client.requests if request["task"] == "assessment_repair"]
    assert result.questions
    assert len(repairs) == 2
    assert all(request["max_questions"] == 1 and len(request["rejected"]) == 1 for request in repairs)


def test_repair_restores_primary_fact_and_evidence_order():
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions

    lesson, facts = fixture()
    facts["f2"] = replace(facts["f1"], fact_id="f2", value="Отдельное условие.")
    row = candidate()
    row["evidence"].append({"fact_id": "f2", "quote": facts["f2"].value})
    original = _parse_questions(json.dumps({"questions": [row]}), lesson_id=lesson.lesson_id,
        facts=list(facts.values()), maximum=1, block_id="b")[0]
    row["evidence"] = [row["evidence"][1], row["evidence"][0], row["evidence"][1]]
    repaired = _parse_questions(json.dumps({"questions": [row]}), lesson_id=lesson.lesson_id,
        facts=list(facts.values()), maximum=1, block_id="b",
        repair_targets={original.question_id: original})[0]
    assert repaired.fact_id == original.fact_id
    assert repaired.evidence_fact_ids == ("f2", "f1")
    assert repaired.source_quote == f"{facts['f2'].value}\n{facts['f1'].value}"


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed():
    import asyncio

    async def cancel():
        raise asyncio.CancelledError()

    lesson, facts = fixture()
    with pytest.raises(asyncio.CancelledError):
        await generate_block_assessment([lesson], facts, Client(), checkpoint=cancel)


def test_real_provider_channel_refusal_is_not_same_as_refusing_all_channels():
    from app.modules.ai.evidence_engine.models import QuestionDraft
    from app.modules.ai.evidence_engine.quality import question_has_ambiguous_options

    q = QuestionDraft("q", "l", "single_choice",
        "Клиент срочно просит отправить его персональные данные в личный мессенджер сотрудника. Как должен поступить сотрудник?",
        ("Отказать в передаче через личный мессенджер и предложить разрешённый канал",
         "Отправить данные в личный мессенджер, так как клиент настаивает на срочности",
         "Отказать в передаче данных любым каналом до окончания срочного обращения"),
        "Отказать в передаче через личный мессенджер и предложить разрешённый канал",
        RULE, "f")
    assert question_has_ambiguous_options(q)  # captured legacy false positive
    assert not question_has_ambiguous_options(replace(q, semantic_reviewed=True))
    identical = replace(q, semantic_reviewed=True, options=(q.correct_answer, q.correct_answer, "Иное"))
    # Exact duplicates are always rejected by candidate contract, before review.
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions
    lesson, facts = fixture()
    raw = candidate(list(identical.options))
    with pytest.raises(ValueError, match="assessment_question_shape"):
        _parse_questions(json.dumps({"questions": [raw]}), lesson_id=lesson.lesson_id,
                         facts=list(facts.values()), maximum=1, block_id="b")
