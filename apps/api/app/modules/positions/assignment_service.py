"""Course assignment kernel — recompute_enrollments.

Materializes the rule→enrollment derivation: a user's enrollments for
`source IN ('position', 'department')` are kept in lockstep with the
union of `PositionCourse` (for the user's position) and
`DepartmentCourse` (for the position's department).

Properties:
  - Idempotent. Calling it twice with no rule change is a no-op.
  - Tenant-isolated. `tenant_id` is derived from `User.tenant_id`,
    never taken as a parameter from the caller.
  - Manual enrollments are never created, modified, or removed.
  - Completed enrollments are never removed, even if the rule that
    caused them is deleted.

Triggers that should call this kernel:
  - After staff import commit (batch: one call per affected user)
  - assign_user_to_position (single user)
  - update_position when course_ids change (recompute all holders)
  - delete_position (recompute holders before drop, then drop)
  - attach/detach course to/from department
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.positions.models import (
    DepartmentCourse,
    Position,
    PositionCourse,
)


@dataclass
class RecomputeResult:
    """Outcome of a single recompute_enrollments call."""

    added: int = 0
    removed: int = 0
    skipped_manual: int = 0
    protected_completed: int = 0

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "skipped_manual": self.skipped_manual,
            "protected_completed": self.protected_completed,
        }


async def recompute_enrollments(
    db: AsyncSession,
    user_id: UUID,
) -> RecomputeResult:
    """Recompute rule-driven enrollments for a single user.

    Steps (see plan B1a §recompute_enrollments algorithm for full text):
      1. Load User to derive tenant_id. Bail if user is missing or
         has no tenant.
      2. Collect expected course set from PositionCourse (for the
         user's position) and DepartmentCourse (for the position's
         department). position takes priority over department for
         the same (user, course).
      3. Split current enrollments into rule_rows and manual set.
      4. Diff in two sets. Manual is never in to_add or to_remove.
         Completed rows are filtered out of to_remove.
      5. Apply diff in a single batch per direction.

    Note: this function does not commit. The caller decides when
    the transaction boundary is.
    """
    user = await db.get(User, user_id)
    if user is None or user.tenant_id is None:
        return RecomputeResult()

    tenant_id = user.tenant_id
    result = RecomputeResult()

    # ── Step 2: collect expected courses from rules ─────────────
    # course_id → source ('position' wins over 'department')
    expected: dict[UUID, str] = {}

    if user.position_id is not None:
        # Position rules
        pc_result = await db.execute(
            select(PositionCourse.course_id).where(
                PositionCourse.position_id == user.position_id,
            )
        )
        for (course_id,) in pc_result.all():
            expected[course_id] = "position"

        # Department rules — look up via Position.department_id
        pos = await db.get(Position, user.position_id)
        if pos is not None and pos.department_id is not None:
            dc_result = await db.execute(
                select(DepartmentCourse.course_id).where(
                    DepartmentCourse.department_id == pos.department_id,
                    DepartmentCourse.tenant_id == tenant_id,
                )
            )
            for (course_id,) in dc_result.all():
                if course_id not in expected:
                    expected[course_id] = "department"

    # ── Step 3: split current enrollments ──────────────────────
    cur_result = await db.execute(
        select(Enrollment.course_id, Enrollment.source, Enrollment.status).where(
            Enrollment.user_id == user_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    rule_rows: dict[UUID, tuple[str, str]] = {}  # course_id → (source, status)
    manual_courses: set[UUID] = set()

    for course_id, source, status in cur_result.all():
        if source in ("position", "department"):
            rule_rows[course_id] = (source, status)
        elif source == "manual":
            manual_courses.add(course_id)
        # Unknown source values (e.g. 'tenant' from a future feature)
        # are treated as protected — same as manual.

    # ── Step 4: diff in two sets ────────────────────────────────
    # to_add: rule says we should have it, we don't have a rule row
    #         for it AND we don't have a manual row for it.
    to_add: dict[UUID, str] = {}
    for course_id, source in expected.items():
        if course_id in rule_rows:
            continue
        if course_id in manual_courses:
            result.skipped_manual += 1
            continue
        to_add[course_id] = source

    # to_remove: rule says we shouldn't have it, we have a rule row,
    #         AND the rule row is not completed.
    to_remove: list[UUID] = []
    for course_id, (source, status) in rule_rows.items():
        if course_id in expected:
            continue
        if status == "completed":
            result.protected_completed += 1
            continue
        to_remove.append(course_id)

    # ── Step 5: apply diff ──────────────────────────────────────
    for course_id, source in to_add.items():
        db.add(Enrollment(
            user_id=user_id,
            course_id=course_id,
            tenant_id=tenant_id,
            status="enrolled",
            source=source,
        ))
    result.added = len(to_add)

    if to_remove:
        await db.execute(
            delete(Enrollment).where(
                and_(
                    Enrollment.user_id == user_id,
                    Enrollment.course_id.in_(to_remove),
                    Enrollment.tenant_id == tenant_id,
                    Enrollment.source.in_(("position", "department")),
                    Enrollment.status == "enrolled",
                )
            )
        )
    result.removed = len(to_remove)

    await db.flush()
    return result
