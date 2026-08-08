"""Invitation service — bulk create, resend, accept.

Phase 1 of employee onboarding epic (docs/plans/employee-onboarding.md).

Key behaviors:
- Bulk create: dedupe + validate emails, check tenant conflicts, create
  user_invitations. A new email gets a pending User; an imported staff User
  without password/Telegram access is reused instead of duplicated.
- Resend: create a new row with fresh token, mark old as 'superseded'
- Request code: send a scoped email OTP to the HR-managed address.
- Accept: validate token + email OTP, activate the existing learner identity,
  mark the invitation accepted, and issue JWTs for passwordless auto-login.

The initial invite URL may be delivered by any configured notification channel.
Identity activation itself always verifies control of the stored email address.
"""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, create_refresh_token
from app.core.email import EmailDeliveryError, EmailService
from app.models.enrollment import Enrollment
from app.models.tenant_settings import TenantSettings
from app.models.users import User, UserInvitation
from app.modules.auth.email_otp import (
    consume_email_code,
    create_invitation_email_code,
    invalidate_email_code,
)
from app.modules.courses.models import Course
from app.modules.positions.models import Position

# Conservative email regex — not RFC-perfect but rejects obvious garbage.
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

TRANSIENT_DELIVERY_CATEGORIES = frozenset(
    {
        "provider_timeout",
        "provider_unreachable",
        "provider_rate_limited",
        "provider_unavailable",
    }
)


class TransientInvitationDeliveryError(RuntimeError):
    """Safe marker used by the Celery task to request a bounded retry."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def is_transient_delivery_category(category: str | None) -> bool:
    return category in TRANSIENT_DELIVERY_CATEGORIES


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


async def _get_tenant_invite_language(db: AsyncSession, tenant_id: UUID) -> str:
    """Read the tenant email language and keep an explicit safe fallback."""
    result = await db.execute(
        select(TenantSettings.default_language).where(
            TenantSettings.tenant_id == tenant_id
        )
    )
    language = result.scalar_one_or_none()
    return language if language in {"ru", "kk", "en"} else "ru"


def _build_invite_url(token: str, base_url: str | None = None) -> str:
    """Build the invite URL. Falls back to kml.kz if no base_url configured."""
    base = (base_url or "https://app.kml.kz").rstrip("/")
    return f"{base}/accept-invite?token={token}"


def _delivery_payload(invitation: UserInvitation) -> dict:
    return {
        "delivery_status": invitation.delivery_status,
        "delivery_message_id": invitation.delivery_message_id,
        "delivery_last_attempt_at": invitation.delivery_last_attempt_at,
        "delivery_attempt_count": invitation.delivery_attempt_count,
        "delivery_failure_category": invitation.delivery_failure_category,
        "delivery_failure_message": invitation.delivery_failure_message,
    }


async def attempt_invitation_delivery(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    invitation_id: UUID,
    invite_url: str,
    retry_transient: bool = False,
) -> dict:
    """Attempt one link delivery after its invitation row is committed.

    A provider failure is recorded on the invitation and never raised back to
    the batch caller, so valid invitation creation remains durable.
    """
    # Invitation creation commits before delivery; restore the transaction-
    # local tenant context before querying or updating the new row.
    await _set_invitation_tenant_context(db, tenant_id)
    result = await db.execute(
        select(UserInvitation).where(
            UserInvitation.id == invitation_id,
            UserInvitation.tenant_id == tenant_id,
        )
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if not EmailService.delivery_ready():
        invitation.delivery_failure_category = "provider_unconfigured"
        invitation.delivery_failure_message = (
            "Automatic email delivery is not configured; use the activation link manually."
        )
        await db.commit()
        return _delivery_payload(invitation)

    invitation.delivery_last_attempt_at = datetime.now(UTC)
    invitation.delivery_attempt_count = (invitation.delivery_attempt_count or 0) + 1
    invitation.delivery_failure_category = None
    invitation.delivery_failure_message = None

    try:
        from app.models.tenants import Tenant

        tenant_name = (
            await db.execute(select(Tenant.name).where(Tenant.id == tenant_id))
        ).scalar_one_or_none() or "Kamilya LMS"
        language = await _get_tenant_invite_language(db, tenant_id)
        learner_name = f"{invitation.first_name} {invitation.last_name}".strip()
        if not learner_name:
            learner_name = {"ru": "Сотрудник", "kk": "Қызметкер", "en": "Learner"}[language]
        message_id = await EmailService().send_invitation_link(
            to_email=invitation.email,
            invite_url=invite_url,
            company_name=tenant_name,
            learner_name=learner_name,
            language=language,
        )
    except EmailDeliveryError as exc:
        invitation.delivery_status = "pending" if (
            retry_transient and is_transient_delivery_category(exc.category)
        ) else "failed"
        invitation.delivery_failure_category = exc.category[:64]
        invitation.delivery_failure_message = exc.message[:500]
        if retry_transient and is_transient_delivery_category(exc.category):
            await db.commit()
            raise TransientInvitationDeliveryError(exc.category) from exc
    except Exception:
        invitation.delivery_status = "failed"
        invitation.delivery_failure_category = "internal_error"
        invitation.delivery_failure_message = "The invitation email could not be sent."
    else:
        invitation.delivery_status = "sent"
        invitation.delivery_message_id = message_id

    await db.commit()
    return _delivery_payload(invitation)


async def _set_invitation_tenant_context(db: AsyncSession, tenant_id: UUID) -> None:
    """Set RLS tenant context after a public token lookup resolves tenant_id."""
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})


async def bulk_create_invitations(
    db: AsyncSession,
    tenant_id: UUID,
    invited_by: UUID,
    raw_emails: list[str],
    base_url: str | None = None,
    default_role: str = "student",
    personnel_numbers: dict[str, str] | None = None,
) -> dict:
    """Process a list of emails, create invitations + pending User rows.

    personnel_numbers: optional {email: personnel_number} map. The value remains
    HR-owned identity metadata and is never requested from the learner during
    activation.

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

    # 2. Check existing users in this tenant. Keep the tenant predicate on
    # the query so an email in another tenant can never be attached here.
    existing_users_result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            func.lower(User.email).in_(valid_emails),
        ).order_by(User.created_at.asc(), User.id.asc())
    )
    existing_users_by_email: dict[str, list[User]] = {}
    for existing_user in existing_users_result.scalars().all():
        if existing_user.email:
            existing_users_by_email.setdefault(
                _normalize_email(existing_user.email), []
            ).append(existing_user)

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
        existing_users = existing_users_by_email.get(email, [])
        if len(existing_users) > 1:
            skipped.append({"email": email, "reason": "duplicate_email_identity"})
            continue
        if email in pending_emails:
            skipped.append({"email": email, "reason": "pending_invite_exists"})
            continue
        if existing_users:
            if any(existing_user.has_login_access for existing_user in existing_users):
                skipped.append({"email": email, "reason": "already_has_access"})
                continue
            if any(existing_user.role == "student" for existing_user in existing_users):
                to_create.append(email)
                continue
            skipped.append({"email": email, "reason": "already_in_tenant"})
            continue
        to_create.append(email)

    if not to_create:
        return {"created": [], "skipped_existing": skipped, "invalid": invalid}

    # 5. Create pending User + UserInvitation rows
    expiry_days = await _get_tenant_invite_expiry_days(db, tenant_id)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=expiry_days)

    created: list[dict] = []
    pn_map = {
        _normalize_email(email): number
        for email, number in (personnel_numbers or {}).items()
    }
    for email in to_create:
        existing_users = existing_users_by_email.get(email, [])
        existing_student = next(
            (
                user for user in existing_users
                if user.role == "student" and not user.has_login_access
            ),
            None,
        )
        if existing_student:
            user_id = existing_student.id
            first_name = existing_student.first_name
            last_name = existing_student.last_name
            # Preserve staff data imported before login was configured.
            pn = existing_student.personnel_number or pn_map.get(email)
        else:
            user_id = uuid4()
            first_name = ""
            last_name = ""
            pn = pn_map.get(email)
            db.add(User(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                personnel_number=pn,
                first_name=first_name,
                last_name=last_name,
                role=default_role,
                is_active=False,
                password_hash=None,
                status="inactive",
            ))

        token = _generate_token()
        invitation_id = uuid4()
        db.add(UserInvitation(
            id=invitation_id,
            tenant_id=tenant_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            personnel_number=pn,
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
            "personnel_number": pn,
        })

    await db.commit()

    return {"created": created, "skipped_existing": skipped, "invalid": invalid}


async def create_or_refresh_user_invitation(
    db: AsyncSession,
    tenant_id: UUID,
    invited_by: UUID,
    user_id: UUID,
    base_url: str | None = None,
) -> dict:
    """Create a fresh activation link for one exact learner identity.

    Course assignment already operates on ``user_id``. Keeping the same
    identifier here prevents an invitation from being attached to another
    historical row that happens to share the email address.
    """
    user_result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
        )
    )
    target = user_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if target.role != "student":
        raise HTTPException(
            status_code=409,
            detail="Ссылка активации доступна только для обучающегося",
        )
    email = _normalize_email(target.email or "")
    if not _is_valid_email(email):
        raise HTTPException(
            status_code=422,
            detail="У сотрудника не указан корректный email",
        )
    if target.has_login_access:
        raise HTTPException(
            status_code=409,
            detail="У сотрудника уже настроен вход",
        )

    identities_result = await db.execute(
        select(User.id).where(
            User.tenant_id == tenant_id,
            func.lower(func.btrim(User.email)) == email,
        )
    )
    identity_ids = list(identities_result.scalars().all())
    if identity_ids != [target.id]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Email связан с несколькими профилями сотрудников. "
                "Объедините дубли перед созданием ссылки."
            ),
        )

    pending_result = await db.execute(
        select(UserInvitation).where(
            UserInvitation.tenant_id == tenant_id,
            func.lower(func.btrim(UserInvitation.email)) == email,
            UserInvitation.status == "pending",
        )
    )
    pending = pending_result.scalar_one_or_none()
    if pending is not None and pending.user_id != target.id:
        raise HTTPException(
            status_code=409,
            detail="Ожидающее приглашение связано с другим профилем сотрудника",
        )

    expiry_days = await _get_tenant_invite_expiry_days(db, tenant_id)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=expiry_days)
    token = _generate_token()
    invitation_id = uuid4()
    superseded_old_id: UUID | None = None

    if pending is not None:
        superseded_old_id = pending.id
        pending.status = "superseded"
        pending.superseded_by = invitation_id
        # Release the partial unique index before inserting the replacement.
        await db.flush()

    db.add(UserInvitation(
        id=invitation_id,
        tenant_id=tenant_id,
        email=email,
        first_name=target.first_name,
        last_name=target.last_name,
        personnel_number=target.personnel_number,
        role="student",
        invited_by=invited_by,
        token=token,
        status="pending",
        expires_at=expires_at,
        user_id=target.id,
    ))
    await db.commit()

    return {
        "email": email,
        "invitation_id": invitation_id,
        "invite_url": _build_invite_url(token, base_url),
        "expires_at": expires_at,
        "superseded_old_id": superseded_old_id,
    }


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
    now = datetime.now(UTC)
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
        "email": old.email,
        "invite_url": _build_invite_url(new_token, base_url),
        "expires_at": expires_at,
        "superseded_old_id": old.id,
    }


def _mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return ""
    visible = local[:1]
    return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"


def _public_invitation_payload(
    inv: UserInvitation | None,
    *,
    tenant_name: str = "",
    user: User | None = None,
    position_name: str | None = None,
    course_titles: list[str] | None = None,
    valid: bool,
    reason: str | None,
) -> dict:
    email = inv.email if inv else ""
    return {
        "masked_email": _mask_email(email),
        "tenant_name": tenant_name,
        "role": inv.role if inv else "",
        "first_name": (user.first_name if user else "") or (inv.first_name if inv else ""),
        "last_name": (user.last_name if user else "") or (inv.last_name if inv else ""),
        "position_name": position_name,
        "course_titles": course_titles or [],
        "expires_at": inv.expires_at if inv else datetime.min.replace(tzinfo=UTC),
        "valid": valid,
        "reason_if_invalid": reason,
    }


async def _get_pending_invitation(db: AsyncSession, token: str) -> UserInvitation:
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    await _set_invitation_tenant_context(db, inv.tenant_id)
    if inv.status != "pending":
        reasons = {
            "accepted": "Это приглашение уже принято",
            "expired": "Срок действия приглашения истёк",
            "revoked": "Приглашение отозвано",
            "superseded": "Приглашение заменено новым",
        }
        raise HTTPException(
            status_code=410,
            detail=reasons.get(inv.status, f"Статус приглашения: {inv.status}"),
        )
    if inv.expires_at < datetime.now(UTC):
        inv.status = "expired"
        await db.commit()
        raise HTTPException(status_code=410, detail="Срок действия приглашения истёк")
    if not inv.user_id:
        raise HTTPException(status_code=500, detail="Приглашение не связано с сотрудником")
    return inv


async def get_public_invitation(db: AsyncSession, token: str, tenant_lookup=None) -> dict:
    """Return read-only HR identity and assigned-course context for a token."""
    result = await db.execute(
        select(UserInvitation).where(UserInvitation.token == token)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        return _public_invitation_payload(
            None,
            valid=False,
            reason="invitation_not_found",
        )

    await _set_invitation_tenant_context(db, inv.tenant_id)

    from app.models.tenants import Tenant  # local import to avoid circular

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == inv.tenant_id))
    ).scalar_one_or_none()
    tenant_name = tenant.name if tenant else "Kamilya LMS"
    user = await db.get(User, inv.user_id) if inv.user_id else None
    position_name = None
    if user and user.position_id:
        position_name = (
            await db.execute(
                select(Position.name).where(
                    Position.id == user.position_id,
                    Position.tenant_id == inv.tenant_id,
                )
            )
        ).scalar_one_or_none()
    course_titles: list[str] = []
    if user:
        course_titles = list(
            (
                await db.execute(
                    select(Course.title)
                    .join(Enrollment, Enrollment.course_id == Course.id)
                    .where(
                        Enrollment.tenant_id == inv.tenant_id,
                        Enrollment.user_id == user.id,
                        Course.tenant_id == inv.tenant_id,
                        Course.status == "published",
                    )
                    .order_by(Enrollment.enrolled_at.desc(), Course.title.asc())
                )
            ).scalars().all()
        )

    reason_by_status = {
        "accepted": "already_accepted",
        "superseded": "superseded",
        "revoked": "revoked",
        "expired": "expired",
    }
    if inv.status in reason_by_status:
        return _public_invitation_payload(
            inv,
            tenant_name=tenant_name,
            user=user,
            position_name=position_name,
            course_titles=course_titles,
            valid=False,
            reason=reason_by_status[inv.status],
        )
    if inv.expires_at < datetime.now(UTC):
        if inv.status == "pending":
            inv.status = "expired"
            await db.commit()
        return _public_invitation_payload(
            inv,
            tenant_name=tenant_name,
            user=user,
            position_name=position_name,
            course_titles=course_titles,
            valid=False,
            reason="expired",
        )

    return _public_invitation_payload(
        inv,
        tenant_name=tenant_name,
        user=user,
        position_name=position_name,
        course_titles=course_titles,
        valid=True,
        reason=None,
    )


async def request_invitation_code(db: AsyncSession, token: str) -> dict:
    inv = await _get_pending_invitation(db, token)
    user = await db.get(User, inv.user_id)
    if not user or user.tenant_id != inv.tenant_id:
        raise HTTPException(status_code=500, detail="Сотрудник приглашения не найден")
    if not user.email or _normalize_email(user.email) != _normalize_email(inv.email):
        raise HTTPException(status_code=409, detail="Email сотрудника изменён. Запросите новое приглашение")

    from app.models.tenants import Tenant

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == inv.tenant_id))
    ).scalar_one_or_none()
    tenant_name = tenant.name if tenant else "Kamilya LMS"
    learner_name = f"{user.first_name} {user.last_name}".strip() or "Сотрудник"
    email_service = EmailService()
    if not email_service.delivery_ready():
        raise HTTPException(
            status_code=503,
            detail="Отправка email временно недоступна. Обратитесь к методологу",
        )
    code, expires_in, created = await create_invitation_email_code(
        email=inv.email,
        user_id=str(user.id),
        tenant_id=str(inv.tenant_id),
        role=inv.role,
        invitation_id=str(inv.id),
    )
    if created:
        try:
            await email_service.send_invitation_code(
                to_email=inv.email,
                code=code,
                company_name=tenant_name,
                learner_name=learner_name,
            )
        except Exception as exc:
            await invalidate_email_code(
                email=inv.email,
                purpose="invitation",
                subject_id=str(inv.id),
            )
            raise HTTPException(
                status_code=503,
                detail="Не удалось отправить код. Попробуйте ещё раз",
            ) from exc
    return {
        "ok": True,
        "expires_in": expires_in,
        "retry_after": min(60, expires_in),
    }


async def accept_invitation(
    db: AsyncSession,
    token: str,
    code: str,
    accepted_ip: str | None = None,
    accepted_user_agent: str | None = None,
) -> dict:
    """Activate the HR-managed identity after a scoped email OTP check."""
    inv = await _get_pending_invitation(db, token)
    otp = await consume_email_code(
        email=inv.email,
        code=code.strip(),
        purpose="invitation",
        subject_id=str(inv.id),
    )
    if not otp or otp.get("user_id") != str(inv.user_id):
        raise HTTPException(status_code=401, detail="Неверный или просроченный код")

    user = await db.get(User, inv.user_id)
    if not user or user.tenant_id != inv.tenant_id:
        raise HTTPException(status_code=500, detail="Сотрудник приглашения не найден")
    if not user.first_name.strip() or not user.last_name.strip():
        raise HTTPException(
            status_code=409,
            detail="В карточке сотрудника не заполнены ФИО. Обратитесь к методологу",
        )
    if not user.email or _normalize_email(user.email) != _normalize_email(inv.email):
        raise HTTPException(status_code=409, detail="Email сотрудника изменён. Запросите новое приглашение")

    accepted_at = datetime.now(UTC)
    user.is_active = True
    user.status = "active"
    user.email_verified_at = accepted_at
    user.last_login = accepted_at

    inv.status = "accepted"
    inv.accepted_at = accepted_at
    inv.verification_method = "email_otp"
    if accepted_ip:
        inv.accepted_ip = accepted_ip[:64]
    if accepted_user_agent:
        inv.accepted_user_agent = accepted_user_agent[:500]

    from app.modules.audit.service import log_action
    from app.modules.auth.service import build_user_payload, issue_refresh_session

    user_payload = await build_user_payload(db, user)
    roles = user_payload["roles"]
    active_role = user_payload["role"]
    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "roles": roles,
        "active_role": active_role,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "active_role": active_role,
    })
    await issue_refresh_session(db, user, refresh_token, user_agent=accepted_user_agent, ip_address=accepted_ip)
    course_ids = list(
        (
            await db.execute(
                select(Enrollment.course_id)
                .join(Course, Course.id == Enrollment.course_id)
                .where(
                    Enrollment.tenant_id == user.tenant_id,
                    Enrollment.user_id == user.id,
                    Course.tenant_id == user.tenant_id,
                    Course.status == "published",
                )
                .order_by(Enrollment.enrolled_at.desc())
            )
        ).scalars().all()
    )
    await log_action(
        db,
        user.tenant_id,
        "invitation.accept.email_otp",
        "user_invitation",
        resource_id=str(inv.id),
        user_id=user.id,
        ip_address=accepted_ip,
        user_agent=accepted_user_agent,
    )
    await db.commit()

    next_url = f"/courses/{course_ids[0]}" if len(course_ids) == 1 else "/student"

    return {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "role": active_role,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user_payload,
        "next_url": next_url,
    }
