import logging
from typing import Annotated

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


def _reference(request_id) -> str:
    return f"KML-{request_id.hex[:8].upper()}"


@router.post("/requests", response_model=SupportRequestCreated, status_code=status.HTTP_201_CREATED)
async def create_support_request(
    payload: SupportRequestCreate,
    db: DBSession,
    user: TenantUser,
) -> SupportRequestCreated:
    tenant_name = await db.scalar(select(Tenant.name).where(Tenant.id == user.tenant_id)) or "Kamilya LMS"
    requester_name = " ".join(part for part in (user.first_name.strip(), user.last_name.strip()) if part)
    item = SupportRequest(
        tenant_id=user.tenant_id,
        created_by=user.id,
        requester_email=user.email.strip().lower() if user.email else None,
        requester_name=requester_name or "Kamilya LMS user",
        requester_role=user.role,
        category=payload.category,
        subject=payload.subject,
        message=payload.message,
        current_path=payload.current_path,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    await db.commit()

    reference = _reference(item.id)
    settings = get_settings()
    try:
        message_id = await EmailService().send_support_request(
            to_email=settings.SUPPORT_EMAIL,
            reply_to=item.requester_email,
            reference=reference,
            tenant_name=tenant_name,
            requester_name=item.requester_name,
            requester_email=item.requester_email,
            requester_role=item.requester_role,
            category=item.category,
            subject=item.subject,
            message=item.message,
            current_path=item.current_path,
        )
        item.delivery_status = "sent" if message_id else "deferred"
    except EmailDeliveryError as exc:
        item.delivery_status = "failed"
        item.delivery_failure_category = exc.category
        logger.warning("support request email failed reference=%s category=%s", reference, exc.category)
    except Exception:
        item.delivery_status = "failed"
        item.delivery_failure_category = "unexpected_delivery_error"
        logger.exception("support request email failed reference=%s", reference)

    await db.commit()
    return SupportRequestCreated(
        id=item.id,
        reference=reference,
        delivery_status=item.delivery_status,
        created_at=item.created_at,
    )
