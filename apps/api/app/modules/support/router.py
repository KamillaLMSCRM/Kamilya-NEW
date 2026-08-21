import logging
from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_tenant_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.email import EmailDeliveryError, EmailService
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.support.models import SupportRequest
from app.modules.support.schemas import SupportRequestCreate, SupportRequestCreated

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/support", tags=["support"])
DBSession = Annotated[AsyncSession, Depends(get_db)]
TenantUser = Annotated[User, Depends(require_tenant_user())]


def _reference(request_id: UUID) -> str:
    return f"KML-{request_id.hex[:8].upper()}"


@router.post("/requests", response_model=SupportRequestCreated, status_code=status.HTTP_201_CREATED)
async def create_support_request(
    payload: SupportRequestCreate,
    db: DBSession,
    user: TenantUser,
) -> SupportRequestCreated:
    tenant_name = await db.scalar(select(Tenant.name).where(Tenant.id == user.tenant_id)) or "Kamilya LMS"
    first_name = cast(str | None, user.first_name) or ""
    last_name = cast(str | None, user.last_name) or ""
    raw_email = cast(str | None, user.email)
    requester_email = raw_email.strip().lower() if raw_email else None
    requester_name = " ".join(part for part in (first_name.strip(), last_name.strip()) if part)
    requester_name = requester_name or "Kamilya LMS user"
    requester_role = cast(str, user.role)
    item = SupportRequest(
        tenant_id=user.tenant_id,
        created_by=user.id,
        requester_email=requester_email,
        requester_name=requester_name,
        requester_role=requester_role,
        category=payload.category,
        subject=payload.subject,
        message=payload.message,
        current_path=payload.current_path,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    await db.commit()

    writable_item = cast(Any, item)
    request_id = cast(UUID, item.id)
    reference = _reference(request_id)
    settings = get_settings()
    delivery_status: Literal["sent", "deferred", "failed"]
    try:
        message_id = await EmailService().send_support_request(
            to_email=settings.SUPPORT_EMAIL,
            reply_to=requester_email,
            reference=reference,
            tenant_name=tenant_name,
            requester_name=requester_name,
            requester_email=requester_email,
            requester_role=requester_role,
            category=payload.category,
            subject=payload.subject,
            message=payload.message,
            current_path=payload.current_path,
        )
        delivery_status = "sent" if message_id else "deferred"
    except EmailDeliveryError as exc:
        delivery_status = "failed"
        writable_item.delivery_failure_category = exc.category
        logger.warning("support request email failed reference=%s category=%s", reference, exc.category)
    except Exception:
        delivery_status = "failed"
        writable_item.delivery_failure_category = "unexpected_delivery_error"
        logger.exception("support request email failed reference=%s", reference)

    writable_item.delivery_status = delivery_status
    await db.commit()
    return SupportRequestCreated(
        id=request_id,
        reference=reference,
        delivery_status=delivery_status,
        created_at=cast(datetime, item.created_at),
    )
