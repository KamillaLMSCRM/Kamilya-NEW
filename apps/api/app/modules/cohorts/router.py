from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortMember
from app.modules.cohorts.schemas import (
    CohortCreate,
    CohortDetail,
    CohortLinks,
    CohortMembers,
    CohortSummary,
    CohortUpdate,
    LearnerCohort,
)

router = APIRouter(prefix="/cohorts", tags=["cohorts"], dependencies=[Depends(require_tenant_user())])
MANAGER_ROLES = ("methodologist",)


async def _get(db: AsyncSession, cohort_id: UUID, tenant_id: UUID) -> Cohort:
    item = (
        await db.execute(select(Cohort).where(Cohort.id == cohort_id, Cohort.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return item


async def _summary(db: AsyncSession, item: Cohort) -> CohortSummary:
    members = (
        await db.scalar(
            select(func.count(CohortMember.id)).where(
                CohortMember.cohort_id == item.id, CohortMember.tenant_id == item.tenant_id
            )
        )
        or 0
    )
    return CohortSummary(
        id=item.id,
        name=item.name,
        description=item.description,
        is_active=item.is_active,
        member_count=members,
        created_at=item.created_at,
    )


async def _detail(db: AsyncSession, item: Cohort) -> CohortDetail:
    summary = await _summary(db, item)
    users = (
        (
            await db.execute(
                select(CohortMember.user_id).where(
                    CohortMember.cohort_id == item.id, CohortMember.tenant_id == item.tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    return CohortDetail(**summary.model_dump(), user_ids=list(users))


@router.get("", response_model=list[CohortSummary])
async def list_cohorts(db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    items = (
        (await db.execute(select(Cohort).where(Cohort.tenant_id == user.tenant_id).order_by(Cohort.created_at.desc())))
        .scalars()
        .all()
    )
    return [await _summary(db, item) for item in items]


@router.post("", response_model=CohortSummary, status_code=201)
async def create_cohort(
    payload: CohortCreate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))
):
    item = Cohort(
        tenant_id=user.tenant_id, created_by=user.id, name=payload.name.strip(), description=payload.description.strip()
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return await _summary(db, item)


@router.patch("/{cohort_id}", response_model=CohortSummary)
async def update_cohort(
    cohort_id: UUID,
    payload: CohortUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*MANAGER_ROLES)),
):
    item = await _get(db, cohort_id, user.tenant_id)
    if payload.name is not None:
        item.name = payload.name.strip()
    if payload.description is not None:
        item.description = payload.description.strip()
    if not item.name:
        raise HTTPException(status_code=422, detail="Cohort name cannot be empty")
    await db.commit()
    await db.refresh(item)
    return await _summary(db, item)


@router.put("/{cohort_id}/members", response_model=CohortSummary)
async def replace_members(
    cohort_id: UUID,
    payload: CohortMembers,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*MANAGER_ROLES)),
):
    item = await _get(db, cohort_id, user.tenant_id)
    if len(set(payload.user_ids)) != len(payload.user_ids):
        raise HTTPException(status_code=422, detail="Duplicate members are not allowed")
    valid_users = (
        set(
            (
                await db.execute(
                    select(User.id).where(
                        User.tenant_id == user.tenant_id,
                        User.id.in_(payload.user_ids),
                        User.role == "student",
                        User.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if payload.user_ids
        else set()
    )
    if valid_users != set(payload.user_ids):
        raise HTTPException(status_code=422, detail={"code": "members_outside_tenant"})
    await db.execute(
        delete(CohortMember).where(CohortMember.cohort_id == item.id, CohortMember.tenant_id == user.tenant_id)
    )
    for uid in payload.user_ids:
        db.add(CohortMember(tenant_id=user.tenant_id, cohort_id=item.id, user_id=uid))
    await db.commit()
    return await _summary(db, item)


@router.put("/{cohort_id}/links", response_model=CohortSummary, deprecated=True)
async def replace_links_legacy(
    cohort_id: UUID,
    payload: CohortLinks,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*MANAGER_ROLES)),
):
    """Compatibility alias for old clients; courses are no longer writable."""
    if payload.course_ids:
        raise HTTPException(
            status_code=410, detail={"code": "cohort_courses_deprecated", "use": f"/cohorts/{cohort_id}/members"}
        )
    response.headers["Deprecation"] = "true"
    response.headers["X-Kamilya-Deprecated"] = "Use /cohorts/{cohort_id}/members"
    return await replace_members(cohort_id, CohortMembers(user_ids=payload.user_ids), db, user)


@router.get("/my", response_model=list[LearnerCohort])
async def my_cohorts(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = await db.execute(
        select(Cohort)
        .join(CohortMember, CohortMember.cohort_id == Cohort.id)
        .where(
            Cohort.tenant_id == user.tenant_id,
            CohortMember.tenant_id == user.tenant_id,
            CohortMember.user_id == user.id,
            Cohort.is_active.is_(True),
        )
        .order_by(Cohort.created_at.desc())
    )
    return [
        LearnerCohort(id=cohort.id, name=cohort.name, description=cohort.description) for cohort in rows.scalars().all()
    ]


@router.get("/{cohort_id}", response_model=CohortDetail)
async def get_cohort(cohort_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    return await _detail(db, await _get(db, cohort_id, user.tenant_id))
