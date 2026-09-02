"""Durable course-assignment notification outbox interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RECOVERY_BATCH_SIZE = 20
FINALIZATION_KINDS = frozenset({"success", "terminal", "transient", "defer"})


@dataclass(frozen=True)
class ClaimedAssignmentNotification:
    id: UUID
    tenant_id: UUID
    enrollment_id: UUID
    claim_token: UUID


@dataclass(frozen=True)
class DueAssignmentNotification:
    id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class AssignmentNotificationStatus:
    enrollment_id: UUID
    status: str
    attempt_count: int
    delivered_at: object | None
    last_error_category: str | None


async def queue_manual_enrollment_notification(
    db: AsyncSession, *, tenant_id: UUID, enrollment_id: UUID, assigned_by: UUID
) -> UUID | None:
    """Insert in the caller's enrollment transaction without dispatching."""
    return await db.scalar(
        text("SELECT enqueue_course_assignment_notification(:tenant_id, :enrollment_id, :assigned_by)"),
        {"tenant_id": tenant_id, "enrollment_id": enrollment_id, "assigned_by": assigned_by},
    )


class PostgresAssignmentNotificationStore:
    """RLS-safe adapter over bounded SECURITY DEFINER functions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim(self, *, tenant_id: UUID, notification_id: UUID) -> ClaimedAssignmentNotification | None:
        row = (
            (
                await self.db.execute(
                    text("SELECT * FROM claim_course_assignment_notification(" ":tenant_id, :notification_id)"),
                    {"tenant_id": tenant_id, "notification_id": notification_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        await self.db.commit()
        if row is None:
            return None
        return ClaimedAssignmentNotification(
            id=row["id"],
            tenant_id=row["tenant_id"],
            enrollment_id=row["enrollment_id"],
            claim_token=row["claim_token"],
        )

    async def finalize(
        self,
        event: ClaimedAssignmentNotification,
        *,
        kind: str,
        message_id: str | None = None,
        error_category: str = "",
    ) -> bool:
        if kind not in FINALIZATION_KINDS:
            raise ValueError("invalid assignment notification finalization kind")
        value = await self.db.scalar(
            text(
                "SELECT finalize_course_assignment_notification("
                ":tenant_id, :id, :token, :kind, :message_id, :error_category)"
            ),
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

    async def due(self, limit: int = RECOVERY_BATCH_SIZE) -> list[DueAssignmentNotification]:
        bounded = max(1, min(limit, 100))
        rows = (
            (
                await self.db.execute(
                    text("SELECT * FROM due_course_assignment_notifications(:limit)"),
                    {"limit": bounded},
                )
            )
            .mappings()
            .all()
        )
        return [DueAssignmentNotification(id=row["id"], tenant_id=row["tenant_id"]) for row in rows]

    async def statuses(self, *, tenant_id: UUID, course_id: UUID) -> dict[UUID, AssignmentNotificationStatus]:
        rows = (
            (
                await self.db.execute(
                    text("SELECT * FROM course_assignment_notification_statuses(:tenant_id, :course_id)"),
                    {"tenant_id": tenant_id, "course_id": course_id},
                )
            )
            .mappings()
            .all()
        )
        return {
            row["enrollment_id"]: AssignmentNotificationStatus(
                enrollment_id=row["enrollment_id"],
                status=row["status"],
                attempt_count=row["attempt_count"],
                delivered_at=row["delivered_at"],
                last_error_category=row["last_error_category"],
            )
            for row in rows
        }

    async def requeue(self, *, tenant_id: UUID, enrollment_id: UUID) -> UUID | None:
        value = await self.db.scalar(
            text("SELECT requeue_course_assignment_notification(:tenant_id, :enrollment_id)"),
            {"tenant_id": tenant_id, "enrollment_id": enrollment_id},
        )
        await self.db.commit()
        return value


@dataclass(frozen=True)
class ClaimedLearningPathAssignmentNotification:
    id: UUID
    tenant_id: UUID
    learning_path_assignment_id: UUID
    claim_token: UUID


async def queue_learning_path_assignment_notification(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    learning_path_assignment_id: UUID,
    assigned_by: UUID | None,
) -> UUID | None:
    """Enqueue one durable program notification in the caller transaction."""
    return await db.scalar(
        text(
            "SELECT enqueue_learning_path_assignment_notification("
            ":tenant_id, :learning_path_assignment_id, :assigned_by)"
        ),
        {
            "tenant_id": tenant_id,
            "learning_path_assignment_id": learning_path_assignment_id,
            "assigned_by": assigned_by,
        },
    )


class PostgresLearningPathAssignmentNotificationStore:
    """RLS-safe adapter for durable program-assignment notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def claim(
        self, *, tenant_id: UUID, notification_id: UUID
    ) -> ClaimedLearningPathAssignmentNotification | None:
        row = (
            (
                await self.db.execute(
                    text(
                        "SELECT * FROM claim_learning_path_assignment_notification("
                        ":tenant_id, :notification_id)"
                    ),
                    {"tenant_id": tenant_id, "notification_id": notification_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        await self.db.commit()
        if row is None:
            return None
        return ClaimedLearningPathAssignmentNotification(
            id=row["id"],
            tenant_id=row["tenant_id"],
            learning_path_assignment_id=row["learning_path_assignment_id"],
            claim_token=row["claim_token"],
        )

    async def finalize(
        self,
        event: ClaimedLearningPathAssignmentNotification,
        *,
        kind: str,
        message_id: str | None = None,
        error_category: str = "",
    ) -> bool:
        if kind not in FINALIZATION_KINDS:
            raise ValueError("invalid assignment notification finalization kind")
        value = await self.db.scalar(
            text(
                "SELECT finalize_learning_path_assignment_notification("
                ":tenant_id, :id, :token, :kind, :message_id, :error_category)"
            ),
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

    async def due(self, limit: int = RECOVERY_BATCH_SIZE) -> list[DueAssignmentNotification]:
        bounded = max(1, min(limit, 100))
        rows = (
            (
                await self.db.execute(
                    text("SELECT * FROM due_learning_path_assignment_notifications(:limit)"),
                    {"limit": bounded},
                )
            )
            .mappings()
            .all()
        )
        return [DueAssignmentNotification(id=row["id"], tenant_id=row["tenant_id"]) for row in rows]
