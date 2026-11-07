"""Source-review continuation identity and locked handoff helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.modules.source_editorial_review.service import verified_preparation_binding


def valid_continuation(rows: Sequence[Any], queued: Any, original_sha: str) -> bool:
    """Accept only a still-latest queue bound to a real preceding worker claim."""
    if not rows or rows[-1].id != queued.id or queued.kind != "queued":
        return False
    predecessor = queued.payload.get("continuation_from")
    binding = queued.payload.get("preparation")
    claim = next((row for row in rows[:-1] if str(row.id) == predecessor and row.kind == "running"), None)
    if claim is None:
        return False
    parent = next((row for row in rows if str(row.id) == str(claim.payload.get("queued_event_id"))
                   and row.kind == "queued"), None)
    if (parent is None or parent.sequence + 1 != claim.sequence or parent.actor_id != queued.actor_id
            or parent.original_blob_sha256 != original_sha
            or parent.payload.get("pages") != queued.payload.get("pages")
            or parent.payload.get("preparation") is not None and parent.payload.get("preparation") != binding):
        return False
    intervening = [row for row in rows if claim.sequence < row.sequence < queued.sequence]
    if any(row.kind != "analysis_block" or row.actor_id != claim.actor_id
           or row.original_blob_sha256 != original_sha or row.payload.get("claim_id") != str(claim.id)
           for row in intervening):
        return False
    return bool(claim.actor_id == queued.actor_id
                and claim.original_blob_sha256 == original_sha and queued.original_blob_sha256 == original_sha
                and (binding is None or verified_preparation_binding(rows[:-1], original_sha, binding)))


def lineage(rows: Sequence[Any], queued: Any) -> tuple[list[str], dict[str, Any] | None, Any | None, Any]:
    """Follow committed queue/claim ancestry, retaining exact explicit acknowledgement."""
    indexed = {str(row.id): row for row in rows}
    claim_ids: list[str] = []
    current = queued
    seen: set[str] = set()
    while current.payload.get("continuation_from"):
        claim_id = current.payload["continuation_from"]
        if not isinstance(claim_id, str) or claim_id in seen:
            raise ValueError("source_review_continuation_invalid")
        seen.add(claim_id)
        claim = indexed.get(claim_id)
        if claim is None or claim.kind != "running" or claim.actor_id != queued.actor_id:
            raise ValueError("source_review_continuation_invalid")
        claim_ids.append(claim_id)
        previous = indexed.get(str(claim.payload.get("queued_event_id")))
        if (previous is None or previous.kind != "queued" or previous.actor_id != queued.actor_id
                or previous.original_blob_sha256 != queued.original_blob_sha256):
            raise ValueError("source_review_continuation_invalid")
        current = previous
    ack = current.payload.get("acknowledged_unknown")
    failure = None
    if ack is not None:
        if not isinstance(ack, dict) or set(ack) != {"failure_event_id", "request_id", "actor_id"}:
            raise ValueError("source_review_acknowledgement_invalid")
        if any(not isinstance(value, str) for value in ack.values()):
            raise ValueError("source_review_acknowledgement_invalid")
        failure = indexed.get(ack["failure_event_id"])
        if (failure is None or failure.kind != "failed" or failure.sequence != current.sequence - 1
                or failure.original_blob_sha256 != queued.original_blob_sha256
                or ack["actor_id"] != str(current.actor_id) or ack["request_id"] != str(current.request_id)):
            raise ValueError("source_review_acknowledgement_invalid")
        if (failure.payload.get("unknown_visual_outcome") is True or not (
                failure.payload.get("code") == "source_review_provider_outcome_unknown"
                or failure.payload.get("code") == "source_review_timeout"
                and str(failure.payload.get("phase", "")).endswith("_request"))):
            raise ValueError("source_review_acknowledgement_invalid")
    return claim_ids, ack, failure, current


async def handoff(*, claim: Any, binding: dict[str, Any] | None, pages: object,
                  open_locked: Callable[[], Any], read_rows: Callable[[Any], Awaitable[list[Any]]],
                  add_queued: Callable[[Any, Any, int, dict[str, Any]], Any],
                  owns: Callable[[Any], bool], dispatch: Callable[[Any], None]) -> str:
    """Commit a single source-bound successor before attempting delivery."""
    async with open_locked() as (db, doc):
        rows = await read_rows(db)
        if (not rows or not owns(rows[-1]) or doc.content_sha256 != claim.original_blob_sha256
                or binding is not None and not verified_preparation_binding(rows, claim.original_blob_sha256, binding)):
            return "claim_changed"
        payload: dict[str, Any] = {"continuation_from": str(claim.id)}
        if binding is not None:
            payload["preparation"] = binding
        if pages is not None:
            payload["pages"] = pages
        event = add_queued(db, doc, rows[-1].sequence + 1, payload)
        await db.commit()
    try:
        dispatch(event)
    except Exception:
        return "continuation_pending"
    return "continued"
