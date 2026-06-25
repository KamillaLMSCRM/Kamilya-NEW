"""Invitation service — bulk create, resend, accept.

Phase 1 of employee onboarding epic (docs/plans/employee-onboarding.md).

Key behaviors:
- Bulk create: dedupe + validate emails, check tenant conflicts, create user_invitations
  + create pending User rows (is_active=false, no password) so position-courses /
  enrollments can FK to them
- Resend: create a new row with fresh token, mark old as 'superseded'
- Accept: validate token + expiry, set user password + activate, mark invitation
  'accepted', issue JWT for auto-login

Email is NOT sent — methodologist copies the invite_url and delivers manually
(see Email Strategy in design doc).
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token
from app.models.tenant_settings import TenantSettings
from app.models.users import User, UserInvitation

ph = PasswordHasher()

# Conservative email regex — not RFC-perfect but rejects obvious garbage.
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 320


def _generate_token() -> str:
    """32-char URL-safe token. ~190 bits of entropy."""
    return secrets.token_urlsafe(24)


async def _get_tenant_invite_expiry_days(db: AsyncSession, tenant_id: UUID) -> int:
    """Read tenant_settings.invite_expiry_days; default 3 if row absent."""
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    )
    settings = result.scalar_one_or_none()
    if settings and settings.invite_expiry_days:
        return settings.invite_expiry_days
    return 3


def _build_invite_url(token: str, base_url: str | None = None) -> str:
    """Build the invite URL. Falls back to kml.kz if no base_url configured."""
    base = (base_url or "https://app.kml.kz").rstrip("/")
    return f"{base}/accept-invite?token={token}"


async def bulk_create_invitations(
    db: AsyncSession,
    tenant_id: UUID,
    invited_by: UUID,
    raw_emails: list[str],
    base_url: str | None = None,
    default_role: str = "student",
) -> dict:
    """Process a list of emails, create invitations + pending User rows.

    Returns: {created: [...], skipped_existing: [...], invalid: [...]}
    """
    # 1. Dedupe + validate input
    seen: set[str] = set()
    valid_emails: list[str] = []
    invalid: list[dict] = []
    for raw in raw_emails:
        norm = _normalize_email(raw)
        if not norm:
            invalid.append({"input": raw, "reason": "invalid_email"})
            continue
        if not _is_valid_email(norm):
            invalid.append({"input": raw, "reason": "invalid_email"})
            continue
        if norm in seen:
            continue  # dedupe silently
        seen.add(norm)
        valid_emails.append(norm)

    if not valid_emails:
        return {"created": [], "skipped_existing": [], "invalid": invalid}

    # 2. Check existing users in this tenant
    existing_users_result = await db.execute(
        select(User.email).where(
            User.tenant_id == tenant_id,
            User.email.in_(valid_emails),
        )
    )
    existing_emails: set[str] = {row[0].lower() for row in existing_users_result.all()}

    # 3. Check pending invitations in this tenant
    pending_inv_result = await db.execute(
        select(UserInvitation.email).where(
            UserInvitation.tenant_id == tenant_id,
            UserInvitation.email.in_(valid_emails),
            UserInvitation.status == "pending",
        )
    )
    pending_emails: set[str] = {row[0].lower() for row in pending_inv_result.all()}

    # 4. Filter out conflicts
    to_create: list[str] = []
    skipped: list[dict] = []
    for email in valid_emails:
        if email in existing_emails:
            skipped.append({"email": email, "reason": "already_in_tenant"})
            continue
        if email in pending_emails:
            skipped.append({"email": email, "reason": "pending_invite_exists"})
            continue
        to_create.append(email)

    if not to_create:
        return {"created": [], "skipped_existing": skipped, "invalid": invalid}

    # 5. Create pending User + UserInvitation rows
    expiry_days = await _get_tenant_invite_expiry_days(db, tenant_id)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=expiry_days)

    created: list[dict] = []
    for email in to_create:
        user_id = uuid4()
        db.add(User(
            id=user_id,
            tenant_id=tenant_id,
            email=email,
            first_name="",
            last_name="",
            role=default_role,
            is_active=False,
            password_hash=None,
            status="inactive",  # user accepted invite → "active"
        ))

        token = _generate_token()
        invitation_id = uuid4()
        db.add(UserInvitation(
            id=invitation_id,
            tenant_id=tenant_id,
            email=email,
            first_name="",
            last_name="",
            role=default_role,
            invited_by=invited_by,
            token=token,
            status="pending",
            expires_at=expires_at,
            user_id=user_id,
        ))

        created.append({
            "email": email,
            "invitation_id": invitation_id,
            "invite_url": _build_invite_url(token, base_url),
            "expires_at": expires_at,
        })

    await db.commit()

    return {"created": created, "skipped_existing": skipped, "invalid": invalid}


async def resend_invitation(
    db: AsyncSession,
    tenant_id: UUID,
    invitation_id: UUID,
    base_url: str | None = None,
) -> dict:
    """Create a new invitation row with fresh token; mark old as superseded.

    Works for both 'pending' and 'expired' rows — re-invite always allowed
    within the tenant.
    """
    old = await db.get(UserInvitation, invitation_id)
    if not old or old.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if old.status not in ("pending", "expired"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot re-invite: status is '{old.status}'",
        )

    # Find associated pending user (must exist; created together)
    if not old.user_id:
        raise HTTPException(status_code=500, detail="Invitation has no associated user")

    expiry_days = await _get_tenant_invite_expiry_days(db, tenant_id)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=expiry_days)
    new_token = _generate_token()
    new_id = uuid4()

    db.add(UserInvitation(
        id=new_id,
        tenant_id=old.tenant_id,
        email=old.email,
        first_name=old.first_name,
        last_name=old.last_name,
        role=old.role,
        invited_by=old.invited_by,
        token=new_token,
        status="pending",
        expires_at=expires_at,
        user_id=old.user_id,
    ))

    old.status = "superseded"
    old.superseded_by = new_id

    await db.commit()

    return {
        "invitation_id": new_id,
        "invite_url": _build_invite_url(new_token, base_url),
        "expires_at": expires_at,
        "superseded_old_id": old.id,
    }


async def get_public_invitation(db: AsyncSession, token: str, tenant_lookup=None) -> dict:
    """Resolve token → {email, tenant_name, role, expires_at, valid, reason_if_invalid}.

    No auth — anyone with the token can view. Used by /accept-invite page on load.
    Returns dict; HTTPException is NOT raised (so frontend can show the user
    a friendly "link expired" message).
    """
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        return {
            "email": "",
            "tenant_name": "",
            "role": "",
            "expires_at": datetime.min.replace(tzinfo=timezone.utc),
            "valid": False,
            "reason_if_invalid": "invitation_not_found",
        }

    # Look up tenant name
    from app.models.tenants import Tenant  # local import to avoid circular
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == inv.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    tenant_name = tenant.name if tenant else "Unknown"

    if inv.status == "accepted":
        return {
            "email": inv.email,
            "tenant_name": tenant_name,
            "role": inv.role,
            "expires_at": inv.expires_at,
            "valid": False,
            "reason_if_invalid": "already_accepted",
        }
    if inv.status == "superseded":
        return {
            "email": inv.email,
            "tenant_name": tenant_name,
            "role": inv.role,
            "expires_at": inv.expires_at,
            "valid": False,
            "reason_if_invalid": "superseded",
        }
    if inv.status == "revoked":
        return {
            "email": inv.email,
            "tenant_name": tenant_name,
            "role": inv.role,
            "expires_at": inv.expires_at,
            "valid": False,
            "reason_if_invalid": "revoked",
        }
    if inv.status == "expired" or inv.expires_at < datetime.now(timezone.utc):
        # Lazy-expire: if status was still 'pending' but past expiry, flip it.
        if inv.status == "pending":
            inv.status = "expired"
            await db.commit()
        return {
            "email": inv.email,
            "tenant_name": tenant_name,
            "role": inv.role,
            "expires_at": inv.expires_at,
            "valid": False,
            "reason_if_invalid": "expired",
        }

    return {
        "email": inv.email,
        "tenant_name": tenant_name,
        "role": inv.role,
        "expires_at": inv.expires_at,
        "valid": True,
        "reason_if_invalid": None,
    }


async def accept_invitation(
    db: AsyncSession,
    token: str,
    first_name: str,
    last_name: str,
    password: str,
) -> dict:
    """Validate token, set user password, activate user, issue JWT.

    Raises HTTPException on failure. Returns {user_id, tenant_id, role, access_token}.
    """
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.status != "pending":
        reasons = {
            "accepted": "Это приглашение уже принято",
            "expired": "Срок действия приглашения истёк",
            "revoked": "Приглашение отозвано",
            "superseded": "Приглашение заменено новым — проверьте почту/мессенджер",
        }
        raise HTTPException(status_code=410, detail=reasons.get(inv.status, f"Статус: {inv.status}"))
    if inv.expires_at < datetime.now(timezone.utc):
        inv.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="Срок действия приглашения истёк")
    if not inv.user_id:
        raise HTTPException(status_code=500, detail="Invitation has no associated user")

    # Activate user
    user = await db.get(User, inv.user_id)
    if not user:
        raise HTTPException(status_code=500, detail="Associated user not found")
    if user.tenant_id != inv.tenant_id:
        raise HTTPException(status_code=500, detail="Tenant mismatch")

    user.first_name = first_name.strip()
    user.last_name = last_name.strip()
    user.password_hash = ph.hash(password)
    user.is_active = True
    user.status = "active"
    user.last_login = datetime.now(timezone.utc)

    # Mark invitation accepted
    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)

    await db.commit()

    # Issue JWT for auto-login
    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "roles": [user.role],
    })

    return {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "access_token": access_token,
        "refresh_token": None,  # v1: not issued on accept; user can log in normally later
    }
