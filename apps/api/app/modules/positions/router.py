"""Positions — API router with course attachment"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.modules.positions.models import Position, PositionCourse
from app.modules.positions.schemas import PositionCreate, PositionUpdate, PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])


async def _sync_courses(db: AsyncSession, position_id: uuid.UUID, course_ids: list[uuid.UUID] | None):
    """Replace all position_courses for a position."""
    if course_ids is None:
        return
    await db.execute(delete(PositionCourse).where(PositionCourse.position_id == position_id))
    for cid in course_ids:
        db.add(PositionCourse(position_id=position_id, course_id=cid))


async def _get_course_ids(db: AsyncSession, position_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(PositionCourse.course_id).where(PositionCourse.position_id == position_id)
    )
    return [row[0] for row in result.all()]


@router.get("", response_model=list[PositionResponse])
async def list_positions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position)
        .where(Position.tenant_id == user.tenant_id)
        .order_by(Position.created_at.desc())
    )
    positions = result.scalars().all()
    responses = []
    for pos in positions:
        course_ids = await _get_course_ids(db, pos.id)
        responses.append(PositionResponse(
            id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
            department=pos.department, level=pos.level,
            responsibilities=pos.responsibilities, requirements=pos.requirements,
            course_ids=course_ids, employee_count=pos.employee_count,
            created_at=pos.created_at,
        ))
    return responses


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    course_ids = await _get_course_ids(db, pos.id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids, employee_count=pos.employee_count,
        created_at=pos.created_at,
    )


@router.post("", response_model=PositionResponse, status_code=201)
async def create_position(
    req: PositionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pos = Position(
        tenant_id=user.tenant_id,
        name=req.name,
        department=req.department,
        level=req.level,
        responsibilities=req.responsibilities,
        requirements=req.requirements,
    )
    db.add(pos)
    await db.flush()

    if req.course_ids:
        await _sync_courses(db, pos.id, req.course_ids)
        await db.flush()

    course_ids = await _get_course_ids(db, pos.id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids, employee_count=pos.employee_count,
        created_at=pos.created_at,
    )


@router.put("/{position_id}", response_model=PositionResponse)
async def update_position(
    position_id: uuid.UUID,
    req: PositionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    for field, value in req.model_dump(exclude_unset=True, exclude={"course_ids"}).items():
        setattr(pos, field, value)

    if req.course_ids is not None:
        await _sync_courses(db, pos.id, req.course_ids)

    await db.flush()
    course_ids = await _get_course_ids(db, pos.id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids, employee_count=pos.employee_count,
        created_at=pos.created_at,
    )


@router.delete("/{position_id}", status_code=204)
async def delete_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    await db.delete(pos)


@router.post("/{position_id}/assign/{target_user_id}")
async def assign_user_to_position(
    position_id: uuid.UUID,
    target_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Assign a user to a position and auto-enroll them in all position courses."""
    from app.models.enrollment import Enrollment
    from uuid import uuid4 as uuid4_fn

    # Verify position exists
    pos_result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = pos_result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    # Verify target user exists
    target = await db.get(User, target_user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")

    # Assign position to user
    target.position_id = position_id

    # Update employee_count
    count_result = await db.execute(
        select(func.count(User.id)).where(
            User.position_id == position_id,
            User.tenant_id == user.tenant_id,
        )
    )
    pos.employee_count = count_result.scalar() or 0

    # Auto-enroll in all position courses
    course_ids = await _get_course_ids(db, position_id)
    enrolled_count = 0
    for cid in course_ids:
        existing = await db.execute(
            select(Enrollment).where(
                Enrollment.course_id == cid,
                Enrollment.user_id == target_user_id,
                Enrollment.tenant_id == user.tenant_id,
            )
        )
        if not existing.scalar_one_or_none():
            db.add(Enrollment(
                id=uuid4_fn(),
                course_id=cid,
                user_id=target_user_id,
                tenant_id=user.tenant_id,
                status="enrolled",
            ))
            enrolled_count += 1

    await db.flush()

    return {
        "status": "ok",
        "position": pos.name,
        "courses_attached": len(course_ids),
        "newly_enrolled": enrolled_count,
    }


@router.post("/unassign/{target_user_id}")
async def unassign_user_from_position(
    target_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a user from their position."""
    target = await db.get(User, target_user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")

    old_position_id = target.position_id
    target.position_id = None

    # Update old position employee_count
    if old_position_id:
        from sqlalchemy import func as sqlfunc
        count_result = await db.execute(
            select(sqlfunc.count(User.id)).where(
                User.position_id == old_position_id,
                User.tenant_id == user.tenant_id,
            )
        )
        pos = await db.get(Position, old_position_id)
        if pos:
            pos.employee_count = count_result.scalar() or 0

    await db.flush()
    return {"status": "ok"}
