"""Focused contract tests for industry course blueprints."""

from uuid import uuid4

import pytest

from app.modules.courses.blueprint_catalog import (
    FINANCE_IS_BLUEPRINT_ID,
    FINANCE_IS_BLUEPRINT_VERSION,
    get_blueprint,
)
from app.modules.courses.blueprint_schemas import BlueprintInstantiationRequest
from app.modules.courses.blueprint_service import (
    BlueprintContentConflictError,
    adaptation_snapshot,
    assert_blueprint_ready_for_approval,
    calculate_adaptation,
    get_catalog,
)
from app.modules.courses.models import Course


def test_finance_blueprint_has_localized_non_overlapping_structure() -> None:
    ru = get_blueprint("ru")
    kk = get_blueprint("kk")

    assert ru["id"] == kk["id"] == FINANCE_IS_BLUEPRINT_ID
    assert ru["version"] == kk["version"] == FINANCE_IS_BLUEPRINT_VERSION
    assert len(ru["lessons"]) == len(kk["lessons"]) == 8
    assert [item["id"] for item in ru["lessons"]] == [item["id"] for item in kk["lessons"]]
    assert len({item["title"] for item in ru["lessons"]}) == 8
    assert sum(len(item["questions"]) for item in ru["lessons"]) == 16

    for locale in (ru, kk):
        for lesson in locale["lessons"]:
            assert len(lesson["questions"]) == 2
            for _, choices, correct_index, explanation in lesson["questions"]:
                assert len(choices) == 3
                assert 0 <= correct_index < len(choices)
                assert explanation.strip()


def test_catalog_exposes_marketing_ratio_as_estimate_and_limitations() -> None:
    item = get_catalog("ru", include_financial=True)[0]

    assert item.estimated_ready_percent == 70
    assert item.customization_percent == 30
    assert item.module_count == 1
    assert item.lesson_count == 8
    assert item.quiz_question_count == 16
    assert len(item.checklist) == 8
    assert any("не гарантирует" in limitation for limitation in item.limitations)
    assert any("ЭЦП" in limitation for limitation in item.limitations)


def test_adaptation_progress_requires_real_answers() -> None:
    blueprint = get_blueprint("ru")
    readiness, completed, missing = calculate_adaptation(blueprint, {})
    assert readiness == 70
    assert completed == []
    assert len(missing) == 8

    answers = {item["id"]: f"Ответ для {item['id']}" for item in blueprint["checklist"]}
    readiness, completed, missing = calculate_adaptation(blueprint, answers)
    assert readiness == 100
    assert completed == [item["id"] for item in blueprint["checklist"]]
    assert missing == []

    with pytest.raises(ValueError, match="Unknown adaptation items"):
        calculate_adaptation(blueprint, {"invented": "not allowed"})


def test_instantiation_schema_normalizes_answers_and_document_ids() -> None:
    document_id = uuid4()
    request = BlueprintInstantiationRequest(
        locale="ru",
        answers={"incident_channel": "  security@example.kz  ", "remote_work": "  "},
        source_document_ids=[document_id, document_id],
    )
    assert request.answers == {"incident_channel": "security@example.kz"}
    assert request.source_document_ids == [document_id]


def test_incomplete_blueprint_course_cannot_be_approved() -> None:
    course = Course(
        tenant_id=uuid4(),
        title="Finance IS",
        description="",
        source_analysis={
            "blueprint": {
                "id": FINANCE_IS_BLUEPRINT_ID,
                "version": FINANCE_IS_BLUEPRINT_VERSION,
                "locale": "ru",
            },
            "adaptation": {
                "readiness_percent": 70,
                "answers": {},
                "source_document_ids": [],
                "completed_checklist_items": [],
                "missing_checklist_items": ["incident_channel"],
            },
        },
    )
    with pytest.raises(BlueprintContentConflictError):
        assert_blueprint_ready_for_approval(course)

    course.source_analysis["adaptation"].update(
        readiness_percent=100,
        completed_checklist_items=["incident_channel"],
        missing_checklist_items=[],
    )
    assert_blueprint_ready_for_approval(course)
    snapshot = adaptation_snapshot(course)
    assert snapshot.readiness_percent == 100


def test_blueprint_routes_are_registered_before_release() -> None:
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/v1/course-blueprints" in paths
    assert "/api/v1/course-blueprints/{blueprint_id}/instantiate" in paths
    assert "/api/v1/courses/{course_id}/blueprint-adaptation" in paths
