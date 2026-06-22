"""Positions — API router"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.modules.positions.models import Position
from app.modules.positions.schemas import PositionCreate, PositionResponse

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
    )
    db.add(pos)
    await db.flush()
    await db.refresh(pos)
    return pos
