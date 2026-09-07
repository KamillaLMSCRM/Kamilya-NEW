"""Persistence operations for the singleton generation route."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.model_routing.models import GenerationModelRouting


async def get_routing(
    db: AsyncSession,
    *,
    for_update: bool = False,
) -> GenerationModelRouting | None:
    statement = select(GenerationModelRouting).where(GenerationModelRouting.id == 1)
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()
