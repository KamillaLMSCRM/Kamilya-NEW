from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.course_approval.service import decide
from app.modules.courses.router import publish_course, review_course
from app.modules.courses.schemas import CourseReviewRequest
from app.modules.courses.source_uncertainty import (
    preserve_source_uncertainty,
    require_source_uncertainty_clear,
)


@pytest.mark.parametrize("marker", [None, {}, [], {"source_sha256": "stale"}])
def test_marker_is_preserved_and_always_blocks(marker):
    old = {"unresolved_source_uncertainty": marker}
    merged = preserve_source_uncertainty(old, {"other": "new"})
    assert merged["unresolved_source_uncertainty"] == marker
    with pytest.raises(HTTPException) as error:
        require_source_uncertainty_clear(merged)
    assert error.value.status_code == 409
    require_source_uncertainty_clear({"ordinary": True})


def test_replacement_cannot_forge_server_owned_hold():
    assert "unresolved_source_uncertainty" not in preserve_source_uncertainty(
        {}, {"unresolved_source_uncertainty": {"forged": True}}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["manual", "publish", "revision"])
async def test_marked_course_cannot_be_approved_or_published(operation):
    tenant, course_id = uuid4(), uuid4()
    course = SimpleNamespace(id=course_id, tenant_id=tenant, status="draft",
                             source_analysis={"unresolved_source_uncertainty": {}})
    result = SimpleNamespace(scalar_one_or_none=lambda: course)
    db = SimpleNamespace(execute=AsyncMock(return_value=result), scalar=AsyncMock(return_value=course))
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant)
    with pytest.raises(HTTPException) as error:
        if operation == "manual":
            await review_course(course_id, CourseReviewRequest(review_status="approved"), None, db, user)
        elif operation == "publish":
            await publish_course(course_id, request=None, db=db, user=user)
        else:
            await decide(db, attempt=SimpleNamespace(), revision=SimpleNamespace(course_id=course_id),
                         reviewer=SimpleNamespace(), tenant_id=tenant, actor_id=user.id, decision="approve",
                         reason=None, warning_acknowledged=False)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "source_uncertainty_review_required"


def test_actual_generation_source_hold_blocks_but_other_quality_states_do_not():
    with pytest.raises(HTTPException) as error:
        require_source_uncertainty_clear({"evidence_v2": {"quality_status": "source_needs_review"}})
    assert error.value.detail["code"] == "source_uncertainty_review_required"
    for analysis in ({}, {"evidence_v2": {"quality_status": "validated_draft"}},
                     {"evidence_v2": {"quality_status": "assessment_needs_review"}}):
        require_source_uncertainty_clear(analysis)
    with pytest.raises(HTTPException):
        require_source_uncertainty_clear({"evidence_v2": {}})

@pytest.fixture(autouse=True)
def enable_qa_guard(monkeypatch):
    monkeypatch.setattr("app.modules.courses.source_uncertainty.qa_source_holds_enabled", lambda tenant: True)
    monkeypatch.setattr("app.modules.courses.source_uncertainty.is_qa_source_tenant", lambda tenant: True)


@pytest.mark.asyncio
@pytest.mark.parametrize("held_at", ["live", "snapshot"])
async def test_qa_reviewer_checks_live_and_frozen_generation_holds(held_at):
    tenant, course_id, revision_id, reviewer_id = uuid4(), uuid4(), uuid4(), uuid4()
    held = {"evidence_v2": {"quality_status": "lesson_surface_needs_review"}}
    course = SimpleNamespace(source_analysis=held if held_at == "live" else {})
    revision = SimpleNamespace(id=revision_id, course_id=course_id,
        snapshot={"course": {"source_analysis": held if held_at == "snapshot" else {}}})
    reviewer = SimpleNamespace(id=reviewer_id)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[course, revision, reviewer]), commit=AsyncMock(), flush=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await decide(db, attempt=SimpleNamespace(), revision=revision, reviewer=reviewer,
            tenant_id=tenant, actor_id=uuid4(), decision="approve", reason=None, warning_acknowledged=False)
    assert error.value.detail["code"] == "source_uncertainty_review_required"
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_resolve_source_uncertainty_clears_hold_and_records_audit():
    """Verify that authorized resolve_source_uncertainty clears the hold and records audit trail."""
    from app.modules.courses.source_uncertainty import (
        SOURCE_UNCERTAINTY_KEY,
        require_persisted_source_hold_clear,
        resolve_source_uncertainty,
    )

    actor_id = uuid4()
    initial_analysis = {SOURCE_UNCERTAINTY_KEY: {"status": "review_required", "origin": "generation"}}

    # Guard blocks initially
    with pytest.raises(HTTPException) as error:
        require_persisted_source_hold_clear(initial_analysis)
    assert error.value.detail["code"] == "source_uncertainty_review_required"

    # Authorized resolution
    resolved = resolve_source_uncertainty(
        initial_analysis,
        reason="Методист выполнил сверку регламента",
        methodologist_user_id=actor_id,
    )

    # Hold is cleared and audit trail is preserved
    assert SOURCE_UNCERTAINTY_KEY not in resolved
    assert resolved["source_uncertainty_resolution"]["status"] == "resolved"
    assert resolved["source_uncertainty_resolution"]["resolved_by"] == str(actor_id)
    assert resolved["source_uncertainty_resolution"]["reason"] == "Методист выполнил сверку регламента"
    assert "resolved_at" in resolved["source_uncertainty_resolution"]
    assert "content_hash" in resolved["source_uncertainty_resolution"]

    # Guard now passes
    require_persisted_source_hold_clear(resolved)

    # Calling resolve on an already-resolved analysis (marker absent) raises ValueError
    with pytest.raises(ValueError) as no_hold_err:
        resolve_source_uncertainty(resolved, reason="Повторное действие без маркера", methodologist_user_id=actor_id)
    assert "отсутствует активная блокировка" in str(no_hold_err.value)

    # Rejects invalid / unauthenticated calls
    with pytest.raises(ValueError):
        resolve_source_uncertainty(initial_analysis, reason="Проверка", methodologist_user_id=None)
    with pytest.raises(ValueError):
        resolve_source_uncertainty(initial_analysis, reason="", methodologist_user_id=actor_id)
    with pytest.raises(ValueError):
        resolve_source_uncertainty(initial_analysis, reason="коротко", methodologist_user_id=actor_id)

    # Content hash mismatch rejects resolution
    with pytest.raises(ValueError) as hash_err:
        resolve_source_uncertainty(
            initial_analysis,
            reason="Методист выполнил сверку регламента",
            methodologist_user_id=actor_id,
            expected_content_hash="bad-hash-00000000000000000000000000000000",
        )
    assert "Несоответствие версии содержания" in str(hash_err.value)

    # Active violations without acknowledgment rejects resolution
    analysis_with_violations = {
        SOURCE_UNCERTAINTY_KEY: {"status": "review_required"},
        "evidence_v3": {"violations": ["Критическое смысловое искажение: закрыть дверь vs открыть"]},
    }
    with pytest.raises(ValueError) as defect_err:
        resolve_source_uncertainty(
            analysis_with_violations,
            reason="Методист проверил регламент и утвердил",
            methodologist_user_id=actor_id,
        )
    assert "обнаружены неисправленные замечания/нарушения" in str(defect_err.value)

    # Resolving with explicit acknowledgment succeeds
    resolved_with_ack = resolve_source_uncertainty(
        analysis_with_violations,
        reason="Методист проверил регламент и согласовал замечание как исключение",
        methodologist_user_id=actor_id,
        acknowledged_defects=["Критическое смысловое искажение: закрыть дверь vs открыть"],
    )
    assert SOURCE_UNCERTAINTY_KEY not in resolved_with_ack
    assert resolved_with_ack["source_uncertainty_resolution"]["acknowledged_defects"] == [
        "Критическое смысловое искажение: закрыть дверь vs открыть"
    ]
    assert resolved_with_ack["evidence_v3"]["acknowledged_defects"] == [
        "Критическое смысловое искажение: закрыть дверь vs открыть"
    ]

    # Calling resolve second time appends to history without overwriting previous audit records
    second_actor = uuid4()
    second_analysis = {**resolved, SOURCE_UNCERTAINTY_KEY: {"status": "review_required"}}
    second_resolved = resolve_source_uncertainty(
        second_analysis,
        reason="Вторая проверка после правок регламента",
        methodologist_user_id=second_actor,
    )
    assert len(second_resolved["resolutions_history"]) == 2
    assert second_resolved["resolutions_history"][0]["resolved_by"] == str(actor_id)
    assert second_resolved["resolutions_history"][1]["resolved_by"] == str(second_actor)
