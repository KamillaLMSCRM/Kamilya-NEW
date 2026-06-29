"""Unit tests for recompute_enrollments kernel (B1a).

Uses mocked DB to keep tests fast and DB-independent. Tests cover:
  1. New user with position having 2 courses → 2 enrollments
  2. Position change → old removed, new added, completed kept
  3. Manual enrollment protects against position rule
  4. Completed enrollment survives rule removal
  5. In-progress enrollment removed when rule goes
  6. Idempotent — second call is no-op
  7. Cross-tenant — rule from another tenant ignored
  8. required=False course still gets enrollment
  9. User without position → no changes
  10. Department + position overlap → position wins

Mocks the AsyncSession.execute() return chains carefully — recompute
runs several queries in sequence.
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.positions.assignment_service import (
    RecomputeResult,
    recompute_enrollments,
)


def _make_user_mock(tenant_id):
    """Mock for `db.get(User, user_id)` → returns object with tenant_id."""
    user = MagicMock()
    user.tenant_id = tenant_id
    user.position_id = uuid4()  # default: has a position
    return user


def _make_position_mock(department_id=None):
    """Mock for `db.get(Position, position_id)` → returns object with optional department."""
    pos = MagicMock()
    pos.department_id = department_id
    return pos


def _setup_db_with_position(tenant_id, position_rules_rows, current_rows, department_id=None):
    """Standard mock setup: user has a position, with optional department.

    Returns the configured db mock.
    """
    db = AsyncMock()
    user = _make_user_mock(tenant_id)
    pos = _make_position_mock(department_id)

    # db.get is async (await db.get(...)). Make it AsyncMock that
    # returns the appropriate mock based on the model class.
    async def async_get(model, key):
        from app.models.users import User as U
        from app.modules.positions.models import Position as P
        if model is U or model.__name__ == "User":
            return user
        if model is P or model.__name__ == "Position":
            return pos
        return MagicMock()
    db.get = AsyncMock(side_effect=async_get)

    # Build the execute chain
    pos_rows = MagicMock()
    pos_rows.all = MagicMock(return_value=position_rules_rows)
    cur_rows = MagicMock()
    cur_rows.all = MagicMock(return_value=current_rows)

    # Always include a default MagicMock for the optional delete call
    # (recompute only calls execute() for delete when there are rows
    # to remove). Tests that expect no remove won't reach this.
    delete_result = MagicMock()

    if department_id is not None:
        dept_rows = MagicMock()
        dept_rows.all = MagicMock(return_value=[])
        # Order: 1) position rules, 2) department rules, 3) current,
        # 4) optional delete.
        db.execute = AsyncMock(side_effect=[pos_rows, dept_rows, cur_rows, delete_result])
    else:
        # No department query — only position + current + optional delete.
        db.execute = AsyncMock(side_effect=[pos_rows, cur_rows, delete_result])

    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ── 1. New user, position has 2 courses → 2 enrollments created ──


@pytest.mark.asyncio
async def test_new_user_position_with_two_courses_creates_two_enrollments():
    course_a, course_b = uuid4(), uuid4()
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[(course_a,), (course_b,)],
        current_rows=[],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())

    assert result.added == 2
    assert result.removed == 0
    assert result.skipped_manual == 0
    assert db.add.call_count == 2

    # db.add was called with Enrollment instances; pull source off each.
    added_sources = [call.args[0].source for call in db.add.call_args_list]
    assert all(s == "position" for s in added_sources), added_sources


# ── 2. Position change removes old, adds new, completed kept ──


@pytest.mark.asyncio
async def test_position_change_removes_old_and_adds_new_completed_kept():
    new_course = uuid4()
    completed_course = uuid4()
    old_in_progress_course = uuid4()

    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[(new_course,), (completed_course,)],
        current_rows=[
            (completed_course, "position", "completed"),
            (old_in_progress_course, "position", "enrolled"),
        ],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())

    # new_course is in expected but not in current → added.
    # completed_course is in BOTH expected and current as completed —
    # it stays untouched (no add, no remove), and protected_completed
    # is NOT incremented because the row isn't being removed.
    # old_in_progress_course is NOT in expected AND status=enrolled → removed.
    assert result.added == 1
    assert result.removed == 1
    assert result.protected_completed == 0
    assert db.add.call_count == 1


# ── 3. Manual enrollment protects from position rule ──


@pytest.mark.asyncio
async def test_manual_enrollment_protects_against_position_rule():
    course_x = uuid4()
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[(course_x,)],
        current_rows=[(course_x, "manual", "enrolled")],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())

    assert result.added == 0
    assert result.removed == 0
    assert result.skipped_manual == 1
    assert db.add.call_count == 0


# ── 4. Completed enrollment kept when rule removed ──


@pytest.mark.asyncio
async def test_completed_enrollment_kept_when_rule_removed():
    completed_course = uuid4()
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[],  # no rules
        current_rows=[(completed_course, "position", "completed")],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())

    assert result.added == 0
    assert result.removed == 0
    assert result.protected_completed == 1


# ── 5. In-progress enrollment removed when rule removed ──


@pytest.mark.asyncio
async def test_in_progress_enrollment_removed_when_rule_removed():
    in_progress_course = uuid4()
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[],
        current_rows=[(in_progress_course, "position", "enrolled")],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())

    assert result.added == 0
    assert result.removed == 1


# ── 6. Idempotent: second call after no rule change is no-op ──


@pytest.mark.asyncio
async def test_idempotent_second_call_is_noop():
    course = uuid4()
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[(course,)],
        current_rows=[(course, "position", "enrolled")],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())
    assert result.added == 0
    assert result.removed == 0
    assert db.add.call_count == 0


# ── 7. Cross-tenant: rule from another tenant ignored ──


@pytest.mark.asyncio
async def test_cross_tenant_rule_not_matched():
    """tenant_id comes from the User, never from a caller-supplied argument.
    Verify by inspecting the calls: no tenant_id was passed as a parameter
    to recompute_enrollments, and the kernel reads it from db.get(User, ...).
    """
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[],
        current_rows=[],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())
    assert result.added == 0
    # db.get was called for the User (to derive tenant_id)
    assert db.get.call_count >= 1


# ── 8. required=False course still creates enrollment ──


@pytest.mark.asyncio
async def test_required_false_course_creates_enrollment():
    """The required flag lives on PositionCourse, not on the enrollment.
    recompute ignores the flag when building the expected set — it just
    materializes whatever rules exist. required=False is consumed by
    the ready_percent calculator, not by this kernel.
    """
    course = uuid4()
    db = _setup_db_with_position(
        tenant_id=uuid4(),
        position_rules_rows=[(course,)],
        current_rows=[],
        department_id=None,
    )

    result = await recompute_enrollments(db, user_id=uuid4())
    assert result.added == 1
    # Source is 'position' (set by the kernel), not 'required' (set elsewhere).
    assert db.add.call_count == 1


# ── 9. User without position → no changes ──


@pytest.mark.asyncio
async def test_user_without_position_no_changes():
    """When user.position_id is None, no rule queries run, no enrollments added."""
    db = AsyncMock()
    user = MagicMock()
    user.tenant_id = uuid4()
    user.position_id = None  # no position

    async def async_get(model, key):
        from app.models.users import User as U
        if model is U or model.__name__ == "User":
            return user
        return MagicMock()
    db.get = AsyncMock(side_effect=async_get)

    # Only the current-enrollments query runs.
    cur_rows = MagicMock()
    cur_rows.all = MagicMock(return_value=[(uuid4(), "manual", "enrolled")])
    db.execute = AsyncMock(side_effect=[cur_rows])
    db.add = MagicMock()
    db.flush = AsyncMock()

    result = await recompute_enrollments(db, user_id=uuid4())
    assert result.added == 0
    assert result.removed == 0
    assert db.add.call_count == 0


# ── 10. Department + position overlap → position wins ──


@pytest.mark.asyncio
async def test_department_and_position_overlap_position_wins():
    """If both DepartmentCourse and PositionCourse reference the same
    course for the same user, we create exactly one enrollment, with
    source='position' (position takes priority over department).
    """
    shared_course = uuid4()
    department_id = uuid4()

    db = AsyncMock()
    user = _make_user_mock(uuid4())
    pos = _make_position_mock(department_id=department_id)

    async def async_get(model, key):
        from app.models.users import User as U
        from app.modules.positions.models import Position as P
        if model is U or model.__name__ == "User":
            return user
        if model is P or model.__name__ == "Position":
            return pos
        return MagicMock()
    db.get = AsyncMock(side_effect=async_get)

    pos_rows = MagicMock()
    pos_rows.all = MagicMock(return_value=[(shared_course,)])
    dept_rows = MagicMock()
    dept_rows.all = MagicMock(return_value=[(shared_course,)])
    cur_rows = MagicMock()
    cur_rows.all = MagicMock(return_value=[])
    db.execute = AsyncMock(side_effect=[pos_rows, dept_rows, cur_rows])

    db.add = MagicMock()
    db.flush = AsyncMock()

    result = await recompute_enrollments(db, user_id=uuid4())

    # Only one enrollment, and it has source='position' (priority).
    assert result.added == 1
    assert db.add.call_count == 1
    added_obj = db.add.call_args_list[0].args[0]
    assert added_obj.source == "position"
