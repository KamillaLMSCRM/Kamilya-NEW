"""Course assignment kernel for position, department and organization rules."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.positions.models import DepartmentCourse, Position, PositionCourse
from app.modules.training_rules.models import OrganizationCourseRule


MANAGED_RULE_SOURCES = frozenset(("position", "department", "organization"))


@dataclass
class RecomputeResult:
    """Outcome of one enrollment recomputation."""

    added: int = 0
    removed: int = 0
    updated: int = 0
    skipped_manual: int = 0
    skipped_protected: int = 0
    protected_completed: int = 0

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "updated": self.updated,
            "skipped_manual": self.skipped_manual,
            "skipped_protected": self.skipped_protected,
            "protected_completed": self.protected_completed,
        }


@dataclass(frozen=True)
class RuleChangePreview:
    """Read-only impact estimate for one organization or department rule."""

    affected_employees: int = 0
    enrollments_to_add: int = 0
    in_progress_to_remove: int = 0
    protected_completed: int = 0
    protected_other_sources: int = 0

    def to_dict(self) -> dict:
        return {
            "affected_employees": self.affected_employees,
            "enrollments_to_add": self.enrollments_to_add,
            "in_progress_to_remove": self.in_progress_to_remove,
            "protected_completed": self.protected_completed,
            "protected_other_sources": self.protected_other_sources,
        }


async def _published_rule_courses(
    db: AsyncSession,
    rule_model,
    tenant_id: UUID,
    extra_filters: tuple = (),
) -> list[UUID]:
    result = await db.execute(
        select(rule_model.course_id)
        .join(Course, Course.id == rule_model.course_id)
        .where(
            rule_model.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
            Course.status == "published",
            *extra_filters,
        )
    )
    return [course_id for (course_id,) in result.all()]


async def _rule_course_sets(
    db: AsyncSession,
    user: User,
) -> tuple[set[UUID], set[UUID], set[UUID]]:
    """Return published position, department and organization course sets."""
    tenant_id = user.tenant_id
    assert tenant_id is not None
    position_courses: set[UUID] = set()
    department_courses: set[UUID] = set()

    if user.position_id is not None:
        position_courses = set(
            await _published_rule_courses(
                db,
                PositionCourse,
                tenant_id,
                (PositionCourse.position_id == user.position_id,),
            )
        )
        position = await db.get(Position, user.position_id)
        if position is not None and position.department_id is not None:
            department_courses = set(
                await _published_rule_courses(
                    db,
                    DepartmentCourse,
                    tenant_id,
                    (DepartmentCourse.department_id == position.department_id,),
                )
            )

    organization_courses = set(
        await _published_rule_courses(db, OrganizationCourseRule, tenant_id)
    )
    return position_courses, department_courses, organization_courses


def _effective_sources(
    position_courses: set[UUID],
    department_courses: set[UUID],
    organization_courses: set[UUID],
) -> dict[UUID, str]:
    expected = {course_id: "organization" for course_id in organization_courses}
    expected.update({course_id: "department" for course_id in department_courses})
    expected.update({course_id: "position" for course_id in position_courses})
    return expected


async def recompute_enrollments(db: AsyncSession, user_id: UUID) -> RecomputeResult:
    """Materialize the effective training rules for one tenant user.

    Position has precedence over department, and department has precedence over
    organization. Automatic removal controls only the three managed sources.
    Manual, cohort, learning-path and unknown sources remain untouched; a
    completed enrollment is never removed or rewritten.
    """
    user = await db.get(User, user_id)
    if user is None or user.tenant_id is None:
        return RecomputeResult()
    if user.role != "student" or not user.is_active:
        return RecomputeResult()

    tenant_id = user.tenant_id
    result = RecomputeResult()
    position_courses, department_courses, organization_courses = await _rule_course_sets(db, user)
    expected = _effective_sources(position_courses, department_courses, organization_courses)

    current_result = await db.execute(
        select(Enrollment.course_id, Enrollment.source, Enrollment.status).where(
            Enrollment.user_id == user_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    managed_rows: dict[UUID, tuple[str, str]] = {}
    protected_rows: dict[UUID, tuple[str, str]] = {}
    for course_id, source, status in current_result.all():
        if source in MANAGED_RULE_SOURCES:
            managed_rows[course_id] = (source, status)
        else:
            protected_rows[course_id] = (source, status)

    to_add: dict[UUID, str] = {}
    for course_id, source in expected.items():
        if course_id in managed_rows:
            continue
        protected = protected_rows.get(course_id)
        if protected is None:
            to_add[course_id] = source
        elif protected[0] == "manual":
            result.skipped_manual += 1
        else:
            result.skipped_protected += 1

    to_remove: list[UUID] = []
    to_update: list[tuple[UUID, str, str]] = []
    for course_id, (current_source, current_status) in managed_rows.items():
        desired_source = expected.get(course_id)
        if desired_source is None:
            if current_status == "completed":
                result.protected_completed += 1
            else:
                to_remove.append(course_id)
        elif current_source != desired_source and current_status != "completed":
            to_update.append((course_id, current_source, desired_source))

    for course_id, source in to_add.items():
        db.add(
            Enrollment(
                user_id=user_id,
                course_id=course_id,
                tenant_id=tenant_id,
                status="enrolled",
                source=source,
            )
        )
    result.added = len(to_add)

    for course_id, current_source, desired_source in to_update:
        await db.execute(
            update(Enrollment)
            .where(
                Enrollment.user_id == user_id,
                Enrollment.course_id == course_id,
                Enrollment.tenant_id == tenant_id,
                Enrollment.source == current_source,
                Enrollment.status != "completed",
            )
            .values(source=desired_source)
        )
    result.updated = len(to_update)

    if to_remove:
        await db.execute(
            delete(Enrollment).where(
                and_(
                    Enrollment.user_id == user_id,
                    Enrollment.course_id.in_(to_remove),
                    Enrollment.tenant_id == tenant_id,
                    Enrollment.source.in_(MANAGED_RULE_SOURCES),
                    Enrollment.status != "completed",
                )
            )
        )
    result.removed = len(to_remove)

    await db.flush()
    return result


async def preview_rule_change(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    scope: str,
    operation: str,
    course_id: UUID,
    department_id: UUID | None = None,
) -> RuleChangePreview:
    """Calculate the exact enrollment impact of a proposed rule mutation.

    This function is deliberately read-only. The caller has already validated
    the rule target and course; the helper only overlays the requested change
    in memory over the currently persisted rule sets.
    """
    if scope == "organization":
        user_query = select(User).where(
            User.tenant_id == tenant_id,
            User.role == "student",
            User.is_active.is_(True),
        )
    elif scope == "department" and department_id is not None:
        user_query = (
            select(User)
            .join(Position, User.position_id == Position.id)
            .where(
                User.tenant_id == tenant_id,
                User.role == "student",
                User.is_active.is_(True),
                Position.tenant_id == tenant_id,
                Position.department_id == department_id,
            )
        )
    else:
        raise ValueError("Department rule preview requires department_id")

    users = list((await db.execute(user_query)).scalars().all())
    preview = RuleChangePreview(affected_employees=len(users))
    adds = removals = completed = protected = 0

    for user in users:
        position_courses, department_courses, organization_courses = await _rule_course_sets(db, user)
        target_courses = organization_courses if scope == "organization" else department_courses
        if operation == "attach":
            target_courses.add(course_id)
        elif operation == "detach":
            target_courses.discard(course_id)
        else:
            raise ValueError("Unsupported rule preview operation")

        desired_source = _effective_sources(
            position_courses, department_courses, organization_courses
        ).get(course_id)
        current = await db.execute(
            select(Enrollment.source, Enrollment.status).where(
                Enrollment.tenant_id == tenant_id,
                Enrollment.user_id == user.id,
                Enrollment.course_id == course_id,
            )
        )
        current_row = current.first()
        if desired_source is not None and current_row is None:
            adds += 1
            continue
        if current_row is None:
            continue
        current_source, current_status = current_row
        if desired_source is not None and current_source not in MANAGED_RULE_SOURCES:
            if current_status == "completed":
                completed += 1
            else:
                protected += 1
        elif desired_source is None and current_source in MANAGED_RULE_SOURCES:
            if current_status == "completed":
                completed += 1
            else:
                removals += 1

    return RuleChangePreview(
        affected_employees=len(users),
        enrollments_to_add=adds,
        in_progress_to_remove=removals,
        protected_completed=completed,
        protected_other_sources=protected,
    )
