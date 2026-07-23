"""Kiosk links service — identify workers by personnel_number, list their courses.

Stage 1b of employee onboarding epic.

Public flow (no auth):
1. HR creates kiosk link → gets URL (e.g. https://app.kml.kz/kiosk/abc123)
2. HR prints URL as QR code, posts on workshop wall
3. Worker scans → sees kiosk page
4. Worker enters their personnel_number → POST /kiosks/{token}/identify
5. Server returns: user identity (first/last name, position, dept), list of
   assigned courses with progress (from position_courses + enrollments)
6. Worker clicks a course → opens existing course player (reused)
7. Worker takes quiz → existing QuizAttempt flow records attempt

Audit:
- Identify attempts (success + fail) logged via print for now
- Could extend to a kiosk_audit table later if compliance demands
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import create_access_token
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.positions.models import Position, PositionCourse

# Per TZ §3.5: kiosk JWTs are short-lived (15-30 min) so a worker
# closing the tab on a shared device doesn't leave a session
# open for the next user. 20 min sits in the middle of the
# window and gives enough time to actually watch a course.
KIOSK_JWT_TTL_MINUTES = 20

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────


def _generate_kiosk_token() -> str:
    """24-char URL-safe token. ~144 bits entropy (still infeasible to brute force)."""
    return secrets.token_urlsafe(16)


async def establish_public_kiosk_tenant_context(
    db: AsyncSession,
    token: str,
) -> UUID | None:
    """Resolve an opaque kiosk token, then enable normal tenant RLS.

    Public kiosk requests have no JWT and therefore no tenant context. The
    database function exposes only the matching tenant UUID; all subsequent
    reads still run through the regular tenant policies.
    """
    result = await db.execute(
        text("SELECT lookup_kiosk_tenant_by_token(:token)"),
        {"token": token},
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        return None
    await db.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant_id)},
    )
    return tenant_id


# ── Admin CRUD ──────────────────────────────────────────────────


async def create_kiosk_link(
    db: AsyncSession,
    tenant_id: UUID,
    created_by: UUID,
    name: str,
    location: str | None = None,
    scope_position_id: UUID | None = None,
    expires_at: datetime | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a new kiosk link for the tenant.

    Returns {id, name, token, kiosk_url, ...}.
    """
    token = _generate_kiosk_token()
    kiosk_id = uuid4()

    from app.models.kiosk_link import KioskLink  # local import to avoid circular

    link = KioskLink(
        id=kiosk_id,
        tenant_id=tenant_id,
        name=name.strip(),
        token=token,
        location=(location or "").strip() or None,
        scope_position_id=scope_position_id,
        is_active=True,
        created_by=created_by,
        expires_at=expires_at,
    )
    db.add(link)
    # Keep the request transaction open. Tenant RLS context is installed with
    # transaction-local set_config() during authentication, so committing here
    # would clear it before the router builds the response. The request-scoped
    # get_db dependency performs the final commit.
    await db.flush()

    base = (base_url or "https://app.kml.kz").rstrip("/")
    return {
        "id": link.id,
        "name": link.name,
        "token": link.token,
        "kiosk_url": f"{base}/kiosk/{link.token}",
        "location": link.location,
        "scope_position_id": link.scope_position_id,
        "is_active": link.is_active,
        "expires_at": link.expires_at,
        "created_at": link.created_at,
    }


async def list_kiosk_links(db: AsyncSession, tenant_id: UUID) -> list:
    """List all kiosk links for the tenant, newest first."""
    from app.models.kiosk_link import KioskLink

    result = await db.execute(
        select(KioskLink)
        .where(KioskLink.tenant_id == tenant_id)
        .order_by(KioskLink.created_at.desc())
    )
    return result.scalars().all()


async def get_kiosk_link(db: AsyncSession, tenant_id: UUID, kiosk_id: UUID):
    from app.models.kiosk_link import KioskLink
    link = await db.get(KioskLink, kiosk_id)
    if not link or link.tenant_id != tenant_id:
        return None
    return link


async def update_kiosk_link(
    db: AsyncSession,
    tenant_id: UUID,
    kiosk_id: UUID,
    patch: dict,
):
    from app.models.kiosk_link import KioskLink
    link = await db.get(KioskLink, kiosk_id)
    if not link or link.tenant_id != tenant_id:
        return None
    for k, v in patch.items():
        if hasattr(link, k):
            setattr(link, k, v)
    await db.commit()
    await db.refresh(link)
    return link


async def delete_kiosk_link(db: AsyncSession, tenant_id: UUID, kiosk_id: UUID) -> bool:
    from app.models.kiosk_link import KioskLink
    link = await db.get(KioskLink, kiosk_id)
    if not link or link.tenant_id != tenant_id:
        return False
    await db.delete(link)
    await db.commit()
    return True


async def list_kiosk_access_logs(db: AsyncSession, tenant_id: UUID, kiosk_id: UUID | None = None, limit: int = 50) -> list:
    from app.models.kiosk_link import KioskAccessLog, KioskLink

    query = (
        select(KioskAccessLog, KioskLink.name)
        .join(KioskLink, KioskAccessLog.kiosk_id == KioskLink.id)
        .where(KioskAccessLog.tenant_id == tenant_id)
        .order_by(KioskAccessLog.created_at.desc())
        .limit(limit)
    )
    if kiosk_id:
        query = query.where(KioskAccessLog.kiosk_id == kiosk_id)
    result = await db.execute(query)
    rows = []
    for log, kiosk_name in result.all():
        rows.append({
            "id": log.id,
            "kiosk_id": log.kiosk_id,
            "kiosk_name": kiosk_name,
            "user_id": log.user_id,
            "personnel_number": log.personnel_number,
            "success": log.success,
            "reason": log.reason,
            "ip_address": log.ip_address,
            "created_at": log.created_at,
        })
    return rows


async def _record_kiosk_access(
    db: AsyncSession,
    link,
    personnel_number: str,
    success: bool,
    reason: str | None = None,
    user_id: UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    from app.models.kiosk_link import KioskAccessLog

    db.add(KioskAccessLog(
        tenant_id=link.tenant_id,
        kiosk_id=link.id,
        user_id=user_id,
        personnel_number=personnel_number[:128] if personnel_number else None,
        success=success,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent[:500] if user_agent else None,
    ))


# ── Public kiosk flow (no auth) ──────────────────────────────────


async def get_public_kiosk(db: AsyncSession, token: str) -> dict:
    """Resolve token → {name, tenant_name, scope_position_name, valid, reason_if_invalid}.

    No auth — anyone with the kiosk URL can view. Used by /kiosk/{token} page.
    """
    from app.models.kiosk_link import KioskLink

    result = await db.execute(select(KioskLink).where(KioskLink.token == token))
    link = result.scalar_one_or_none()
    if not link:
        return {
            "name": "",
            "tenant_name": "",
            "scope_position_name": None,
            "location": None,
            "valid": False,
            "reason_if_invalid": "kiosk_not_found",
        }

    # Tenant name
    from app.models.tenants import Tenant
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == link.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    tenant_name = tenant.name if tenant else ""

    # Scope position name (if scoped)
    pos_name = None
    if link.scope_position_id:
        pos_result = await db.execute(
            select(Position).where(Position.id == link.scope_position_id)
        )
        pos = pos_result.scalar_one_or_none()
        pos_name = pos.name if pos else None

    # Validity checks
    if not link.is_active:
        return {
            "name": link.name,
            "tenant_name": tenant_name,
            "scope_position_name": pos_name,
            "location": link.location,
            "valid": False,
            "reason_if_invalid": "kiosk_disabled",
        }
    if link.expires_at and link.expires_at < datetime.now(timezone.utc):
        return {
            "name": link.name,
            "tenant_name": tenant_name,
            "scope_position_name": pos_name,
            "location": link.location,
            "valid": False,
            "reason_if_invalid": "kiosk_expired",
        }

    return {
        "name": link.name,
        "tenant_name": tenant_name,
        "scope_position_name": pos_name,
        "location": link.location,
        "valid": True,
        "reason_if_invalid": None,
    }


async def identify_at_kiosk(
    db: AsyncSession,
    token: str,
    personnel_number: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Worker enters their personnel_number → server returns identity + assigned courses.

    Used by kiosk page after worker types their tab number.

    Returns {user: {...}, courses: [{course_id, title, status, progress_percent}]}

    Raises HTTPException on failure.
    """
    from app.models.kiosk_link import KioskLink

    pn = personnel_number.strip()
    if not pn:
        raise HTTPException(status_code=422, detail="Введите табельный номер")

    # Resolve kiosk
    result = await db.execute(select(KioskLink).where(KioskLink.token == token))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Киоск не найден")
    if not link.is_active:
        raise HTTPException(status_code=410, detail="Киоск отключён")
    if link.expires_at and link.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Срок действия киоска истёк")

    # Find user by personnel_number (case-insensitive) within tenant
    user_result = await db.execute(
        select(User).where(
            User.tenant_id == link.tenant_id,
            User.personnel_number.ilike(pn),
        )
    )
    user = user_result.scalar_one_or_none()
    if not user:
        # Don't leak whether the user exists in another tenant
        logger.info(f"kiosk identify failed: pn={pn} not found in tenant {link.tenant_id}")
        await _record_kiosk_access(db, link, pn, False, "personnel_number_not_found", None, ip_address, user_agent)
        await db.commit()
        raise HTTPException(
            status_code=404,
            detail="Табельный номер не найден. Обратитесь к HR.",
        )

    if not user.is_active or user.status != "active":
        logger.info(f"kiosk identify: user {user.id} inactive")
        await _record_kiosk_access(db, link, pn, False, "user_inactive", user.id, ip_address, user_agent)
        await db.commit()
        raise HTTPException(status_code=403, detail="Учётная запись не активна. Обратитесь к HR.")

    # Check kiosk scope (if scoped to a position, user must have that position)
    if link.scope_position_id:
        if str(user.position_id) != str(link.scope_position_id):
            logger.info(f"kiosk identify: user {user.id} position mismatch")
            await _record_kiosk_access(db, link, pn, False, "position_mismatch", user.id, ip_address, user_agent)
            await db.commit()
            raise HTTPException(
                status_code=403,
                detail="Этот киоск не для вашей должности. Обратитесь к HR.",
            )

    # Get user's assigned courses via position_courses + direct enrollments
    course_ids: set[UUID] = set()
    if user.position_id:
        pc_result = await db.execute(
            select(PositionCourse.course_id).where(PositionCourse.position_id == user.position_id)
        )
        course_ids.update(row[0] for row in pc_result.all())

    # Direct enrollments too (in case of course assigned ad-hoc)
    enr_result = await db.execute(
        select(Enrollment.course_id).where(
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == link.tenant_id,
        )
    )
    course_ids.update(row[0] for row in enr_result.all())

    # Enrollment.status remains "enrolled" while lesson progress is recorded.
    # Treat any completed lesson as a started course so the kiosk resume badge
    # matches the course player.
    started_course_ids: set[UUID] = set()
    if course_ids:
        from app.models.progress import Progress

        progress_result = await db.execute(
            select(Progress.course_id)
            .where(
                Progress.tenant_id == link.tenant_id,
                Progress.user_id == user.id,
                Progress.course_id.in_(course_ids),
                Progress.completed.is_(True),
            )
            .distinct()
        )
        started_course_ids.update(row[0] for row in progress_result.all())

    # Fetch course details
    # Importing Course triggers SQLAlchemy to resolve the "Module" relationship string
    # in Course's model, so we also import Module to make sure it's registered.
    from app.modules.courses.models import Course
    from app.modules.lessons.models import Module  # noqa: F401  (registers Module for Course.relationship)
    courses_data: list[dict] = [] 
    if course_ids:
        course_result = await db.execute(
            select(Course).where(Course.id.in_(course_ids))
        )
        courses = course_result.scalars().all()
        for c in courses:
            # Get enrollment status
            enr_status_result = await db.execute(
                select(Enrollment).where(
                    Enrollment.user_id == user.id,
                    Enrollment.course_id == c.id,
                )
            )
            enr = enr_status_result.scalar_one_or_none()
            status = "not_started"
            if enr:
                if enr.completed_at:
                    status = "completed"
                elif enr.status != "enrolled" or c.id in started_course_ids:
                    status = "in_progress"

            courses_data.append({
                "course_id": str(c.id),
                "title": c.title,
                "description": (c.description or "")[:200],
                "status": status,
            })

    # Sort: in_progress first, then not_started, then completed
    status_order = {"in_progress": 0, "not_started": 1, "completed": 2}
    courses_data.sort(key=lambda x: (status_order.get(x["status"], 9), x["title"]))

    # Get position name for display
    pos_name = None
    if user.position_id:
        pos_result = await db.execute(select(Position).where(Position.id == user.position_id))
        pos = pos_result.scalar_one_or_none()
        pos_name = pos.name if pos else None

    logger.info(f"kiosk identify: user {user.id} ({pn}) identified at kiosk {link.id}")

    # Per TZ §3.5: issue a short-lived JWT so the worker can
    # actually open courses. Without this, identify returns
    # identity + course list but the course player (which
    # requires auth) bounces the worker back to login. The
    # token is short-lived (KIOSK_JWT_TTL_MINUTES) to protect
    # shared devices: when the worker closes the tab, the
    # next user must re-identify with their own tab number.
    # `auth_method="kiosk"` is recorded in the token payload
    # so audit logs can distinguish kiosk sessions from
    # magic-link / telegram sessions.
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "role": user.role,
            "auth_method": "kiosk",
        },
        expires_delta=timedelta(minutes=KIOSK_JWT_TTL_MINUTES),
    )
    await _record_kiosk_access(db, link, pn, True, None, user.id, ip_address, user_agent)
    await db.commit()

    return {
        "user": {
            "user_id": str(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "personnel_number": user.personnel_number,
            "position_name": pos_name,
        },
        "kiosk_name": link.name,
        "kiosk_location": link.location,
        "courses": courses_data,
        "access_token": access_token,
        "token_type": "bearer",
    }
