from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.core.email import EmailService
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.announcements.models import Announcement
from app.modules.announcements.schemas import AnnouncementCreate, AnnouncementSendResult, AnnouncementSummary

router = APIRouter(prefix="/announcements", tags=["announcements"], dependencies=[Depends(require_tenant_user())])
MANAGER_ROLES = ("methodologist",)


def _summary(item: Announcement) -> AnnouncementSummary:
    return AnnouncementSummary(id=item.id, title=item.title, body=item.body, course_id=item.course_id, status=item.status, recipients_count=item.recipients_count, sent_count=item.sent_count, failed_count=item.failed_count, sent_at=item.sent_at, created_at=item.created_at)


async def _get(db: AsyncSession, announcement_id: UUID, tenant_id: UUID) -> Announcement:
    item = (await db.execute(select(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == tenant_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return item


@router.get("", response_model=list[AnnouncementSummary])
async def list_announcements(db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    result = await db.execute(select(Announcement).where(Announcement.tenant_id == user.tenant_id).order_by(Announcement.created_at.desc()))
    return [_summary(item) for item in result.scalars().all()]


@router.post("", response_model=AnnouncementSummary, status_code=201)
async def create_announcement(payload: AnnouncementCreate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    if payload.course_id:
        course = (await db.execute(select(Course).where(Course.id == payload.course_id, Course.tenant_id == user.tenant_id))).scalar_one_or_none()
        if not course:
            raise HTTPException(status_code=422, detail={"code": "course_outside_tenant"})
    item = Announcement(tenant_id=user.tenant_id, created_by=user.id, course_id=payload.course_id, title=payload.title.strip(), body=payload.body.strip())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return _summary(item)


@router.post("/{announcement_id}/send", response_model=AnnouncementSendResult)
async def send_announcement(announcement_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = await _get(db, announcement_id, user.tenant_id)
    if item.status in ("sent", "partial"):
        raise HTTPException(status_code=409, detail="Announcement has already been sent")
    tenant = (await db.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))).scalar_one_or_none() or "Kamilya LMS"
    course_title = None
    if item.course_id:
        course_title = (await db.execute(select(Course.title).where(Course.id == item.course_id, Course.tenant_id == user.tenant_id))).scalar_one_or_none()
    query = select(User.email).join(Enrollment, Enrollment.user_id == User.id).where(User.tenant_id == user.tenant_id, User.is_active.is_(True), User.email.is_not(None))
    if item.course_id:
        query = query.where(Enrollment.course_id == item.course_id)
    emails = sorted({email.strip().lower() for email in (await db.execute(query)).scalars().all() if email and email.strip()})
    sent = failed = 0
    service = EmailService()
    for email in emails:
        try:
            await service.send_announcement(to_email=email, company_name=tenant, title=item.title, body=item.body, course_title=course_title)
            sent += 1
        except Exception:
            failed += 1
    item.recipients_count = len(emails)
    item.sent_count = sent
    item.failed_count = failed
    item.status = "sent" if failed == 0 else "partial"
    item.sent_at = datetime.now(timezone.utc)
    item.result = {"delivery": "resend_or_log", "course_id": str(item.course_id) if item.course_id else None}
    await db.commit()
    return AnnouncementSendResult(announcement=_summary(item), sent_count=sent, failed_count=failed)
