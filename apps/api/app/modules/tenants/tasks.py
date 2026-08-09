"""Notifications-queue entry points for CRM lead-outbox delivery."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.celery_app import celery_app
from app.modules.tenants.crm_outbox import deliver_event, recover_due_events


@celery_app.task(name="crm.deliver_lead_outbox")
def deliver_lead_outbox_task(event_id: str) -> dict:
    return asyncio.run(deliver_event(UUID(event_id)))


@celery_app.task(name="crm.recover_lead_outbox")
def recover_lead_outbox_task() -> dict:
    # Process a bounded batch directly. After worker downtime, repeated timer
    # calls therefore observe shrinking durable work instead of each fan-out
    # enqueueing the same event IDs behind one another.
    return asyncio.run(recover_due_events())
