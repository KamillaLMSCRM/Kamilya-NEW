from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.modules.competencies.models import Competency, CompetencyCourse, PositionCompetency
from app.modules.competencies.schemas import CompetencyCreate, CompetencyDetail, CompetencyLinks, CompetencySummary, CompetencyUpdate
from app.modules.positions.models import Position

router = APIRouter(prefix="/competencies", tags=["competencies"], dependencies=[Depends(require_tenant_user())])
MANAGER_ROLES = ("admin", "org_admin", "methodologist", "teacher")


async def _get(db: AsyncSession, competency_id: UUID, tenant_id: UUID) -> Competency:
    result = await db.execute(
        select(Competency).options(selectinload(Competency.position_links), selectinload(Competency.course_links))
        .where(Competency.id == competency_id, Competency.tenant_id == tenant_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Competency not found")
    return item


def _summary(item: Competency) -> CompetencySummary:
    return CompetencySummary(id=item.id, name=item.name, description=item.description, created_at=item.created_at, position_count=len(item.position_links), course_count=len(item.course_links))


def _detail(item: Competency) -> CompetencyDetail:
    return CompetencyDetail(**_summary(item).model_dump(), position_ids=[link.position_id for link in item.position_links], course_ids=[link.course_id for link in item.course_links])


@router.get("", response_model=list[CompetencySummary])
async def list_competencies(db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    result = await db.execute(select(Competency).options(selectinload(Competency.position_links), selectinload(Competency.course_links)).where(Competency.tenant_id == user.tenant_id).order_by(Competency.name))
    return [_summary(item) for item in result.scalars().unique().all()]


@router.post("", response_model=CompetencyDetail, status_code=201)
async def create_competency(payload: CompetencyCreate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = Competency(tenant_id=user.tenant_id, name=payload.name.strip(), description=payload.description.strip())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return CompetencyDetail(id=item.id, name=item.name, description=item.description, created_at=item.created_at, position_count=0, course_count=0, position_ids=[], course_ids=[])


@router.get("/{competency_id}", response_model=CompetencyDetail)
async def get_competency(competency_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    return _detail(await _get(db, competency_id, user.tenant_id))


@router.patch("/{competency_id}", response_model=CompetencyDetail)
async def update_competency(competency_id: UUID, payload: CompetencyUpdate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = await _get(db, competency_id, user.tenant_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    await db.commit()
    return _detail(await _get(db, competency_id, user.tenant_id))


@router.put("/{competency_id}/links", response_model=CompetencyDetail)
async def replace_links(competency_id: UUID, payload: CompetencyLinks, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    item = await _get(db, competency_id, user.tenant_id)
    if len(set(payload.position_ids)) != len(payload.position_ids) or len(set(payload.course_ids)) != len(payload.course_ids):
        raise HTTPException(status_code=422, detail="Duplicate links are not allowed")
    valid_positions = set((await db.execute(select(Position.id).where(Position.tenant_id == user.tenant_id, Position.id.in_(payload.position_ids)))).scalars().all()) if payload.position_ids else set()
    valid_courses = set((await db.execute(select(Course.id).where(Course.tenant_id == user.tenant_id, Course.id.in_(payload.course_ids)))).scalars().all()) if payload.course_ids else set()
    if valid_positions != set(payload.position_ids) or valid_courses != set(payload.course_ids):
        raise HTTPException(status_code=422, detail={"code": "links_outside_tenant"})
    await db.execute(delete(PositionCompetency).where(PositionCompetency.competency_id == item.id, PositionCompetency.tenant_id == user.tenant_id))
    await db.execute(delete(CompetencyCourse).where(CompetencyCourse.competency_id == item.id, CompetencyCourse.tenant_id == user.tenant_id))
    for position_id in payload.position_ids:
        db.add(PositionCompetency(tenant_id=user.tenant_id, position_id=position_id, competency_id=item.id))
    for course_id in payload.course_ids:
        db.add(CompetencyCourse(tenant_id=user.tenant_id, competency_id=item.id, course_id=course_id))
    await db.commit()
    return _detail(await _get(db, competency_id, user.tenant_id))
