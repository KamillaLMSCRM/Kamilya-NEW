"""Bounded SQL-function adapter for recurring learning reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RECOVERY_BATCH_SIZE = 20
FINALIZATION_KINDS = frozenset({"success", "terminal", "transient", "defer", "skipped"})


@dataclass(frozen=True, slots=True)
class ClaimedLearningReminder:
    id: UUID
    tenant_id: UUID
    claim_token: UUID


@dataclass(frozen=True, slots=True)
class DueLearningReminder:
    id: UUID
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class LearningReminderPayload:
    email: str | None
    learner_name: str
    company_name: str
    title: str
    target_type: str
    target_id: UUID
    due_at: datetime
    has_login_access: bool


class PostgresLearningReminderStore:
    """RLS-safe adapter over the reminder module's fixed SQL interface."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim(self, *, tenant_id: UUID, reminder_id: UUID) -> ClaimedLearningReminder | None:
        row = (
            (
                await self.db.execute(
                    text("SELECT * FROM public.claim_learning_reminder(:tenant_id, :reminder_id)"),
                    {"tenant_id": tenant_id, "reminder_id": reminder_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        await self.db.commit()
        if row is None:
            return None
        return ClaimedLearningReminder(id=row["id"], tenant_id=row["tenant_id"], claim_token=row["claim_token"])

    async def payload(self, event: ClaimedLearningReminder) -> LearningReminderPayload | None:
        row = (
            (
                await self.db.execute(
                    text("SELECT * FROM public.learning_reminder_payload(:tenant_id, :id, :token)"),
                    {"tenant_id": event.tenant_id, "id": event.id, "token": event.claim_token},
                )
            )
            .mappings()
            .one_or_none()
        )
        await self.db.commit()
        if row is None:
            return None
        return LearningReminderPayload(
            email=cast(str | None, row["email"]),
            learner_name=cast(str, row["learner_name"]),
            company_name=cast(str, row["company_name"]),
            title=cast(str, row["title"]),
            target_type=cast(str, row["target_type"]),
            target_id=cast(UUID, row["target_id"]),
            due_at=cast(datetime, row["due_at"]),
            has_login_access=bool(row["has_login_access"]),
        )

    async def begin_send(self, event: ClaimedLearningReminder, *, payload_hash: str, transport: str = "resend") -> bool:
        value = await self.db.scalar(
            text("SELECT public.begin_learning_reminder_send(:tenant_id, :id, :token, :payload_hash, :transport)"),
            {"tenant_id": event.tenant_id, "id": event.id, "token": event.claim_token, "payload_hash": payload_hash, "transport": transport},
        )
        await self.db.commit()
        return bool(value)

    async def finalize(
        self,
        event: ClaimedLearningReminder,
        *,
        kind: str,
        message_id: str | None = None,
        error_category: str = "",
    ) -> bool:
        if kind not in FINALIZATION_KINDS:
            raise ValueError("invalid learning reminder finalization kind")
        value = await self.db.scalar(
            text("SELECT public.finalize_learning_reminder(:tenant_id, :id, :token, :kind, :message_id, :error_category)"),
            {
                "tenant_id": event.tenant_id,
                "id": event.id,
                "token": event.claim_token,
                "kind": kind,
                "message_id": message_id,
                "error_category": error_category,
            },
        )
        await self.db.commit()
        return bool(value)

    async def due(self, limit: int = RECOVERY_BATCH_SIZE) -> list[DueLearningReminder]:
        bounded = max(1, min(limit, 100))
        rows = (
            (await self.db.execute(text("SELECT * FROM public.due_learning_reminders(:limit)"), {"limit": bounded}))
            .mappings()
            .all()
        )
        return [DueLearningReminder(id=row["id"], tenant_id=row["tenant_id"]) for row in rows]
