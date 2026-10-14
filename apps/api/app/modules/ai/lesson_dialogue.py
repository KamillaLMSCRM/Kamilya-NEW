"""Durable ownership, replay and bounded recall; no independent model/command path."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, _set_user_security_context
from app.core.log_redaction import redact_sensitive_text
from app.models.users import User
from app.modules.ai.dialogue_models import LessonDialogueExchange as Exchange
from app.modules.ai.schemas import AIChatHistory, AIChatRequest, AIChatResponse
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module

LEASE = timedelta(minutes=10)


async def _commit(db: AsyncSession) -> None:
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(503, "Dialogue persistence unavailable; read history") from None


async def _context(db: AsyncSession, user: User) -> None:
    # Transaction-local settings are lost on commit/rollback, never reuse them.
    await _set_tenant_security_context(db, str(user.tenant_id))
    await _set_user_security_context(db, str(user.id))


async def authorize_lesson(db: AsyncSession, user: User, course_id: UUID, lesson_id: UUID | None, *, lock: bool = False) -> None:
    if user.role != "methodologist" or not isinstance(user.tenant_id, UUID):
        raise HTTPException(403, "Methodologist tenant context required")
    # A caller may reuse its session after a committed exchange. Never assume
    # the authentication transaction's LOCAL settings survived that commit.
    await _context(db, user)
    query = select(Lesson.id).join(Module, Module.id == Lesson.module_id)
    query = query.join(Course, Course.id == Module.course_id).where(
            Lesson.id == lesson_id, Course.id == course_id, Lesson.tenant_id == user.tenant_id,
            Module.tenant_id == user.tenant_id, Course.tenant_id == user.tenant_id)
    if lock:
        query = query.with_for_update(read=True, of=[Lesson, Module, Course])
    visible = await db.scalar(query)
    if visible is None:
        raise HTTPException(404, "Lesson not found")


def scope(user: User, course_id: UUID, lesson_id: UUID | None, language: str) -> tuple[Any, ...]:
    return (Exchange.tenant_id == user.tenant_id, Exchange.actor_id == user.id,
            Exchange.course_id == course_id, Exchange.lesson_id == lesson_id,
            Exchange.language == language)


def admitted_history(rows: Iterable[Any], req: AIChatRequest) -> AIChatHistory | None:
    """Keep newest four whole admitted pairs; stored prose is still untrusted."""
    pairs = []
    for row in rows:
        response = AIChatResponse.model_validate(row.response)
        if response.history_eligible is not True:
            continue
        suggestion = ("\n\nProposed lesson text (unverified, not an execution receipt):\n" + response.apply_lesson_content
                      if response.apply_lesson_content else "")
        pairs.extend([{"role": "user", "content": row.message},
                      {"role": "assistant", "content": response.reply + suggestion}])
    pairs = pairs[-8:]
    while pairs and sum(len(turn["content"]) for turn in pairs) > 32000:
        pairs = pairs[2:]
    if not pairs:
        return None
    return AIChatHistory.model_validate(dict(course_id=req.course_id, context="lesson", target_id=req.target_id,
                         language=req.language, turns=pairs))


def fingerprint(req: AIChatRequest) -> str:
    body = {"course": str(req.course_id), "lesson": str(req.target_id),
            "language": req.language, "message": req.message, "intent": req.intent}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def history_page(db: AsyncSession, user: User, course_id: UUID, lesson_id: UUID,
                       language: str, before: UUID | None = None) -> dict[str, Any]:
    await authorize_lesson(db, user, course_id, lesson_id)
    filters = scope(user, course_id, lesson_id, language)
    query = select(Exchange).where(*filters, Exchange.state == "completed")
    if before:
        cursor = await db.scalar(select(Exchange).where(*filters, Exchange.id == before,
                                                       Exchange.state == "completed"))
        if cursor is None:
            raise HTTPException(404, "History cursor not found")
        from sqlalchemy import and_, or_
        query = query.where(or_(Exchange.created_at < cursor.created_at,
            and_(Exchange.created_at == cursor.created_at, Exchange.id < cursor.id)))
    rows = list((await db.scalars(query.order_by(Exchange.created_at.desc(), Exchange.id.desc()).limit(21))).all())
    has_more = len(rows) > 20
    rows = rows[:20]
    pending = await db.scalar(select(Exchange.id).where(*filters, Exchange.state == "pending",
        Exchange.created_at > datetime.now(UTC) - LEASE))
    latest = await db.scalar(select(Exchange).where(*filters)
        .order_by(Exchange.created_at.desc(), Exchange.id.desc()).limit(1))
    interrupted = latest.id if latest is not None and (
        latest.state == "failed" or latest.state == "pending" and latest.created_at <= datetime.now(UTC) - LEASE
    ) else None
    return {"exchanges": [{"id": row.id, "message": row.message,
                "response": AIChatResponse.model_validate(row.response), "created_at": row.created_at}
            for row in reversed(rows)], "has_more": has_more,
            "next_before": rows[-1].id if has_more else None, "pending_request_id": pending,
            "interrupted_request_id": interrupted}


async def _fail_pending(db: AsyncSession, user: User, req: AIChatRequest, code: str) -> None:
    await db.rollback()
    await _context(db, user)
    await db.execute(update(Exchange).where(*scope(user, req.course_id, req.target_id, req.language),
        Exchange.id == req.durable_request_id, Exchange.state == "pending").values(state="failed", error_code=code))
    await _commit(db)


async def send_durable(req: AIChatRequest, db: AsyncSession, user: User,
                       generate: Callable[[AIChatRequest], Awaitable[AIChatResponse]]) -> AIChatResponse:
    await authorize_lesson(db, user, req.course_id, req.target_id)
    safe_message = redact_sensitive_text(req.message)
    if not safe_message.strip() or len(safe_message) > 2000:
        raise HTTPException(422, "Redacted message exceeds dialogue bounds")
    filters = scope(user, req.course_id, req.target_id, req.language)
    digest = fingerprint(req)
    existing = await db.scalar(select(Exchange).where(*filters, Exchange.id == req.durable_request_id))
    if existing:
        if existing.fingerprint != digest:
            raise HTTPException(409, "Dialogue request conflict")
        if existing.state == "completed":
            return AIChatResponse.model_validate(existing.response)
        if existing.state == "pending" and existing.created_at <= datetime.now(UTC) - LEASE:
            raise HTTPException(503, "Dialogue request interrupted; read history")
        raise HTTPException(409 if existing.state == "pending" else 503,
                            "Dialogue request pending" if existing.state == "pending" else "Dialogue request failed; read history")
    # Reclaim an expired reservation only as a terminal failure, never replay its
    # model call. A late original completion cannot update a failed row.
    await db.execute(update(Exchange).where(*filters, Exchange.state == "pending",
        Exchange.created_at <= datetime.now(UTC) - LEASE).values(state="failed", error_code="interrupted"))
    rows = list((await db.scalars(select(Exchange).where(*filters, Exchange.state == "completed",
        Exchange.response["history_eligible"].as_boolean().is_(True))
        .order_by(Exchange.created_at.desc(), Exchange.id.desc()).limit(4))).all())
    recall = admitted_history(reversed(rows), req)
    db.add(Exchange(id=req.durable_request_id, tenant_id=user.tenant_id, actor_id=user.id,
        course_id=req.course_id, lesson_id=req.target_id, language=req.language,
        fingerprint=digest, message=safe_message, state="pending"))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Dialogue request already reserved; read history") from None
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(503, "Dialogue persistence unavailable; read history") from None
    # Fetch current lesson/policy data for the existing chat path, then release
    # its read transaction before inference via the supplied callback.
    await _context(db, user)
    model_req = req.model_copy(update={"durable_request_id": None, "history": recall})
    try:
        result = await generate(model_req)
    except Exception as exc:
        code = "interrupted" if isinstance(exc, HTTPException) and exc.status_code < 500 else "provider_unavailable"
        await _fail_pending(db, user, req, code)
        raise
    # Persist the screened result before acknowledging it. No provider output,
    # error trace, credential or application receipt is written to this archive.
    try:
        await authorize_lesson(db, user, req.course_id, req.target_id, lock=True)
    except HTTPException:
        await _fail_pending(db, user, req, "interrupted")
        raise
    safe = result.model_copy(update={"reply": redact_sensitive_text(result.reply),
        "apply_lesson_content": redact_sensitive_text(result.apply_lesson_content) if result.apply_lesson_content else None,
        "apply_lesson_title_hint": redact_sensitive_text(result.apply_lesson_title_hint) if result.apply_lesson_title_hint else None})
    updated = await db.execute(update(Exchange).where(*filters, Exchange.id == req.durable_request_id,
        Exchange.state == "pending", Exchange.created_at > datetime.now(UTC) - LEASE)
        .values(state="completed", response=safe.model_dump(mode="json")))
    if getattr(updated, "rowcount", None) != 1:
        await db.rollback()
        raise HTTPException(409, "Dialogue request interrupted; read history")
    await _commit(db)
    return safe
