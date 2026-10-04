"""Source-bound plans consume the canonical generation command, not HTTP routes."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.document import Document
from app.models.users import User

from .assignment_service import WorkbenchConflict, WorkbenchNotFound, _assert_actor
from .document_models import DocumentPlan
from .document_schemas import (
    DocumentExecution,
    DocumentPlanResponse,
    DocumentPreview,
    DocumentPreviewRequest,
    DocumentSnapshot,
    DocumentSource,
)
from .plan_contract import ActorContext, ConfirmationRequest


def document_fingerprint(snapshot: DocumentSnapshot) -> str:
    return hashlib.sha256(json.dumps(snapshot.model_dump(mode="json"), sort_keys=True,
                                    separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


async def resolve_document_sources(
    db: AsyncSession, actor: ActorContext, ids: list[UUID], *, lock: bool = False,
) -> tuple[DocumentSource, ...]:
    query = select(Document).where(Document.id.in_(ids), Document.tenant_id == actor.tenant_id,
                                   Document.lifecycle_status == "active").order_by(Document.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    rows = list((await db.scalars(query)).all())
    by_id = {cast(UUID, row.id): row for row in rows}
    if set(by_id) != set(ids):
        raise WorkbenchNotFound("documents_not_found")
    if any(not row.content_sha256 for row in rows):
        raise WorkbenchConflict("document_source_unverified")
    if any(row.index_status not in {"ready", "partial"} for row in rows):
        raise WorkbenchConflict("document_source_not_ready")
    return tuple(DocumentSource(document_id=doc_id, title=by_id[doc_id].title,
                                version=by_id[doc_id].version, content_sha256=by_id[doc_id].content_sha256,
                                index_revision=by_id[doc_id].index_revision) for doc_id in ids)


def _preview(snapshot: DocumentSnapshot, fingerprint: str) -> DocumentPreview:
    return DocumentPreview(**snapshot.model_dump(exclude={"tenant_id", "actor_id"}), fingerprint=fingerprint)


async def create_document_preview(
    db: AsyncSession, actor: ActorContext, body: DocumentPreviewRequest, *, now: datetime | None = None,
) -> DocumentPreview:
    _assert_actor(actor)
    now = now or datetime.now(UTC)
    sources = await resolve_document_sources(db, actor, body.generation.documents)
    count = await db.scalar(select(func.count()).select_from(DocumentPlan).where(
        DocumentPlan.tenant_id == actor.tenant_id, DocumentPlan.actor_id == actor.actor_id,
        DocumentPlan.status == "ready", DocumentPlan.expires_at > now,
    ))
    if count is not None and count >= 20:
        raise WorkbenchConflict("preview_limit")
    snapshot = DocumentSnapshot(plan_id=uuid4(), revision=1, tenant_id=actor.tenant_id,
                                actor_id=actor.actor_id, expires_at=now + timedelta(minutes=15),
                                instruction=body.instruction, generation=body.generation, sources=sources)
    fingerprint = document_fingerprint(snapshot)
    db.add(DocumentPlan(id=snapshot.plan_id, tenant_id=actor.tenant_id, actor_id=actor.actor_id,
                        snapshot=snapshot.model_dump(mode="json"), fingerprint=fingerprint,
                        expires_at=snapshot.expires_at, status="ready"))
    await db.flush()
    return _preview(snapshot, fingerprint)


async def _owned(db: AsyncSession, actor: ActorContext, plan_id: UUID, *, lock: bool) -> DocumentPlan:
    _assert_actor(actor)
    query = select(DocumentPlan).where(DocumentPlan.id == plan_id, DocumentPlan.tenant_id == actor.tenant_id,
                                       DocumentPlan.actor_id == actor.actor_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise WorkbenchNotFound("plan_not_found")
    return row


async def _execution(db: AsyncSession, actor: ActorContext, row: DocumentPlan) -> DocumentExecution:
    from app.modules.ai.router import _job_response

    job = await db.scalar(select(AIJob).where(AIJob.id == row.job_id, AIJob.tenant_id == actor.tenant_id,
                                             AIJob.user_id == actor.actor_id))
    if job is None:
        raise WorkbenchNotFound("job_not_found")
    return DocumentExecution(plan_id=row.id, job=await _job_response(db, job))


async def get_document_plan(db: AsyncSession, actor: ActorContext, plan_id: UUID) -> DocumentPlanResponse:
    row = await _owned(db, actor, plan_id, lock=False)
    if row.status == "submitted":
        return await _execution(db, actor, row)
    if datetime.now(UTC) >= row.expires_at:
        raise WorkbenchConflict("expired")
    return _preview(DocumentSnapshot.model_validate(row.snapshot), row.fingerprint)


async def confirm_document_plan(
    db: AsyncSession, actor: ActorContext, request: ConfirmationRequest, user: User,
    *, now: datetime | None = None,
) -> DocumentExecution:
    from app.modules.ai.router import submit_course_generation

    row = await _owned(db, actor, request.plan_id, lock=True)
    snapshot = DocumentSnapshot.model_validate(row.snapshot)
    if user.id != actor.actor_id or user.tenant_id != actor.tenant_id or user.role != "methodologist":
        raise WorkbenchConflict("context_mismatch")
    if request.revision != snapshot.revision or request.fingerprint != row.fingerprint:
        raise WorkbenchConflict("confirmation_mismatch")
    if snapshot.tenant_id != actor.tenant_id or snapshot.actor_id != actor.actor_id:
        raise WorkbenchConflict("context_mismatch")
    if row.status == "submitted":
        return await _execution(db, actor, row)
    now = now or datetime.now(UTC)
    if now >= snapshot.expires_at:
        raise WorkbenchConflict("expired")
    sources = await resolve_document_sources(db, actor, snapshot.generation.documents, lock=True)
    current = snapshot.model_copy(update={"sources": sources})
    if document_fingerprint(current) != row.fingerprint:
        raise WorkbenchConflict("stale")
    plan_id = row.id

    async def bind_job(job: AIJob) -> None:
        row.status, row.job_id = "submitted", job.id
        await db.flush()

    job = await submit_course_generation(snapshot.generation, db, user, before_commit=bind_job)
    return DocumentExecution(plan_id=plan_id, job=job)
