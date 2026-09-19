"""Contract tests for the DEV-only objective-alignment experiment.

These prove deterministic provenance and structural rejection only. They do not
claim that normalized strings establish real instructional or semantic quality.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from scripts.dev.objective_alignment.engine import (
    generate,
    parse_plan,
    parse_quiz,
    parse_teaching,
)


FACTS = {
    "f1": SourceFact("f1", "Device", "storage", "Store the unit upright during transport.", "p1"),
    "f2": SourceFact("f2", "Device", "inspection", "Inspect the seal before each use.", "p2"),
}


def dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def plan(*, objectives=None, omitted=None) -> dict:
    return {
        "objectives": objectives if objectives is not None else [{
            "id": "o1",
            "learner_action": "Transport the device in the required orientation",
            "decision": "Keep the device upright during transport",
            "conditions": "During transport",
            "evidence": [{"fact_id": "f1", "quote": "Store the unit upright during transport."}],
        }],
        "omitted": omitted if omitted is not None else [
            {"fact_id": "f2", "reason": "Informational detail not needed for this objective"}
        ],
    }


def valid_plan():
    return parse_plan(dump(plan()), FACTS)


def teaching() -> dict:
    return {"blocks": [{
        "objective_id": "o1",
        "heading": "Upright transport",
        "explanation": "Keep the device upright whenever it is transported to preserve the required orientation.",
        "application": "Before moving it, confirm the device remains upright.",
    }]}


def quiz(*, options=None, taught_quote="Keep the device upright whenever it is transported") -> dict:
    return {"items": [{
        "objective_id": "o1",
        "prompt": "How should the device be positioned during transport?",
        "options": options if options is not None else [
            {"text": "Keep the device upright", "correct": True, "action_or_property": "keep upright", "error_mechanism": ""},
            {"text": "Lay the device on its side", "correct": False, "action_or_property": "lay on side", "error_mechanism": "wrong orientation"},
        ],
        "taught_quote": taught_quote,
        "explanation": "The source requires upright transport.",
    }], "unassessable": []}


@pytest.mark.parametrize("raw", [
    plan(omitted=[]),
    plan(omitted=[{"fact_id": "unknown", "reason": "This unsupported fact is informational"}]),
])
def test_parse_plan_rejects_missing_or_unknown_fact_accounting(raw):
    with pytest.raises(ValueError, match="unaccounted_or_unknown_fact"):
        parse_plan(dump(raw), FACTS)


def test_parse_plan_rejects_invalid_source_quote():
    raw = plan()
    raw["objectives"][0]["evidence"][0]["quote"] = "Invented source statement."
    with pytest.raises(ValueError, match="invalid_source_quote"):
        parse_plan(dump(raw), FACTS)


def test_parse_plan_expands_valid_partial_citation_to_the_complete_source_fact():
    full_source = "Keep upright. Use only the approved carrier. Urgency is no exception."
    facts = {"f1": SourceFact("f1", "Device", "transport", full_source, "p1")}
    raw = plan(
        objectives=[{
            **plan()["objectives"][0],
            "evidence": [{"fact_id": "f1", "quote": "Keep upright."}],
        }],
        omitted=[],
    )

    parsed = parse_plan(dump(raw), facts)

    assert parsed.objectives[0].evidence[0].quote == full_source


def test_parse_plan_drops_redundant_omission_for_an_already_cited_fact():
    raw = plan(omitted=[
        {"fact_id": "f1", "reason": "The cited fact is already used by the objective"},
        {"fact_id": "f2", "reason": "Informational detail not needed for this objective"},
    ])

    parsed = parse_plan(dump(raw), FACTS)

    assert [item.fact_id for item in parsed.omitted] == ["f2"]


def test_parse_plan_rejects_same_decision_even_with_distinct_ids():
    raw = plan(objectives=[
        plan()["objectives"][0],
        {**plan()["objectives"][0], "id": "o2", "decision": " keep the device upright during transport! "},
    ], omitted=[{"fact_id": "f2", "reason": "Informational detail not needed for this objective"}])
    with pytest.raises(ValueError, match="duplicate_decision"):
        parse_plan(dump(raw), FACTS)


def test_parse_plan_replaces_not_required_prohibition_with_source_tethered_objective():
    source = ("Первый ответ подтверждает приём обращения и сообщает следующий шаг. "
              "Окончательное решение в первом ответе не требуется.")
    facts, _ = _russian_plan_and_lesson(
        source, decision="Составить первый ответ с подтверждением и следующим шагом"
    )
    raw = {
        "objectives": [{
            "id": "o1",
            "learner_action": "Составить первый ответ без окончательного решения",
            "decision": "Не включать окончательное решение в первый ответ",
            "conditions": "Окончательное решение в первом ответе не требуется",
            "normative_force": "mixed",
            "evidence": [{"fact_id": "ru1", "quote": source}],
        }],
        "omitted": [],
    }
    parsed = parse_plan(dump(raw), facts)

    objective = parsed.objectives[0]
    assert objective.source_tethered is True
    assert objective.decision == source
    assert "не включать" not in objective.learner_action.casefold()


def test_parse_teaching_rejects_missing_or_extra_objective_block():
    raw = {"blocks": [{**teaching()["blocks"][0], "objective_id": "other"}]}
    with pytest.raises(ValueError, match="teaching_objective_mismatch"):
        parse_teaching(dump(raw), valid_plan())


def test_parse_teaching_fills_missing_objective_from_its_complete_source():
    raw_plan = plan(omitted=[])
    raw_plan["objectives"].append({
        **raw_plan["objectives"][0],
        "id": "o2",
        "learner_action": "Inspect the seal before each use of the device",
        "decision": "Inspect the seal before use",
        "conditions": "Before each use",
        "evidence": [{"fact_id": "f2", "quote": FACTS["f2"].value}],
    })
    parsed_plan = parse_plan(dump(raw_plan), FACTS)

    parsed = parse_teaching(dump(teaching()), parsed_plan)

    assert [block.objective_id for block in parsed.blocks] == ["o1", "o2"]
    assert parsed.blocks[1].source_tethered is True
    assert FACTS["f2"].value in parsed.blocks[1].explanation


def test_parse_teaching_replaces_new_material_scenario_details_with_source_tethered_block():
    source = ("Персональные данные нельзя передавать в личные мессенджеры. "
              "Используется только разрешённый канал; срочность не является исключением.")
    _, raw_plan = _russian_plan_and_lesson(
        source, decision="При передаче персональных данных выбрать разрешённый канал",
        conditions="Срочность не является исключением",
    )
    raw = {"blocks": [{
        "objective_id": "o1", "heading": "Разрешённый канал",
        "explanation": source,
        "application": ("Если коллега просит данные, а разрешённый канал недоступен, "
                        "нужно дождаться его доступности."),
    }]}
    parsed = parse_teaching(dump(raw), raw_plan)
    block = parsed.blocks[0]
    assert block.source_tethered is True
    assert block.explanation == source
    assert "коллега" not in block.application.casefold()
    assert "недоступ" not in block.application.casefold()


def test_parse_teaching_accepts_source_tethered_russian_application():
    source = ("Персональные данные нельзя передавать в личные мессенджеры. "
              "Используется только разрешённый канал; срочность не является исключением.")
    _, raw_plan = _russian_plan_and_lesson(
        source, decision="При передаче персональных данных выбрать разрешённый канал",
        conditions="Срочность не является исключением",
    )
    raw = {"blocks": [{
        "objective_id": "o1", "heading": "Разрешённый канал",
        "explanation": source,
        "application": ("При срочности персональные данные передаются только через "
                        "разрешённый канал, а не в личный мессенджер."),
    }]}
    parsed = parse_teaching(dump(raw), raw_plan)
    assert parsed.blocks[0].application.startswith("При срочности")
    assert parsed.blocks[0].source_tethered is False


def test_parse_quiz_rejects_missing_objective_id():
    raw = {"items": [], "unassessable": []}
    with pytest.raises(ValueError, match="assessment_objective_mismatch"):
        parse_quiz(dump(raw), valid_plan(), "lesson text")


def test_parse_quiz_rejects_multiple_correct_options():
    options = quiz()["items"][0]["options"]
    options[1]["correct"] = True
    with pytest.raises(ValueError, match="single_correct_required"):
        parse_quiz(dump(quiz(options=options)), valid_plan(), "Keep the device upright whenever it is transported")


def test_parse_quiz_drops_duplicate_wrong_action_despite_different_excuses():
    options = [
        {"text": "Keep the device upright", "correct": True, "action_or_property": "keep upright", "error_mechanism": ""},
        {"text": "Keep it sideways for speed", "correct": False, "action_or_property": "Lay it on its side.", "error_mechanism": "faster handling"},
        {"text": "Keep it sideways for space", "correct": False, "action_or_property": " lay it on its side ", "error_mechanism": "save storage space"},
    ]
    parsed = parse_quiz(
        dump(quiz(options=options)), valid_plan(),
        "Keep the device upright whenever it is transported",
    )

    assert [option.text for option in parsed.items[0].options] == [
        "Keep the device upright", "Keep it sideways for speed",
    ]


@pytest.mark.parametrize(("raw", "error"), [
    (quiz(options=[
        {"text": "Keep the device upright", "correct": True, "action_or_property": "keep upright", "error_mechanism": ""},
        {"text": "Lay the device on its side", "correct": False, "action_or_property": "lay on side", "error_mechanism": ""},
    ]), "duplicate_or_empty_error"),
    (quiz(taught_quote="This was never taught"), "not_taught_quote"),
])
def test_parse_quiz_rejects_missing_error_or_wrong_taught_quote(raw, error):
    with pytest.raises(ValueError, match=error):
        parse_quiz(dump(raw), valid_plan(), "Keep the device upright whenever it is transported")


def test_parse_quiz_accepts_meaningfully_distinct_same_subject_alternatives():
    options = [
        {"text": "Keep the device upright", "correct": True, "action_or_property": "keep upright", "error_mechanism": ""},
        {"text": "Lay the device on its side", "correct": False, "action_or_property": "lay on side", "error_mechanism": "wrong orientation"},
        {"text": "Invert the device", "correct": False, "action_or_property": "invert device", "error_mechanism": "reversed orientation"},
    ]
    parsed = parse_quiz(dump(quiz(options=options)), valid_plan(), "Keep the device upright whenever it is transported")
    assert len(parsed.items[0].options) == 3


def _russian_plan_and_lesson(source_value, *, decision, conditions=""):
    facts = {"ru1": SourceFact("ru1", "Правило", "положение", source_value, "p1")}
    raw = plan(objectives=[{
        "id": "o1", "learner_action": decision, "decision": decision,
        "conditions": conditions, "normative_force": "mixed",
        "evidence": [{"fact_id": "ru1", "quote": source_value}],
    }], omitted=[])
    return facts, parse_plan(dump(raw), facts)


def test_parse_quiz_rejects_new_scenario_condition_and_action_absent_from_source():
    source = ("Персональные данные нельзя передавать в личные мессенджеры. "
              "Используется только разрешённый канал; срочность не является исключением.")
    facts, raw_plan = _russian_plan_and_lesson(
        source, decision="При передаче персональных данных выбрать разрешённый канал",
        conditions="Срочность не является исключением",
    )
    raw_quiz = quiz(taught_quote=source)
    raw_quiz["items"][0].update({
        "prompt": ("Нужно срочно передать персональные данные, а разрешённый канал "
                   "временно недоступен. Как следует поступить?"),
        "options": [
            {"text": "Дождаться доступности разрешённого канала и передать данные только через него",
             "correct": True, "action_or_property": "дождаться доступности", "error_mechanism": ""},
            {"text": "Передать данные в личный мессенджер", "correct": False,
             "action_or_property": "передать в личный мессенджер", "error_mechanism": "неверный канал"},
        ],
    })
    with pytest.raises(ValueError, match="unsupported_scenario_terms"):
        parse_quiz(dump(raw_quiz), raw_plan, source)
    assert facts["ru1"].value == source


def test_parse_quiz_neutralizes_unsupported_requirement_in_stem_when_key_is_supported():
    source = ("Персональные данные нельзя передавать в личные мессенджеры. "
              "Используется только разрешённый канал; срочность не является исключением.")
    _, raw_plan = _russian_plan_and_lesson(
        source, decision="При передаче персональных данных выбрать разрешённый канал",
        conditions="Срочность не является исключением",
    )
    raw_quiz = quiz(taught_quote=source)
    raw_quiz["items"][0].update({
        "prompt": ("Возникла необходимость передать персональные данные срочно. "
                   "Какой канал используется?"),
        "options": [
            {"text": "Только разрешённый канал", "correct": True,
             "action_or_property": "разрешённый канал", "error_mechanism": ""},
            {"text": "Личный мессенджер", "correct": False,
             "action_or_property": "личный мессенджер", "error_mechanism": "неразрешённый канал"},
        ],
    })

    parsed = parse_quiz(dump(raw_quiz), raw_plan, source)

    assert parsed.items[0].prompt == "Какой вариант соответствует правилу из материала?"
    assert parsed.items[0].source_tethered is True


def test_parse_quiz_rejects_not_required_rewritten_as_without():
    source = ("Первый ответ подтверждает приём обращения и сообщает следующий шаг. "
              "Окончательное решение в первом ответе не требуется.")
    _, raw_plan = _russian_plan_and_lesson(
        source, decision="Составить первый ответ с подтверждением и следующим шагом",
    )
    raw_quiz = quiz(taught_quote=source)
    raw_quiz["items"][0].update({
        "prompt": "Что должен содержать первый ответ на обращение?",
        "options": [
            {"text": "Подтверждение приёма и следующий шаг без окончательного решения",
             "correct": True, "action_or_property": "ответ без окончательного решения", "error_mechanism": ""},
            {"text": "Только окончательное решение", "correct": False,
             "action_or_property": "только решение", "error_mechanism": "пропуск обязательных частей"},
        ],
    })
    with pytest.raises(ValueError, match="optional_exclusion"):
        parse_quiz(dump(raw_quiz), raw_plan, source)


def test_parse_quiz_accepts_direct_source_tethered_russian_decision():
    source = ("Персональные данные нельзя передавать в личные мессенджеры. "
              "Используется только разрешённый канал; срочность не является исключением.")
    _, raw_plan = _russian_plan_and_lesson(
        source, decision="При передаче персональных данных выбрать разрешённый канал",
        conditions="Срочность не является исключением",
    )
    raw_quiz = quiz(taught_quote=source)
    raw_quiz["items"][0].update({
        "prompt": "Какой канал используется для передачи персональных данных при срочности?",
        "options": [
            {"text": "Только разрешённый канал", "correct": True,
             "action_or_property": "разрешённый канал", "error_mechanism": ""},
            {"text": "Личный мессенджер", "correct": False,
             "action_or_property": "личный мессенджер", "error_mechanism": "неразрешённый канал"},
        ],
    })
    parsed = parse_quiz(dump(raw_quiz), raw_plan, source)
    assert parsed.items[0].options[0].text == "Только разрешённый канал"


def test_parse_quiz_accepts_source_faithful_responsibility_paraphrase():
    source = ("Сотрудник продолжает отслеживать обращение после эскалации. "
              "Ответственность переходит только после явного подтверждения принимающей стороны.")
    _, raw_plan = _russian_plan_and_lesson(
        source,
        decision="Продолжать отслеживать обращение до явного подтверждения принимающей стороны",
        conditions="После эскалации",
    )
    raw_quiz = quiz(taught_quote=source)
    raw_quiz["items"][0].update({
        "prompt": "Когда сотрудник может считать ответственность перешедшей?",
        "options": [
            {"text": "Только после явного подтверждения принимающей стороны", "correct": True,
             "action_or_property": "переход после явного подтверждения", "error_mechanism": ""},
            {"text": "Сразу после эскалации", "correct": False,
             "action_or_property": "переход при эскалации", "error_mechanism": "слишком ранний переход"},
        ],
    })
    parsed = parse_quiz(dump(raw_quiz), raw_plan, source)
    assert parsed.items[0].prompt.startswith("Когда сотрудник")


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def ainvoke_validated(self, messages, *, parser, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(value=parser(next(self.responses)))


@pytest.mark.asyncio
async def test_generate_passes_source_to_plan_and_final_lesson_to_quiz():
    lesson = LessonDraft("l1", "Module", "Title", "old", "", ("f1", "f2"), (), 5)
    client = FakeClient([dump(plan()), dump(teaching()), dump(quiz())])

    result = await generate([lesson], FACTS, client, audit_enabled=False, contract_retries=0)

    payloads = [json.loads(call[0][1]["content"]) for call in client.calls]
    assert [payload["task"] for payload in payloads] == ["objective_plan", "objective_teaching", "objective_assessment"]
    assert payloads[0]["facts"] == [
        {"fact_id": fact.fact_id, "subject": fact.subject, "attribute": fact.attribute,
         "value": fact.value, "source_locator": fact.source_locator,
         "confidence": fact.confidence, "uncertainty": fact.uncertainty}
        for fact in FACTS.values()
    ]
    assert payloads[2]["lesson"] == result["realized_course"]["lessons"][0]["content"]


@pytest.mark.asyncio
async def test_contract_retry_is_identified_as_a_separate_reasoning_role():
    lesson = LessonDraft("l1", "Module", "Title", "old", "", ("f1", "f2"), (), 5)
    invalid = plan()
    invalid["objectives"][0]["evidence"][0]["quote"] = "Not in the source."
    client = FakeClient([dump(invalid), dump(plan()), dump(teaching()), dump(quiz())])

    await generate([lesson], FACTS, client, audit_enabled=False, contract_retries=1)

    tasks = [json.loads(call[0][1]["content"])["task"] for call in client.calls]
    assert tasks == ["objective_plan", "objective_plan_contract_repair",
                     "objective_teaching", "objective_assessment"]


@pytest.mark.asyncio
async def test_generate_replaces_position_dependent_model_explanation_with_verified_evidence():
    lesson = LessonDraft("l1", "Module", "Title", "old", "", ("f1", "f2"), (), 5)
    raw_quiz = quiz()
    raw_quiz["items"][0]["explanation"] = (
        "The first option is right; the second option is wrong."
    )
    client = FakeClient([dump(plan()), dump(teaching()), dump(raw_quiz)])

    result = await generate([lesson], FACTS, client, audit_enabled=False, contract_retries=0)

    question = result["realized_assessment"]["questions"][0]
    assert question["explanation"] == FACTS["f1"].value
    assert "first option" not in question["explanation"].casefold()
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_generate_renders_identical_source_tethered_teaching_block_once():
    source = ("Сотрудник продолжает отслеживать обращение после эскалации. "
              "Ответственность переходит только после явного подтверждения принимающей стороны.")
    facts = {"ru1": SourceFact("ru1", "Эскалация", "правило", source, "p1")}
    raw_plan = {
        "objectives": [
            {"id": "o1", "learner_action": "Продолжать отслеживать обращение после эскалации",
             "decision": "Продолжать отслеживание", "conditions": "После эскалации",
             "evidence": [{"fact_id": "ru1", "quote": source}]},
            {"id": "o2", "learner_action": "Определить момент перехода ответственности",
             "decision": "Переход после явного подтверждения", "conditions": "После эскалации",
             "evidence": [{"fact_id": "ru1", "quote": source}]},
        ],
        "omitted": [],
    }
    raw_teaching = {"blocks": [
        {"objective_id": objective_id, "heading": "Правило из источника",
         "explanation": source, "application": source, "source_tethered": True}
        for objective_id in ("o1", "o2")
    ]}
    items = []
    for objective_id, prompt, correct, wrong in (
        ("o1", "Что делает сотрудник после эскалации?", "Продолжает отслеживать обращение",
         "Прекращает отслеживать обращение"),
        ("o2", "Когда переходит ответственность?", "После явного подтверждения принимающей стороны",
         "Сразу после эскалации"),
    ):
        items.append({
            "objective_id": objective_id, "prompt": prompt,
            "options": [
                {"text": correct, "correct": True, "action_or_property": correct, "error_mechanism": ""},
                {"text": wrong, "correct": False, "action_or_property": wrong,
                 "error_mechanism": "неверное применение правила"},
            ],
            "taught_quote": source, "explanation": source,
        })
    client = FakeClient([dump(raw_plan), dump(raw_teaching), dump({"items": items, "unassessable": []})])
    lesson = LessonDraft("l1", "Module", "Title", "old", "", ("ru1",), (), 5)

    result = await generate([lesson], facts, client, audit_enabled=False, contract_retries=0)

    content = result["realized_course"]["lessons"][0]["content"]
    assert content.count("## Правило из источника") == 1
    assert len(result["realized_assessment"]["questions"]) == 2


@pytest.mark.asyncio
async def test_generate_propagates_client_or_parser_failure_instead_of_returning_success():
    lesson = LessonDraft("l1", "Module", "Title", "old", "", ("f1", "f2"), (), 5)
    invalid = plan()
    invalid["objectives"][0]["evidence"][0]["quote"] = "Not in the source."
    with pytest.raises(ValueError, match="invalid_source_quote"):
        await generate([lesson], FACTS, FakeClient([dump(invalid)]), contract_retries=0)


@pytest.mark.asyncio
async def test_generate_propagates_client_failure_instead_of_returning_empty_success():
    class FailingClient:
        async def ainvoke_validated(self, *args, **kwargs):
            raise RuntimeError("synthetic provider failure")

    lesson = LessonDraft("l1", "Module", "Title", "old", "", ("f1", "f2"), (), 5)
    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        await generate([lesson], FACTS, FailingClient())
