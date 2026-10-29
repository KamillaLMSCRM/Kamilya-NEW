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

LENGTH_SIGNAL_DISTRACTORS = [
    (
        "Зарегистрировать приемку полностью, сохранив сведения о возвращенной "
        "единице исключительно во внутриоперационном комментарии."
    ),
    (
        "Передать следующей смене устное уведомление, исключив документирование "
        "результата приемки и возвращенных единиц."
    ),
]


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


def test_same_tabular_attribute_and_short_answer_has_one_course_identity() -> None:
    facts = {
        "north": SourceFact(
            "north", "Север", "Гарантия", "24 месяца",
            "doc_id=d1;source_revision=r1;section=Коллекции;row=2;column=Гарантия",
        ),
        "reef": SourceFact(
            "reef", "Риф", "Гарантия", "24 месяца",
            "doc_id=d1;source_revision=r1;section=Коллекции;row=4;column=Гарантия",
        ),
    }
    first = QuestionDraft(
        "q1", "l1", "single_choice", "Какова гарантия для Север?",
        ("24 месяца", "18 месяцев", "12 месяцев"), "24 месяца", "24 месяца",
        "north", evidence_fact_ids=("north",), semantic_reviewed=True,
    )
    second = replace(
        first, question_id="q2", fact_id="reef", prompt="Какова гарантия для Риф?",
        evidence_fact_ids=("reef",),
    )

    assert _course_question_identity(first, facts) == _course_question_identity(second, facts)


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


@pytest.mark.parametrize("invented_index", [0, 1, 2])
def test_constraint_parser_reports_invented_key_or_undetermined_requirements(invented_index):
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_constraint_reviews

    lesson, facts = fixture()
    question = QuestionDraft(
        "q", lesson.lesson_id, "single_choice", "Как передавать данные?",
        (ATOMIC_RULE, OPTIONS[1], OPTIONS[2]), ATOMIC_RULE, ATOMIC_RULE, "f1",
        evidence_fact_ids=("f1",), semantic_reviewed=True,
    )
    payload = {
        "rules": [{"fact_id": "f1", "quote": ATOMIC_RULE, "kind": "forbidden"}],
        "reviews": [{"question_id": "q", "distinct_errors": True, "reason": "untrusted prose",
                     "options": [{"index": i, "relation": ("entailed" if i == 0 else
                                                            "undetermined" if i == invented_index else "contradicted"),
                                  "invented_constraint": i == invented_index,
                                  "realistic_error": i > 0} for i in range(3)]}],
    }
    verdicts = _parse_constraint_reviews(json.dumps(payload), [question], list(facts.values()))
    assert not verdicts["q"]
    assert f"constraint_option_{invented_index}:invented_constraint" in verdicts.reasons["q"]


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


def test_repair_feedback_uses_original_option_identity_after_review_pruning():
    from app.modules.ai.evidence_engine.semantic_assessment import (
        _original_option_reasons,
        _rejected_option_feedback,
    )

    original = QuestionDraft("q", "l", "single_choice", "Вопрос?",
                             ("Ключ", "Снят при первой проверке", "Допустимая ошибка", "Новое условие"),
                             "Ключ", "Пояснение", "f1")
    reviewed = replace(original, options=(original.options[0], *original.options[2:]))
    reasons = _original_option_reasons(reviewed, original, [
        "constraint_option_2:invented_constraint", "constraint_duplicate_misconceptions",
    ])
    assert reasons == ["constraint_option_3:invented_constraint", "constraint_duplicate_misconceptions"]
    feedback = _rejected_option_feedback(original, reasons)
    assert feedback == [{"index": 3, "text": "Новое условие",
                         "reasons": ["constraint_option_3:invented_constraint"]}]


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
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_lesson_length_signal_gets_only_existing_single_repair_and_cannot_escape_by_omission(repair_succeeds):
    class LengthSignalClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] not in {"assessment_generate", "assessment_repair"}:
                return await super().ainvoke_validated(messages, parser, **kwargs)
            self.requests.append(request)
            repairing = request["task"] == "assessment_repair"
            rows = []
            for index, axis in enumerate(request["axes"]):
                distractors = LENGTH_SIGNAL_DISTRACTORS
                if repairing and repair_succeeds:
                    distractors = [
                        "Отметить всю накладную как принятую и передать непринятую единицу следующей смене без отдельного отражения возврата.",
                        "При передаче смены сотрудник сообщает о результате приемки только устно, оставляя журнал без записи и не передавая сведения о непринятых единицах товара.",
                    ]
                rows.append({"axis_id": axis["axis_id"],
                             "prompt": (request["rejected"][0]["prompt"] if repairing else
                                        f"Как выполнить обязательное действие {index + 1} при приемке?"),
                             "distractors": distractors})
            return SimpleNamespace(value=parser(json.dumps({"questions": rows}, ensure_ascii=False)),
                                   attempt_count=1)

    claims = [
        "При частичной приемке нельзя отмечать всю накладную как принятую, если хотя бы одна единица возвращена.",
        "При передаче смены сотрудник обязан записать результат приемки в журнал и передать следующей смене сведения о непринятых единицах товара.",
    ]
    facts = {f"f{index}": SourceFact(f"f{index}", "Приемка", "правило", claim,
                                      "doc_id=d1;section=acceptance")
             for index, claim in enumerate(claims)}
    lesson = LessonDraft("l1", "Работа", "Приемка товара", "Отразить приемку",
                         " ".join(claims), tuple(facts), (), 1)
    client = LengthSignalClient()
    result = await generate_block_assessment([lesson], facts, client)
    repairs = [request for request in client.requests if request["task"] == "assessment_repair"]
    assert len(repairs) == 1
    assert repairs[0]["rejected"][0]["rejection_reasons"] == ["assessment_answer_length_signal"]
    assert len(client.requests) == (6 if repair_succeeds else 4)
    if repair_succeeds:
        assert len(result.questions) == 2
        assert result.audit["unresolved_quality_signals"] == []
        assert result.audit["repaired"] == 1
    else:
        assert len(result.questions) == 1
        assert result.audit["unresolved_quality_signals"]
        assert result.audit["unresolved_quality_signals"][0]["lesson_id"] == "l1"
    assert all(question.correct_answer in claims for question in result.questions)


@pytest.mark.asyncio
async def test_shape_recovery_precedes_the_separate_singleton_semantic_repair():
    class CombinedFeedbackClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] in {"assessment_generate", "assessment_repair"}:
                self.requests.append(request)
                repairing = request["task"] == "assessment_repair"
                recovering = bool(request.get("rejected"))
                if recovering:
                    reasons = request["rejected"][0]["rejection_reasons"]
                    if not repairing:
                        assert "assessment_answer_length_signal" in reasons
                        assert request["rejected"][0]["answer_shape"]["source_claim_chars"] >= 80
                    else:
                        assert "assessment_answer_length_signal" not in reasons
                        assert reasons  # independent semantic rejection, not another shape retry
                rows = [{"axis_id": axis["axis_id"],
                         "prompt": (request["rejected"][0]["prompt"] if recovering else
                                    f"Как выполнить обязательное действие {index + 1} при приемке?"),
                         "distractors": ([
                             "При передаче смены сотрудник оставляет сведения о непринятых единицах только у себя и не делает записи в журнале.",
                             "При частичном возврате всю накладную отмечают принятой, а информацию о возвращённом товаре не передают следующей смене.",
                         ] if repairing else [
                             "При передаче смены сотрудник сообщает о результате приемки только устно, оставляя журнал без записи и не передавая сведения о непринятых единицах товара.",
                             "Отметить всю накладную как принятую и передать непринятую единицу следующей смене без отдельного отражения возврата.",
                         ] if recovering else ["Принять всё сразу.", "Передать устно."])}
                        for index, axis in enumerate(request["axes"])]
                return SimpleNamespace(value=parser(json.dumps({"questions": rows}, ensure_ascii=False)),
                                       attempt_count=1)
            if request["task"] == "assessment_review" and not any(
                prior["task"] == "assessment_repair" for prior in self.requests
            ):
                self.requests.append(request)
                payload = verdict(request, reject=True)
                return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1)
            return await super().ainvoke_validated(messages, parser, **kwargs)

    claims = [
        "При частичной приемке нельзя отмечать всю накладную как принятую, если хотя бы одна единица возвращена.",
        "При передаче смены сотрудник обязан записать результат приемки в журнал и передать следующей смене сведения о непринятых единицах товара.",
    ]
    facts = {f"f{index}": SourceFact(f"f{index}", "Приемка", "правило", claim,
                                   "doc_id=d1;section=acceptance")
             for index, claim in enumerate(claims)}
    lesson = LessonDraft("l1", "Работа", "Приемка товара", "Отразить приемку",
                         " ".join(claims), tuple(facts), (), 1)
    client = CombinedFeedbackClient()
    result = await generate_block_assessment([lesson], facts, client)
    assert len(result.questions) == 2
    assert result.audit["unresolved_quality_signals"] == []
    repairs = [request for request in client.requests if request["task"] == "assessment_repair"]
    assert len(repairs) == 2  # exactly one repair per rejected question, never a second round
    assert result.audit["attempt_counts"]["replacement"] == 2
    assert result.audit["attempt_counts"]["model_repair"] == 2
    assert all(question.correct_answer in claims for question in result.questions)


@pytest.mark.parametrize(("option", "restates"), [
    ("Проект нельзя публиковать, если он имеет статус «на доработку» или «отклонено», но уведомление подготовлено.", True),
    ("Проект нельзя публиковать, если он имеет статус «на доработку» или «отклонено».", True),
    ("Проект можно публиковать, если он имеет статус «на доработку» или «отклонено».", False),
    ("Проект нельзя публиковать только если он имеет статус «на доработку» или «отклонено».", False),
    ("Проект нельзя публиковать, если он имеет статус «одобрено».", False),
    ("Уведомление нельзя публиковать, если оно имеет статус «на доработку» или «отклонено».", False),
])
def test_truth_preserving_prohibition_is_not_a_wrong_answer(option, restates):
    from app.modules.ai.evidence_engine.semantic_assessment import _restates_conditional_prohibition

    key = "Нельзя публиковать проект, который имеет статус «на доработку» или «отклонено»."
    assert _restates_conditional_prohibition(key, option) is restates


@pytest.mark.asyncio
async def test_final_deduplication_cannot_expose_an_unreported_length_signal(monkeypatch):
    class ThreeQuestionClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] != "assessment_generate":
                return await super().ainvoke_validated(messages, parser, **kwargs)
            self.requests.append(request)
            rows = [{"axis_id": axis["axis_id"],
                     "prompt": f"Как выполнить действие {index + 1} при приемке?",
                     "distractors": (LENGTH_SIGNAL_DISTRACTORS if index < 2 else
                                     ["Ответственный сотрудник отмечает всю накладную как принятую и передает непринятую единицу следующей смене без записи в журнал.",
                                      "Сообщить о непринятом товаре только устно."])}
                    for index, axis in enumerate(request["axes"])]
            assert len(rows) == 3
            return SimpleNamespace(value=parser(json.dumps({"questions": rows}, ensure_ascii=False)), attempt_count=1)

    claims = [
        "При частичной приемке нельзя отмечать всю накладную как принятую, если хотя бы одна единица возвращена.",
        "При передаче смены сотрудник обязан записать результат приемки в журнал и передать следующей смене сведения о непринятых единицах товара.",
        "Сотрудник обязан записать возврат товара в журнал приемки.",
    ]
    facts = {f"f{index}": SourceFact(f"f{index}", "Приемка", "правило", claim,
                                      "doc_id=d1;section=acceptance")
             for index, claim in enumerate(claims)}
    lesson = LessonDraft("l1", "Работа", "Приемка товара", "Отразить приемку",
                         " ".join(claims), tuple(facts), (), 1)
    # A deterministic duplicate-identity seam models late removal of the only
    # non-signalling question; it must not cause another paid repair loop.
    identities = iter([("first",), ("second",), ("first",)])
    monkeypatch.setattr("app.modules.ai.evidence_engine.semantic_assessment._course_question_identity",
                        lambda *_: next(identities))
    client = ThreeQuestionClient()
    result = await generate_block_assessment([lesson], facts, client)
    assert len(result.questions) == 2
    assert len(client.requests) == 3
    assert result.audit["unresolved_quality_signals"]
    assert result.audit["terminal_status"] == "review_required"


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
    assert repair["rejected"][0]["rejected_options"] == [
        {"index": 1, "text": repair["rejected"][0]["options"][1],
         "reasons": ["constraint_option_1:expected_contradicted_got_undetermined"]},
        {"index": 2, "text": repair["rejected"][0]["options"][2],
         "reasons": ["constraint_option_2:expected_contradicted_got_undetermined"]},
    ]
    assert "untrusted model prose" not in json.dumps(repair)


@pytest.mark.asyncio
@pytest.mark.parametrize("reorder", [False, True])
async def test_unchanged_rejected_repair_is_not_reviewed_and_audited_again(reorder):
    class NoProgressClient(Client):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] != "assessment_constraints":
                result = await super().ainvoke_validated(messages, parser, **kwargs)
                if reorder and request["task"] == "assessment_repair":
                    return SimpleNamespace(value=[replace(question, options=tuple(reversed(question.options)))
                                                  for question in result.value], attempt_count=1)
                return result
            self.requests.append(request)
            facts = {fact["fact_id"]: fact for fact in request["facts"]}
            payload = {"rules": [{"fact_id": fid, "quote": fact["value"], "kind": "required"}
                                 for fid, fact in facts.items()],
                       "reviews": [{"question_id": q["question_id"], "reason": "same misconception",
                                    "distinct_errors": False,
                                    "options": [{"index": i, "relation": "entailed" if i == 0 else "contradicted",
                                                 "invented_constraint": False, "realistic_error": True}
                                                for i in range(len(q["options"]))]}
                                   for q in request["questions"]]}
            return SimpleNamespace(value=parser(json.dumps(payload)), attempt_count=1)

    lesson, facts = fixture()
    client = NoProgressClient()
    result = await generate_block_assessment([lesson], facts, client)
    # An exhausted no-progress repair cannot trigger new provider calls. Its
    # existing two positive audits may now retain one exact wrong alternative.
    assert len(result.questions) == 1
    question = result.questions[0]
    assert question.kind == "single_choice" and len(question.options) == 2
    assert question.correct_answer == ATOMIC_RULE
    assert set(question.options) <= {ATOMIC_RULE, *OPTIONS[1:]}
    assert [request["task"] for request in client.requests] == [
        "assessment_generate", "assessment_review", "assessment_constraints", "assessment_repair",
    ]
    assert any("assessment_repair_no_progress" in row["reasons"]
               for row in result.audit["post_review_pruned"])

@pytest.mark.asyncio
async def test_failed_repair_drops_question_without_quota_padding():
    lesson, facts = fixture()
    client = Client(bad=True, repair=False)
    result = await generate_block_assessment([lesson], facts, client)
    assert result.questions == ()
    assert len(client.requests) == 3
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
                    "distractors": (
                        ["Заявление рассматривается в течение 30 дней.",
                         "Заявление рассматривается в течение 45 дней."]
                        if "15 дней" in axis["source_claim"] else OPTIONS[1:]
                    ),
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
                    "distractors": (
                        ["Заявление рассматривается в течение 30 дней.",
                         "Заявление рассматривается в течение 45 дней."]
                        if "15 дней" in axis["source_claim"] else OPTIONS[1:]
                    ),
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
@pytest.mark.parametrize("extra_attributes", [0, 1, 2])
async def test_spreadsheet_question_budget_covers_distinct_entities_before_more_attributes(extra_attributes):
    facts: dict[str, SourceFact] = {}
    ordered_ids: list[str] = []
    for row, subject, warranty, purpose in (
        (2, "Север", "24 месяца", "Для прихожей"),
        (3, "Берег", "18 месяцев", "Для спальни"),
        (4, "Риф", "24 месяца", "Для гостиной"),
    ):
        row_values = [("warranty", "Гарантия", warranty)]
        if extra_attributes >= 1:
            row_values.append(("purpose", "Назначение", purpose))
        if extra_attributes >= 2:
            row_values.append(("material", "Материал", "Массив сосны"))
        for suffix, attribute, value in row_values:
            fact_id = f"{row}-{suffix}"
            facts[fact_id] = SourceFact(
                fact_id, subject, attribute, value,
                f"doc_id=d1;section=Коллекции;row={row};column={attribute}",
            )
            ordered_ids.append(fact_id)
    lesson = LessonDraft(
        "l-catalog", "Коллекции", "Основные характеристики", "Сравнивать коллекции",
        "", tuple(ordered_ids), (), 2,
    )

    client = Client(empty=True)
    result = await generate_block_assessment([lesson], facts, client)

    requested_axes = [
        axis
        for request in client.requests
        if request["task"] == "assessment_generate"
        for axis in request["axes"]
    ]
    assert result.audit["requested_axes"] == 3
    assert {axis["subject"] for axis in requested_axes} == {"Север", "Берег", "Риф"}
    assert len({axis["attribute"] for axis in requested_axes}) == extra_attributes + 1
    assert result.questions == ()


def _reporting_peer_fixture():
    facts = {}
    for row, subject, value in (
        (2, "Старт", "итоговый статус"),
        (3, "Команда", "статус и прогресс"),
        (4, "Организация", "статус, прогресс и экспорт"),
    ):
        fact_id = f"report-{row}"
        facts[fact_id] = SourceFact(
            fact_id, subject, "Отчётность", value,
            f"doc_id=matrix;source_revision=revision1;section=Пакеты;table=1;row={row};column=3",
        )
    lesson = LessonDraft("reporting", "Пакеты", "Отчётность", "Сравнивать отчётность", "",
                         tuple(facts), (), 2)
    return lesson, facts


@pytest.mark.asyncio
async def test_exact_table_peer_candidates_still_need_blind_review_and_constraint_audit():
    lesson, facts = _reporting_peer_fixture()
    client = Client(empty=True)
    result = await generate_block_assessment([lesson], facts, client)
    assert len(result.questions) == 3
    assert result.audit["source_peer_candidates"] == 3
    assert [request["task"] for request in client.requests] == [
        "assessment_review", "assessment_constraints",
    ] * 3
    for question in result.questions:
        primary = facts[question.fact_id]
        assert question.correct_answer == primary.value
        assert question.evidence_fact_ids == (primary.fact_id,)
        assert set(question.options) == {fact.value for fact in facts.values()}
        assert question.semantic_reviewed


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "document", "revision", "section", "table", "column", "missing_revision", "missing_row",
    "merged_row", "duplicate_subject", "duplicate_value", "uncertainty", "low_confidence",
    "predicate", "supporting_only", "sheet_without_table", "row_alias",
])
async def test_table_peer_shortcut_does_not_cross_uncertain_or_ambiguous_source_scope(mutation):
    lesson, facts = _reporting_peer_fixture()
    peer = facts["report-3"]
    tokens = {"document": ("doc_id=matrix", "doc_id=elsewhere"),
              "revision": ("source_revision=revision1", "source_revision=revision2"),
              "section": ("section=Пакеты", "section=Иное"),
              "table": ("table=1", "table=2"), "column": ("column=3", "column=4"),
              "missing_revision": ("source_revision=revision1;", ""),
              "missing_row": ("row=3;", ""), "merged_row": ("row=3", "row=3-4"),
              "row_alias": ("row=3", "row=02")}
    if mutation in tokens:
        before, after = tokens[mutation]
        peer = replace(peer, source_locator=peer.source_locator.replace(before, after))
    elif mutation == "duplicate_subject":
        peer = replace(peer, subject=facts["report-2"].subject)
    elif mutation == "duplicate_value":
        peer = replace(peer, value=facts["report-2"].value)
    elif mutation == "uncertainty":
        peer = replace(peer, uncertainty="local_ocr")
    elif mutation == "low_confidence":
        peer = replace(peer, confidence=0.9)
    elif mutation == "predicate":
        peer = replace(peer, value="статус и прогресс, если запрос подтверждён")
    elif mutation == "supporting_only":
        lesson = replace(lesson, fact_ids=("report-2", "report-4"), supporting_fact_ids=("report-3",))
    elif mutation == "sheet_without_table":
        facts = {fid: replace(fact, source_locator=fact.source_locator.replace(
            "table=1;", "sheet=Пакеты;")) for fid, fact in facts.items()}
        peer = facts["report-3"]
    facts["report-3"] = peer
    result = await generate_block_assessment([lesson], facts, Client(empty=True))
    assert result.questions == ()
    assert result.audit.get("source_peer_candidates", 0) == 0


@pytest.mark.asyncio
async def test_table_peer_candidates_are_not_accepted_without_independent_review():
    lesson, facts = _reporting_peer_fixture()
    result = await generate_block_assessment([lesson], facts, Client(empty=True, outage=True))
    assert result.questions == ()
    assert result.audit.get("source_peer_candidates", 0) == 3
    assert result.audit["failures"]


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
            if request["task"] == "assessment_generate":
                self.requests.append(request)
                axis = request["axes"][0]
                payload = {"questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": f"Каково значение «{axis['attribute']}»?",
                    "distractors": ["Другая коллекция", "Третья коллекция"],
                }]}
                return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)),
                                       attempt_count=1)
            return await super().ainvoke_validated(messages, parser, **kwargs)

    client = PartialClient()
    result = await generate_block_assessment([lesson], facts, client)

    author_requests = [request for request in client.requests
                       if request["task"] == "assessment_generate"]
    assert [len(request["axes"]) for request in author_requests] == [3, 1, 1]
    assert result.audit["derived_axes"] == 3
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
async def test_narrative_assessment_budget_follows_independent_source_targets():
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
    assert len(client.requests) == 2
    assert sum(len(r["axes"]) for r in client.requests) == 5
    assert all(len(r["axes"]) <= 4 for r in client.requests)
    omitted = [row for row in result.audit["block_outcomes"]
               if row["outcome"] == "density_omitted"]
    assert omitted == []
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
    assert any(x.get("stage") == "assessment_generate" and x["reason"] == "assessment_context_too_large"
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
