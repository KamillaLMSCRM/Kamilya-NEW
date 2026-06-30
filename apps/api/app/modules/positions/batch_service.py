"""Batch wrappers around recompute_enrollments.

These functions are the bridge between rule mutations and the
recompute kernel. They exist so a single call (e.g. "attach this
course to this department") propagates correctly to every affected
user without each caller having to do the per-user fan-out itself.

Three functions:
  - recompute_position_holders(position_id) — every User with
    position_id == position_id is recomputed. Triggered by
    update_position when course_ids change.
  - recompute_department_members(department_id) — every holder of
    every position in the department. Triggered by
    attach/detach course to department.
  - apply_rules_for_users(user_ids, actor_id) — batch wrapper, used
    by Celery after staff import and as the explicit
    /admin/staff/apply-rules endpoint.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.modules.positions.assignment_service import (
    RecomputeResult,
    recompute_enrollments,
)
from app.modules.positions.models import Position

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Aggregate outcome across many recompute calls."""

    users_processed: int = 0
    added: int = 0
    removed: int = 0
    skipped_manual: int = 0
    protected_completed: int = 0

    def merge(self, other: RecomputeResult) -> None:
        self.users_processed += 1
        self.added += other.added
        self.removed += other.removed
        self.skipped_manual += other.skipped_manual
        self.protected_completed += other.protected_completed

    def to_dict(self) -> dict:
        return {
            "users_processed": self.users_processed,
            "added": self.added,
            "removed": self.removed,
            "skipped_manual": self.skipped_manual,
            "protected_completed": self.protected_completed,
        }


async def recompute_position_holders(
    db: AsyncSession,
    position_id: UUID,
    tenant_id: UUID,
) -> BatchResult:
    """Recompute enrollments for every user whose position_id is this.

    Returns the aggregate. Each per-user recompute may add/remove rows;
    we commit the transaction boundary to the caller (no commit here).
    """
    result = BatchResult()
    holder_result = await db.execute(
        select(User.id).where(
            User.position_id == position_id,
            User.tenant_id == tenant_id,
        )
    )
    holder_ids = list(holder_result.scalars().all())
    for user_id in holder_ids:
        outcome = await recompute_enrollments(db, user_id)
        result.merge(outcome)
    return result


async def recompute_department_members(
    db: AsyncSession,
    department_id: UUID,
    tenant_id: UUID,
) -> BatchResult:
    """Recompute enrollments for every user who holds a position
    in this department.
    """
    result = BatchResult()
    pos_result = await db.execute(
        select(Position.id).where(
            Position.department_id == department_id,
            Position.tenant_id == tenant_id,
        )
    )
    # Pre-existing bug fixed 2026-06-30: `pos_result.scalars().all()`
    # on a single-column SELECT returns native `asyncpg.UUID` objects
    # (not Row objects and not `uuid.UUID`). Iterating with `row[0]`
    # then tried UUID[0] and raised
    #   TypeError: 'asyncpg.pgproto.pgproto.UUID' object is not subscriptable
    # The bug was dormant because legacy Excel-imported tenants had
    # `Position.department_id = NULL` for every row, so the earlier
    # `if not position_ids: return result` short-circuit masked it.
    # After the slug-or-UUID fix backfills Position.department_id,
    # recompute actually iterates — and crashed.
    # Fix: take scalars() as-is (already UUID values, not Rows).
    position_ids = list(pos_result.scalars().all())
    if not position_ids:
        return result

    user_result = await db.execute(
        select(User.id).where(
            User.position_id.in_(position_ids),
            User.tenant_id == tenant_id,
        )
    )
    user_ids = list(user_result.scalars().all())
    for user_id in user_ids:
        outcome = await recompute_enrollments(db, user_id)
        result.merge(outcome)
    return result


async def apply_rules_for_users(
    db: AsyncSession,
    user_ids: Sequence[UUID],
) -> BatchResult:
    """Run recompute for a list of users. Used by Celery task and the
    /admin/staff/apply-rules endpoint. Idempotent.

    Logs the aggregate so Celery task result is informative.
    """
    result = BatchResult()
    for user_id in user_ids:
        outcome = await recompute_enrollments(db, user_id)
        result.merge(outcome)
    logger.info(
        "apply_rules_for_users: users=%d added=%d removed=%d skipped_manual=%d protected_completed=%d",
        result.users_processed,
        result.added,
        result.removed,
        result.skipped_manual,
        result.protected_completed,
    )
    return result
