"""Tests for P1-5: enroll_users must validate user status and tenant.

Per TZ §7 P1-5:
  - `enroll_users` does not validate tenant/status
  - Solution: validation + unique-constraint

The pre-fix `enroll_users` happily inserted enrollment rows for:
  - users from OTHER tenants (cross-tenant leak if course_id was
    wrong-tenant — but that path is blocked upstream; still, the
    INSERT itself doesn't double-check the user's tenant matches
    the caller's tenant)
  - users that are inactive (`is_active=False` or
    `status != 'active'`)
  - duplicate (user, course) pairs under race conditions (the
    runtime check is racy; only a DB constraint is safe)

These tests cover the application-layer validation. The DB
constraint lives in a migration and is verified separately
(test_enrollment_unique_constraint.py is the right place).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.enrollments.service import enroll_users


# ── helpers ─────────────────────────────────────────────────


def _user(*, user_id=None, tenant_id=None, is_active=True, status="active"):
    u = MagicMock()
    u.id = user_id or uuid4()
    u.tenant_id = tenant_id or uuid4()
    u.is_active = is_active
    u.status = status
    return u


def _db_with_users_and_dupes(users_for_lookup: list, dup_results: list):
    """Mock db with two kinds of execute():
      - First N calls (N = users_for_lookup) return the corresponding
        user list from `users_for_lookup` (the SELECT users by id query,
        consumed via result.scalars().all()).
      - Subsequent calls (one per user enrollment check) return
        items from `dup_results` (the SELECT enrollment WHERE... query,
        consumed via result.scalar_one_or_none()).

    Each item popped from `dup_results` corresponds to the next
    duplicate-check call. None = not yet enrolled.
    """
    db = AsyncMock()
    user_q = list(users_for_lookup)
    dupe_q = list(dup_results)

    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        if user_q:
            # SELECT users → result.scalars().all() returns a list of users.
            # `users_for_lookup` items are expected to be lists of user mocks.
            scalars_mock = MagicMock()
            scalars_mock.all = MagicMock(return_value=user_q.pop(0))
            result.scalars = MagicMock(return_value=scalars_mock)
        elif dupe_q:
            # SELECT enrollment WHERE... → scalar_one_or_none returns the row.
            result.scalar_one_or_none = MagicMock(return_value=dupe_q.pop(0))
        else:
            result.scalar_one_or_none = MagicMock(return_value=None)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ── 1. enroll active user in same tenant ────────────────────


@pytest.mark.asyncio
async def test_enroll_active_user_in_tenant_succeeds():
    """Happy path: active user in the same tenant gets enrolled."""
    from app.models.enrollment import Enrollment

    tenant = uuid4()
    course = uuid4()
    user = _user(tenant_id=tenant, is_active=True, status="active")

    # 1 user lookup → user. 1 dup check → None (not yet enrolled).
    db = _db_with_users_and_dupes(
        users_for_lookup=[[user]], dup_results=[None]
    )

    result = await enroll_users(db, course, tenant, [user.id])
    assert len(result) == 1
    db.add.assert_called_once()
    add_call = db.add.call_args[0][0]
    assert isinstance(add_call, Enrollment)
    assert add_call.user_id == user.id
    assert add_call.course_id == course
    assert add_call.tenant_id == tenant


# ── 2. enroll rejects inactive user ─────────────────────────


@pytest.mark.asyncio
async def test_enroll_rejects_inactive_user():
    """An inactive user must NOT be enrolled. The pre-fix code
    happily inserted; this test pins the new contract.
    """
    tenant = uuid4()
    course = uuid4()
    inactive_user = _user(tenant_id=tenant, is_active=False, status="inactive")

    db = _db_with_users_and_dupes(
        users_for_lookup=[[inactive_user]], dup_results=[]
    )

    result = await enroll_users(db, course, tenant, [inactive_user.id])

    # No enrollment created.
    assert result == []
    db.add.assert_not_called()


# ── 3. enroll rejects user with status != 'active' ──────────


@pytest.mark.asyncio
async def test_enroll_rejects_user_with_non_active_status():
    """is_active=True but status='suspended' (e.g. HR suspended
    the user) must NOT be enrolled. Status is the source of
    truth; is_active is a derived convenience flag.
    """
    tenant = uuid4()
    course = uuid4()
    suspended_user = _user(tenant_id=tenant, is_active=True, status="suspended")

    db = _db_with_users_and_dupes(
        users_for_lookup=[[suspended_user]], dup_results=[]
    )

    result = await enroll_users(db, course, tenant, [suspended_user.id])

    assert result == []
    db.add.assert_not_called()


# ── 4. enroll rejects user from different tenant ────────────


@pytest.mark.asyncio
async def test_enroll_rejects_user_from_other_tenant():
    """Defense in depth: if a caller somehow hands us a user_id
    from a different tenant, the service MUST refuse. The course
    belongs to `tenant` so enrolling a user from `other_tenant`
    would create a cross-tenant Enrollment row.
    """
    tenant = uuid4()
    other_tenant = uuid4()
    course = uuid4()
    cross_user = _user(tenant_id=other_tenant, is_active=True, status="active")

    db = _db_with_users_and_dupes(
        users_for_lookup=[[cross_user]], dup_results=[]
    )

    result = await enroll_users(db, course, tenant, [cross_user.id])

    # Refuse — cross-tenant is a 404 / security issue.
    assert result == []
    db.add.assert_not_called()


# ── 5. enroll is mixed: valid + invalid in one call ─────────


@pytest.mark.asyncio
async def test_enroll_mixed_valid_and_invalid_users():
    """One bulk call: 4 users (1 active+same-tenant, 1 inactive,
    1 other-tenant, 1 already-enrolled). Only 1 should be added.
    """
    tenant = uuid4()
    other_tenant = uuid4()
    course = uuid4()

    good = _user(tenant_id=tenant, is_active=True, status="active")
    inactive = _user(tenant_id=tenant, is_active=False, status="inactive")
    cross = _user(tenant_id=other_tenant, is_active=True, status="active")
    already = _user(tenant_id=tenant, is_active=True, status="active")

    # 4 user lookups (one per id). The user-lookup returns
    # ALL 4 users in one shot (it's a single SELECT IN-query).
    # Then 2 dup checks — one for each user that survived the
    # validation filters: `good` (fresh) and `already` (dup).
    existing_enrollment = MagicMock()
    db = _db_with_users_and_dupes(
        users_for_lookup=[[good, inactive, cross, already]],
        dup_results=[None, existing_enrollment],
    )

    result = await enroll_users(
        db, course, tenant,
        [good.id, inactive.id, cross.id, already.id],
    )

    assert len(result) == 1
    assert db.add.call_count == 1
    added = db.add.call_args[0][0]
    assert added.user_id == good.id


# ── 6. duplicate enrollment is silently skipped ─────────────


@pytest.mark.asyncio
async def test_enroll_skips_duplicate():
    """Idempotent: re-enrolling the same (user, course) is a no-op
    (returns empty list, doesn't raise). The DB unique constraint
    is the race-safe backstop; the application check is the
    fast-path.
    """
    tenant = uuid4()
    course = uuid4()
    user = _user(tenant_id=tenant)

    # 1 user lookup → user. 1 dup check → existing row.
    existing = MagicMock()
    db = _db_with_users_and_dupes(
        users_for_lookup=[[user]], dup_results=[existing]
    )

    result = await enroll_users(db, course, tenant, [user.id])

    assert result == []
    db.add.assert_not_called()
