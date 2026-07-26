"""Focused unit coverage for organization-wide course-rule inheritance."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.positions.assignment_service import recompute_enrollments


def _result(rows):
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


def _user(tenant_id, position_id=None):
    return MagicMock(
        tenant_id=tenant_id,
        position_id=position_id,
        role="student",
        is_active=True,
    )


def _db_for_user(*, user, organization_rows, current_rows, position_rows=None, department_rows=None):
    db = AsyncMock()
    position = MagicMock(department_id=uuid4())

    async def get(model, _):
        if model.__name__ == "User":
            return user
        return position

    db.get = AsyncMock(side_effect=get)
    sequence = []
    if position_rows is not None:
        sequence.append(_result(position_rows))
        if department_rows is not None:
            sequence.append(_result(department_rows))
    sequence.extend([_result(organization_rows), _result(current_rows), MagicMock(), MagicMock()])
    db.execute = AsyncMock(side_effect=sequence)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_organization_rule_applies_to_new_user_without_position():
    tenant_id = uuid4()
    course_id = uuid4()
    db = _db_for_user(
        user=_user(tenant_id),
        organization_rows=[(course_id,)],
        current_rows=[],
    )

    outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 1
    assert db.add.call_args.args[0].source == "organization"


@pytest.mark.asyncio
async def test_position_department_and_organization_use_declared_precedence():
    tenant_id = uuid4()
    position_course, department_course, organization_course = uuid4(), uuid4(), uuid4()
    db = _db_for_user(
        user=_user(tenant_id, uuid4()),
        position_rows=[(position_course,)],
        department_rows=[(department_course,)],
        organization_rows=[(position_course,), (department_course,), (organization_course,)],
        current_rows=[],
    )

    outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 3
    sources = {call.args[0].course_id: call.args[0].source for call in db.add.call_args_list}
    assert sources[position_course] == "position"
    assert sources[department_course] == "department"
    assert sources[organization_course] == "organization"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["manual", "cohort", "learning_path", "future_source"])
async def test_protected_source_is_not_replaced_by_organization_rule(source):
    tenant_id = uuid4()
    course_id = uuid4()
    db = _db_for_user(
        user=_user(tenant_id),
        organization_rows=[(course_id,)],
        current_rows=[(course_id, source, "enrolled")],
    )

    outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 0
    assert outcome.removed == 0
    assert db.add.call_count == 0
    if source == "manual":
        assert outcome.skipped_manual == 1
    else:
        assert outcome.skipped_protected == 1


@pytest.mark.asyncio
async def test_completed_organization_enrollment_is_not_removed_on_detach():
    db = _db_for_user(
        user=_user(uuid4()),
        organization_rows=[],
        current_rows=[(uuid4(), "organization", "completed")],
    )

    outcome = await recompute_enrollments(db, uuid4())

    assert outcome.removed == 0
    assert outcome.protected_completed == 1


@pytest.mark.asyncio
async def test_existing_organization_enrollment_is_upgraded_to_position_source():
    course_id = uuid4()
    db = _db_for_user(
        user=_user(uuid4(), uuid4()),
        position_rows=[(course_id,)],
        department_rows=[],
        organization_rows=[(course_id,)],
        current_rows=[(course_id, "organization", "enrolled")],
    )

    outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 0
    assert outcome.updated == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "is_active"),
    [("admin", True), ("methodologist", True), ("student", False)],
)
async def test_organization_rule_does_not_enroll_non_learner_account(role, is_active):
    tenant_id = uuid4()
    course_id = uuid4()
    user = _user(tenant_id)
    user.role = role
    user.is_active = is_active
    db = _db_for_user(
        user=user,
        organization_rows=[(course_id,)],
        current_rows=[],
    )

    outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 0
    assert db.execute.await_count == 0
    db.add.assert_not_called()
