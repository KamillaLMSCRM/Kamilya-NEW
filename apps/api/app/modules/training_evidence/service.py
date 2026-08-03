"""Append-only training evidence service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.release_models import ContentRelease
from app.modules.training_evidence.models import (
    TrainingEvidenceEvent,
    TrainingEvidenceLegalHold,
    TrainingEvidenceStepUpConfirmation,
)
from app.modules.training_procedures.models import TrainingProcedure

_REGULATED_PROCEDURE_TYPES = {"acknowledgement", "internal_attestation", "admission_decision"}
_SYSTEM_PROCEDURE_TYPES = {"training", "knowledge_check"}


def _correction_workflow_error(procedure_type: str) -> HTTPException:
    if procedure_type in _SYSTEM_PROCEDURE_TYPES:
        code = "system_evidence_workflow_required"
        message = "Training and knowledge-check evidence is corrected by the trusted learning workflow"
    elif procedure_type in {"internal_attestation", "admission_decision"}:
        code = "regulated_evidence_workflow_required"
        message = "Attestation and admission evidence requires a dedicated regulated workflow"
    else:
        code = "acknowledgement_correction_required"
        message = "Generic corrections are limited to acknowledgement evidence"
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )


def _event_requires_confirmation(event: TrainingEvidenceEvent) -> bool:
    snapshot = event.payload_snapshot
    return isinstance(snapshot, Mapping) and isinstance(snapshot.get("confirmation"), Mapping)


async def _confirmation_event_ids(
    db: AsyncSession,
    tenant_id: UUID,
    event_ids: list[UUID],
) -> set[UUID]:
    if not event_ids:
        return set()
    rows = await db.scalars(
        select(TrainingEvidenceStepUpConfirmation.event_id).where(
            TrainingEvidenceStepUpConfirmation.tenant_id == tenant_id,
            TrainingEvidenceStepUpConfirmation.event_id.in_(event_ids),
        )
    )
    return set(rows.all())


async def _content_releases_by_id(
    db: AsyncSession,
    tenant_id: UUID,
    release_ids: list[UUID],
) -> dict[UUID, ContentRelease]:
    if not release_ids:
        return {}
    releases = await db.scalars(
        select(ContentRelease).where(
            ContentRelease.tenant_id == tenant_id,
            ContentRelease.id.in_(release_ids),
        )
    )
    return {release.id: release for release in releases.all()}


def _learner_event_response(
    event: TrainingEvidenceEvent,
    confirmed_event_ids: set[UUID],
    release: ContentRelease | None = None,
):
    from app.modules.training_evidence.schemas import LearnerEvidenceEventResponse

    snapshot = event.payload_snapshot if isinstance(event.payload_snapshot, Mapping) else {}
    confirmation = snapshot.get("confirmation")
    confirmation = confirmation if isinstance(confirmation, Mapping) else {}
    procedure = snapshot.get("procedure")
    procedure = procedure if isinstance(procedure, Mapping) else {}
    procedure_title = procedure.get("title")
    procedure_title = procedure_title if isinstance(procedure_title, str) else None
    statement = confirmation.get("statement")
    object_version = confirmation.get("object_version")
    statement = statement if isinstance(statement, str) else None
    object_version = object_version if isinstance(object_version, str) else None

    release_version = release.version if release is not None else snapshot.get("release_version")
    if isinstance(release_version, bool):
        release_version = None
    elif isinstance(release_version, str) and release_version.isdigit():
        release_version = int(release_version)
    elif not isinstance(release_version, int):
        release_version = None

    release_sha256 = release.snapshot_sha256 if release is not None else (
        snapshot.get("content_release_sha256") or snapshot.get("release_sha256")
    )
    if not (
        isinstance(release_sha256, str)
        and len(release_sha256) == 64
        and all(character in "0123456789abcdefABCDEF" for character in release_sha256)
    ):
        release_sha256 = None

    if not _event_requires_confirmation(event):
        confirmation_status = "not_required"
    elif event.id in confirmed_event_ids:
        confirmation_status = "confirmed"
    else:
        confirmation_status = "pending"
    return LearnerEvidenceEventResponse(
        id=event.id,
        enrollment_id=event.enrollment_id,
        content_release_id=event.content_release_id,
        training_procedure_id=event.training_procedure_id,
        procedure_type=event.procedure_type,
        record_type=event.record_type,
        related_event_id=event.related_event_id,
        occurred_at=event.occurred_at,
        created_at=event.created_at,
        confirmation_status=confirmation_status,
        procedure_title=procedure_title,
        confirmation_statement=statement,
        confirmation_object_version=object_version,
        release_version=release_version,
        release_sha256=release_sha256,
    )


def canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime | None) -> datetime:
    return value or datetime.now(UTC)


def _source_event_matches(
    existing: TrainingEvidenceEvent,
    *,
    tenant_id: UUID,
    user_id: UUID,
    enrollment_id: UUID | None,
    content_release_id: UUID | None,
    training_procedure_id: UUID | None,
    procedure_type: str,
    record_type: str,
    related_event_id: UUID | None,
    payload_sha256: str,
) -> bool:
    """Return whether an existing key represents this exact original event."""

    return (
        existing.tenant_id == tenant_id
        and existing.user_id == user_id
        and existing.enrollment_id == enrollment_id
        and existing.content_release_id == content_release_id
        and existing.training_procedure_id == training_procedure_id
        and existing.procedure_type == procedure_type
        and existing.record_type == record_type == "original"
        and existing.related_event_id is None
        and related_event_id is None
        and existing.payload_sha256 == payload_sha256
    )


async def _tenant_user(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _assert_links(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    user_id: UUID,
    enrollment_id: UUID | None,
    content_release_id: UUID | None,
) -> None:
    await _tenant_user(db, tenant_id, user_id)
    enrollment = None
    if enrollment_id is not None:
        enrollment = await db.scalar(
            select(Enrollment).where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
        )
        if enrollment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found")
        if enrollment.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enrollment user mismatch")

    if content_release_id is not None:
        release = await db.scalar(
            select(ContentRelease).where(
                ContentRelease.id == content_release_id,
                ContentRelease.tenant_id == tenant_id,
            )
        )
        if release is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content release not found")
        if enrollment is not None and release.course_id != enrollment.course_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Release does not match enrollment course"
            )
        if enrollment is not None and enrollment.content_release_id not in (None, content_release_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Release does not match enrollment"
            )


async def get_event(db: AsyncSession, tenant_id: UUID, event_id: UUID) -> TrainingEvidenceEvent:
    event = await db.scalar(
        select(TrainingEvidenceEvent).where(
            TrainingEvidenceEvent.id == event_id,
            TrainingEvidenceEvent.tenant_id == tenant_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence event not found")
    return event


async def list_events(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    user_id: UUID | None = None,
    procedure_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TrainingEvidenceEvent]:
    query = select(TrainingEvidenceEvent).where(TrainingEvidenceEvent.tenant_id == tenant_id)
    if user_id is not None:
        query = query.where(TrainingEvidenceEvent.user_id == user_id)
    if procedure_type is not None:
        query = query.where(TrainingEvidenceEvent.procedure_type == procedure_type)
    query = query.order_by(TrainingEvidenceEvent.occurred_at.desc()).offset(offset).limit(limit)
    return list((await db.scalars(query)).all())


async def list_learner_events(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    *,
    enrollment_id: UUID | None = None,
    procedure_type: str | None = None,
    confirmation_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Return a safe, own-subject evidence projection for a learner.

    The event, release, and confirmation data are loaded in three batched,
    tenant-scoped queries;
    status filtering is expressed against the immutable event snapshot and
    confirmation existence before pagination, so this is not an N+1 read.
    """

    confirmation_exists = select(TrainingEvidenceStepUpConfirmation.id).where(
        TrainingEvidenceStepUpConfirmation.tenant_id == tenant_id,
        TrainingEvidenceStepUpConfirmation.event_id == TrainingEvidenceEvent.id,
    ).exists()
    confirmation_configured = TrainingEvidenceEvent.payload_snapshot["confirmation"].is_not(None)
    query = select(TrainingEvidenceEvent).where(
        TrainingEvidenceEvent.tenant_id == tenant_id,
        TrainingEvidenceEvent.user_id == user_id,
    )
    if enrollment_id is not None:
        query = query.where(TrainingEvidenceEvent.enrollment_id == enrollment_id)
    if procedure_type is not None:
        query = query.where(TrainingEvidenceEvent.procedure_type == procedure_type)
    if confirmation_status == "not_required":
        query = query.where(~confirmation_configured)
    elif confirmation_status == "pending":
        query = query.where(confirmation_configured, ~confirmation_exists)
    elif confirmation_status == "confirmed":
        query = query.where(confirmation_exists)
    query = query.order_by(TrainingEvidenceEvent.occurred_at.desc(), TrainingEvidenceEvent.id.desc())
    query = query.offset(offset).limit(limit)
    events = list((await db.scalars(query)).all())
    releases_by_id = await _content_releases_by_id(
        db,
        tenant_id,
        [event.content_release_id for event in events if event.content_release_id is not None],
    )
    confirmed_event_ids = await _confirmation_event_ids(
        db, tenant_id, [event.id for event in events]
    )
    return [
        _learner_event_response(event, confirmed_event_ids, releases_by_id.get(event.content_release_id))
        for event in events
    ]


async def get_learner_event(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    event_id: UUID,
):
    """Load one event only when its subject is the authenticated learner."""

    event = await get_event(db, tenant_id, event_id)
    if event.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence event not found")
    release = None
    if event.content_release_id is not None:
        release = await db.scalar(
            select(ContentRelease).where(
                ContentRelease.tenant_id == tenant_id,
                ContentRelease.id == event.content_release_id,
            )
        )
    confirmed_event_ids = await _confirmation_event_ids(db, tenant_id, [event.id])
    return _learner_event_response(event, confirmed_event_ids, release)


async def list_step_up_confirmations(
    db: AsyncSession, tenant_id: UUID, event_id: UUID
) -> list[TrainingEvidenceStepUpConfirmation]:
    await get_event(db, tenant_id, event_id)
    result = await db.scalars(
        select(TrainingEvidenceStepUpConfirmation)
        .where(
            TrainingEvidenceStepUpConfirmation.tenant_id == tenant_id,
            TrainingEvidenceStepUpConfirmation.event_id == event_id,
        )
        .order_by(TrainingEvidenceStepUpConfirmation.confirmed_at)
    )
    return list(result.all())


async def list_legal_holds(db: AsyncSession, tenant_id: UUID, event_id: UUID) -> list[TrainingEvidenceLegalHold]:
    await get_event(db, tenant_id, event_id)
    result = await db.scalars(
        select(TrainingEvidenceLegalHold)
        .where(
            TrainingEvidenceLegalHold.tenant_id == tenant_id,
            TrainingEvidenceLegalHold.event_id == event_id,
        )
        .order_by(TrainingEvidenceLegalHold.occurred_at)
    )
    return list(result.all())


async def record_event(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    user_id: UUID,
    procedure_type: str,
    payload_snapshot: dict[str, Any],
    source_event_key: str | None = None,
    enrollment_id: UUID | None = None,
    content_release_id: UUID | None = None,
    training_procedure_id: UUID | None = None,
    record_type: str = "original",
    related_event_id: UUID | None = None,
    reason: str | None = None,
    occurred_at: datetime | None = None,
) -> TrainingEvidenceEvent:
    await _assert_links(
        db,
        tenant_id,
        user_id=user_id,
        enrollment_id=enrollment_id,
        content_release_id=content_release_id,
    )
    await _tenant_user(db, tenant_id, actor_user_id)
    payload_snapshot = deepcopy(payload_snapshot)
    if record_type != "original":
        if related_event_id is None:
            raise HTTPException(status_code=422, detail="Related event is required")
        parent = await get_event(db, tenant_id, related_event_id)
        if record_type == "correction":
            # Generic corrections are a controlled clerical operation for
            # acknowledgements only. Other evidence has its own trusted workflow.
            if procedure_type != "acknowledgement":
                raise _correction_workflow_error(procedure_type)
            if parent.procedure_type != "acknowledgement":
                raise _correction_workflow_error(parent.procedure_type)
        if parent.procedure_type != procedure_type:
            raise HTTPException(status_code=422, detail="Procedure type must match related event")
        if training_procedure_id is not None and training_procedure_id != parent.training_procedure_id:
            raise HTTPException(status_code=422, detail="Correction must keep the original training procedure")
        training_procedure_id = parent.training_procedure_id
        if (
            parent.user_id != user_id
            or parent.enrollment_id != enrollment_id
            or parent.content_release_id != content_release_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Correction must keep the original subject and evidence links",
            )
        if not reason:
            raise HTTPException(status_code=422, detail="Reason is required")
        parent_snapshot = parent.payload_snapshot if isinstance(parent.payload_snapshot, Mapping) else {}
        # Generic correction payloads may describe the factual change, but
        # server-owned procedure, commission and decision evidence must not be
        # replaced by caller-controlled JSON.
        payload_snapshot.pop("procedure", None)
        payload_snapshot.pop("training_procedure", None)
        payload_snapshot.pop("commission", None)
        payload_snapshot.pop("decision", None)
        if training_procedure_id is not None:
            procedure_snapshot = parent_snapshot.get("training_procedure") or parent_snapshot.get("procedure")
            if isinstance(procedure_snapshot, Mapping):
                procedure_snapshot = deepcopy(dict(procedure_snapshot))
                payload_snapshot["procedure"] = procedure_snapshot
                payload_snapshot["training_procedure"] = deepcopy(procedure_snapshot)
        else:
            payload_snapshot.pop("training_procedure", None)
    elif related_event_id is not None or reason is not None:
        raise HTTPException(status_code=422, detail="Original event cannot link a correction or reason")

    if record_type == "original":
        if procedure_type in _REGULATED_PROCEDURE_TYPES:
            if training_procedure_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "training_procedure_required", "message": "An active training procedure is required"},
                )
            procedure = await db.scalar(
                select(TrainingProcedure).where(
                    TrainingProcedure.id == training_procedure_id,
                    TrainingProcedure.tenant_id == tenant_id,
                    TrainingProcedure.status == "active",
                )
            )
            if procedure is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "training_procedure_not_found", "message": "Active training procedure not found"},
                )
            if procedure.procedure_type != procedure_type:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "training_procedure_type_mismatch",
                        "message": "Training procedure type must match the evidence procedure type",
                    },
                )
            procedure_snapshot: dict[str, Any] = {
                "id": str(procedure.id),
                "code": procedure.code,
                "version": str(procedure.version),
                "title": procedure.title,
                "type": procedure.procedure_type,
                "procedure_type": procedure.procedure_type,
                "confirmation_method": procedure.confirmation_method,
                "approval_reference": procedure.approval_reference,
                "approval_date": procedure.approval_date.isoformat() if procedure.approval_date else None,
                "approved_by_name": procedure.approved_by_name,
                "legal_basis": procedure.legal_basis,
                "local_basis": procedure.local_basis,
                "retention_class": procedure.retention_class,
                "retention_days": procedure.retention_days,
            }
            if procedure.procedure_type == "internal_attestation":
                if "commission" in payload_snapshot or "decision" in payload_snapshot:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": "regulated_evidence_workflow_required",
                            "message": "Commission evidence requires the dedicated attestation workflow",
                        },
                    )
                procedure_snapshot["commission_snapshot_rules"] = deepcopy(procedure.commission_snapshot_rules)
            if procedure.procedure_type == "admission_decision":
                if "commission" in payload_snapshot or "decision" in payload_snapshot:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": "regulated_evidence_workflow_required",
                            "message": "Admission evidence requires the dedicated decision workflow",
                        },
                    )
                procedure_snapshot["authorized_decision_rules"] = deepcopy(procedure.authorized_decision_rules)
            if procedure.procedure_type == "acknowledgement":
                # Commission and decision records require their dedicated
                # regulated workflows and must never enter the export chain
                # through the generic acknowledgement endpoint.
                payload_snapshot.pop("commission", None)
                payload_snapshot.pop("decision", None)
            # `procedure` is the canonical export contract. Keep the explicit
            # training_procedure copy for consumers that need to distinguish a
            # definition snapshot from a course/procedure display object.
            payload_snapshot["procedure"] = deepcopy(procedure_snapshot)
            payload_snapshot["training_procedure"] = procedure_snapshot
        elif procedure_type in _SYSTEM_PROCEDURE_TYPES:
            if training_procedure_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "training_procedure_not_allowed", "message": "System evidence cannot use a training procedure"},
                )
            payload_snapshot.pop("training_procedure", None)
            payload_snapshot.pop("commission", None)
            payload_snapshot.pop("decision", None)
        else:
            raise HTTPException(status_code=422, detail="Unsupported evidence procedure type")

    payload_sha256 = canonical_json_sha256(payload_snapshot)
    if source_event_key:
        existing = await db.scalar(
            select(TrainingEvidenceEvent).where(
                TrainingEvidenceEvent.tenant_id == tenant_id,
                TrainingEvidenceEvent.source_event_key == source_event_key,
            )
        )
        if existing is not None:
            if _source_event_matches(
                existing,
                tenant_id=tenant_id,
                user_id=user_id,
                enrollment_id=enrollment_id,
                content_release_id=content_release_id,
                training_procedure_id=training_procedure_id,
                procedure_type=procedure_type,
                record_type=record_type,
                related_event_id=related_event_id,
                payload_sha256=payload_sha256,
            ):
                return existing
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evidence source event key already exists with a different payload",
            ) from None

    event = TrainingEvidenceEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        enrollment_id=enrollment_id,
        content_release_id=content_release_id,
        training_procedure_id=training_procedure_id,
        procedure_type=procedure_type,
        source_event_key=source_event_key,
        record_type=record_type,
        related_event_id=related_event_id,
        reason=reason,
        payload_snapshot=payload_snapshot,
        payload_sha256=payload_sha256,
        recorded_by_user_id=actor_user_id,
        occurred_at=_utc(occurred_at),
    )
    if source_event_key:
        # The unique constraint is the concurrency backstop. A savepoint lets
        # the surrounding course/quiz transaction survive a losing race so we
        # can return the winner instead of rolling back the business result.
        try:
            async with db.begin_nested():
                db.add(event)
                await db.flush()
        except IntegrityError:
            existing = await db.scalar(
                select(TrainingEvidenceEvent).where(
                    TrainingEvidenceEvent.tenant_id == tenant_id,
                    TrainingEvidenceEvent.source_event_key == source_event_key,
                )
            )
            if existing is None:
                raise
            if _source_event_matches(
                existing,
                tenant_id=tenant_id,
                user_id=user_id,
                enrollment_id=enrollment_id,
                content_release_id=content_release_id,
                training_procedure_id=training_procedure_id,
                procedure_type=procedure_type,
                record_type=record_type,
                related_event_id=related_event_id,
                payload_sha256=payload_sha256,
            ):
                return existing
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evidence source event key already exists with a different payload",
            ) from None
    else:
        db.add(event)
        await db.flush()
    return event


async def confirm_step_up(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    user_id: UUID,
    action_text: str,
    object_version: str,
    reauth_method: str,
    ip_address: str | None,
    user_agent: str | None,
    confirmed_at: datetime | None = None,
) -> TrainingEvidenceStepUpConfirmation:
    event = await get_event(db, tenant_id, event_id)
    if event.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Confirmation user must match evidence subject",
        )
    await _tenant_user(db, tenant_id, user_id)
    confirmed = _utc(confirmed_at)
    hash_payload = {
        "event_id": str(event.id),
        "user_id": str(user_id),
        "action_text": action_text,
        "object_version": object_version,
        "reauth_method": reauth_method,
        "confirmed_at": confirmed.isoformat(),
        "ip_address": ip_address,
        "user_agent": user_agent,
    }
    confirmation = TrainingEvidenceStepUpConfirmation(
        tenant_id=tenant_id,
        event_id=event.id,
        user_id=user_id,
        action_text=action_text,
        object_version=object_version,
        reauth_method=reauth_method,
        confirmed_at=confirmed,
        ip_address=ip_address,
        user_agent=user_agent,
        confirmation_sha256=canonical_json_sha256(hash_payload),
    )
    db.add(confirmation)
    await db.flush()
    return confirmation


async def add_legal_hold(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    actor_user_id: UUID,
    action: str,
    reason: str,
    occurred_at: datetime | None = None,
) -> TrainingEvidenceLegalHold:
    event = await get_event(db, tenant_id, event_id)
    await _tenant_user(db, tenant_id, actor_user_id)
    latest_hold = await db.scalar(
        select(TrainingEvidenceLegalHold)
        .where(
            TrainingEvidenceLegalHold.tenant_id == tenant_id,
            TrainingEvidenceLegalHold.event_id == event_id,
        )
        .order_by(
            TrainingEvidenceLegalHold.occurred_at.desc(),
            TrainingEvidenceLegalHold.created_at.desc(),
        )
        .limit(1)
    )
    if action == "placed" and latest_hold is not None and latest_hold.action == "placed":
        raise HTTPException(status_code=422, detail="Legal hold is already active")
    if action == "released" and (latest_hold is None or latest_hold.action != "placed"):
        raise HTTPException(status_code=422, detail="Cannot release an inactive legal hold")
    when = _utc(occurred_at)
    hash_payload = {
        "event_id": str(event.id),
        "tenant_id": str(tenant_id),
        "action": action,
        "reason": reason,
        "acted_by_user_id": str(actor_user_id),
        "occurred_at": when.isoformat(),
    }
    hold = TrainingEvidenceLegalHold(
        tenant_id=tenant_id,
        event_id=event.id,
        action=action,
        reason=reason,
        acted_by_user_id=actor_user_id,
        occurred_at=when,
        payload_sha256=canonical_json_sha256(hash_payload),
    )
    db.add(hold)
    await db.flush()
    return hold
