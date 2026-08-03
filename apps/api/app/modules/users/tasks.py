"""Background delivery tasks for learner invitations."""
from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.models.users import UserInvitation
from app.modules.users.invitations_service import (
    TransientInvitationDeliveryError,
    _build_invite_url,
    _set_invitation_tenant_context,
    attempt_invitation_delivery,
)


async def _deliver_invitation(
    *,
    tenant_id: UUID,
    invitation_id: UUID,
) -> dict[str, str | int | None]:
    """Deliver one invitation using a fresh session and tenant context.

    The row lock makes duplicate broker deliveries idempotent: a second task
    waits for the first attempt to commit and then observes the terminal
    delivery state instead of sending another message.
    """
    async with async_session_factory() as db:
        await _set_invitation_tenant_context(db, tenant_id)
        result = await db.execute(
            select(UserInvitation)
            .where(
                UserInvitation.id == invitation_id,
                UserInvitation.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        invitation = result.scalar_one_or_none()
        if invitation is None:
            return {"status": "not_found"}

        if invitation.status != "pending":
            return {"status": "skipped", "reason": "invitation_not_pending"}
        if invitation.delivery_status == "sent":
            return {"status": "skipped", "reason": "already_sent"}
        if invitation.delivery_status == "failed":
            return {"status": "skipped", "reason": "permanent_failure_recorded"}

        settings = get_settings()
        delivery = await attempt_invitation_delivery(
            db,
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            invite_url=_build_invite_url(
                invitation.token,
                getattr(settings, "PUBLIC_URL", None),
            ),
            retry_transient=True,
        )
        return {
            "status": str(delivery.get("delivery_status", "pending")),
            "attempt_count": int(delivery.get("delivery_attempt_count") or 0),
        }


@celery_app.task(
    bind=True,
    name="users.deliver_invitation",
    autoretry_for=(TransientInvitationDeliveryError,),
    retry_backoff=5,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def deliver_invitation_task(self, tenant_id: str, invitation_id: str) -> dict:
    """Deliver an invitation without trusting caller-controlled tenant data.

    ``autoretry_for`` is intentionally narrowed to the marker raised only for
    transient provider errors. The task returns for missing, already accepted,
    already sent, permanent provider, and unconfigured-provider outcomes.
    """
    return asyncio.run(
        _deliver_invitation(
            tenant_id=UUID(tenant_id),
            invitation_id=UUID(invitation_id),
        )
    )
