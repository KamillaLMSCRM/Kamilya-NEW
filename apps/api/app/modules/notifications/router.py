from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_tenant_user
from app.core.db import get_db
from app.models.users import User

from .service import list_notifications, mark_all_read, mark_read, notification_payload

router = APIRouter(prefix="/notifications", tags=["notifications"])
TenantUser = Annotated[User, Depends(require_tenant_user())]
DbSession = Annotated[AsyncSession, Depends(get_db)]


class NotificationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    context: dict[str, object]
    action_path: str
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItemResponse]
    unread_count: int


class NotificationReadAllResponse(BaseModel):
    updated: int
    unread_count: int = 0


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    db: DbSession,
    user: TenantUser,
    limit: int = Query(20, ge=1, le=50),
) -> NotificationListResponse:
    rows, unread = await list_notifications(
        db,
        tenant_id=cast(UUID, user.tenant_id),
        recipient_user_id=cast(UUID, user.id),
        limit=limit,
    )
    return NotificationListResponse(
        items=[NotificationItemResponse.model_validate(notification_payload(row)) for row in rows],
        unread_count=unread,
    )


@router.post("/{notification_id}/read", response_model=NotificationItemResponse)
async def read_notification(
    notification_id: UUID,
    db: DbSession,
    user: TenantUser,
) -> NotificationItemResponse:
    item = await mark_read(
        db,
        tenant_id=cast(UUID, user.tenant_id),
        recipient_user_id=cast(UUID, user.id),
        notification_id=notification_id,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    await db.commit()
    return NotificationItemResponse.model_validate(notification_payload(item))


@router.post("/read-all", response_model=NotificationReadAllResponse)
async def read_all_notifications(db: DbSession, user: TenantUser) -> NotificationReadAllResponse:
    updated = await mark_all_read(
        db,
        tenant_id=cast(UUID, user.tenant_id),
        recipient_user_id=cast(UUID, user.id),
    )
    await db.commit()
    return NotificationReadAllResponse(updated=updated)
