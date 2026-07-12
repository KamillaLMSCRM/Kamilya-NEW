from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortCourse, CohortMember
from app.modules.cohorts.schemas import CohortCreate, CohortLinks, CohortSummary, LearnerCohort

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


@router.get("", response_model=list[CohortSummary])
async def list_cohorts(db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    items = (await db.execute(select(Cohort).where(Cohort.tenant_id == user.tenant_id).order_by(Cohort.created_at.desc()))).scalars().all()
    return [await _summary(db, item) for item in items]


@router.post("", response_model=CohortSummary, status_code=201)
async def create_cohort(payload: CohortCreate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = Cohort(tenant_id=user.tenant_id, created_by=user.id, name=payload.name.strip(), description=payload.description.strip())
    db.add(item); await db.flush(); await db.refresh(item); await db.commit()
    return await _summary(db, item)


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


@router.get("/my", response_model=list[LearnerCohort])
async def my_cohorts(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = await db.execute(select(Cohort, CohortCourse.course_id).join(CohortMember, CohortMember.cohort_id == Cohort.id).outerjoin(CohortCourse, CohortCourse.cohort_id == Cohort.id).where(Cohort.tenant_id == user.tenant_id, CohortMember.tenant_id == user.tenant_id, CohortMember.user_id == user.id, Cohort.is_active.is_(True)))
    grouped: dict[UUID, LearnerCohort] = {}
    for cohort, course_id in rows.all():
        if cohort.id not in grouped: grouped[cohort.id] = LearnerCohort(id=cohort.id, name=cohort.name, description=cohort.description, course_ids=[])
        if course_id and course_id not in grouped[cohort.id].course_ids: grouped[cohort.id].course_ids.append(course_id)
    return list(grouped.values())
