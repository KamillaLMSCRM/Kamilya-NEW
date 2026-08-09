"""Durable, signed delivery of canonical lead events to Kamilya CRM.

The module's external interface is ``deliver_event(event_id)``. PostgreSQL
owns durable state transitions; the HTTP adapter only receives already-claimed
exact payload bytes and never sees database credentials.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import async_session_factory

EVENT_TYPE = "lead.submitted"
RECOVERY_BATCH_SIZE = 20


@dataclass(frozen=True)
class ClaimedLeadEvent:
    id: UUID
    event_id: str
    event_type: str
    payload_bytes: bytes
    claim_token: UUID


class CRMWebhookTransport(Protocol):
    async def send(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> int: ...


class HttpxCRMWebhookTransport:
    async def send(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> int:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0)
        ) as client:
            response = await client.post(url, content=body, headers=headers)
        return response.status_code


class PostgresCRMOutboxStore:
    """RLS-safe adapter over bounded SECURITY DEFINER functions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim(self, event_id: UUID) -> ClaimedLeadEvent | None:
        row = (
            await self.db.execute(
                text("SELECT * FROM crm_claim_lead_outbox(:event_id)"),
                {"event_id": event_id},
            )
        ).mappings().one_or_none()
        await self.db.commit()
        if row is None:
            return None
        return ClaimedLeadEvent(
            id=row["id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            payload_bytes=bytes(row["payload_bytes"]),
            claim_token=row["claim_token"],
        )

    async def finalize(
        self,
        event: ClaimedLeadEvent,
        *,
        kind: str,
        status_code: int | None,
        error_category: str,
    ) -> bool:
        finalized = (
            await self.db.execute(
                text(
                    "SELECT crm_finalize_lead_outbox("
                    ":event_id, :claim_token, :kind, :status_code, :error_category)"
                ),
                {
                    "event_id": event.id,
                    "claim_token": event.claim_token,
                    "kind": kind,
                    "status_code": status_code,
                    "error_category": error_category,
                },
            )
        ).scalar_one()
        await self.db.commit()
        return bool(finalized)

    async def due_ids(self, limit: int = RECOVERY_BATCH_SIZE) -> list[UUID]:
        return list(
            (
                await self.db.execute(
                    text("SELECT id FROM crm_due_lead_outbox(:limit)"),
                    {"limit": limit},
                )
            )
            .scalars()
            .all()
        )


def signed_headers(
    *,
    event_id: str,
    event_type: str,
    body: bytes,
    secret: str,
    now: datetime | None = None,
) -> dict[str, str]:
    timestamp_ms = int((now or datetime.now(UTC)).timestamp() * 1000)
    signed_message = (
        f"{timestamp_ms}\n{event_id}\n{event_type}\n".encode()
        + body
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_message,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-LMS-Event-Id": event_id,
        "X-LMS-Event-Type": event_type,
        "X-LMS-Timestamp": str(timestamp_ms),
        "X-LMS-Signature": signature,
        "Content-Type": "application/json",
    }


def _delivery_kind(status_code: int) -> tuple[str, str]:
    if 200 <= status_code < 300 and status_code != 202:
        return "success", "success"
    if status_code in (202, 429) or status_code >= 500:
        return "transient", "transient_http"
    return "terminal", "terminal_http"


async def _deliver_with_adapters(
    *,
    event_id: UUID,
    store: PostgresCRMOutboxStore,
    transport: CRMWebhookTransport,
    webhook_url: str,
    webhook_secret: str,
) -> dict[str, str | int]:
    event = await store.claim(event_id)
    if event is None:
        return {"status": "skipped"}

    if not webhook_url or not webhook_secret:
        finalized = await store.finalize(
            event,
            kind="defer",
            status_code=None,
            error_category="configuration_missing",
        )
        return {"status": "deferred" if finalized else "lost_claim"}

    status_code: int | None = None
    try:
        status_code = await transport.send(
            url=webhook_url,
            body=event.payload_bytes,
            headers=signed_headers(
                event_id=event.event_id,
                event_type=event.event_type,
                body=event.payload_bytes,
                secret=webhook_secret,
            ),
        )
        kind, category = _delivery_kind(status_code)
    except httpx.RequestError:
        kind, category = "transient", "network"

    finalized = await store.finalize(
        event,
        kind=kind,
        status_code=status_code,
        error_category=category,
    )
    if not finalized:
        return {"status": "lost_claim"}
    return {"status": kind, "http_status": status_code or 0}


async def deliver_event(
    event_id: UUID,
    *,
    transport: CRMWebhookTransport | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
) -> dict[str, str | int]:
    settings = get_settings()
    async with async_session_factory() as db:
        return await _deliver_with_adapters(
            event_id=event_id,
            store=PostgresCRMOutboxStore(db),
            transport=transport or HttpxCRMWebhookTransport(),
            webhook_url=(
                settings.CRM_WEBHOOK_URL
                if webhook_url is None
                else webhook_url
            ),
            webhook_secret=(
                settings.CRM_WEBHOOK_SECRET
                if webhook_secret is None
                else webhook_secret
            ),
        )


async def recover_due_events(limit: int = RECOVERY_BATCH_SIZE) -> dict[str, int]:
    bounded_limit = max(1, min(limit, 100))
    async with async_session_factory() as db:
        due_ids = await PostgresCRMOutboxStore(db).due_ids(bounded_limit)

    processed = 0
    for event_id in due_ids:
        await deliver_event(event_id)
        processed += 1
    return {"due": len(due_ids), "processed": processed}
