"""Tests for P0-3: kiosk identify must return a JWT.

Per TZ §3.5, kiosk identify is the entry point for workers without
email (field workers, shop-floor staff). After they enter their
personnel_number, the server must return a JWT (same as magic-link
auth) so the frontend can put it in authStore and the worker can
actually open courses.

The pre-fix code (kiosk_service.py:212) returned user identity +
course list, but NO access_token. The frontend could not proceed
past course selection because the course player requires auth.

These tests assert:
  1. identify_at_kiosk returns `access_token` field.
  2. The token is a valid JWT (decodable with the same secret).
  3. The token's payload has `sub` = user_id, `tenant_id`,
     `role`, and `auth_method` = "kiosk" (so we can audit
     which login path was used).
  4. The token has a SHORT expiry (≤ 30 min) per TZ §3.5 —
     shared-device protection.
  5. The token is NOT issued for non-active users (re-check).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth import decode_token
from app.core.config import get_settings


# ── helpers ─────────────────────────────────────────────────


def _user(tenant_id=None, role="student", is_active=True, status="active"):
    u = MagicMock()
    u.id = uuid4()
    u.tenant_id = tenant_id or uuid4()
    u.role = role
    u.is_active = is_active
    u.status = status
    u.first_name = "Иван"
    u.last_name = "Иванов"
    u.personnel_number = "PN-001"
    u.position_id = None
    return u


def _kiosk(tenant_id=None):
    from app.models.kiosk_link import KioskLink
    k = MagicMock(spec=KioskLink)
    k.id = uuid4()
    k.tenant_id = tenant_id or uuid4()
    k.name = "Цех №1"
    k.location = "Цех"
    k.token = "abc123"
    k.is_active = True
    # expires_at must be a real datetime or None — not a MagicMock
    # auto-attr, otherwise `if link.expires_at and link.expires_at < ...`
    # raises TypeError when comparing MagicMock to datetime.
    k.expires_at = None
    k.scope_position_id = None
    return k


def _mock_db_for_kiosk(*, kiosk, user):
    """Build a mock AsyncSession that resolves kiosk + user queries.

    Query order in identify_at_kiosk:
      1. SELECT KioskLink WHERE token=...
      2. SELECT User WHERE tenant_id=... AND personnel_number ILIKE ...
    """
    db = AsyncMock()
    call_count = {"n": 0}

    async def execute_side_effect(stmt, *args, **kwargs):
        result = MagicMock()
        call_count["n"] += 1

        if call_count["n"] == 1:
            # Kiosk lookup
            result.scalar_one_or_none = MagicMock(return_value=kiosk)
            result.all = MagicMock(return_value=[])
        else:
            # User lookup
            result.scalar_one_or_none = MagicMock(return_value=user)
            result.all = MagicMock(return_value=[])

        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ── 1. happy path: identify returns access_token ───────────


@pytest.mark.asyncio
async def test_identify_returns_access_token():
    """identify_at_kiosk must include a non-empty access_token field."""
    from app.modules.users.kiosk_service import identify_at_kiosk

    tenant = uuid4()
    user = _user(tenant_id=tenant)
    kiosk = _kiosk(tenant_id=tenant)
    db = _mock_db_for_kiosk(kiosk=kiosk, user=user)

    result = await identify_at_kiosk(db, kiosk.token, user.personnel_number)

    assert "access_token" in result
    assert isinstance(result["access_token"], str)
    assert len(result["access_token"]) > 50  # real JWT, not a stub


# ── 2. token is decodable and has correct claims ───────────


@pytest.mark.asyncio
async def test_identify_token_has_correct_payload():
    """The issued JWT must carry sub=user_id, tenant_id, role,
    and auth_method='kiosk' for audit purposes.
    """
    from app.modules.users.kiosk_service import identify_at_kiosk

    tenant = uuid4()
    user = _user(tenant_id=tenant, role="student")
    kiosk = _kiosk(tenant_id=tenant)
    db = _mock_db_for_kiosk(kiosk=kiosk, user=user)

    result = await identify_at_kiosk(db, kiosk.token, user.personnel_number)
    token = result["access_token"]

    # Decode with the same secret the app uses — proves it's
    # a real, valid token, not a placeholder.
    payload = decode_token(token)
    assert payload["sub"] == str(user.id)
    assert payload["tenant_id"] == str(tenant)
    assert payload["role"] == "student"
    assert payload["auth_method"] == "kiosk"


# ── 3. token has short TTL (≤ 30 min) per TZ §3.5 ──────────


@pytest.mark.asyncio
async def test_identify_token_has_short_ttl():
    """Per TZ §3.5, kiosk tokens are short-lived (15-30 min) to
    protect against shared-device abuse: when the worker closes
    the kiosk tab, the next user must re-identify with their
    own personnel_number.
    """
    from app.modules.users.kiosk_service import identify_at_kiosk

    tenant = uuid4()
    user = _user(tenant_id=tenant)
    kiosk = _kiosk(tenant_id=tenant)
    db = _mock_db_for_kiosk(kiosk=kiosk, user=user)

    result = await identify_at_kiosk(db, kiosk.token, user.personnel_number)
    payload = decode_token(result["access_token"])

    now_ts = int(datetime.now(timezone.utc).timestamp())
    exp_ts = payload["exp"]
    ttl_seconds = exp_ts - now_ts

    # 15-30 minutes per TZ §3.5. We allow up to 30 min (1800s)
    # and require at least 14 min (840s) to be tight.
    assert 14 * 60 <= ttl_seconds <= 30 * 60, (
        f"Kiosk JWT TTL must be 15-30 min per TZ §3.5, got {ttl_seconds}s"
    )


# ── 4. token is NOT issued for inactive users ──────────────


@pytest.mark.asyncio
async def test_identify_does_not_issue_token_for_inactive_user():
    """A user with is_active=False or status!='active' must be
    rejected at identify time, BEFORE any token is minted. We
    don't want a JWT lying around for a deactivated account.
    """
    from app.modules.users.kiosk_service import identify_at_kiosk

    tenant = uuid4()
    user = _user(tenant_id=tenant, is_active=False, status="inactive")
    kiosk = _kiosk(tenant_id=tenant)
    db = _mock_db_for_kiosk(kiosk=kiosk, user=user)

    with pytest.raises(HTTPException) as exc:
        await identify_at_kiosk(db, kiosk.token, user.personnel_number)
    assert exc.value.status_code == 403
    # Importantly: no token in the response (the raise prevents it)


# ── 5. response shape is preserved (backward compat) ───────


@pytest.mark.asyncio
async def test_identify_response_includes_user_courses_and_token():
    """The pre-existing response shape (user, kiosk_name,
    kiosk_location, courses) must still be present alongside
    the new access_token field.
    """
    from app.modules.users.kiosk_service import identify_at_kiosk

    tenant = uuid4()
    user = _user(tenant_id=tenant)
    kiosk = _kiosk(tenant_id=tenant)
    db = _mock_db_for_kiosk(kiosk=kiosk, user=user)

    result = await identify_at_kiosk(db, kiosk.token, user.personnel_number)

    assert "user" in result
    assert "kiosk_name" in result
    assert "kiosk_location" in result
    assert "courses" in result
    assert "access_token" in result  # new
    assert "token_type" in result  # "bearer" hint for frontend
