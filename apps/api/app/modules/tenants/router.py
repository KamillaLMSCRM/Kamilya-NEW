from __future__ import annotations

import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import argon2
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, create_refresh_token
from app.core.db import get_db
from app.core.email import EmailService
from app.models.tenants import Tenant, TenantLead, TenantUsage
from app.models.tenant_settings import TenantSettings
from app.models.user_roles import UserRole
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.auth.router import _set_refresh_cookie
from app.modules.auth.service import build_user_payload
from app.modules.tenants.schemas import (
    PublicLeadRequest,
    PublicLeadResponse,
    TenantRegisterRequest,
    TenantRegisterResponse,
    TrialLimits,
)


router = APIRouter(prefix="/tenants", tags=["tenants"])
public_router = APIRouter(prefix="/public", tags=["public"])
logger = logging.getLogger(__name__)
_ph = argon2.PasswordHasher()

TRIAL_DAYS = 14
TRIAL_MAX_STUDENTS = 10
TRIAL_SYSTEM_USERS = 3
TRIAL_AI_COURSES = 1
TRIAL_JD_COURSES = 1

CYRILLIC_TRANSLIT = str.maketrans({
    "а": "a", "ә": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d",
    "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
    "қ": "k", "л": "l", "м": "m", "н": "n", "ң": "n", "о": "o", "ө": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ұ": "u", "ү": "u",
    "ф": "f", "х": "h", "һ": "h", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "sch", "ъ": "", "ы": "y", "і": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


def _slugify(name: str) -> str:
    value = name.lower().strip().translate(CYRILLIC_TRANSLIT)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return (value or "tenant")[:63]


def _split_contact_name(name: str) -> tuple[str, str]:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "Admin", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _build_public_lead_message(payload: PublicLeadRequest) -> str | None:
    parts: list[str] = []
    if payload.message:
        parts.append(payload.message.strip())
    metadata = {
        "interest": payload.interest,
        "industry": payload.industry,
        "utm_source": payload.utm_source,
        "utm_medium": payload.utm_medium,
        "utm_campaign": payload.utm_campaign,
        "referrer": payload.referrer,
    }
    compact = {key: value for key, value in metadata.items() if value}
    if compact:
        parts.append(f"Landing metadata: {compact}")
    return "\n\n".join(parts) if parts else None


async def _unique_slug(db: AsyncSession, company_name: str) -> str:
    base = _slugify(company_name)
    candidate = base
    suffix = 1
    while True:
        exists = (await db.execute(select(Tenant.id).where(Tenant.slug == candidate))).scalar_one_or_none()
        if exists is None:
            return candidate
        suffix += 1
        if suffix > 99:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "slug_taken", "message": "Could not generate a free tenant slug."},
            )
        candidate = f"{base}-{suffix}"


@public_router.post("/leads", response_model=PublicLeadResponse, status_code=status.HTTP_201_CREATED)
async def submit_public_lead(
    payload: PublicLeadRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.website:
        return PublicLeadResponse(id=uuid4(), ok=True)

    lead = TenantLead(
        tenant_id=None,
        company_name=payload.company.strip(),
        contact_name=payload.name.strip(),
        email=payload.email,
        phone=payload.phone.strip() if payload.phone else None,
        employee_count_range=str(payload.companySize) if payload.companySize else None,
        preferred_language=payload.locale,
        intent=payload.interest,
        status="lead_submitted",
        source="landing_form",
        message=_build_public_lead_message(payload),
    )
    db.add(lead)
    await db.flush()
    lead_id = lead.id
    await db.commit()
    return PublicLeadResponse(id=lead_id, ok=True)


@router.post("/register", response_model=TenantRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_tenant(
    payload: TenantRegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    existing_user = (
        # tenant-gate: allow - globally unique email check before a tenant exists.
        await db.execute(select(User.id).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "email_taken",
                "message": "This email is already registered. Use login or contact support.",
            },
        )

    slug = await _unique_slug(db, payload.company_name)
    now = datetime.now(UTC)
    trial_ends_at = now + timedelta(days=TRIAL_DAYS)
    first_name, last_name = _split_contact_name(payload.contact_name)

    settings = {
        "registration": {
            "source": "landing",
            "intent": payload.intent,
            "preferred_language": payload.preferred_language,
        },
        "trial_limits": {
            "ai_course_generations_limit": TRIAL_AI_COURSES,
            "jd_course_generations_limit": TRIAL_JD_COURSES,
            "max_students": TRIAL_MAX_STUDENTS,
            "system_users_limit": TRIAL_SYSTEM_USERS,
            "trial_days": TRIAL_DAYS,
        },
        "telegram_bot_mode": "shared",
    }

    tenant = Tenant(
        name=payload.company_name,
        slug=slug,
        status="trial",
        plan="trial",
        trial_started_at=now,
        trial_ends_at=trial_ends_at,
        max_users=TRIAL_MAX_STUDENTS,
        max_courses_per_month=TRIAL_AI_COURSES + TRIAL_JD_COURSES,
        billing_contact_email=payload.email,
        billing_company_name=payload.company_name,
        billing_identifier=payload.billing_identifier,
        settings=settings,
    )
    db.add(tenant)
    await db.flush()

    # RLS context is required before inserting tenant-scoped rows as lms_app.
    await db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant.id)})

    # Auto-create per-tenant settings row with the model defaults so
    # downstream endpoints (logo_url, default_language, quiz_pass_threshold,
    # monthly_llm_budget_usd_cents, etc.) never read NULL / get 500s.
    # Without this, all 7 production tenants had settings=NULL because the
    # row was never seeded — see P1 QA report 2026-07-10 bug #5.
    db.add(TenantSettings(tenant_id=tenant.id))

    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=payload.email,
        password_hash=_ph.hash(payload.password),
        first_name=first_name,
        last_name=last_name,
        role="admin",
        is_active=True,
        status="active",
    )
    db.add(user)
    await db.flush()

    db.add(UserRole(id=uuid4(), user_id=user.id, tenant_id=tenant.id, role="admin"))
    usage = TenantUsage(
        tenant_id=tenant.id,
        active_students_count_snapshot=0,
        system_users_count_snapshot=1,
    )
    db.add(usage)

    lead = TenantLead(
        tenant_id=tenant.id,
        company_name=payload.company_name,
        contact_name=payload.contact_name,
        email=payload.email,
        phone=payload.phone,
        telegram_username=payload.telegram_username,
        employee_count_range=payload.employee_count_range,
        preferred_language=payload.preferred_language,
        intent=payload.intent,
        status="trial_active",
        source="landing",
        message=payload.message,
    )
    db.add(lead)
    await db.flush()

    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": tenant.id,
        "roles": ["admin"],
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": tenant.id,
    })
    _set_refresh_cookie(response, refresh_token)

    await log_action(
        db,
        tenant.id,
        "tenant.trial.started",
        "tenant",
        resource_id=tenant.id,
        user_id=user.id,
        details={
            "source": "landing",
            "intent": payload.intent,
            "lead_id": str(lead.id),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()

    await db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant.id)})
    await db.refresh(tenant)
    await db.refresh(user)
    await db.refresh(lead)

    user_payload = await build_user_payload(db, user)

    # Workspace activation is the primary transaction. A notification-provider
    # outage must not roll it back or turn a successful registration into a 500.
    try:
        await EmailService().send_trial_started(
            to_email=payload.email,
            company_name=payload.company_name,
        )
    except Exception:
        logger.exception(
            "trial-started email failed tenant_id=%s",
            tenant.id,
        )

    return TenantRegisterResponse(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        lead_id=lead.id,
        user_id=user.id,
        role="admin",
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=900,
        user=user_payload,
        trial_started_at=tenant.trial_started_at,
        trial_ends_at=tenant.trial_ends_at,
        limits=TrialLimits(
            ai_course_generations_limit=TRIAL_AI_COURSES,
            jd_course_generations_limit=TRIAL_JD_COURSES,
            max_students=TRIAL_MAX_STUDENTS,
            system_users_limit=TRIAL_SYSTEM_USERS,
            trial_days=TRIAL_DAYS,
        ),
    )
