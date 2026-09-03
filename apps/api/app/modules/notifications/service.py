"""Notification inbox ownership and safe materialization."""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import WorkflowNotificationIntentV1
from .models import NotificationInboxItem

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
_ACTION = re.compile(rf"^(/course-review-requests/{_UUID}|/admin/course-approvals\?courseId={_UUID})$")
_KINDS = {"course_review_assigned", "course_review_reminder", "course_review_overdue"}


def validate_action_path(path: str) -> str:
    if not isinstance(path, str) or not _ACTION.fullmatch(path):
        raise ValueError("action_path is not allowlisted")
    return path


def _context(intent: WorkflowNotificationIntentV1) -> dict[str, object]:
    if intent.kind not in _KINDS:
        raise ValueError("notification kind is not allowlisted")
    if not intent.course_title or len(intent.course_title) > 500:
        raise ValueError("course_title is invalid")
    validate_action_path(intent.action_path)
    return {"course_title": intent.course_title, "due_at": intent.due_at.isoformat() if intent.due_at else None}


async def materialize_notification(db: AsyncSession, intent: WorkflowNotificationIntentV1) -> NotificationInboxItem:
    """Insert one safe row or return the existing row for the source delivery."""
    context = _context(intent)
    await db.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(intent.recipient_user_id)},
    )
    existing = await db.scalar(select(NotificationInboxItem).where(NotificationInboxItem.source_delivery_id == intent.source_delivery_id, NotificationInboxItem.tenant_id == intent.tenant_id))
    if existing is not None:
        if existing.tenant_id != intent.tenant_id or existing.recipient_user_id != intent.recipient_user_id:
            raise ValueError("source delivery ownership conflict") from None
        return existing
    item = NotificationInboxItem(
        tenant_id=intent.tenant_id,
        recipient_user_id=intent.recipient_user_id,
        source_delivery_id=intent.source_delivery_id,
        kind=intent.kind,
        context=context,
        action_path=intent.action_path,
    )
    try:
        async with db.begin_nested():
            db.add(item)
            await db.flush()
    except IntegrityError:
        existing = await db.scalar(select(NotificationInboxItem).where(NotificationInboxItem.source_delivery_id == intent.source_delivery_id, NotificationInboxItem.tenant_id == intent.tenant_id))
        if existing is None:
            raise
        if existing.recipient_user_id != intent.recipient_user_id:
            raise ValueError("source delivery ownership conflict") from None
        return existing
    return item


def notification_payload(item: NotificationInboxItem) -> dict[str, object]:
    return {
        "id": item.id,
        "kind": item.kind,
        "context": item.context,
        "action_path": item.action_path,
        "read_at": item.read_at,
        "created_at": item.created_at,
    }


async def list_notifications(db: AsyncSession, *, tenant_id: UUID, recipient_user_id: UUID, limit: int) -> tuple[list[NotificationInboxItem], int]:
    bounded = max(1, min(limit, 50))
    rows = (await db.scalars(select(NotificationInboxItem).where(NotificationInboxItem.tenant_id == tenant_id, NotificationInboxItem.recipient_user_id == recipient_user_id).order_by(NotificationInboxItem.created_at.desc(), NotificationInboxItem.id.desc()).limit(bounded))).all()
    unread = int(await db.scalar(select(func.count()).select_from(NotificationInboxItem).where(NotificationInboxItem.tenant_id == tenant_id, NotificationInboxItem.recipient_user_id == recipient_user_id, NotificationInboxItem.read_at.is_(None))) or 0)
    return rows, unread


async def mark_read(db: AsyncSession, *, tenant_id: UUID, recipient_user_id: UUID, notification_id: UUID) -> NotificationInboxItem | None:
    item = await db.scalar(select(NotificationInboxItem).where(NotificationInboxItem.id == notification_id, NotificationInboxItem.tenant_id == tenant_id, NotificationInboxItem.recipient_user_id == recipient_user_id))
    if item is None:
        return None
    if item.read_at is None:
        item.read_at = datetime.now(UTC)
        await db.flush()
    return item


async def mark_all_read(db: AsyncSession, *, tenant_id: UUID, recipient_user_id: UUID) -> int:
    result = await db.execute(update(NotificationInboxItem).where(NotificationInboxItem.tenant_id == tenant_id, NotificationInboxItem.recipient_user_id == recipient_user_id, NotificationInboxItem.read_at.is_(None)).values(read_at=datetime.now(UTC)))
    await db.flush()
    return int(result.rowcount or 0)
