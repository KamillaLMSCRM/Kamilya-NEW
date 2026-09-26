"""Canonical precedence contract for effective course requirements.

The assignment materializer and the corporate readiness read model use this
module so that a course cannot have one source in enrollment writes and another
source in the UI explanation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.users import User
from app.modules.organization_scope import resolve_ancestor_path, resolve_ancestor_paths
from app.modules.positions.models import DepartmentCourse, Position, PositionCourse
from app.modules.training_rules.models import OrganizationCourseRule

RequirementSource = Literal["position", "department", "organization"]
RequirementRule = tuple[UUID, UUID | None]
RequirementState = Literal[
    "materialized",
    "missing_enrollment",
    "protected_assignment",
    "stale_managed_enrollment",
]
RequirementAction = Literal["none", "materialize", "review_stale"]
MANAGED_REQUIREMENT_SOURCES = frozenset(("position", "department", "organization"))


@dataclass(frozen=True, slots=True)
class EffectiveRequirement:
    """One winning mandatory-course rule for a tenant employee."""

    course_id: UUID
    source: RequirementSource
    source_ref_id: UUID | None
    scope_path: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class EnrollmentAssignment:
    """Current enrollment data needed to reconcile one course requirement."""

    enrollment_id: UUID
    course_id: UUID
    source: str
    status: str


@dataclass(frozen=True, slots=True)
class MandatoryTrainingProjection:
    """One explainable expected-versus-actual mandatory-training result."""

    course_id: UUID
    requirement_state: RequirementState
    assignment_reason_source: str
    action_required: RequirementAction
    requirement: EffectiveRequirement | None = None
    enrollment_id: UUID | None = None
    enrollment_source: str | None = None
    enrollment_status: str | None = None


def merge_effective_requirements(
    *,
    organization_rules: Iterable[RequirementRule],
    department_rules: Iterable[RequirementRule],
    position_rules: Iterable[RequirementRule],
    department_scope_path: tuple[UUID, ...] = (),
) -> dict[UUID, EffectiveRequirement]:
    """Merge rule rows using the materializer's canonical precedence.

    Department rules must be supplied root-to-leaf. Repeated courses therefore
    end with the closest matching unit before position rules take precedence.
    """

    effective: dict[UUID, EffectiveRequirement] = {}
    for course_id, source_ref_id in organization_rules:
        effective[course_id] = EffectiveRequirement(
            course_id=course_id,
            source="organization",
            source_ref_id=source_ref_id,
        )
    for course_id, source_ref_id in department_rules:
        effective[course_id] = EffectiveRequirement(
            course_id=course_id,
            source="department",
            source_ref_id=source_ref_id,
            scope_path=department_scope_path,
        )
    for course_id, source_ref_id in position_rules:
        effective[course_id] = EffectiveRequirement(
            course_id=course_id,
            source="position",
            source_ref_id=source_ref_id,
        )
    return effective


async def resolve_effective_requirements(
    db: AsyncSession,
    user: User,
) -> dict[UUID, EffectiveRequirement]:
    """Resolve tenant-local published requirements for one employee.

    The resolver owns both precedence and provenance.  The write-side
    materializer and read-side mandatory-training matrix therefore cannot
    disagree about why a course is required.
    """

    tenant_id = cast(UUID | None, user.tenant_id)
    if tenant_id is None:
        return {}

    position_id = user.position_id if isinstance(user.position_id, UUID) else None
    placement_id = getattr(user, "organization_unit_id", None)
    if not isinstance(placement_id, UUID):
        placement_id = None

    position_rules: list[RequirementRule] = []
    if position_id is not None:
        position_rows = await db.execute(
            select(PositionCourse.course_id)
            .join(Course, Course.id == PositionCourse.course_id)
            .where(
                PositionCourse.tenant_id == tenant_id,
                PositionCourse.position_id == position_id,
                Course.tenant_id == tenant_id,
                Course.status == "published",
            )
        )
        position_rules = [
            (course_id, position_id)
            for (course_id,) in position_rows.all()
        ]

    if placement_id is None and position_id is not None:
        legacy_position = await db.execute(
            select(Position.department_id).where(
                Position.id == position_id,
                Position.tenant_id == tenant_id,
            )
        )
        legacy_unit_id = legacy_position.scalar_one_or_none()
        if isinstance(legacy_unit_id, UUID):
            placement_id = legacy_unit_id

    department_scope_path: tuple[UUID, ...] = ()
    department_rules: list[RequirementRule] = []
    if placement_id is not None:
        department_scope_path = tuple(
            await resolve_ancestor_path(db, tenant_id, placement_id)
        )
        department_rows = await db.execute(
            select(DepartmentCourse.course_id, DepartmentCourse.department_id)
            .join(Course, Course.id == DepartmentCourse.course_id)
            .where(
                DepartmentCourse.tenant_id == tenant_id,
                DepartmentCourse.department_id.in_(department_scope_path),
                Course.tenant_id == tenant_id,
                Course.status == "published",
            )
        )
        path_order = {
            unit_id: order
            for order, unit_id in enumerate(department_scope_path)
        }
        department_rules = sorted(
            (
                (course_id, department_id)
                for course_id, department_id in department_rows.all()
            ),
            key=lambda rule: path_order[cast(UUID, rule[1])],
        )

    organization_rows = await db.execute(
        select(OrganizationCourseRule.course_id, OrganizationCourseRule.id)
        .join(Course, Course.id == OrganizationCourseRule.course_id)
        .where(
            OrganizationCourseRule.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
            Course.status == "published",
        )
    )
    organization_rules = [
        (course_id, rule_id)
        for course_id, rule_id in organization_rows.all()
    ]

    return merge_effective_requirements(
        organization_rules=organization_rules,
        department_rules=department_rules,
        position_rules=position_rules,
        department_scope_path=department_scope_path,
    )


async def resolve_effective_requirements_for_users(
    db: AsyncSession,
    users: Iterable[User],
) -> dict[UUID, dict[UUID, EffectiveRequirement]]:
    """Resolve requirements for many employees with bounded shared reads.

    The single-user resolver remains useful to the write-side materializer.
    Matrix reads use this batch variant so organization, hierarchy and rule
    tables are read once per request instead of once per employee.
    """

    user_rows = list(users)
    if not user_rows:
        return {}
    tenant_ids = {
        cast(UUID, user.tenant_id)
        for user in user_rows
        if isinstance(user.tenant_id, UUID)
    }
    if len(tenant_ids) != 1 or any(user.tenant_id is None for user in user_rows):
        raise ValueError("mandatory_training_users_must_share_tenant")
    tenant_id = tenant_ids.pop()

    position_ids = {
        cast(UUID, user.position_id)
        for user in user_rows
        if isinstance(user.position_id, UUID)
    }
    legacy_units_by_position: dict[UUID, UUID] = {}
    if position_ids:
        position_rows = await db.execute(
            select(Position.id, Position.department_id).where(
                Position.tenant_id == tenant_id,
                Position.id.in_(position_ids),
            )
        )
        legacy_units_by_position = {
            position_id: department_id
            for position_id, department_id in position_rows.all()
            if isinstance(department_id, UUID)
        }

    placement_by_user: dict[UUID, UUID | None] = {}
    for user in user_rows:
        placement_id = getattr(user, "organization_unit_id", None)
        if not isinstance(placement_id, UUID):
            position_id = user.position_id if isinstance(user.position_id, UUID) else None
            placement_id = legacy_units_by_position.get(position_id) if position_id else None
        placement_by_user[cast(UUID, user.id)] = (
            placement_id if isinstance(placement_id, UUID) else None
        )

    placements = {
        placement_id
        for placement_id in placement_by_user.values()
        if placement_id is not None
    }
    paths_by_placement = (
        await resolve_ancestor_paths(db, tenant_id, placements)
        if placements
        else {}
    )

    position_rules_by_position: dict[UUID, list[RequirementRule]] = {}
    if position_ids:
        position_course_rows = await db.execute(
            select(PositionCourse.position_id, PositionCourse.course_id)
            .join(Course, Course.id == PositionCourse.course_id)
            .where(
                PositionCourse.tenant_id == tenant_id,
                PositionCourse.position_id.in_(position_ids),
                Course.tenant_id == tenant_id,
                Course.status == "published",
            )
        )
        for position_id, course_id in position_course_rows.all():
            position_rules_by_position.setdefault(position_id, []).append(
                (course_id, position_id)
            )

    unit_ids = {
        unit_id
        for path in paths_by_placement.values()
        for unit_id in path
    }
    department_rules_by_unit: dict[UUID, list[RequirementRule]] = {}
    if unit_ids:
        department_course_rows = await db.execute(
            select(DepartmentCourse.department_id, DepartmentCourse.course_id)
            .join(Course, Course.id == DepartmentCourse.course_id)
            .where(
                DepartmentCourse.tenant_id == tenant_id,
                DepartmentCourse.department_id.in_(unit_ids),
                Course.tenant_id == tenant_id,
                Course.status == "published",
            )
        )
        for department_id, course_id in department_course_rows.all():
            department_rules_by_unit.setdefault(department_id, []).append(
                (course_id, department_id)
            )

    organization_rows = await db.execute(
        select(OrganizationCourseRule.course_id, OrganizationCourseRule.id)
        .join(Course, Course.id == OrganizationCourseRule.course_id)
        .where(
            OrganizationCourseRule.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
            Course.status == "published",
        )
    )
    organization_rules: list[RequirementRule] = [
        (course_id, rule_id)
        for course_id, rule_id in organization_rows.all()
    ]

    resolved: dict[UUID, dict[UUID, EffectiveRequirement]] = {}
    for user in user_rows:
        user_id = cast(UUID, user.id)
        position_id = user.position_id if isinstance(user.position_id, UUID) else None
        placement_id = placement_by_user[user_id]
        path = tuple(paths_by_placement.get(placement_id, ())) if placement_id else ()
        department_rules = [
            rule
            for unit_id in path
            for rule in department_rules_by_unit.get(unit_id, ())
        ]
        resolved[user_id] = merge_effective_requirements(
            organization_rules=organization_rules,
            department_rules=department_rules,
            position_rules=(
                position_rules_by_position.get(position_id, ())
                if position_id is not None
                else ()
            ),
            department_scope_path=path,
        )
    return resolved


def project_mandatory_training(
    *,
    requirements: Mapping[UUID, EffectiveRequirement],
    enrollments: Iterable[EnrollmentAssignment],
) -> tuple[MandatoryTrainingProjection, ...]:
    """Reconcile expected requirements with current enrollment assignments.

    The caller supplies only current enrollment occurrences. Historical
    cancelled or superseded occurrences belong to the training log and must
    not be mixed into this projection.
    """

    current_by_course: dict[UUID, EnrollmentAssignment] = {}
    for current_enrollment in enrollments:
        if current_enrollment.course_id in current_by_course:
            raise ValueError(
                f"duplicate_current_enrollment:{current_enrollment.course_id}"
            )
        current_by_course[current_enrollment.course_id] = current_enrollment

    rows: list[MandatoryTrainingProjection] = []
    for course_id in sorted(
        set(requirements).union(current_by_course),
        key=str,
    ):
        requirement = requirements.get(course_id)
        enrollment = current_by_course.get(course_id)
        if enrollment is None:
            assert requirement is not None
            rows.append(MandatoryTrainingProjection(
                course_id=course_id,
                requirement_state="missing_enrollment",
                assignment_reason_source=requirement.source,
                action_required="materialize",
                requirement=requirement,
            ))
            continue

        enrollment_is_managed = enrollment.source in MANAGED_REQUIREMENT_SOURCES
        if requirement is None:
            state: RequirementState = (
                "stale_managed_enrollment"
                if enrollment_is_managed
                else "protected_assignment"
            )
            action: RequirementAction = (
                "review_stale" if enrollment_is_managed else "none"
            )
            reason_source = enrollment.source
        elif not enrollment_is_managed:
            state = "protected_assignment"
            action = "none"
            reason_source = enrollment.source
        elif enrollment.source != requirement.source:
            state = "stale_managed_enrollment"
            action = "review_stale"
            reason_source = requirement.source
        else:
            state = "materialized"
            action = "none"
            reason_source = requirement.source

        rows.append(MandatoryTrainingProjection(
            course_id=course_id,
            requirement_state=state,
            assignment_reason_source=reason_source,
            action_required=action,
            requirement=requirement,
            enrollment_id=enrollment.enrollment_id,
            enrollment_source=enrollment.source,
            enrollment_status=enrollment.status,
        ))
    return tuple(rows)
