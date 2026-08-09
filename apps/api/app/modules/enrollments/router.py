"""Enrollments — API router"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.enrollments.schemas import (
    AssignmentAccessExchangeRequest,
    AssignmentAccessExchangeResponse,
    AssignmentAccessIssueResponse,
    EnrollmentAccessResponse,
    EnrollmentCreate,
    EnrollmentNotificationResponse,
    EnrollmentResponse,
)
from app.modules.enrollments.service import (
    enroll_users,
    get_course_enrollment_stats,
    get_enrolled_users,
    get_enrollment_access,
    resend_enrollment_notification,
    self_enroll,
    unenroll,
)

router = APIRouter(
    prefix="/courses",
    tags=["enrollments"],
    dependencies=[Depends(require_tenant_user())],
)
public_access_router = APIRouter(prefix="/assignment-access", tags=["assignment-access"])

stats_router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@stats_router.get("/stats")
async def global_enrollment_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Global enrollment statistics for dashboard."""
    total_result = await db.execute(select(func.count(Enrollment.id)).where(Enrollment.tenant_id == user.tenant_id))
    total = total_result.scalar() or 0

    completed_result = await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.tenant_id == user.tenant_id,
            Enrollment.status == "completed",
        )
    )
    completed = completed_result.scalar() or 0

    return {"total": total, "completed": completed}


# Direct user→course assignment is a learning-content/methodologist
# concern (TZ_COURSE_ASSIGNMENT_ACCESS_v1 §1.2 level-4 manual override),
# not tenant administration. Tenant admins manage org/team structure;
# methodologist manages learning trajectories. Students keep the
# self-enrollment path below; everyone else is rejected.

_ENROLLMENT_MANAGER_ROLES = ("methodologist",)


@router.get("/{course_id}/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    try:
        return await get_enrolled_users(db, course_id, user.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{course_id}/enrollments", response_model=list[EnrollmentResponse], status_code=201)
async def create_enrollments(
    course_id: UUID,
    req: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    try:
        enrollments = await enroll_users(db, course_id, user.tenant_id, req.user_ids, assigned_by=user.id)
        await db.commit()
        from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

        for enrollment in enrollments:
            notification_id = getattr(enrollment, "notification_outbox_id", None)
            if notification_id is not None:
                try:
                    deliver_assignment_notification_task.apply_async(args=[str(user.tenant_id), str(notification_id)])
                except Exception:
                    # The committed outbox remains recoverable by the timer.
                    pass
        return enrollments
    except ValueError as exc:
        status_code = 409 if "published" in str(exc) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/enrollments/{enrollment_id}/access", response_model=EnrollmentAccessResponse)
async def enrollment_access(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    """Retrieve assignment access without coupling it to assignment creation."""
    from app.core.config import get_settings

    access = await get_enrollment_access(
        db,
        enrollment_id,
        user.tenant_id,
        base_url=getattr(get_settings(), "PUBLIC_URL", None),
    )
    if access is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return access


@router.post(
    "/enrollments/{enrollment_id}/notification/resend",
    response_model=EnrollmentNotificationResponse,
)
async def resend_assignment_notification(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    notification_id = await resend_enrollment_notification(db, tenant_id=user.tenant_id, enrollment_id=enrollment_id)
    if notification_id is None:
        raise HTTPException(status_code=404, detail="Assignment notification not found")
    from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

    try:
        deliver_assignment_notification_task.apply_async(args=[str(user.tenant_id), str(notification_id)])
    except Exception:
        pass
    return EnrollmentNotificationResponse(enrollment_id=enrollment_id, notification_id=notification_id)


@router.post("/enrollments/{enrollment_id}/access-without-email", response_model=AssignmentAccessIssueResponse)
async def issue_access_without_email(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    from app.core.config import get_settings
    from app.modules.enrollments.access_service import issue_assignment_access

    issued = await issue_assignment_access(
        db, enrollment_id, user.tenant_id, getattr(get_settings(), "PUBLIC_URL", None)
    )
    if issued is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return issued


@public_access_router.post("/{token}/exchange", response_model=AssignmentAccessExchangeResponse)
async def exchange_access_without_email(
    token: str, payload: AssignmentAccessExchangeRequest, db: AsyncSession = Depends(get_db)
):
    from app.modules.enrollments.access_service import establish_assignment_access_context, exchange_assignment_access

    tenant_id = await establish_assignment_access_context(db, token)
    if tenant_id is None:
        # Do not distinguish random, expired, revoked, or cross-tenant links.
        raise HTTPException(status_code=404, detail="Access link not found")
    from sqlalchemy import text

    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
    result = await exchange_assignment_access(db, token, payload.pin)
    if result is None:
        raise HTTPException(status_code=401, detail="Access link or PIN is invalid")
    return result


@router.post("/{course_id}/enroll", response_model=EnrollmentResponse, status_code=201)
async def enroll_self(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Self-enrollment — student enrolls themselves in a course."""
    try:
        return await self_enroll(db, course_id, user.id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/enrollments/{enrollment_id}", status_code=204)
async def remove_enrollment(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    try:
        await unenroll(db, enrollment_id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{course_id}/enrollment-stats")
async def enrollment_stats(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    """Get enrollment statistics for a course."""
    return await get_course_enrollment_stats(db, course_id, user.tenant_id)
