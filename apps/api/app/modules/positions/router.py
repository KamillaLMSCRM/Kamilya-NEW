"""Positions — API router"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.modules.positions.models import Position
from app.modules.positions.schemas import PositionCreate, PositionUpdate, PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])


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
    return result.scalars().all()


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
    return pos


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
    await db.refresh(pos)
    return pos


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

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(pos, field, value)

    await db.flush()
    await db.refresh(pos)
    return pos


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
