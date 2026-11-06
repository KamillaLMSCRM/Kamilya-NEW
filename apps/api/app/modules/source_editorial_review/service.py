"""Own the source-review lifecycle, admission, and historical snapshot readback."""

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document
from app.modules.source_editorial_review.domain import (
    POLICY,
    ApprovedEditorialDocument,
    ReviewCommand,
    ReviewConflictError,
    ReviewState,
    text_hash,
)
from app.modules.source_editorial_review.domain import SOURCE_PINS as SOURCE_PINS
from app.modules.source_editorial_review.models import DocumentEditorialEvent as Event

_SHA = re.compile(r"[0-9a-f]{64}")
_ANALYSIS_STALE_AFTER = timedelta(minutes=20)


def review_enabled() -> bool:
    settings = get_settings()
    configured = settings.SOURCE_EDITORIAL_REVIEW_ENABLED
    return configured if configured is not None else settings.APP_ENV != "test"


async def owned_document(db: AsyncSession, tenant_id: UUID, document_id: UUID, *, lock: bool = False) -> Document:
    query = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id,
                                   Document.lifecycle_status == "active")
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


async def history(db: AsyncSession, tenant_id: UUID, document_id: UUID, until: int | None = None) -> list[Event]:
    query = select(Event).where(Event.tenant_id == tenant_id, Event.document_id == document_id)
    if until is not None:
        query = query.where(Event.sequence <= until)
    return list((await db.scalars(query.order_by(Event.sequence))).all())


def read_state(rows: Sequence[Event], blob_sha: object) -> ReviewState:
    state = ReviewState()
    for row in rows:
        if row.original_blob_sha256 != blob_sha:
            raise ReviewConflictError("source_review_original_changed")
        state.apply(row.sequence, row.kind, row.payload)
    return state


def latest_status(rows: Sequence[Event]) -> str:
    if not rows:
        return "not_started"
    row = rows[-1]
    if row.kind in {"queued", "running", "analysis_block"} and row.created_at < datetime.now(UTC) - _ANALYSIS_STALE_AFTER:
        return "interrupted"
    return {"approved": "approved", "queued": "queued", "running": "running", "analysis_block": "running", "failed": "failed"}.get(
        row.kind, "in_review"
    )


def public_event(row: Event) -> dict[str, Any]:
    return {"id": row.id, "revision": row.sequence, "kind": row.kind,
            "actor_id": row.actor_id, "created_at": row.created_at}


def snapshot_identity(row: Event) -> dict[str, Any]:
    return {"document_id": str(row.document_id), "approval_id": str(row.id), "revision": row.sequence,
            "original_blob_sha256": row.original_blob_sha256, "working_sha256": row.payload["working_sha256"]}


def review_view(doc: Document, rows: Sequence[Event], state: ReviewState, receipt: Event | None = None) -> dict[str, Any]:
    journal: list[dict[str, Any]] = []
    analysis = None
    for row in rows:
        if row.kind == "analyzed":
            analysis = {key: row.payload.get(key) for key in ("model_calls", "usage", "policy", "analysis_policy")}
            journal.extend({**public_event(row), **change, "kind": "automatic", "item_id": change["id"],
                            "actor_id": None, "policy": row.payload["policy"]}
                           for change in row.payload["automatic"])
        elif row.kind in {"resolved", "issue_reopened", "auto_undone", "approved", "reopened"}:
            event_kind = "manual_edit" if row.kind == "resolved" and "manual_issue" in row.payload else row.kind
            journal.append({**public_event(row), "kind": event_kind, **{key: row.payload[key] for key in
                ("item_id", "start", "end", "before", "after", "reason", "decision", "working_sha256")
                if key in row.payload}})
    working = state.working()[0] if state.original else None
    return {"document_id": doc.id, "title": doc.title, "document_version": doc.version,
            "revision": state.revision, "status": latest_status(rows), "error": state.error,
            "questions": [{**issue, "resolution": state.decisions.get(key)} for key, issue in state.issues.items()],
            "automatic": [{**change, "undone": key in state.disabled_auto}
                          for key, change in state.automatic.items()],
            "original_text": state.original or None, "working_text": working,
            "approval": ({**snapshot_identity(rows[-1]), "actor_id": rows[-1].actor_id,
                          "created_at": rows[-1].created_at} if state.approval else None),
            "journal": journal, "analysis": analysis, "receipt": public_event(receipt) if receipt else None}


def add_event(
    db: AsyncSession, doc: Document, *, actor_id: UUID, sequence: int, kind: str, payload: dict[str, Any],
    command: ReviewCommand | None = None,
) -> Event:
    blob = str(doc.content_sha256 or "")
    if not _SHA.fullmatch(blob):
        raise ReviewConflictError("source_review_original_unavailable")
    row = Event(id=uuid4(), document_id=UUID(str(doc.id)), tenant_id=UUID(str(doc.tenant_id)),
                actor_id=actor_id, sequence=sequence, kind=kind, original_blob_sha256=blob, payload=payload,
                request_id=command.request_id if command else None,
                command_sha256=text_hash(command.model_dump_json()) if command else None)
    db.add(row)
    return row


async def apply_command(
    db: AsyncSession, doc: Document, actor_id: UUID, command: ReviewCommand,
) -> tuple[list[Event], ReviewState, Event, bool]:
    rows = await history(db, UUID(str(doc.tenant_id)), UUID(str(doc.id)))
    state = read_state(rows, doc.content_sha256)
    duplicate = next((row for row in rows if row.request_id == command.request_id), None)
    if duplicate:
        if duplicate.actor_id != actor_id or duplicate.command_sha256 != text_hash(command.model_dump_json()):
            raise ReviewConflictError("source_review_request_id_conflict")
        return rows, state, duplicate, duplicate.kind == "queued" and state.status == "queued" and rows[-1] is duplicate
    if latest_status(rows) == "interrupted":
        state.status = "failed"
    kind, payload = state.plan(command)
    event = add_event(db, doc, actor_id=actor_id, sequence=state.revision + 1, kind=kind,
                      payload=payload, command=command)
    await db.flush()
    state.apply(event.sequence, kind, payload)
    return [*rows, event], state, event, kind == "queued"


async def statuses(db: AsyncSession, tenant_id: UUID, ids: Sequence[UUID]) -> dict[str, str]:
    if not ids:
        return {}
    stmt = (select(Event.document_id, Event.kind, Event.created_at, Event.original_blob_sha256, Document.content_sha256)
            .join(Document, (Document.id == Event.document_id) & (Document.tenant_id == tenant_id))
            .where(Event.tenant_id == tenant_id, Event.document_id.in_(ids), Document.lifecycle_status == "active")
            .distinct(Event.document_id).order_by(Event.document_id, Event.sequence.desc()))
    values = {}
    for doc_id, kind, created, frozen_sha, blob_sha in (await db.execute(stmt)).all():
        if frozen_sha != blob_sha:
            values[str(doc_id)] = "source_changed"
        elif kind in {"queued", "running", "analysis_block"} and created < datetime.now(UTC) - _ANALYSIS_STALE_AFTER:
            values[str(doc_id)] = "interrupted"
        elif kind == "analysis_block":
            values[str(doc_id)] = "running"
        else:
            values[str(doc_id)] = kind if kind in {"queued", "running", "failed", "approved"} else "in_review"
    return {str(doc_id): values.get(str(doc_id), "not_started") for doc_id in ids}


async def pin_reviews(db: AsyncSession, tenant_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
    """Called after document locks, before quota reservation or queue creation."""
    pins = []
    missing = []
    for doc_id in ids:
        row = await db.scalar(select(Event).where(Event.tenant_id == tenant_id, Event.document_id == doc_id)
                              .order_by(Event.sequence.desc()).limit(1))
        doc = await owned_document(db, tenant_id, doc_id)
        if row is None or row.kind != "approved" or row.original_blob_sha256 != doc.content_sha256:
            missing.append(str(doc_id))
        else:
            pins.append(snapshot_identity(row))
    if missing:
        raise HTTPException(status_code=409, detail={"code": "source_editorial_review_required",
                                                     "document_ids": missing})
    return pins


async def read_approval(db: AsyncSession, tenant_id: UUID, doc: Document, approval_id: UUID) -> tuple[Event, ReviewState]:
    event = await db.scalar(select(Event).where(Event.tenant_id == tenant_id, Event.document_id == doc.id,
                                                Event.id == approval_id, Event.kind == "approved"))
    if event is None:
        raise HTTPException(status_code=404, detail="Source edition not found")
    state = read_state(await history(db, tenant_id, UUID(str(doc.id)), event.sequence), doc.content_sha256)
    expected = {**event.payload}
    working, spans = state.working()
    if (state.status != "approved" or state.issues.keys() - state.decisions.keys()
            or expected != {"working": working, "working_sha256": text_hash(working),
                            "original_sha256": text_hash(state.original), "spans": spans, "policy": POLICY}):
        raise ReviewConflictError("source_review_snapshot_invalid")
    return event, state


async def resolve_pins(
    db: AsyncSession, tenant_id: UUID, selected: Sequence[str], raw_pins: object,
) -> dict[str, ApprovedEditorialDocument]:
    """Resolve only the immutable approved rows named by the owned job."""
    if (not isinstance(raw_pins, list) or len(raw_pins) != len(selected) or not selected
            or len(set(selected)) != len(selected)):
        raise ReviewConflictError("source_review_pins_invalid")
    result: dict[str, ApprovedEditorialDocument] = {}
    for doc_id, pin in zip(selected, raw_pins, strict=True):
        if not isinstance(pin, dict) or pin.get("document_id") != doc_id:
            raise ReviewConflictError("source_review_pins_invalid")
        try:
            approval_id = UUID(str(pin.get("approval_id")))
            doc = await owned_document(db, tenant_id, UUID(doc_id))
            event, state = await read_approval(db, tenant_id, doc, approval_id)
        except (HTTPException, ValueError) as exc:
            raise ReviewConflictError("source_review_snapshot_unavailable") from exc
        if snapshot_identity(event) != pin:
            raise ReviewConflictError("source_review_snapshot_mismatch")
        result[doc_id] = ApprovedEditorialDocument(
            document_id=doc_id, source_revision=f"document:{event.original_blob_sha256}",
            approval_id=str(event.id), recognized_text=state.original, working_text=event.payload["working"],
            working_sha256=event.payload["working_sha256"], spans=tuple(event.payload["spans"]),
            fidelity=state.fidelity,
        )
    return result
