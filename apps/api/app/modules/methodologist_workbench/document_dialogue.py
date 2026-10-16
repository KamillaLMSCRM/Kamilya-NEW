"""Durable private preparation; canonical document service owns all execution."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, _set_user_security_context
from app.core.log_redaction import redact_sensitive_text
from app.models.users import User

from .assignment_service import WorkbenchConflict, WorkbenchNotFound, _assert_actor
from .document_answers import (
    DocumentAnswer,
    SourceExcerpt,
    answer_document,
    read_excerpt,
    validate_citations,
    validate_evidence,
)
from .document_dialogue_models import DocumentDialogueExchange as Exchange
from .document_dialogue_models import DocumentDialogueTask as Task
from .document_dialogue_schemas import (
    CreateDialogue,
    DialogueDraft,
    DocumentDialogue,
    DocumentDialogueList,
    DocumentExchange,
    InterpretedDocument,
    PreviewDialogue,
    SaveDialogue,
    SendDocumentMessage,
)
from .document_intent import DocumentCandidate, DocumentClarification, DocumentInterpretRequest, interpret_document
from .document_models import DocumentPlan
from .document_schemas import DocumentGenerationRequest, DocumentPlanResponse, DocumentPreviewRequest, DocumentSource
from .document_service import create_document_preview, get_document_plan, resolve_document_sources
from .plan_contract import ActorContext

LEASE = timedelta(minutes=2)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def failure_code(error: Exception) -> str:
    if isinstance(error, WorkbenchConflict) and str(error) == "dialogue_source_stale":
        return "source_stale"
    if isinstance(error, HTTPException):
        if error.status_code == 429:
            return "budget_denied"
        if error.status_code == 503 and error.detail == "dialogue_provider_unavailable":
            return "provider_unavailable"
        if error.status_code == 502 and error.detail == "dialogue_invalid_response":
            return "invalid_response"
    if isinstance(error, SQLAlchemyError):
        return "persistence_unavailable"
    if isinstance(error, ValidationError):
        return "invalid_response"
    if isinstance(error, ValueError) and not isinstance(error, WorkbenchConflict):
        return "invalid_response"
    return "interrupted"


def safe_draft(draft: DialogueDraft, language: str) -> DialogueDraft:
    if draft.candidate.language != language:
        raise WorkbenchConflict("dialogue_language_mismatch")
    candidate = draft.candidate.model_dump()
    for key in ("target_audience", "course_intent", "combination_goal"):
        candidate[key] = redact_sensitive_text(candidate[key])
    return DialogueDraft.model_validate({**draft.model_dump(), "instruction": redact_sensitive_text(draft.instruction),
                                         "candidate": candidate})


async def context(db: AsyncSession, actor: ActorContext) -> None:
    _assert_actor(actor)
    await _set_tenant_security_context(db, str(actor.tenant_id))
    await _set_user_security_context(db, str(actor.actor_id))
    from app.models.user_roles import UserRole

    active = await db.scalar(select(User.id).where(
        User.id == actor.actor_id, User.tenant_id == actor.tenant_id,
        User.is_active.is_(True), User.status == "active",
        or_(User.role == "methodologist", select(UserRole.user_id).where(
            UserRole.user_id == User.id, UserRole.tenant_id == User.tenant_id,
            UserRole.role == "methodologist").exists()),
    ))
    if active is None:
        raise WorkbenchNotFound("dialogue_actor_not_found")


async def owned_task(db: AsyncSession, actor: ActorContext, task_id: UUID, *, lock: bool = False) -> Task:
    await context(db, actor)
    query = select(Task).where(Task.id == task_id, Task.tenant_id == actor.tenant_id, Task.actor_id == actor.actor_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = await db.scalar(query)
    if task is None:
        raise WorkbenchNotFound("dialogue_not_found")
    return task


async def current_sources(db: AsyncSession, actor: ActorContext, task: Task, *, lock: bool = False) -> bool:
    stored = tuple(DocumentSource.model_validate(item) for item in task.sources)
    try:
        sources = await resolve_document_sources(db, actor, [item.document_id for item in stored], lock=lock)
    except (WorkbenchNotFound, WorkbenchConflict):
        # An owner's archived discussion remains readable, but never authorizes
        # fresh model work or execution against unavailable/moved sources.
        return False
    return sources == stored


async def exchanges(db: AsyncSession, actor: ActorContext, task: Task) -> list[Exchange]:
    return list((await db.scalars(select(Exchange).where(
        Exchange.task_id == task.id, Exchange.tenant_id == actor.tenant_id, Exchange.actor_id == actor.actor_id,
    ).order_by(Exchange.created_at, Exchange.id).limit(40))).all())


async def view(db: AsyncSession, actor: ActorContext, task: Task) -> DocumentDialogue:
    rows = await exchanges(db, actor, task)
    pending = next((row for row in reversed(rows) if row.state == "pending"), None)
    latest = rows[-1] if rows else None
    now = datetime.now(UTC)
    return DocumentDialogue(
        id=task.id, revision=task.revision, language=task.language, sources=task.sources,
        draft=task.draft, plan_id=task.plan_id, source_stale=not await current_sources(db, actor, task),
        pending_request_id=pending.id if pending and pending.created_at > now - LEASE else None,
        interrupted_request_id=latest.id if latest and (latest.state == "failed" or
            latest.state == "pending" and latest.created_at <= now - LEASE) else None,
        exchanges=[DocumentExchange(id=row.id, instruction=row.instruction, state=row.state,
            response=row.response, error_code=row.error_code, created_at=row.created_at) for row in rows],
        created_at=task.created_at, updated_at=task.updated_at,
    )


async def read_task(db: AsyncSession, actor: ActorContext, task_id: UUID) -> DocumentDialogue:
    return await view(db, actor, await owned_task(db, actor, task_id))


async def create_task(db: AsyncSession, actor: ActorContext, body: CreateDialogue) -> DocumentDialogue:
    await context(db, actor)
    # Serialize the per-actor quota and duplicate create key across concurrent tabs.
    await db.scalar(select(User.id).where(User.id == actor.actor_id,
        User.tenant_id == actor.tenant_id).with_for_update())
    fingerprint = digest(body.model_dump(mode="json"))
    task = await db.scalar(select(Task).where(Task.id == body.task_id, Task.tenant_id == actor.tenant_id,
                                              Task.actor_id == actor.actor_id))
    if task is not None:
        if task.creation_fingerprint != fingerprint:
            raise WorkbenchConflict("dialogue_creation_conflict")
        return await view(db, actor, task)
    count = await db.scalar(select(func.count()).select_from(Task).where(
        Task.tenant_id == actor.tenant_id, Task.actor_id == actor.actor_id))
    if count is not None and count >= 100:
        raise WorkbenchConflict("dialogue_task_limit")
    sources = await resolve_document_sources(db, actor, body.document_ids, lock=True)
    task = Task(id=body.task_id, tenant_id=actor.tenant_id, actor_id=actor.actor_id,
        language=body.language, sources=[source.model_dump(mode="json") for source in sources],
        creation_fingerprint=fingerprint, draft=safe_draft(body.draft, body.language).model_dump(mode="json"),
        revision=1, plan_id=None)
    db.add(task)
    await db.flush()
    return await view(db, actor, task)


async def list_tasks(db: AsyncSession, actor: ActorContext, before: UUID | None = None) -> DocumentDialogueList:
    await context(db, actor)
    query = select(Task).where(Task.tenant_id == actor.tenant_id, Task.actor_id == actor.actor_id)
    if before:
        cursor = await owned_task(db, actor, before)
        query = query.where(or_(Task.updated_at < cursor.updated_at,
            and_(Task.updated_at == cursor.updated_at, Task.id < cursor.id)))
    rows = list((await db.scalars(query.order_by(Task.updated_at.desc(), Task.id.desc()).limit(21))).all())
    more = len(rows) > 20
    rows = rows[:20]
    return DocumentDialogueList(tasks=[dict(id=row.id, title=row.sources[0]["title"],
        updated_at=row.updated_at, plan_id=row.plan_id) for row in rows],
        has_more=more, next_before=rows[-1].id if more else None)


async def mutable(db: AsyncSession, actor: ActorContext, task: Task, expected: int) -> list[Exchange]:
    if task.revision != expected:
        raise WorkbenchConflict("dialogue_revision_stale")
    if not await current_sources(db, actor, task, lock=True):
        raise WorkbenchConflict("dialogue_source_stale")
    if task.plan_id:
        plan = await db.scalar(select(DocumentPlan).where(DocumentPlan.id == task.plan_id,
            DocumentPlan.tenant_id == actor.tenant_id, DocumentPlan.actor_id == actor.actor_id))
        if plan is None or plan.status != "ready":
            raise WorkbenchConflict("dialogue_plan_requires_recovery")
    return await exchanges(db, actor, task)


def require_idle(rows: list[Exchange]) -> None:
    if any(row.state == "pending" for row in rows):
        raise WorkbenchConflict("dialogue_request_pending")


async def save_task(db: AsyncSession, actor: ActorContext, task_id: UUID, body: SaveDialogue) -> DocumentDialogue:
    task = await owned_task(db, actor, task_id, lock=True)
    require_idle(await mutable(db, actor, task, body.expected_revision))
    draft = safe_draft(body.draft, task.language).model_dump(mode="json")
    if draft != task.draft:
        task.draft, task.plan_id, task.revision = draft, None, task.revision + 1
        await db.flush()
        await db.refresh(task)
    return await view(db, actor, task)


async def preview_task(db: AsyncSession, actor: ActorContext, task_id: UUID, body: PreviewDialogue) -> DocumentPlanResponse:
    task = await owned_task(db, actor, task_id, lock=True)
    require_idle(await mutable(db, actor, task, body.expected_revision))
    if task.plan_id:
        try:
            return await get_document_plan(db, actor, task.plan_id)
        except WorkbenchConflict as exc:
            if str(exc) != "expired":
                raise
    draft = DialogueDraft.model_validate(task.draft)
    candidate = draft.candidate.model_dump()
    try:
        generation = DocumentGenerationRequest.model_validate({**candidate,
            "documents": [source["document_id"] for source in task.sources],
            "language_confirmed": draft.language_confirmed, "reuse_reason": draft.reuse_reason})
    except ValidationError:
        raise HTTPException(422, "dialogue_draft_incomplete") from None
    preview = await create_document_preview(db, actor,
        DocumentPreviewRequest(instruction=draft.instruction or draft.candidate.course_intent, generation=generation),
        dialogue_context=(task.id, task.revision))
    task.plan_id = preview.plan_id
    await db.flush()
    return preview


async def fail_request(db: AsyncSession, actor: ActorContext, task_id: UUID, request_id: UUID, code: str) -> None:
    await db.rollback()
    task = await owned_task(db, actor, task_id, lock=True)
    row = await db.scalar(select(Exchange).where(Exchange.id == request_id, Exchange.task_id == task.id,
        Exchange.tenant_id == actor.tenant_id, Exchange.actor_id == actor.actor_id))
    if row and row.state == "pending":
        row.state, row.error_code = "failed", code
        task.revision += 1
        await db.commit()


async def send_message(db: AsyncSession, actor: ActorContext, task_id: UUID,
                       body: SendDocumentMessage, *, content_question: bool = False) -> DocumentDialogue:
    task = await owned_task(db, actor, task_id, lock=True)
    fingerprint = digest({"task_id": str(task_id), **body.model_dump(mode="json"),
                          **({"purpose": "content_question"} if content_question else {})})
    existing = await db.scalar(select(Exchange).where(Exchange.id == body.request_id,
        Exchange.task_id == task.id, Exchange.tenant_id == actor.tenant_id, Exchange.actor_id == actor.actor_id))
    if existing:
        if existing.fingerprint != fingerprint:
            raise WorkbenchConflict("dialogue_request_conflict")
        if existing.state == "completed":
            return await view(db, actor, task)
        raise HTTPException(409 if existing.state == "pending" else 503,
                            "dialogue_request_pending" if existing.state == "pending" else "dialogue_request_failed")
    rows = await mutable(db, actor, task, body.expected_revision)
    if content_question and task.plan_id:
        raise WorkbenchConflict("dialogue_content_requires_new_task")
    if len(rows) >= 40:
        raise WorkbenchConflict("dialogue_exchange_limit")
    now = datetime.now(UTC)
    for row in rows:
        if row.state == "pending" and row.created_at <= now - LEASE:
            row.state, row.error_code = "failed", "interrupted"
    require_idle(rows)
    instruction = redact_sensitive_text(body.instruction)
    if not instruction.strip() or len(instruction) > 4000:
        raise HTTPException(422, "dialogue_redacted_instruction_invalid")
    draft = DialogueDraft.model_validate(task.draft).model_copy(update={"instruction": instruction})
    recall = [row.instruction for row in rows if row.state == "completed"
              and row.response and row.response.get("state") != "answered"][-4:]
    model_context = {"prior_instructions": recall, "current_candidate": draft.candidate.model_dump(),
                     "source_titles": [redact_sensitive_text(source["title"])[:1000] for source in task.sources]}
    language = task.language
    sources = tuple(DocumentSource.model_validate(source) for source in task.sources)
    content_recall = [{"question": row.instruction, "answer": row.response["answer"][:2000]}
        for row in rows if row.state == "completed" and row.response and row.response.get("state") == "answered"][-4:]
    if not content_question:
        task.draft, task.plan_id = draft.model_dump(mode="json"), None
    task.revision += 1
    await db.flush()  # Task revision must exist before the exchange scope trigger.
    db.add(Exchange(id=body.request_id, task_id=task.id, tenant_id=actor.tenant_id, actor_id=actor.actor_id,
        base_revision=body.expected_revision, fingerprint=fingerprint, instruction=instruction, state="pending"))
    try:
        # Unknown/cancelled commit is reconciled by exact request key below,
        # never by replaying inference. No connection/lock across inference.
        reservation = asyncio.create_task(db.commit())
        try:
            await asyncio.shield(reservation)
        except asyncio.CancelledError:
            # Finish this exact commit before reusing the session for recovery.
            # This is not another commit or a model retry.
            await reservation
            raise
        await context(db, actor)
        result: DocumentCandidate | DocumentClarification | DocumentAnswer
        evidence = None
        if content_question:
            evidence = await answer_document(db, actor, sources, instruction, language, content_recall)
            result = evidence.response
        else:
            from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings, runtime_settings_scope

            policy = await resolve_runtime_settings(db)
            with runtime_settings_scope(policy):
                result = await interpret_document(db, actor, DocumentInterpretRequest(instruction=instruction, language=language),
                    dialogue_context=model_context, provider_deadline_seconds=policy.number("document_dialogue.provider_seconds"))
        await db.commit()
        task = await owned_task(db, actor, task_id, lock=True)
        if not await current_sources(db, actor, task, lock=True):
            raise WorkbenchConflict("dialogue_source_stale")
        if evidence is not None:
            await validate_evidence(db, actor, evidence)
        completed_row = await db.scalar(select(Exchange).where(Exchange.id == body.request_id,
            Exchange.task_id == task.id, Exchange.tenant_id == actor.tenant_id, Exchange.actor_id == actor.actor_id))
        if completed_row is None or completed_row.state != "pending" or completed_row.created_at <= datetime.now(UTC) - LEASE:
            raise WorkbenchConflict("dialogue_request_interrupted")
        if isinstance(result, DocumentCandidate) and result.language != language:
            result = DocumentClarification(code="dialogue_language_mismatch")
        if isinstance(result, DocumentClarification) and result.code == "intent_provider_unavailable":
            raise HTTPException(503, "dialogue_provider_unavailable")
        if isinstance(result, DocumentCandidate):
            updated = safe_draft(DialogueDraft.model_validate(task.draft).model_copy(update={"candidate": result}), language)
            task.draft = updated.model_dump(mode="json")
            response: InterpretedDocument | DocumentClarification | DocumentAnswer = InterpretedDocument(candidate=updated.candidate)
        else:
            response = result
        completed_row.state, completed_row.response = "completed", response.model_dump(mode="json")
        task.revision += 1
        await db.flush()
        await db.refresh(task)
        response_task = await view(db, actor, task)
        await db.commit()
        return response_task
    except asyncio.CancelledError:
        await fail_request(db, actor, task_id, body.request_id, "interrupted")
        raise
    except Exception as exc:
        await fail_request(db, actor, task_id, body.request_id, failure_code(exc))
        raise


async def citation_source(db: AsyncSession, actor: ActorContext, task_id: UUID,
                          exchange_id: UUID, number: int) -> SourceExcerpt:
    task = await owned_task(db, actor, task_id, lock=True)
    if not await current_sources(db, actor, task, lock=True):
        raise WorkbenchConflict("dialogue_source_stale")
    row = await db.scalar(select(Exchange).where(Exchange.id == exchange_id, Exchange.task_id == task.id,
        Exchange.tenant_id == actor.tenant_id, Exchange.actor_id == actor.actor_id, Exchange.state == "completed"))
    if row is None or not row.response or row.response.get("state") != "answered":
        raise WorkbenchNotFound("dialogue_citation_not_found")
    answer = DocumentAnswer.model_validate(row.response)
    await validate_citations(db, actor, answer)
    citation = next((item for item in answer.citations if item.number == number), None)
    if citation is None:
        raise WorkbenchNotFound("dialogue_citation_not_found")
    source = next((item for item in task.sources if item["document_id"] == str(citation.document_id)), None)
    if source is None or any(source[key] != getattr(citation, key) for key in ("version", "content_sha256", "index_revision")):
        raise WorkbenchConflict("dialogue_source_stale")
    return await read_excerpt(db, actor, citation)
