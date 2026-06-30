"""Batch wrappers around recompute_enrollments.

These functions are the bridge between rule mutations and the
recompute kernel. They exist so a single call (e.g. "attach this
course to this department") propagates correctly to every affected
user without each caller having to do the per-user fan-out itself.

Four functions:
  - recompute_position_holders(position_id) — every User with
    position_id == position_id is recomputed. Triggered by
    update_position when course_ids change.
  - recompute_department_members(department_id) — every holder of
    every position in the department. Triggered by
    attach/detach course to department.
  - recompute_all_tenant_users(tenant_id) — every user in the
    tenant. Triggered by attach/detach course to tenant.
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
    holder_ids = [row[0] for row in holder_result.scalars().all()]
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
    position_ids = [row[0] for row in pos_result.scalars().all()]
    if not position_ids:
        return result

    user_result = await db.execute(
        select(User.id).where(
            User.position_id.in_(position_ids),
            User.tenant_id == tenant_id,
        )
    )
    user_ids = [row[0] for row in user_result.scalars().all()]
    for user_id in user_ids:
        outcome = await recompute_enrollments(db, user_id)
        result.merge(outcome)
    return result


async def recompute_all_tenant_users(
    db: AsyncSession,
    tenant_id: UUID,
) -> BatchResult:
    """Recompute enrollments for every user in the tenant.

    Triggered by attach_course_to_tenant / detach_course_from_tenant.
    For a 1000-user tenant this can take a few seconds; consider
    dispatching to Celery for large tenants (TODO, not done today).
    """
    result = BatchResult()
    user_result = await db.execute(
        select(User.id).where(User.tenant_id == tenant_id)
    )
    user_ids = [row[0] for row in user_result.scalars().all()]
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
