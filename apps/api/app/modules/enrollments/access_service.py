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
from app.models.enrollment_access_policy import EnrollmentAccessPolicy
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


def can_exchange_assignment_link(credential: AssignmentAccessCredential, *, now: datetime) -> bool:
    """Whether a public link may start a new PIN exchange.

    The credential expiry intentionally belongs to the public link rather than
    to an already-issued assignment bearer token.  The latter is checked on
    each request through the credential's revocation status and the exact
    enrollment policy window.
    """
    return not credential.revoked_at and credential.expires_at > now


def record_assignment_exchange_start(
    policy: EnrollmentAccessPolicy,
    credential: AssignmentAccessCredential,
    *,
    now: datetime,
) -> None:
    """Atomically mark a successful first exchange while both rows are locked."""
    if policy.completion_window_started_at is None:
        policy.completion_window_started_at = now
        if policy.completion_window_minutes:
            policy.completion_window_expires_at = now + timedelta(minutes=policy.completion_window_minutes)
    credential.first_exchanged_at = credential.first_exchanged_at or now


def access_policy_payload(policy: EnrollmentAccessPolicy) -> dict:
    now = datetime.now(UTC)
    expired = bool(
        policy.revoked_at
        or (policy.completion_window_started_at is None and policy.link_expires_at and policy.link_expires_at <= now)
        or (policy.due_at and policy.due_at <= now)
        or (policy.completion_window_expires_at and policy.completion_window_expires_at <= now)
    )
    return {
        "enrollment_id": policy.enrollment_id,
        "delivery_mode": policy.delivery_mode,
        "link_expires_at": policy.link_expires_at,
        "completion_window_minutes": policy.completion_window_minutes,
        "completion_window_started_at": policy.completion_window_started_at,
        "completion_window_expires_at": policy.completion_window_expires_at,
        "due_at": policy.due_at,
        "state": "expired" if expired else "available",
    }


async def upsert_access_policy(
    db: AsyncSession,
    *,
    enrollment: Enrollment,
    delivery_mode: str,
    link_expires_at: datetime | None = None,
    completion_window_minutes: int | None = None,
    due_at: datetime | None = None,
) -> EnrollmentAccessPolicy:
    policy = await db.scalar(
        select(EnrollmentAccessPolicy)
        .where(
            EnrollmentAccessPolicy.enrollment_id == enrollment.id,
            EnrollmentAccessPolicy.tenant_id == enrollment.tenant_id,
        )
        .with_for_update()
    )
    if policy is None:
        policy = EnrollmentAccessPolicy(
            tenant_id=enrollment.tenant_id,
            enrollment_id=enrollment.id,
            user_id=enrollment.user_id,
            delivery_mode=delivery_mode,
        )
        db.add(policy)
    policy.delivery_mode = delivery_mode
    policy.link_expires_at = link_expires_at
    policy.completion_window_minutes = completion_window_minutes
    policy.due_at = due_at
    policy.revoked_at = None
    policy.revoked_reason = None
    # A changed window defines a fresh, not-yet-started policy. Existing
    # access credentials are independently reissued/revoked by the caller.
    policy.completion_window_started_at = None
    policy.completion_window_expires_at = None
    await db.flush()
    return policy


async def get_access_policy(
    db: AsyncSession, *, enrollment_id: UUID, tenant_id: UUID, lock: bool = False
) -> EnrollmentAccessPolicy | None:
    statement = select(EnrollmentAccessPolicy).where(
        EnrollmentAccessPolicy.enrollment_id == enrollment_id,
        EnrollmentAccessPolicy.tenant_id == tenant_id,
    )
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def issue_assignment_access(
    db: AsyncSession,
    enrollment_id: UUID,
    tenant_id: UUID,
    base_url: str | None,
    *,
    link_expires_at: datetime | None = None,
    completion_window_minutes: int | None = None,
    due_at: datetime | None = None,
    allow_email: bool = False,
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
        or (bool((learner.email or "").strip()) and not allow_email)
        or enrollment.status not in {"enrolled", "in_progress"}
    ):
        return None
    existing_policy = await get_access_policy(db, enrollment_id=enrollment.id, tenant_id=tenant_id, lock=True)
    if existing_policy is not None and existing_policy.completion_window_started_at is not None:
        # A reissued URL/PIN must never silently grant a fresh completion
        # window. Deliberate deadline changes belong to the audited extend
        # endpoint, which requires an operator reason.
        raise AssignmentAccessWindowAlreadyStartedError
    active = await db.scalars(
        select(AssignmentAccessCredential)
        .where(
            AssignmentAccessCredential.enrollment_id == enrollment_id,
            AssignmentAccessCredential.tenant_id == tenant_id,
            AssignmentAccessCredential.revoked_at.is_(None),
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    for credential in active:
        credential.revoked_at = now
        credential.revoked_reason = "reissued"
    token, pin = secrets.token_urlsafe(32), f"{secrets.randbelow(1_000_000):06d}"
    expires_at = link_expires_at or (now + ACCESS_TTL)
    if expires_at <= now:
        return None
    effective_window_minutes = (
        completion_window_minutes
        if completion_window_minutes is not None
        else (existing_policy.completion_window_minutes if existing_policy else None)
    )
    effective_due_at = due_at if due_at is not None else (existing_policy.due_at if existing_policy else None)
    policy = await upsert_access_policy(
        db,
        enrollment=enrollment,
        delivery_mode="personal_link",
        link_expires_at=expires_at,
        completion_window_minutes=effective_window_minutes,
        due_at=effective_due_at,
    )
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
        "user_id": enrollment.user_id,
        "access_url": f"{(base_url or 'https://app.kml.kz').rstrip('/')}/access/{token}",
        "temporary_pin": pin,
        "expires_at": expires_at,
        **access_policy_payload(policy),
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
        or not can_exchange_assignment_link(credential, now=now)
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
    enrollment_row = await db.scalar(
        select(Enrollment)
        .where(Enrollment.id == credential.enrollment_id, Enrollment.tenant_id == credential.tenant_id)
        .with_for_update()
    )
    if enrollment_row is None:
        return None
    policy = await get_access_policy(db, enrollment_id=enrollment_row.id, tenant_id=credential.tenant_id, lock=True)
    if policy is None or policy.delivery_mode != "personal_link":
        return None
    if policy.revoked_at:
        return None
    if policy.link_expires_at and policy.link_expires_at <= now:
        raise AssignmentWindowExpiredError("assignment_link_expired", policy.link_expires_at)
    if policy.due_at and policy.due_at <= now:
        raise AssignmentWindowExpiredError("assignment_due_at_expired", policy.due_at)
    if policy.completion_window_expires_at and policy.completion_window_expires_at <= now:
        raise AssignmentWindowExpiredError("assignment_completion_window_expired", policy.completion_window_expires_at)
    # The marker is deliberately recorded even without a configured window:
    # after the first successful exchange, link expiry cannot invalidate this
    # already-issued bearer session.  A configured duration additionally
    # creates the independent completion deadline.
    record_assignment_exchange_start(policy, credential, now=now)
    await db.flush()
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
        "assigned_course_id": enrollment_row.course_id,
        "enrollment_id": enrollment_row.id,
        "access_policy": access_policy_payload(policy),
    }


class AssignmentWindowExpiredError(Exception):
    def __init__(self, code: str, expires_at: datetime):
        self.code = code
        self.expires_at = expires_at


class AssignmentAccessWindowAlreadyStartedError(Exception):
    """The access link may not be reissued after its completion window starts."""


def assignment_window_error(exc: AssignmentWindowExpiredError):
    """Structured, user-safe 409 for countdown and expiry UI."""
    from fastapi import HTTPException

    return HTTPException(
        status_code=409,
        detail={"code": exc.code, "expires_at": exc.expires_at.isoformat()},
    )


async def require_active_enrollment_window(
    db: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    course_id: UUID,
    enrollment_id: UUID | None = None,
) -> Enrollment | None:
    """Gate learner actions for a personal-link assignment after exchange.

    Normal account/email learners retain existing course behavior. Assignment
    access JWTs are already credential-bound in auth; this guard adds the
    enrollment-specific completion and absolute deadline semantics.
    """
    criteria = [
        Enrollment.tenant_id == tenant_id,
        Enrollment.user_id == user_id,
        Enrollment.course_id == course_id,
        Enrollment.status.in_(("enrolled", "in_progress")),
    ]
    if enrollment_id is not None:
        criteria.append(Enrollment.id == enrollment_id)
    enrollment = await db.scalar(select(Enrollment).where(*criteria).order_by(Enrollment.enrolled_at.desc()).limit(1))
    if enrollment is None:
        return None
    policy = await get_access_policy(db, enrollment_id=enrollment.id, tenant_id=tenant_id)
    if policy is None or policy.delivery_mode != "personal_link":
        return enrollment
    now = datetime.now(UTC)
    if policy.revoked_at:
        raise AssignmentWindowExpiredError("assignment_access_revoked", policy.revoked_at)
    if policy.due_at and policy.due_at <= now:
        raise AssignmentWindowExpiredError("assignment_due_at_expired", policy.due_at)
    if policy.completion_window_expires_at and policy.completion_window_expires_at <= now:
        raise AssignmentWindowExpiredError("assignment_completion_window_expired", policy.completion_window_expires_at)
    return enrollment


async def get_assignment_access_window(
    db: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    course_id: UUID,
    enrollment_id: UUID | None,
) -> dict | None:
    """Return timer-safe state only for the enrollment bound to this JWT."""
    if enrollment_id is None:
        return None
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.id == enrollment_id,
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
        )
    )
    if enrollment is None:
        return None
    policy = await get_access_policy(db, enrollment_id=enrollment.id, tenant_id=tenant_id)
    if policy is None or policy.delivery_mode != "personal_link":
        return None
    return {"server_now": datetime.now(UTC), "access_policy": access_policy_payload(policy)}
