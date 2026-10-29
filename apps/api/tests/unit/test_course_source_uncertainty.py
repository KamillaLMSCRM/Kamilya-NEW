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
