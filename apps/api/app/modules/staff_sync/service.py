"""Idempotent employee lifecycle operations for Staff Sync."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trial_limits import assert_can_create_learners, assert_tenant_access
from app.models.user_sessions import UserSession
from app.models.users import User
from app.modules.positions.batch_service import apply_rules_for_users
from app.modules.positions.models import Position

from .auth import StaffSyncContext, hash_staff_sync_token
from .models import StaffSyncCredential, StaffSyncEvent, StaffSyncIdentity
from .schemas import (
    StaffSyncCredentialCreate,
    StaffSyncCredentialCreated,
    StaffSyncEmployeeInput,
    StaffSyncEventRequest,
    StaffSyncEventResponse,
)


class StaffSyncConflictError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_INTEGRITY_CONFLICT_CODES = {
    "uq_user_telegram": "telegram_conflict",
    "uq_users_tenant_personnel": "personnel_number_conflict",
    "uq_users_tenant_email_ci": "email_conflict",
    "uq_staff_sync_external_identity": "external_identity_conflict",
    "uq_staff_sync_user_source": "user_source_conflict",
}


def integrity_conflict_code(exc: IntegrityError) -> str | None:
    candidate = exc.orig
    for current in (candidate, getattr(candidate, "__cause__", None)):
        constraint_name = getattr(current, "constraint_name", None)
        if constraint_name in _INTEGRITY_CONFLICT_CODES:
            return _INTEGRITY_CONFLICT_CODES[constraint_name]
    return None


def canonical_event_sha256(payload: StaffSyncEventRequest) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def rotate_credential(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    created_by: UUID | None,
    payload: StaffSyncCredentialCreate,
) -> StaffSyncCredentialCreated:
    now = datetime.now(UTC)
    if payload.expires_at is not None and payload.expires_at <= now:
        raise HTTPException(status_code=422, detail="Credential expiry must be in the future")

    active = list((await db.scalars(
        select(StaffSyncCredential).where(
            StaffSyncCredential.tenant_id == tenant_id,
            StaffSyncCredential.revoked_at.is_(None),
        )
    )).all())
    for credential in active:
        credential.is_active = False
        credential.revoked_at = now

    token = secrets.token_urlsafe(48)
    credential = StaffSyncCredential(
        tenant_id=tenant_id,
        name=payload.name.strip(),
        token_hash=hash_staff_sync_token(token),
        scopes=["staff:sync"],
        is_active=True,
        expires_at=payload.expires_at,
        created_by=created_by,
    )
    db.add(credential)
    await db.flush()
    return StaffSyncCredentialCreated(
        id=credential.id,
        name=credential.name,
        token=token,
        scopes=list(credential.scopes),
        expires_at=credential.expires_at,
        created_at=credential.created_at,
    )


async def _identity_and_user(
    db: AsyncSession,
    context: StaffSyncContext,
    payload: StaffSyncEventRequest,
) -> tuple[StaffSyncIdentity | None, User | None]:
    identity = await db.scalar(
        select(StaffSyncIdentity).where(
            StaffSyncIdentity.tenant_id == context.tenant_id,
            StaffSyncIdentity.source == payload.source,
            StaffSyncIdentity.external_employee_id == payload.external_employee_id,
        )
    )
    if identity is None:
        return None, None
    user = await db.scalar(
        select(User).where(
            User.id == identity.user_id,
            User.tenant_id == context.tenant_id,
        )
    )
    if user is None:
        raise StaffSyncConflictError("identity_target_missing", "Linked employee no longer exists")
    if user.role != "student":
        raise StaffSyncConflictError("managed_role_forbidden", "Staff Sync cannot modify privileged users")
    return identity, user


async def _resolve_position(
    db: AsyncSession,
    tenant_id: UUID,
    external_key: str | None,
    *,
    required: bool,
) -> Position | None:
    if not external_key:
        if required:
            raise StaffSyncConflictError("position_required", "position_external_key is required for a new employee")
        return None
    positions = list((await db.scalars(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.external_key == external_key.strip(),
            Position.is_active.is_(True),
        )
    )).all())
    if not positions:
        raise StaffSyncConflictError("position_not_found", "Position external key was not found")
    if len(positions) > 1:
        raise StaffSyncConflictError("position_ambiguous", "Position external key is not unique")
    return positions[0]


async def _assert_employee_keys_available(
    db: AsyncSession,
    tenant_id: UUID,
    employee: StaffSyncEmployeeInput,
    current_user_id: UUID | None,
) -> None:
    pn = employee.personnel_number.strip().lower()
    pn_owner = await db.scalar(
        select(User.id).where(
            User.tenant_id == tenant_id,
            func.lower(func.btrim(User.personnel_number)) == pn,
            User.id != current_user_id if current_user_id is not None else User.id.is_not(None),
        )
    )
    if pn_owner is not None:
        raise StaffSyncConflictError("personnel_number_conflict", "Personnel number belongs to another employee")

    if employee.email:
        email = str(employee.email).strip().lower()
        email_owner = await db.scalar(
            select(User.id).where(
                User.tenant_id == tenant_id,
                func.lower(func.btrim(User.email)) == email,
                User.id != current_user_id if current_user_id is not None else User.id.is_not(None),
            )
        )
        if email_owner is not None:
            raise StaffSyncConflictError("email_conflict", "Email belongs to another employee")


def _apply_employee_fields(user: User, employee: StaffSyncEmployeeInput) -> list[str]:
    updates = {
        "personnel_number": employee.personnel_number.strip(),
        "first_name": employee.first_name.strip(),
        "last_name": employee.last_name.strip(),
        "email": str(employee.email).strip().lower() if employee.email else None,
        "phone": (employee.phone or "").strip() or None,
        "hire_date": employee.hire_date,
    }
    changed: list[str] = []
    for field, value in updates.items():
        if getattr(user, field) != value:
            if field == "email":
                user.email_verified_at = None
            setattr(user, field, value)
            changed.append(field)
    return changed


async def _upsert_employee(
    db: AsyncSession,
    context: StaffSyncContext,
    payload: StaffSyncEventRequest,
    *,
    allow_reactivate: bool,
) -> tuple[User, str, list[str]]:
    assert payload.employee is not None
    employee = payload.employee
    identity, user = await _identity_and_user(db, context, payload)
    position = await _resolve_position(
        db,
        context.tenant_id,
        employee.position_external_key,
        required=user is None,
    )

    if user is None:
        was_created = False
        existing = await db.scalar(
            select(User).where(
                User.tenant_id == context.tenant_id,
                func.lower(func.btrim(User.personnel_number)) == employee.personnel_number.strip().lower(),
            )
        )
        if existing is not None:
            if existing.role != "student":
                raise StaffSyncConflictError("managed_role_forbidden", "Staff Sync cannot link a privileged user")
            existing_email = (existing.email or "").strip().lower() or None
            requested_email = str(employee.email).strip().lower() if employee.email else None
            if existing_email and requested_email and existing_email != requested_email:
                raise StaffSyncConflictError(
                    "employee_identity_conflict",
                    "Personnel number and email point to different employee data",
                )
            user = existing
        else:
            await _assert_employee_keys_available(
                db,
                context.tenant_id,
                employee,
                current_user_id=None,
            )
            await assert_can_create_learners(db, context.tenant_id, requested=1)
            was_created = True
            user = User(
                tenant_id=context.tenant_id,
                personnel_number=employee.personnel_number.strip(),
                first_name=employee.first_name.strip(),
                last_name=employee.last_name.strip(),
                email=str(employee.email).strip().lower() if employee.email else None,
                phone=(employee.phone or "").strip() or None,
                hire_date=employee.hire_date,
                role="student",
                is_active=True,
                status="active",
                position_id=position.id if position else None,
            )
            db.add(user)
            await db.flush()

        identity = StaffSyncIdentity(
            tenant_id=context.tenant_id,
            source=payload.source,
            external_employee_id=payload.external_employee_id,
            user_id=user.id,
        )
        db.add(identity)
        created_or_linked = "created" if was_created else "linked"
    else:
        created_or_linked = "updated"

    if not user.is_active and not allow_reactivate:
        raise StaffSyncConflictError("employee_inactive", "Use reactivate for an inactive employee")

    await _assert_employee_keys_available(db, context.tenant_id, employee, user.id)
    changed = _apply_employee_fields(user, employee)
    if position is not None and user.position_id != position.id:
        user.position_id = position.id
        changed.append("position_id")
    if allow_reactivate and not user.is_active:
        await assert_can_create_learners(db, context.tenant_id, requested=1)
        user.is_active = True
        user.status = "active"
        changed.extend(["is_active", "status"])

    await db.flush()
    await apply_rules_for_users(db, [user.id])
    status = "reactivated" if allow_reactivate and "is_active" in changed else created_or_linked
    if status in {"updated", "linked"} and not changed:
        status = "unchanged"
    return user, status, sorted(set(changed))


async def _terminate_employee(
    db: AsyncSession,
    context: StaffSyncContext,
    payload: StaffSyncEventRequest,
) -> tuple[User, str, list[str]]:
    _, user = await _identity_and_user(db, context, payload)
    if user is None:
        raise StaffSyncConflictError("identity_not_found", "External employee identity is not linked")
    if not user.is_active:
        return user, "unchanged", []
    user.is_active = False
    user.status = "inactive"
    await db.execute(
        delete(UserSession).where(
            UserSession.tenant_id == context.tenant_id,
            UserSession.user_id == user.id,
        )
    )
    await db.flush()
    return user, "deactivated", ["is_active", "status", "sessions"]


async def process_event(
    db: AsyncSession,
    context: StaffSyncContext,
    payload: StaffSyncEventRequest,
) -> StaffSyncEventResponse:
    await assert_tenant_access(db, context.tenant_id)
    now = datetime.now(UTC)
    effective_at = payload.effective_at
    if effective_at.tzinfo is None:
        effective_at = effective_at.replace(tzinfo=UTC)
    if effective_at > now:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "future_effective_at_not_supported",
                "message": "Scheduled lifecycle events are not enabled yet",
            },
        )

    payload_sha256 = canonical_event_sha256(payload)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {
            "lock_key": (
                f"staff-sync:{context.tenant_id}:{payload.source}:{payload.event_id}"
            )
        },
    )
    existing = await db.scalar(
        select(StaffSyncEvent).where(
            StaffSyncEvent.tenant_id == context.tenant_id,
            StaffSyncEvent.source == payload.source,
            StaffSyncEvent.event_id == payload.event_id,
        )
    )
    if existing is not None:
        if existing.payload_sha256 != payload_sha256:
            raise HTTPException(
                status_code=409,
                detail={"code": "event_id_reused", "message": "event_id was already used with another payload"},
            )
        outcome = existing.outcome_json or {}
        return StaffSyncEventResponse(
            event_id=existing.event_id,
            action=existing.action,
            status=existing.status,
            employee_id=existing.employee_id,
            external_employee_id=existing.external_employee_id,
            changed_fields=list(outcome.get("changed_fields") or []),
            error_code=outcome.get("error_code"),
            message=outcome.get("message"),
            replayed=True,
        )

    event = StaffSyncEvent(
        tenant_id=context.tenant_id,
        credential_id=context.credential_id,
        source=payload.source,
        event_id=payload.event_id,
        payload_sha256=payload_sha256,
        action=payload.action,
        external_employee_id=payload.external_employee_id,
        status="processing",
        effective_at=effective_at,
    )
    db.add(event)
    credential = await db.get(StaffSyncCredential, context.credential_id)
    if credential is not None:
        credential.last_used_at = now
    await db.flush()

    try:
        async with db.begin_nested():
            if payload.action == "upsert":
                user, event_status, changed = await _upsert_employee(
                    db, context, payload, allow_reactivate=False,
                )
            elif payload.action == "terminate":
                user, event_status, changed = await _terminate_employee(db, context, payload)
            else:
                if payload.employee is None:
                    _, current = await _identity_and_user(db, context, payload)
                    if current is None:
                        raise StaffSyncConflictError(
                            "identity_not_found",
                            "External employee identity is not linked",
                        )
                    if current.is_active:
                        user, event_status, changed = current, "unchanged", []
                    else:
                        await assert_can_create_learners(db, context.tenant_id, requested=1)
                        current.is_active = True
                        current.status = "active"
                        await db.flush()
                        await apply_rules_for_users(db, [current.id])
                        user, event_status, changed = current, "reactivated", ["is_active", "status"]
                else:
                    user, event_status, changed = await _upsert_employee(
                        db, context, payload, allow_reactivate=True,
                    )
        event.employee_id = user.id
        event.status = event_status
        event.outcome_json = {"changed_fields": changed}
    except StaffSyncConflictError as conflict:
        event.status = "conflict"
        event.outcome_json = {"error_code": conflict.code, "message": conflict.message}
        changed = []
    except IntegrityError as integrity_error:
        conflict_code = integrity_conflict_code(integrity_error)
        if conflict_code is None:
            raise
        event.status = "conflict"
        event.outcome_json = {
            "error_code": conflict_code,
            "message": "Employee identity conflicts with an existing record",
        }
        changed = []

    event.processed_at = datetime.now(UTC)
    await db.flush()
    return StaffSyncEventResponse(
        event_id=event.event_id,
        action=payload.action,
        status=event.status,
        employee_id=event.employee_id,
        external_employee_id=event.external_employee_id,
        changed_fields=changed,
        error_code=event.outcome_json.get("error_code"),
        message=event.outcome_json.get("message"),
    )
