"""Self-service tenant registration via Telegram ID.

This is the v1 public onboarding flow. Replaces the dead email/password
/public-register that had no SMTP backing.

Flow:
  1. Anonymous user opens /register, fills company + telegram_id + name.
  2. POST /auth/register-by-telegram -> creates Tenant + first admin User.
  3. User is redirected to /login, generates a 6-digit code, sends it
     to the @kamilla_lms_bot on Telegram.
  4. Bot webhook (auth/telegram.py) looks up the user by telegram_id
     (the one we just stored), verifies the code, returns JWT.

No password, no email, no SMTP — the Telegram ID IS the credential.

Error codes (HTTP 409):
  telegram_id_taken   — this telegram_id is already bound to some user.
                        User should login instead of registering.
  slug_taken          — another tenant already owns this slug. Pick a
                        different company name (or use the existing one).
"""
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.audit.service import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str) -> str:
    """Make a URL-safe slug from a company name.

    - lowercase
    - replace any non-[a-z0-9-] with '-'
    - collapse multiple dashes
    - trim dashes from edges
    - cap at 63 chars (Postgres identifier limit safe)
    """
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9а-я\s-]", "", s, flags=re.UNICODE)
    # transliterate cyrillic -> latin is intentionally skipped — instead
    # we replace non-ascii runs with dashes (acme-company). If the user
    # wants a custom slug they can rename the tenant later.
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        s = "tenant"
    return s[:63]


class TelegramRegisterRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    telegram_id: int = Field(..., gt=0, description="Numeric Telegram user ID")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)


class TelegramRegisterResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    telegram_id: int
    role: str
    next_step: str = "go_to_login"


@router.post("/register-by-telegram", response_model=TelegramRegisterResponse)
async def register_by_telegram(
    req: TelegramRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public self-service registration. No auth required."""
    import logging
    logger = logging.getLogger(__name__)

    # 1. telegram_id must be globally unique across all tenants
    existing = (
        # tenant-gate: allow - globally unique Telegram ID check before tenant selection.
        await db.execute(select(User).where(User.telegram_id == req.telegram_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "telegram_id_taken",
                "message": (
                    "Этот Telegram уже привязан к аккаунту Kamilya LMS. "
                    "Войдите через /login."
                ),
            },
        )

    # 2. Derive a tenant slug from company name and ensure uniqueness
    base_slug = _slugify(req.company)
    candidate_slug = base_slug
    suffix = 1
    while True:
        slug_taken = (
            await db.execute(select(Tenant).where(Tenant.slug == candidate_slug))
        ).scalar_one_or_none()
        if slug_taken is None:
            break
        suffix += 1
        if suffix > 99:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "slug_taken",
                    "message": (
                        f"Не удалось подобрать свободный URL для «{req.company}». "
                        "Попробуйте другое название."
                    ),
                },
            )
        candidate_slug = f"{base_slug}-{suffix}"

    # 3. Create tenant + admin user
    tenant = Tenant(
        name=req.company,
        slug=candidate_slug,
        status="trial",
        plan="trial",
    )
    db.add(tenant)
    await db.flush()

    await db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant.id)})

    user = User(
        tenant_id=tenant.id,
        telegram_id=req.telegram_id,
        first_name=req.first_name,
        last_name=req.last_name,
        role="admin",  # first user of a tenant is always admin
        is_active=True,
        status="active",
    )
    db.add(user)
    await db.flush()

    # 4. Audit
    try:
        await log_action(
            db,
            tenant.id,
            "register",
            "user",
            resource_id=str(user.id),
            user_id=user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={
                "method": "telegram",
                "telegram_id": req.telegram_id,
                "tenant_slug": candidate_slug,
            },
        )
    except Exception as e:
        logger.exception(f"log_action failed: {e}")
        # Don't fail the registration if audit write fails — log and continue.

    await db.commit()

    return TelegramRegisterResponse(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        telegram_id=req.telegram_id,
        role="admin",
        next_step="go_to_login",
    )
