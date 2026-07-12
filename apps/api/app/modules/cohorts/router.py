from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortCourse, CohortMember
from app.modules.cohorts.schemas import CohortApplyResult, CohortCreate, CohortDetail, CohortLinks, CohortProgress, CohortSummary, LearnerCohort

router = APIRouter(prefix="/cohorts", tags=["cohorts"], dependencies=[Depends(require_tenant_user())])
MANAGER_ROLES = ("admin", "org_admin", "methodologist", "teacher")


async def _get(db: AsyncSession, cohort_id: UUID, tenant_id: UUID) -> Cohort:
    item = (await db.execute(select(Cohort).where(Cohort.id == cohort_id, Cohort.tenant_id == tenant_id))).scalar_one_or_none()
    if not item: raise HTTPException(status_code=404, detail="Cohort not found")
    return item


async def _summary(db: AsyncSession, item: Cohort) -> CohortSummary:
    members = await db.scalar(select(func.count(CohortMember.id)).where(CohortMember.cohort_id == item.id, CohortMember.tenant_id == item.tenant_id)) or 0
    courses = await db.scalar(select(func.count(CohortCourse.id)).where(CohortCourse.cohort_id == item.id, CohortCourse.tenant_id == item.tenant_id)) or 0
    return CohortSummary(id=item.id, name=item.name, description=item.description, is_active=item.is_active, member_count=members, course_count=courses, created_at=item.created_at)


async def _detail(db: AsyncSession, item: Cohort) -> CohortDetail:
    summary = await _summary(db, item)
    users = (await db.execute(select(CohortMember.user_id).where(CohortMember.cohort_id == item.id, CohortMember.tenant_id == item.tenant_id))).scalars().all()
    courses = (await db.execute(select(CohortCourse.course_id).where(CohortCourse.cohort_id == item.id, CohortCourse.tenant_id == item.tenant_id))).scalars().all()
    return CohortDetail(**summary.model_dump(), user_ids=list(users), course_ids=list(courses))


@router.get("", response_model=list[CohortSummary])
async def list_cohorts(db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    items = (await db.execute(select(Cohort).where(Cohort.tenant_id == user.tenant_id).order_by(Cohort.created_at.desc()))).scalars().all()
    return [await _summary(db, item) for item in items]


@router.post("", response_model=CohortSummary, status_code=201)
async def create_cohort(payload: CohortCreate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = Cohort(tenant_id=user.tenant_id, created_by=user.id, name=payload.name.strip(), description=payload.description.strip())
    db.add(item); await db.flush(); await db.refresh(item); await db.commit()
    return await _summary(db, item)


@router.get("/{cohort_id}", response_model=CohortDetail)
async def get_cohort(cohort_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    return await _detail(db, await _get(db, cohort_id, user.tenant_id))


@router.put("/{cohort_id}/links", response_model=CohortSummary)
async def replace_links(cohort_id: UUID, payload: CohortLinks, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = await _get(db, cohort_id, user.tenant_id)
    if len(set(payload.user_ids)) != len(payload.user_ids) or len(set(payload.course_ids)) != len(payload.course_ids): raise HTTPException(status_code=422, detail="Duplicate links are not allowed")
    valid_users = set((await db.execute(select(User.id).where(User.tenant_id == user.tenant_id, User.id.in_(payload.user_ids)))).scalars().all()) if payload.user_ids else set()
    valid_courses = set((await db.execute(select(Course.id).where(Course.tenant_id == user.tenant_id, Course.id.in_(payload.course_ids)))).scalars().all()) if payload.course_ids else set()
    if valid_users != set(payload.user_ids) or valid_courses != set(payload.course_ids): raise HTTPException(status_code=422, detail={"code": "links_outside_tenant"})
    await db.execute(delete(CohortMember).where(CohortMember.cohort_id == item.id, CohortMember.tenant_id == user.tenant_id)); await db.execute(delete(CohortCourse).where(CohortCourse.cohort_id == item.id, CohortCourse.tenant_id == user.tenant_id))
    for uid in payload.user_ids: db.add(CohortMember(tenant_id=user.tenant_id, cohort_id=item.id, user_id=uid))
    for cid in payload.course_ids: db.add(CohortCourse(tenant_id=user.tenant_id, cohort_id=item.id, course_id=cid))
    await db.commit()
    return await _summary(db, item)


@router.post("/{cohort_id}/apply", response_model=CohortApplyResult)
async def apply_cohort(cohort_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = await _get(db, cohort_id, user.tenant_id)
    user_ids = list((await db.execute(select(CohortMember.user_id).where(CohortMember.cohort_id == item.id, CohortMember.tenant_id == user.tenant_id))).scalars().all())
    course_ids = list((await db.execute(select(CohortCourse.course_id).where(CohortCourse.cohort_id == item.id, CohortCourse.tenant_id == user.tenant_id))).scalars().all())
    existing = {(row.user_id, row.course_id) for row in (await db.execute(select(Enrollment.user_id, Enrollment.course_id).where(Enrollment.tenant_id == user.tenant_id, Enrollment.user_id.in_(user_ids), Enrollment.course_id.in_(course_ids)))).all()} if user_ids and course_ids else set()
    added = 0
    for user_id in user_ids:
        for course_id in course_ids:
            if (user_id, course_id) in existing: continue
            db.add(Enrollment(user_id=user_id, course_id=course_id, tenant_id=user.tenant_id, status="enrolled", source="cohort")); added += 1
    await db.commit()
    return CohortApplyResult(cohort_id=item.id, members=len(user_ids), courses=len(course_ids), added=added, skipped_existing=len(user_ids) * len(course_ids) - added)


@router.get("/{cohort_id}/progress", response_model=CohortProgress)
async def cohort_progress(cohort_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = await _get(db, cohort_id, user.tenant_id)
    user_ids = list((await db.execute(select(CohortMember.user_id).where(CohortMember.cohort_id == item.id, CohortMember.tenant_id == user.tenant_id))).scalars().all())
    course_ids = list((await db.execute(select(CohortCourse.course_id).where(CohortCourse.cohort_id == item.id, CohortCourse.tenant_id == user.tenant_id))).scalars().all())
    rows = (await db.execute(select(Enrollment.status, func.count(Enrollment.id)).where(Enrollment.tenant_id == user.tenant_id, Enrollment.user_id.in_(user_ids), Enrollment.course_id.in_(course_ids)).group_by(Enrollment.status))).all() if user_ids and course_ids else []
    counts = {status: count for status, count in rows}; total = sum(counts.values()); completed = counts.get("completed", 0); assigned = counts.get("enrolled", 0); in_progress = max(total - completed - assigned, 0)
    return CohortProgress(cohort_id=item.id, total_assignments=total, assigned=assigned, in_progress=in_progress, completed=completed)


@router.get("/my", response_model=list[LearnerCohort])
async def my_cohorts(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = await db.execute(select(Cohort, CohortCourse.course_id).join(CohortMember, CohortMember.cohort_id == Cohort.id).outerjoin(CohortCourse, CohortCourse.cohort_id == Cohort.id).where(Cohort.tenant_id == user.tenant_id, CohortMember.tenant_id == user.tenant_id, CohortMember.user_id == user.id, Cohort.is_active.is_(True)))
    grouped: dict[UUID, LearnerCohort] = {}
    for cohort, course_id in rows.all():
        if cohort.id not in grouped: grouped[cohort.id] = LearnerCohort(id=cohort.id, name=cohort.name, description=cohort.description, course_ids=[])
        if course_id and course_id not in grouped[cohort.id].course_ids: grouped[cohort.id].course_ids.append(course_id)
    return list(grouped.values())
