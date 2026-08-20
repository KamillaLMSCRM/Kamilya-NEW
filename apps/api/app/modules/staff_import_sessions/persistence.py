"""Transactional persistence boundary for adaptive staff import sessions.

This module stores analysis proposals and decisions. Applying a proposal to the
organization/staff tables is deliberately a separate transaction coordinator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff_import_mapping import StaffImportMapping
from app.models.staff_import_session import StaffImportSession, StaffImportSessionEvent

from .schemas import (
    ImportMode,
    ImportSession,
    ImportSessionProposal,
    ImportSessionState,
    MatchAction,
    ProposalConfidence,
)
from .state_machine import apply_transition, bind_proposal_revision


class ImportSessionNotFoundError(LookupError):
    pass


class ImportSessionIdempotencyConflictError(ValueError):
    pass


class ImportSessionMutationConflictError(ValueError):
    pass


def proposal_review_state(proposal: ImportSessionProposal) -> ImportSessionState:
    """Choose the safest review state without accepting ambiguous inference."""

    if any(conflict.blocking for conflict in proposal.conflicts):
        return ImportSessionState.NEEDS_CORRECTION
    items = (*proposal.branches, *proposal.departments, *proposal.positions, *proposal.staff)
    if any(
        item.action is MatchAction.CONFLICT
        or (item.confidence is ProposalConfidence.LOW and item.action is not MatchAction.SKIP)
        for item in items
    ):
        return ImportSessionState.NEEDS_CORRECTION
    return ImportSessionState.READY_FOR_APPROVAL


def record_to_domain(record: StaffImportSession) -> ImportSession:
    proposal = ImportSessionProposal.model_validate(record.proposal_json) if record.proposal_json is not None else None
    return ImportSession(
        session_id=str(record.id),
        tenant_id=record.tenant_id,
        actor_id=record.actor_id,
        actor_role=record.actor_role,
        state=ImportSessionState(record.state),
        mode=ImportMode(record.mode),
        proposal=proposal,
        approval_token_hash=record.approval_token_hash,
        full_reconciliation_confirmation=record.full_reconciliation_confirmation,
        reviewed_revision=record.reviewed_revision,
        approved_revision=record.approved_revision,
        approved_at=record.approved_at,
        expires_at=record.expires_at,
    )


async def create_import_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    actor_role: str,
    idempotency_key: str,
    source_file_name: str,
    source_file_sha256: str,
    source_format: str,
    source_size_bytes: int,
    parser_version: str,
    mapping_id: UUID | None = None,
    source_object_key: str | None = None,
    mode: ImportMode = ImportMode.ADD_OR_UPDATE,
    expires_at: datetime | None = None,
) -> StaffImportSession:
    key = idempotency_key.strip()
    existing_result = await db.execute(
        select(StaffImportSession).where(
            StaffImportSession.tenant_id == tenant_id,
            StaffImportSession.idempotency_key == key,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.source_file_sha256 != source_file_sha256:
            raise ImportSessionIdempotencyConflictError("idempotency key already belongs to a different source file")
        return existing

    now = datetime.now(UTC)
    record = StaffImportSession(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        mapping_id=mapping_id,
        state=ImportSessionState.UPLOADED.value,
        mode=mode.value,
        idempotency_key=key,
        source_file_name=source_file_name.strip(),
        source_file_sha256=source_file_sha256,
        source_format=source_format.lower(),
        source_size_bytes=source_size_bytes,
        source_object_key=source_object_key,
        parser_version=parser_version,
        expires_at=expires_at or now + timedelta(hours=24),
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError as exc:
        # A concurrent request may win the tenant/idempotency-key insert after
        # our initial read. Replay that row instead of surfacing a random 500.
        await db.rollback()
        replay_result = await db.execute(
            select(StaffImportSession).where(
                StaffImportSession.tenant_id == tenant_id,
                StaffImportSession.idempotency_key == key,
            )
        )
        replay = replay_result.scalar_one_or_none()
        if replay is None:
            raise
        if replay.source_file_sha256 != source_file_sha256:
            raise ImportSessionIdempotencyConflictError(
                "idempotency key already belongs to a different source file"
            ) from exc
        return replay
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=None,
            to_state=record.state,
            event_type="session_created",
            event_metadata={
                "source_sha256": source_file_sha256,
                "source_format": record.source_format,
                "parser_version": parser_version,
            },
        )
    )
    await db.flush()
    return record


async def get_import_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    for_update: bool = False,
) -> StaffImportSession:
    statement = select(StaffImportSession).where(
        StaffImportSession.id == session_id,
        StaffImportSession.tenant_id == tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    record = result.scalar_one_or_none()
    if record is None:
        raise ImportSessionNotFoundError("staff import session not found")
    return record


async def cleanup_expired_import_sources(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    storage,
    now: datetime | None = None,
    limit: int = 20,
    raise_on_storage_error: bool = False,
) -> int:
    """Delete a bounded batch of expired tenant source workbooks.

    Source files can contain the full staff register, so an abandoned review
    session must not leave the original workbook in object storage forever.
    Failed storage deletions are deliberately left retryable: the database key
    is cleared only after the object backend confirms deletion.
    """

    current_time = now or datetime.now(UTC)
    statement = (
        select(StaffImportSession)
        .where(
            StaffImportSession.tenant_id == tenant_id,
            StaffImportSession.source_object_key.is_not(None),
            StaffImportSession.expires_at.is_not(None),
            StaffImportSession.expires_at <= current_time,
            StaffImportSession.state != ImportSessionState.COMMITTING.value,
        )
        .order_by(StaffImportSession.expires_at.asc(), StaffImportSession.id.asc())
        .limit(max(1, min(limit, 100)))
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(statement)
    records = list(result.scalars().all())
    deleted = 0
    storage_error: Exception | None = None
    for record in records:
        source_key = record.source_object_key
        if not source_key:
            continue
        try:
            storage.delete_bytes(source_key)
        except Exception as exc:  # noqa: BLE001 - keep the key for the next bounded retry
            storage_error = storage_error or exc
            continue
        previous_state = record.state
        record.source_object_key = None
        if previous_state not in {
            ImportSessionState.COMMITTED.value,
            ImportSessionState.FAILED.value,
            ImportSessionState.EXPIRED.value,
        }:
            record.state = ImportSessionState.EXPIRED.value
        db.add(
            StaffImportSessionEvent(
                tenant_id=tenant_id,
                session_id=record.id,
                actor_id=record.actor_id,
                from_state=previous_state,
                to_state=record.state,
                event_type="source_retention_expired",
                event_metadata={"source_deleted": True},
            )
        )
        deleted += 1
    if deleted:
        await db.flush()
    if storage_error is not None and raise_on_storage_error:
        raise storage_error
    return deleted


async def save_proposal(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    actor_id: UUID,
    proposal: ImportSessionProposal,
) -> StaffImportSession:
    record = await get_import_session(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        for_update=True,
    )
    if record.state in {
        ImportSessionState.APPROVED.value,
        ImportSessionState.COMMITTING.value,
        ImportSessionState.COMMITTED.value,
        ImportSessionState.REJECTED.value,
        ImportSessionState.EXPIRED.value,
    }:
        raise ImportSessionMutationConflictError("session no longer accepts proposal changes")

    current = record_to_domain(record)
    bound = bind_proposal_revision(current, proposal)
    assert bound.proposal is not None
    previous_state = record.state
    target = proposal_review_state(bound.proposal)
    record.proposal_json = bound.proposal.model_dump(mode="json")
    record.proposal_revision = bound.proposal.revision
    record.proposal_hash = bound.proposal.revision_hash
    record.reviewed_revision = bound.reviewed_revision
    record.mode = bound.mode.value
    record.state = target.value
    record.error_code = None
    record.error_message = None
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=previous_state,
            to_state=target.value,
            event_type="proposal_saved",
            event_metadata={
                "revision": record.proposal_revision,
                "proposal_hash": record.proposal_hash,
            },
        )
    )
    await db.flush()
    return record


async def save_workbook_analysis(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    actor_id: UUID,
    analysis: dict,
    mapping: dict[str, str] | None,
    needs_mapping: bool,
) -> StaffImportSession:
    record = await get_import_session(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        for_update=True,
    )
    if record.state not in {
        ImportSessionState.UPLOADED.value,
        ImportSessionState.INSPECTING.value,
        ImportSessionState.NEEDS_MAPPING.value,
    }:
        raise ImportSessionMutationConflictError("session no longer accepts workbook analysis")
    previous_state = record.state
    if record.state == ImportSessionState.UPLOADED.value:
        record.state = ImportSessionState.INSPECTING.value
        db.add(
            StaffImportSessionEvent(
                tenant_id=tenant_id,
                session_id=record.id,
                actor_id=actor_id,
                from_state=previous_state,
                to_state=record.state,
                event_type="workbook_inspection_started",
                event_metadata={},
            )
        )
        await db.flush()
        previous_state = record.state
    record.workbook_analysis = analysis
    record.mapping_json = mapping
    record.state = ImportSessionState.NEEDS_MAPPING.value if needs_mapping else ImportSessionState.NEEDS_REVIEW.value
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=previous_state,
            to_state=record.state,
            event_type="workbook_analyzed",
            event_metadata={"needs_mapping": needs_mapping},
        )
    )
    await db.flush()
    return record


async def approve_import_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    actor_id: UUID,
    revision: str,
    full_reconciliation_confirmation: bool = False,
    now: datetime | None = None,
) -> StaffImportSession:
    record = await get_import_session(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        for_update=True,
    )
    record.full_reconciliation_confirmation = full_reconciliation_confirmation
    domain = record_to_domain(record)
    approved = apply_transition(
        domain,
        ImportSessionState.APPROVED,
        now=now,
        approval_revision=revision,
    )
    previous_state = record.state
    record.state = approved.state.value
    record.approved_revision = approved.approved_revision
    record.approved_at = approved.approved_at
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=previous_state,
            to_state=record.state,
            event_type="proposal_approved",
            event_metadata={"revision": revision},
        )
    )
    await db.flush()
    return record


async def ensure_approved_mapping_profile(
    db: AsyncSession,
    *,
    record: StaffImportSession,
    actor_id: UUID,
    now: datetime | None = None,
) -> StaffImportMapping | None:
    """Persist the approved header mapping as a tenant-scoped reusable hint.

    The profile is never an approval substitute: every later upload still gets
    its own immutable proposal revision and methodologist approval.
    """

    if not record.mapping_json or not record.workbook_analysis:
        return None
    signature = record.workbook_analysis.get("workbook_signature")
    if not isinstance(signature, str) or len(signature) != 64:
        return None
    parser = record.workbook_analysis.get("parser") or {}
    profile_json = {
        "selected_sheet": parser.get("selected_sheet"),
        "header_row": parser.get("header_row"),
        "raw_columns": parser.get("raw_columns") or [],
    }
    approved_at = now or datetime.now(UTC)
    name = f"Автопрофиль: {record.source_file_name} · {signature[:8]}"[:120]
    statement = (
        pg_insert(StaffImportMapping)
        .values(
            tenant_id=record.tenant_id,
            name=name,
            mapping_json=record.mapping_json,
            workbook_signature=signature,
            profile_json=profile_json,
            schema_version="adaptive-v1",
            approved_at=approved_at,
            approved_by=actor_id,
            is_default=False,
            created_by=actor_id,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "workbook_signature"],
            index_where=StaffImportMapping.workbook_signature.is_not(None),
        )
    )
    await db.execute(statement)
    result = await db.execute(
        select(StaffImportMapping).where(
            StaffImportMapping.tenant_id == record.tenant_id,
            StaffImportMapping.workbook_signature == signature,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is not None:
        record.mapping_id = profile.id
        await db.flush()
    return profile
