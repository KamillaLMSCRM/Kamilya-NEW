"""Secure access-without-email credentials for an assignment."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token
from app.core.config import get_settings
from app.models.assignment_access import AssignmentAccessCredential
from app.models.enrollment import Enrollment
from app.models.users import User

PIN_HASHER = PasswordHasher()
ACCESS_TTL = timedelta(days=7)
LOCKOUT = timedelta(minutes=15)
MAX_FAILED_ATTEMPTS = 5


def assignment_access_session_ttl() -> timedelta:
    """Bounded non-refreshable session duration for a PIN exchange."""
    return timedelta(minutes=get_settings().ASSIGNMENT_ACCESS_SESSION_MINUTES)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_assignment_access(
    db: AsyncSession, enrollment_id: UUID, tenant_id: UUID, base_url: str | None
) -> dict | None:
    row = await db.execute(
        select(Enrollment, User)
        .join(User, User.id == Enrollment.user_id)
        .where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
        .with_for_update()
    )
    pair = row.one_or_none()
    if pair is None:
        return None
    enrollment, learner = pair
    if (
        learner.tenant_id != tenant_id
        or learner.role != "student"
        or not learner.is_active
        or learner.status != "active"
        or bool((learner.email or "").strip())
        or enrollment.status not in {"enrolled", "in_progress"}
    ):
        return None
    active = await db.scalars(
        select(AssignmentAccessCredential)
        .where(
            AssignmentAccessCredential.enrollment_id == enrollment_id, AssignmentAccessCredential.revoked_at.is_(None)
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    for credential in active:
        credential.revoked_at = now
        credential.revoked_reason = "reissued"
    token, pin = secrets.token_urlsafe(32), f"{secrets.randbelow(1_000_000):06d}"
    expires_at = now + ACCESS_TTL
    credential = AssignmentAccessCredential(
        tenant_id=tenant_id,
        enrollment_id=enrollment_id,
        user_id=enrollment.user_id,
        token_hash=_token_hash(token),
        pin_hash=PIN_HASHER.hash(pin),
        expires_at=expires_at,
    )
    db.add(credential)
    await db.flush()
    return {
        "enrollment_id": enrollment_id,
        "access_url": f"{(base_url or 'https://app.kml.kz').rstrip('/')}/access/{token}",
        "temporary_pin": pin,
        "expires_at": expires_at,
    }


async def establish_assignment_access_context(db: AsyncSession, token: str) -> UUID | None:
    return await db.scalar(
        text("SELECT lookup_assignment_access_tenant_by_token(:token)"), {"token": _token_hash(token)}
    )


async def exchange_assignment_access(db: AsyncSession, token: str, pin: str) -> dict | None:
    credential = await db.scalar(
        select(AssignmentAccessCredential)
        .where(AssignmentAccessCredential.token_hash == _token_hash(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        credential is None
        or credential.revoked_at
        or credential.expires_at <= now
        or (credential.locked_until and credential.locked_until > now)
    ):
        return None
    try:
        valid = PIN_HASHER.verify(credential.pin_hash, pin)
    except VerifyMismatchError:
        valid = False
    if not valid:
        credential.failed_attempts += 1
        if credential.failed_attempts >= MAX_FAILED_ATTEMPTS:
            credential.locked_until = now + LOCKOUT
        await db.flush()
        return None
    credential.failed_attempts = 0
    credential.locked_until = None
    learner = await db.scalar(
        select(User).where(
            User.id == credential.user_id,
            User.tenant_id == credential.tenant_id,
            User.is_active.is_(True),
            User.status == "active",
            User.role == "student",
        )
    )
    enrollment = await db.scalar(
        select(Enrollment.id).where(
            Enrollment.id == credential.enrollment_id,
            Enrollment.tenant_id == credential.tenant_id,
            Enrollment.user_id == credential.user_id,
            Enrollment.status.in_(("enrolled", "in_progress")),
        )
    )
    if learner is None or enrollment is None:
        return None
    session = create_access_token(
        {
            "sub": str(learner.id),
            "tenant_id": str(learner.tenant_id),
            "active_role": "student",
            "auth_method": "assignment_access",
            "assignment_access_credential_id": str(credential.id),
            "assignment_access_enrollment_id": str(credential.enrollment_id),
        },
        expires_delta=assignment_access_session_ttl(),
    )
    from app.modules.auth.service import build_user_payload

    return {
        "access_token": session,
        "token_type": "bearer",
        "user": await build_user_payload(db, learner, active_role="student"),
    }
