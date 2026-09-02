"""Unit contract tests for LearningPath certificate integration."""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _context():
    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    course_id = uuid4()
    release = SimpleNamespace(id=uuid4())
    course = SimpleNamespace(id=course_id, tenant_id=tenant_id, current_release_id=release.id)
    enrollment = SimpleNamespace(
        id=uuid4(),
        status="enrolled",
        content_release_id=release.id,
        recurring_assignment_id=None,
    )
    certificate = SimpleNamespace(id=uuid4(), certificate_number="KML-COURSE-001")
    evidence = SimpleNamespace(id=uuid4())
    return tenant_id, user, course_id, release, course, enrollment, certificate, evidence


def _db(course, release):
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalar_result(course))
    db.scalar = AsyncMock(side_effect=[1, 1, 0, 0, release])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _completion_patches(enrollment, certificate, evidence, transitions):
    return (
        patch("app.modules.enrollments.access_service.require_active_enrollment_window", new=AsyncMock()),
        patch("app.modules.enrollments.context.current_enrollment", new=AsyncMock(return_value=enrollment)),
        patch(
            "app.modules.learning_paths.service.sync_learning_path_enrollments_after_course_completion",
            new=AsyncMock(return_value=transitions),
        ),
        patch("app.modules.certificates.service.issue_learning_path_certificate", new=AsyncMock()),
        patch("app.modules.certificates.service.issue_certificate", new=AsyncMock(return_value=certificate)),
        patch("app.modules.training_evidence.workflow.record_course_completion", new=AsyncMock(return_value=evidence)),
        patch("app.modules.audit.service.log_action", new=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_completion_issues_one_program_certificate_for_new_transition():
    from app.modules.courses.router import _complete_course_for_user

    tenant_id, user, course_id, release, course, enrollment, certificate, evidence = _context()
    transition = SimpleNamespace(id=uuid4())
    db = _db(course, release)

    with ExitStack() as stack:
        mocks = [stack.enter_context(patcher) for patcher in _completion_patches(enrollment, certificate, evidence, [transition])]
        response = await _complete_course_for_user(db, course_id, user)

    sync_paths = mocks[2]
    issue_program = mocks[3]
    issue_course = mocks[4]
    sync_paths.assert_awaited_once_with(
        db, tenant_id=tenant_id, user_id=user.id, return_completed_assignments=True
    )
    issue_program.assert_awaited_once_with(
        db, tenant_id=tenant_id, user=user, learning_path_assignment_id=transition.id
    )
    issue_course.assert_awaited_once()
    assert response["certificate_id"] == str(certificate.id)
    assert response["certificate_number"] == certificate.certificate_number


@pytest.mark.asyncio
async def test_completion_with_empty_program_transitions_does_not_issue_program_certificate():
    from app.modules.courses.router import _complete_course_for_user

    _tenant_id, user, course_id, release, course, enrollment, certificate, evidence = _context()
    db = _db(course, release)

    with ExitStack() as stack:
        mocks = [stack.enter_context(patcher) for patcher in _completion_patches(enrollment, certificate, evidence, [])]
        response = await _complete_course_for_user(db, course_id, user)

    sync_paths = mocks[2]
    issue_program = mocks[3]
    sync_paths.assert_awaited_once_with(
        db, tenant_id=user.tenant_id, user_id=user.id, return_completed_assignments=True
    )
    issue_program.assert_not_awaited()
    assert response["certificate_id"] == str(certificate.id)
    assert response["certificate_number"] == certificate.certificate_number
