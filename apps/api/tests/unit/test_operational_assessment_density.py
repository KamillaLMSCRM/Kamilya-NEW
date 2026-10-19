"""Source-owned compound rules must not lose distinct targets to a catalog cap."""
import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment


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
    assert len(client.requests[0]["axes"]) == 5
    assert result.audit["requested_axes"] == 5
    assert result.questions == ()  # More source targets never invent accepted questions.


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
