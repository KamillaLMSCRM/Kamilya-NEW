"""Source-owned compound rules must not lose distinct targets to a catalog cap."""
import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason


class _EmptyAuthor:
    def __init__(self):
        self.requests = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        assert request["task"] == "assessment_generate"
        self.requests.append(request)
        return SimpleNamespace(value=parser('{"questions": []}'), attempt_count=1)


@pytest.mark.asyncio
async def test_distinct_document_regions_are_not_deduplicated_as_one_attribute() -> None:
    value = (
        "От 500 100 до 900 000 тенге для РД г. Северный, г. Речной "
        "от 500 100 до 1 200 000 тенге РД г. Южный, г. Степной"
    )
    facts = {str(index): SourceFact(
        str(index), category, "Лимит выдачи, тенге", value,
        f"doc_id=synthetic;source_revision=v1;section=limits;table=1;row={index};column=2",
    ) for index, category in enumerate(("I категория", "II категория"), start=2)}
    lesson = LessonDraft("limits", "Правила", "Категории", "Применять лимиты", "", tuple(facts), (), 2)
    client = _EmptyAuthor()
    result = await generate_block_assessment([lesson], facts, client)
    requested = [axis for request in client.requests for axis in request["axes"]]
    assert len(requested) == 4
    assert {axis["subject"] for axis in requested} == {"I категория", "II категория"}
    assert all("РД г." in axis["required_prompt"] for axis in requested)
    assert result.audit["requested_axes"] == 4
    assert not any(row["reason"] == "assessment_attribute_diversity_limit"
                   for row in result.audit["axis_outcomes"])


@pytest.mark.asyncio
async def test_explicit_operational_list_preserves_all_five_independent_targets() -> None:
    value = (
        "Перед закрытием сотрудник обязан: "
        "1) отключить неисправный прибор; "
        "2) проверить свободный выход; "
        "3) закрыть окна помещения; "
        "4) проверить исправность сигнализации; "
        "5) сообщить руководителю о неисправности."
    )
    fact = SourceFact("closing", "Закрытие помещения", "обязанность", value,
                      "doc_id=synthetic;source_revision=v1;section=closing;part=1")
    lesson = LessonDraft("closing", "Безопасность", "Закрытие", "Закрывать помещение", "", (fact.fact_id,), (), 2)
    assert len(derive_assessment_axes(lesson, [fact], block_id="probe")) == 5
    client = _EmptyAuthor()
    result = await generate_block_assessment([lesson], {fact.fact_id: fact}, client)
    assert sum(len(r["axes"]) for r in client.requests) == 5
    assert max(len(r["axes"]) for r in client.requests) <= 4
    assert result.audit["requested_axes"] == 5
    assert result.questions == ()  # More source targets never invent accepted questions.


def test_compact_ocr_list_without_semicolons_retains_every_action_axis() -> None:
    value = (
        "6.2. Последний сотрудник должен:\n"
        "— отключить приборы, кроме аварийного освещения;\n"
        "-проверить свободный выход\n"
        "— закрыть окна помещения\n"
        "-выключить свет в помещении"
    )
    fact = SourceFact("closing", "Закрытие", "обязанность", value, "section=closing;part=1")
    lesson = LessonDraft("closing", "Безопасность", "Закрытие", "Закрыть помещение", "", (fact.fact_id,), (), 2)
    axes = derive_assessment_axes(lesson, [fact], block_id="probe")
    assert len(axes) == 4
    assert all("Последний сотрудник должен" in axis.required_prompt for axis in axes)
    assert {axis.correct_value for axis in axes} == {
        "отключить приборы, кроме аварийного освещения", "проверить свободный выход",
        "закрыть окна помещения", "выключить свет в помещении",
    }


def test_emergency_list_keeps_urgency_and_concurrent_action_qualifiers() -> None:
    value = (
        "5.1. При обнаружении пожара сотруднику следует:\n"
        "— незамедлительно сообщить пожарной службе адрес объекта;\n"
        "-одновременно с тушением пожара организовать эвакуацию документов;\n"
        "-при необходимости отключить электроэнергию."
    )
    fact = SourceFact("fire", "Действия при пожаре", "обязанность", value, "section=fire;part=1")
    lesson = LessonDraft("fire", "Безопасность", "Пожар", "Действовать", "", (fact.fact_id,), (), 2)
    axes = derive_assessment_axes(lesson, [fact], block_id="probe")
    assert len(axes) == 3
    assert any(axis.correct_value.startswith("незамедлительно сообщить") for axis in axes)
    assert any("одновременно с тушением пожара" in axis.required_prompt for axis in axes)
    assert any("при необходимости" in axis.required_prompt for axis in axes)
    assert all("При обнаружении пожара сотруднику следует" in axis.required_prompt for axis in axes)


def test_narrative_plan_splits_dense_rules_before_the_assessment_safety_ceiling() -> None:
    from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
    from app.modules.ai.evidence_engine.models import SourceDocument, SourceSection
    facts = tuple(SourceFact(
        f"f{index}", "Правила безопасности", "обязанность",
        f"Сотрудник участка {index} обязан:\n" + ";\n".join(
            f"{item}) проверить аварийный выход участка {index} номер {item}" for item in range(1, 9)
        ) + ".", f"section=safety;part={index}",
    ) for index in range(1, 4))
    result = EvidenceCourseEngine().generate_from_document(SourceDocument(
        "dense", "Безопасность", "narrative", (SourceSection("s", "Правила безопасности", "primary", facts),),
    ))
    assert len(result.course.lessons) == 2
    admitted = {fact.fact_id: fact for fact in result.admitted_facts}
    counts = [len(derive_assessment_axes(lesson, [admitted[fid] for fid in lesson.fact_ids], block_id="probe"))
              for lesson in result.course.lessons]
    assert counts == [16, 8]
    assert [fid for lesson in result.course.lessons for fid in lesson.fact_ids] == list(admitted)


def test_instruction_schedules_and_liability_are_not_hidden_in_one_mixed_paragraph() -> None:
    from app.modules.ai.evidence_engine.assessment_axes import has_partial_unatomized_source_contract
    value = (
        "Ответственность за безопасность возлагается на руководителя подразделения. "
        "Все сотрудники должны проходить инструктаж в соответствии с регламентом.\n"
        "-вновь принимаемые сотрудники проходят инструктаж при приеме на работу;\n"
        "— сотрудники организации проходят инструктаж не реже 1 раза в год. "
        "Нарушение требований безопасности влечет за собой дисциплинарную ответственность, "
        "предусмотренную законодательством Республики Казахстан."
    )
    fact = SourceFact("instruction", "Обучение", "обязанность", value, "section=instruction;part=1")
    lesson = LessonDraft("instruction", "", "", "", "", (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id="probe")
    assert any("при приеме на работу" in axis.correct_value for axis in axes)
    assert any("не реже 1 раза в год" in axis.correct_value for axis in axes)
    assert any("дисциплинарную ответственность" in axis.correct_value for axis in axes)
    assert not has_partial_unatomized_source_contract(fact)


def test_schedule_under_an_unfinished_condition_is_not_an_unconditional_obligation() -> None:
    from app.modules.ai.evidence_engine.assessment_axes import _instruction_schedule_axes
    value = "Если вводится новая технология:\n-сотрудники проходят инструктаж перед работой;\n— сотрудники проходят инструктаж каждый год."
    fact = SourceFact("s", "Инструктаж", "обязанность", value, "section=s;part=1")
    assert _instruction_schedule_axes(fact) == []
    for actor in ("он", "она", "они", "лицо", "это"):
        assert _instruction_schedule_axes(SourceFact("s", "Инструктаж", "обязанность",
            f"{actor} проходят инструктаж каждый год.", "section=s;part=1")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["Запрещено блокировать аварийный выход", "Регламент определяет порядок работы подразделения"])
async def test_technical_ceiling_cannot_silently_hide_source_targets(prefix: str) -> None:
    facts = {str(i): SourceFact(
        str(i), "Безопасность", "положение", f"{prefix} номер {i}.",
        f"doc_id=synthetic;source_revision=v1;section=safety;part={i}",
    ) for i in range(1, 22)}
    lesson = LessonDraft("safety", "Безопасность", "Выходы", "Не блокировать выходы", "", tuple(facts), (), 2)
    result = await generate_block_assessment([lesson], facts, _EmptyAuthor())
    assert result.audit["requested_axes"] == 20
    assert result.audit["coverage"]["density_limited_lesson_ids"] == [lesson.lesson_id]
    selection = result.audit["narrative_selection_coverage"][0]
    assert len(selection["eligible_fact_ids"]) == 21
    assert len(selection["selected_fact_ids"]) == 20
    assert selection["complete"] is False
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["terminal_status"] == "review_required"


@pytest.mark.asyncio
async def test_one_compound_fact_exposes_siblings_beyond_the_technical_ceiling() -> None:
    value = "Перед закрытием сотрудник обязан: " + "; ".join(
        f"{i}) проверить аварийный выход номер {i}" for i in range(1, 22)
    ) + "."
    fact = SourceFact("exits", "Закрытие", "обязанность", value,
                      "doc_id=synthetic;source_revision=v1;section=closing;part=1")
    lesson = LessonDraft("exits", "Безопасность", "Закрытие", "Проверить выходы", "", (fact.fact_id,), (), 2)
    assert len(derive_assessment_axes(lesson, [fact], block_id="probe")) == 21
    result = await generate_block_assessment([lesson], {fact.fact_id: fact}, _EmptyAuthor())
    assert result.audit["derived_axes"] == 21
    assert result.audit["requested_axes"] == 20
    assert sum(row["reason"] == "assessment_density_limit" for row in result.audit["axis_outcomes"]) == 1
    coverage = result.audit["structured_list_axis_coverage"][0]
    assert len(coverage["derived_axis_ids"]) == 21
    assert len(coverage["critical_missing_axis_ids"]) == 21  # Empty author accepted none.
    assert coverage["complete"] is False
    assert result.audit["terminal_status"] == "review_required"


@pytest.mark.asyncio
async def test_large_author_context_is_batched_without_losing_source_targets() -> None:
    # Long source-owned labels make the combined request too large although
    # each complete fact and its assessment axis fit. Never truncate either.
    facts = {str(i): SourceFact(
        str(i), "Подразделение " + (f"объект{i} " * 330), "обязанность",
        f"Сотрудник обязан проверить аварийный выход номер {i}.",
        f"doc_id=synthetic;source_revision=v1;section=safety;part={i}",
    ) for i in range(1, 7)}
    lesson = LessonDraft("safety", "Безопасность", "Выходы", "Проверять выходы", "", tuple(facts), (), 2)
    client = _EmptyAuthor()

    result = await generate_block_assessment([lesson], facts, client)

    assert len(client.requests) > 1
    assert all(len(json.dumps(request, ensure_ascii=False)) <= 24000
               for request in client.requests)
    requested = [axis for request in client.requests for axis in request["axes"]]
    assert len(requested) == len({axis["axis_id"] for axis in requested}) == 6
    assert result.audit["requested_axes"] == 6
    assert not any(row["reason"] == "assessment_context_too_large"
                   for row in result.audit["failures"])
    for request in client.requests:
        for fact in request["facts"]:
            assert fact["value"] == facts[fact["fact_id"]].value
            assert fact["subject"] == facts[fact["fact_id"]].subject
    assert result.questions == ()  # Empty author still creates no questions.


@pytest.mark.asyncio
@pytest.mark.parametrize("include_small", [False, True])
async def test_irreducible_author_context_failure_remains_uncovered(include_small: bool) -> None:
    facts = {"large": SourceFact(
        "large", "Объект " * 5000, "обязанность", "Проверить аварийный выход.",
        "doc_id=synthetic;source_revision=v1;section=safety;part=1",
    )}
    if include_small:
        facts["small"] = SourceFact(
            "small", "Помещение", "обязанность", "Закрыть окно.",
            "doc_id=synthetic;source_revision=v1;section=safety;part=2",
        )
    lesson = LessonDraft("safety", "Безопасность", "Выходы", "Проверять выходы", "", tuple(facts), (), 2)
    result = await generate_block_assessment([lesson], facts, _EmptyAuthor())
    assert result.audit["failures"]
    uncovered = [row for row in result.audit["axis_outcomes"] if row["state"] == "uncovered"]
    assert [row["primary_fact_id"] for row in uncovered] == ["large"]
    assert uncovered[0]["reason"] == "assessment_context_too_large"
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["contract_coverage"]["audit_incomplete"] is True
    assert result.audit["terminal_status"] == "review_required"


@pytest.mark.asyncio
async def test_failed_author_batch_is_not_hidden_by_an_empty_successful_sibling() -> None:
    class PartialOutage(_EmptyAuthor):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if any(fact["fact_id"] == "1" for fact in request["facts"]):
                self.requests.append(request)
                raise AllProvidersFailedError("fixture", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE])
            return await super().ainvoke_validated(messages, parser, **kwargs)

    facts = {str(i): SourceFact(
        str(i), "Подразделение " + (f"объект{i} " * 330), "обязанность",
        f"Сотрудник обязан проверить аварийный выход номер {i}.",
        f"doc_id=synthetic;source_revision=v1;section=safety;part={i}",
    ) for i in range(1, 7)}
    lesson = LessonDraft("safety", "Безопасность", "Выходы", "Проверять выходы", "", tuple(facts), (), 2)

    client = PartialOutage()
    result = await generate_block_assessment([lesson], facts, client)

    assert result.audit["failures"]
    uncovered = {row["primary_fact_id"] for row in result.audit["axis_outcomes"]
                 if row["state"] == "uncovered"}
    failed_axes = {axis["axis_id"] for request in client.requests
                   if any(f["fact_id"] == "1" for f in request["facts"])
                   for axis in request["axes"]}
    assert uncovered
    assert uncovered < set(facts)  # A failed child must not erase unrelated siblings.
    assert {row["axis_id"] for row in result.audit["axis_outcomes"]
            if row["state"] == "uncovered"} == failed_axes
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["contract_coverage"]["audit_incomplete"] is True
    assert result.audit["terminal_status"] == "review_required"
