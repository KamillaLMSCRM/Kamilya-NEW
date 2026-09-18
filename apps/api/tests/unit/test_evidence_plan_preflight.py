from __future__ import annotations

from dataclasses import replace

from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import (
    LessonEvidence,
    SourceDocument,
    SourceFact,
    SourceSection,
)
from app.modules.ai.evidence_engine.quality import evaluate_plan_preflight


def _result():
    fact = SourceFact(
        fact_id="fact-1",
        subject="Коллекция",
        attribute="материал",
        value="Фасад изготовлен из МДФ.",
        source_locator="sheet=Коллекции;row=2",
    )
    source = SourceDocument(
        source_id="source-1",
        title="Коллекции",
        kind="spreadsheet",
        sections=(
            SourceSection(
                section_id="section-1",
                title="Коллекции",
                role="primary",
                facts=(fact,),
            ),
        ),
        teachable_units=1,
    )
    return EvidenceCourseEngine().generate_from_document(source)


def test_plan_preflight_accepts_exact_source_coverage_within_capacity() -> None:
    result = _result()

    assert evaluate_plan_preflight(result) == ()
    assert result.evaluation.capacity_ratio == 1.0
    assert result.evaluation.quota_padding_count == 0
    assert result.evaluation.generated_duration_minutes > 0
    assert result.evaluation.invalid_title_count == 0


def test_plan_preflight_rejects_duplicate_fact_ids_and_capacity_inflation() -> None:
    result = _result()
    original = result.evidence_plan[0]
    fact_id = original.fact_ids[0]
    duplicate = replace(original, fact_ids=(fact_id, fact_id))
    extra = LessonEvidence(
        lesson_id="lesson-extra",
        module_title=original.module_title,
        title="Дополнительный урок",
        objective=original.objective,
        fact_ids=(),
        supporting_fact_ids=(),
        source_locators=(),
    )
    inflated = replace(
        result,
        evidence_plan=(duplicate, extra),
        course=replace(result.course, lessons=(*result.course.lessons, result.course.lessons[0])),
    )

    assert evaluate_plan_preflight(inflated) == (
        "duplicate_planned_fact_ids",
        "lesson_capacity_exceeded",
    )


def test_plan_preflight_rejects_missing_admitted_fact_coverage() -> None:
    result = _result()
    missing = replace(result, evidence_plan=(replace(result.evidence_plan[0], fact_ids=()),))

    assert evaluate_plan_preflight(missing) == ("incomplete_planned_fact_coverage",)
