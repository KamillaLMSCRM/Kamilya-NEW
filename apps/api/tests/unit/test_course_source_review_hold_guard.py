"""QA approval holds target generated unresolved evidence, not ordinary edits."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.courses.router import publish_course, review_course
from app.modules.courses.schemas import CourseReviewRequest


def scenario(analysis):
    tenant, course_id = uuid4(), uuid4()
    course = SimpleNamespace(id=course_id, tenant_id=tenant, status="draft", review_status="pending", source_analysis=analysis)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: course)),
        scalar=AsyncMock(), flush=AsyncMock(), refresh=AsyncMock(), commit=AsyncMock())
    return course_id, course, db, SimpleNamespace(id=uuid4(), tenant_id=tenant)


@pytest.mark.asyncio
async def test_qa_manual_edit_review_uses_existing_attestation_flow():
    course_id, course, db, user = scenario({})
    request = SimpleNamespace(client=None, headers={})
    with patch("app.modules.courses.source_uncertainty.qa_source_holds_enabled", return_value=True), \
         patch("app.modules.courses.router.log_action", new=AsyncMock()), \
         patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)):
        await review_course(course_id, CourseReviewRequest(review_status="approved"), request, db, user)
    assert course.review_status == "approved"
    assert db.execute.await_count == 2
    assert "UPDATE lessons" in str(db.execute.await_args_list[1].args[0])
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["review", "publish"])
@pytest.mark.parametrize("quality", ["source_needs_review", "lesson_surface_needs_review"])
async def test_qa_generated_incomplete_source_or_surface_is_held(operation, quality):
    course_id, course, db, user = scenario({"evidence_v2": {"quality_status": quality}})
    with patch("app.modules.courses.source_uncertainty.qa_source_holds_enabled", return_value=True):
        with pytest.raises(HTTPException) as error:
            if operation == "review":
                await review_course(course_id, CourseReviewRequest(review_status="approved"), None, db, user)
            else:
                await publish_course(course_id, request=None, db=db, user=user)
    assert error.value.detail["code"] == "source_uncertainty_review_required"
    db.commit.assert_not_awaited()
    assert course.review_status == "pending"


@pytest.mark.asyncio
async def test_needs_changes_available_when_guard_is_misconfigured():
    course_id, course, db, user = scenario({})
    request = SimpleNamespace(client=None, headers={})
    with patch("app.modules.courses.source_uncertainty.qa_source_holds_enabled", side_effect=AssertionError("not called")), \
         patch("app.modules.courses.router.log_action", new=AsyncMock()), \
         patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)):
        await review_course(course_id, CourseReviewRequest(review_status="needs_changes"), request, db, user)
    assert course.review_status == "needs_changes"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_generated_surface_hold_remains_after_manual_lesson_edit():
    from app.modules.lessons.schemas import LessonUpdate
    from app.modules.lessons.service import update_lesson

    course_id, course, db, user = scenario({"evidence_v2": {"quality_status": "lesson_surface_needs_review"}})
    lesson = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id, title="Original", content="Original text",
        source_document_ids=[uuid4()], source_validation_status="verified")
    lesson_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: lesson)),
        flush=AsyncMock(), refresh=AsyncMock())
    with patch("app.modules.lessons.service._mark_lesson_quizzes_needs_review", new=AsyncMock()):
        await update_lesson(lesson_db, lesson.id, user.tenant_id, LessonUpdate(content="Edited text"))
    assert lesson.source_validation_status == "needs_review"
    with patch("app.modules.courses.source_uncertainty.qa_source_holds_enabled", return_value=True):
        with pytest.raises(HTTPException) as error:
            await review_course(course_id, CourseReviewRequest(review_status="approved"), None, db, user)
    assert error.value.detail["code"] == "source_uncertainty_review_required"
    db.commit.assert_not_awaited()
