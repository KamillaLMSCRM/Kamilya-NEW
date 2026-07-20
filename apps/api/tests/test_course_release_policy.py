"""Release-boundary tests for learner access and AI course publication."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _user(*, role: str, tenant_id=None, user_id=None):
    user = MagicMock()
    user.id = user_id or uuid4()
    user.tenant_id = tenant_id or uuid4()
    user.role = role
    return user


def _course(*, tenant_id, status="draft", review_status="pending", ai_generated=True):
    course = MagicMock()
    course.id = uuid4()
    course.tenant_id = tenant_id
    course.status = status
    course.review_status = review_status
    course.ai_generated = ai_generated
    course.source_instruction_id = None
    return course


def test_course_write_schema_cannot_bypass_publish_endpoint():
    from app.modules.courses.schemas import CourseCreate, CourseUpdate

    with pytest.raises(ValidationError):
        CourseCreate(title="Unsafe", description="", status="published")
    assert "status" not in CourseUpdate.model_fields


@pytest.mark.asyncio
async def test_methodologist_can_read_draft_course():
    from app.modules.courses.access import require_course_access

    tenant_id = uuid4()
    user = _user(role="methodologist", tenant_id=tenant_id)
    course = _course(tenant_id=tenant_id)
    db = AsyncMock()
    db.execute.return_value = _scalar_result(course)

    resolved = await require_course_access(db, course.id, user)

    assert resolved is course
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_student_cannot_read_draft_course_even_when_enrolled():
    from app.modules.courses.access import require_course_access

    tenant_id = uuid4()
    user = _user(role="student", tenant_id=tenant_id)
    course = _course(tenant_id=tenant_id, status="draft")
    db = AsyncMock()
    db.execute.return_value = _scalar_result(course)

    with pytest.raises(HTTPException) as exc:
        await require_course_access(db, course.id, user)

    assert exc.value.status_code == 404
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_student_needs_enrollment_for_published_course():
    from app.modules.courses.access import require_course_access

    tenant_id = uuid4()
    user = _user(role="student", tenant_id=tenant_id)
    course = _course(tenant_id=tenant_id, status="published")
    db = AsyncMock()
    db.execute.side_effect = [_scalar_result(course), _scalar_result(None)]

    with pytest.raises(HTTPException) as exc:
        await require_course_access(db, course.id, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_student_can_read_assigned_published_course():
    from app.modules.courses.access import require_course_access

    tenant_id = uuid4()
    user = _user(role="student", tenant_id=tenant_id)
    course = _course(tenant_id=tenant_id, status="published")
    enrollment = MagicMock()
    db = AsyncMock()
    db.execute.side_effect = [_scalar_result(course), _scalar_result(enrollment)]

    resolved = await require_course_access(db, course.id, user)

    assert resolved is course


@pytest.mark.asyncio
async def test_publish_rejects_unapproved_ai_course():
    from app.modules.courses.router import publish_course

    tenant_id = uuid4()
    user = _user(role="methodologist", tenant_id=tenant_id)
    course = _course(tenant_id=tenant_id, review_status="pending", ai_generated=True)
    db = AsyncMock()
    db.execute.return_value = _scalar_result(course)
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = "pytest"

    with patch("app.modules.courses.router.activate_course_assignments", new=AsyncMock()) as activate:
        with pytest.raises(HTTPException) as exc:
            await publish_course(course.id, request=request, db=db, user=user)

    assert exc.value.status_code == 409
    activate.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_approved_ai_course_activates_assignments():
    from app.modules.courses.router import publish_course

    tenant_id = uuid4()
    user = _user(role="methodologist", tenant_id=tenant_id)
    course = _course(tenant_id=tenant_id, review_status="approved", ai_generated=True)
    db = AsyncMock()
    db.execute.return_value = _scalar_result(course)
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = "pytest"

    with (
        patch("app.modules.courses.router.activate_course_assignments", new=AsyncMock()) as activate,
        patch("app.modules.courses.router.log_action", new=AsyncMock()),
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
    ):
        result = await publish_course(course.id, request=request, db=db, user=user)

    assert result is course
    assert course.status == "published"
    activate.assert_awaited_once_with(db, course)


@pytest.mark.asyncio
async def test_instruction_publication_replaces_prior_binding_and_recomputes():
    from app.modules.courses.publication_service import activate_course_assignments

    tenant_id = uuid4()
    position_id = uuid4()
    course = _course(tenant_id=tenant_id, status="published")
    course.source_instruction_id = uuid4()

    positions = MagicMock()
    positions.scalars.return_value.all.return_value = [position_id]
    departments = MagicMock()
    departments.scalars.return_value.all.return_value = []
    deletion = MagicMock()
    db = AsyncMock()
    db.execute.side_effect = [positions, departments, deletion]

    with (
        patch(
            "app.modules.courses.publication_service.recompute_position_holders",
            new=AsyncMock(),
        ) as recompute_position,
        patch(
            "app.modules.courses.publication_service.recompute_department_members",
            new=AsyncMock(),
        ) as recompute_department,
    ):
        await activate_course_assignments(db, course)

    assert db.execute.await_count == 3
    recompute_position.assert_awaited_once_with(db, position_id, tenant_id)
    recompute_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_student_dashboard_query_excludes_draft_courses():
    from app.modules.student.service import get_student_dashboard

    empty_rows = MagicMock()
    empty_rows.all.return_value = []
    certificate_count = MagicMock()
    certificate_count.scalar.return_value = 0
    db = AsyncMock()
    db.execute.side_effect = [empty_rows, certificate_count]

    await get_student_dashboard(db, uuid4(), uuid4())

    enrollment_query = str(db.execute.await_args_list[0].args[0])
    assert "courses.status" in enrollment_query
    assert "published" in enrollment_query


@pytest.mark.asyncio
async def test_student_quiz_access_delegates_to_lesson_release_policy():
    from app.modules.quizzes.router import _require_quiz_access

    user = _user(role="student")
    quiz = MagicMock()
    quiz.lesson_id = uuid4()
    db = AsyncMock()
    db.execute.return_value = _scalar_result(quiz)

    with patch(
        "app.modules.quizzes.router.require_lesson_access",
        new=AsyncMock(),
    ) as lesson_access:
        resolved = await _require_quiz_access(db, uuid4(), user)

    assert resolved is quiz
    lesson_access.assert_awaited_once_with(db, quiz.lesson_id, user)


@pytest.mark.asyncio
async def test_student_cannot_open_orphan_quiz_by_id():
    from app.modules.quizzes.router import _require_quiz_access

    user = _user(role="student")
    quiz = MagicMock()
    quiz.lesson_id = None
    db = AsyncMock()
    db.execute.return_value = _scalar_result(quiz)

    with pytest.raises(HTTPException) as exc:
        await _require_quiz_access(db, uuid4(), user)

    assert exc.value.status_code == 404
