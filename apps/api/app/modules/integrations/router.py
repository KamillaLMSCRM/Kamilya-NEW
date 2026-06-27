"""Integrations router — admin endpoints for managing tenant channels.

Endpoints:
  GET    /integrations                    — list all channels for current tenant
  POST   /integrations/whatsapp/init      — start WhatsApp session, return QR
  GET    /integrations/whatsapp/status    — current WhatsApp state
  POST   /integrations/whatsapp/logout    — destroy session
  POST   /integrations/whatsapp/test      — send test message to admin's phone
  PUT    /integrations/smtp               — set SMTP config
  POST   /integrations/smtp/test          — send test email
  PUT    /integrations/telegram           — set Telegram bot token
  POST   /integrations/telegram/test      — call getMe to verify token

All endpoints require admin role (tenant_admin or org_admin). Tenants
only see/modify their own integrations — row-level isolation via JWT
tenant_id.
"""

import logging
from uuid import UUID
from typing import List

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.core.config import get_settings
from app.models.users import User

from . import crypto
from .models import TenantIntegration, TenantIntegrationAudit
from .schemas import (
    SMTPConfig, SMTPConfigUpdate, TelegramConfig,
    IntegrationSummary, TestResult, WhatsAppStatus, WhatsAppInitResult,
)
from . import wa_gateway_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

ADMIN_ROLES = ("admin", "org_admin", "superadmin")


# ── Helpers ───────────────────────────────────────────────────────────────


async def _get_or_404(db: AsyncSession, tenant_id: UUID, channel: str) -> TenantIntegration:
    """Fetch existing integration row or 404."""
    result = await db.execute(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.channel == channel,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{channel} integration not configured")
    return row


async def _upsert(
    db: AsyncSession, tenant_id: UUID, channel: str,
    config: dict, user_id: UUID,
) -> TenantIntegration:
    """Insert or update integration row + write audit log.

    Uses INSERT ... ON CONFLICT for atomicity. The audit row records
    WHO changed WHAT for compliance purposes.
    """
    encrypted = crypto.encrypt_config(config)
    result = await db.execute(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.channel == channel,
        )
    )
    row = result.scalar_one_or_none()
    change_type = "updated" if row else "created"
    if row is None:
        row = TenantIntegration(
            tenant_id=tenant_id, channel=channel,
            config_encrypted=encrypted, is_active=True,
        )
        db.add(row)
    else:
        row.config_encrypted = encrypted
        row.is_active = True

    audit = TenantIntegrationAudit(
        tenant_id=tenant_id, channel=channel,
        changed_by=user_id, change_type=change_type,
        metadata_json={"keys": sorted(config.keys())},
    )
    db.add(audit)
    await db.flush()
    return row


# ── List ──────────────────────────────────────────────────────────────────


@router.get("", response_model=List[IntegrationSummary])
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """List all configured integrations for the current tenant."""
    result = await db.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == user.tenant_id)
    )
    rows = result.scalars().all()
    summaries = []
    for r in rows:
        # For WhatsApp, fetch live status from wa-gateway
        extra = {}
        if r.channel == "whatsapp":
            try:
                extra = await wa_gateway_client.get_status(str(user.tenant_id))
            except wa_gateway_client.WAGatewayError as e:
                extra = {"status": "gateway_error", "detail": e.detail}
        summaries.append(IntegrationSummary(
            channel=r.channel,
            is_active=r.is_active,
            last_test_at=r.last_test_at,
            last_test_status=r.last_test_status,
            has_secret=bool(r.config_encrypted),
            updated_at=r.updated_at,
            extra=extra,
        ))
    return summaries


# ── WhatsApp ──────────────────────────────────────────────────────────────


@router.post("/whatsapp/init", response_model=WhatsAppInitResult)
async def init_whatsapp(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Start a WhatsApp session and return QR code (PNG base64) for HR to
    scan from their work phone. If already connected, returns current
    state. Idempotent.
    """
    try:
        result = await wa_gateway_client.init_session(str(user.tenant_id))
    except wa_gateway_client.WAGatewayError as e:
        if e.status_code == 503:
            raise HTTPException(503, detail=f"wa-gateway недоступен: {e.detail}")
        raise HTTPException(502, detail=e.detail)

    # Mark WhatsApp integration as configured (if not yet in DB).
    # We store empty config — actual creds (creds.json) live on gateway.
    await _upsert(
        db, user.tenant_id, "whatsapp",
        config={"gateway_managed": True},
        user_id=user.id,
    )
    await db.commit()

    return WhatsAppInitResult(
        status=result.get("status", "unknown"),
        qr=result.get("qr"),
        phone_number=result.get("phone_number"),
        mock=result.get("mock", False),
    )


@router.get("/whatsapp/status", response_model=WhatsAppStatus)
async def whatsapp_status(
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Current WhatsApp connection status. Poll while UI shows QR code."""
    try:
        result = await wa_gateway_client.get_status(str(user.tenant_id))
    except wa_gateway_client.WAGatewayError as e:
        raise HTTPException(502, detail=e.detail)
    return WhatsAppStatus(
        status=result.get("status", "unknown"),
        phone_number=result.get("phone_number"),
        qr=result.get("qr"),
        qr_expires_at=result.get("qr_expires_at"),
    )


@router.post("/whatsapp/logout")
async def whatsapp_logout(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Destroy WhatsApp session. Tenant will need to re-scan QR."""
    try:
        await wa_gateway_client.logout(str(user.tenant_id))
    except wa_gateway_client.WAGatewayError as e:
        raise HTTPException(502, detail=e.detail)

    # Audit
    db.add(TenantIntegrationAudit(
        tenant_id=user.tenant_id, channel="whatsapp",
        changed_by=user.id, change_type="deleted",
        metadata_json={"reason": "admin_logout"},
    ))
    await db.commit()
    return {"status": "logged_out"}


@router.post("/whatsapp/test", response_model=TestResult)
async def whatsapp_test(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Send a test message to the connected WhatsApp number. Returns
    409 if not connected yet (UI should show "scan QR first").
    """
    try:
        result = await wa_gateway_client.self_test(str(user.tenant_id))
    except wa_gateway_client.WAGatewayError as e:
        if e.status_code == 409:
            raise HTTPException(409, detail="session not connected — scan QR first")
        raise HTTPException(502, detail=e.detail)

    # Mark test as passed
    row = await _get_or_404(db, user.tenant_id, "whatsapp")
    from datetime import datetime, timezone
    row.last_test_at = datetime.now(timezone.utc)
    row.last_test_status = "ok"
    db.add(TenantIntegrationAudit(
        tenant_id=user.tenant_id, channel="whatsapp",
        changed_by=user.id, change_type="test_passed",
        metadata_json=result,
    ))
    await db.commit()
    return TestResult(ok=True, detail=f"message_id={result.get('message_id')}")


# ── SMTP ─────────────────────────────────────────────────────────────────


@router.put("/smtp")
async def set_smtp(
    req: SMTPConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Configure SMTP for this tenant. Password is encrypted at rest."""
    await _upsert(
        db, user.tenant_id, "smtp",
        config=req.model_dump(),
        user_id=user.id,
    )
    await db.commit()
    return {"status": "ok"}


@router.patch("/smtp")
async def update_smtp(
    req: SMTPConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Partial update — if password omitted, keep existing encrypted one."""
    try:
        row = await _get_or_404(db, user.tenant_id, "smtp")
    except HTTPException:
        # No existing config — fall back to PUT semantics
        raise HTTPException(400, detail="no SMTP config to update; use PUT to create")

    existing = crypto.decrypt_config(bytes(row.config_encrypted))
    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, detail="no fields to update")
    existing.update(updates)
    await _upsert(db, user.tenant_id, "smtp", config=existing, user_id=user.id)
    await db.commit()
    return {"status": "ok"}


@router.post("/smtp/test", response_model=TestResult)
async def smtp_test(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Send a test email to admin's own address to verify SMTP config."""
    from datetime import datetime, timezone
    row = await _get_or_404(db, user.tenant_id, "smtp")
    cfg = crypto.decrypt_config(bytes(row.config_encrypted))

    # Try to send to admin's email — fall back to from_addr if missing
    recipient = user.email or cfg.get("from_addr")
    if not recipient:
        raise HTTPException(400, detail="admin has no email and from_addr not configured")

    msg = MIMEMultipart()
    msg["From"] = (
        f"{cfg.get('from_name', '')} <{cfg['from_addr']}>" if cfg.get("from_name") else cfg["from_addr"]
    )
    msg["To"] = recipient
    msg["Subject"] = "Kamilya LMS — test email"
    msg.attach(MIMEText(
        "Если вы читаете это письмо — SMTP настроен корректно.",
        "plain", "utf-8",
    ))

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg["username"],
            password=cfg["password"],
            use_tls=cfg.get("use_tls", True),
            timeout=15,
        )
    except Exception as e:
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_status = f"failed: {e.__class__.__name__}: {str(e)[:200]}"
        db.add(TenantIntegrationAudit(
            tenant_id=user.tenant_id, channel="smtp",
            changed_by=user.id, change_type="test_failed",
            metadata_json={"error": str(e)[:500]},
        ))
        await db.commit()
        raise HTTPException(502, detail=f"SMTP send failed: {e}")

    row.last_test_at = datetime.now(timezone.utc)
    row.last_test_status = "ok"
    db.add(TenantIntegrationAudit(
        tenant_id=user.tenant_id, channel="smtp",
        changed_by=user.id, change_type="test_passed",
        metadata_json={"to": recipient},
    ))
    await db.commit()
    return TestResult(ok=True, detail=f"sent to {recipient}")


# ── Telegram ─────────────────────────────────────────────────────────────


@router.put("/telegram")
async def set_telegram(
    req: TelegramConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Configure Telegram bot token. Created by tenant via @BotFather."""
    await _upsert(
        db, user.tenant_id, "telegram",
        config=req.model_dump(),
        user_id=user.id,
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/telegram/test", response_model=TestResult)
async def telegram_test(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*ADMIN_ROLES)),
):
    """Call Telegram getMe to verify bot token is valid."""
    import httpx
    from datetime import datetime, timezone
    row = await _get_or_404(db, user.tenant_id, "telegram")
    cfg = crypto.decrypt_config(bytes(row.config_encrypted))
    bot_token = cfg["bot_token"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
            data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "unknown telegram error"))
        bot_info = data.get("result", {})
        bot_username = bot_info.get("username", "unknown")
    except Exception as e:
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_status = f"failed: {str(e)[:200]}"
        db.add(TenantIntegrationAudit(
            tenant_id=user.tenant_id, channel="telegram",
            changed_by=user.id, change_type="test_failed",
            metadata_json={"error": str(e)[:500]},
        ))
        await db.commit()
        raise HTTPException(502, detail=f"telegram test failed: {e}")

    row.last_test_at = datetime.now(timezone.utc)
    row.last_test_status = "ok"
    db.add(TenantIntegrationAudit(
        tenant_id=user.tenant_id, channel="telegram",
        changed_by=user.id, change_type="test_passed",
        metadata_json={"bot_username": bot_username},
    ))
    await db.commit()
    return TestResult(ok=True, detail=f"bot: @{bot_username}")