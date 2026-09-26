"""Business orchestration for the mandatory-training read model."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.modules.mandatory_training.repository import (
    EmployeeContext,
    list_current_enrollments,
    list_employee_contexts,
    load_course_contexts,
    load_source_names,
)
from app.modules.mandatory_training.requirements import (
    EnrollmentAssignment,
    MandatoryTrainingProjection,
    project_mandatory_training,
    resolve_effective_requirements_for_users,
)
from app.modules.mandatory_training.schemas import (
    AssignmentReason,
    MandatoryTrainingFilter,
    MandatoryTrainingPage,
    MandatoryTrainingRow,
    MandatoryTrainingSummary,
)
from app.modules.training_log.repository import list_training_log_by_enrollment_ids

MAX_SCOPE_USERS = 1000
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

_OPERATIONAL_FIELDS = (
    "computed_status",
    "progress_percent",
    "assignment_due_at",
    "deadline_state",
    "deadline_status",
    "certificate_status",
    "latest_evidence_event_id",
    "evidence_confirmation_status",
    "evidence_signed_copy_status",
    "evidence_state",
)

_REASON_CODES = {
    "position": "mandatory_training.reason.position",
    "department": "mandatory_training.reason.department",
    "organization": "mandatory_training.reason.organization",
    "manual": "mandatory_training.reason.manual",
    "cohort": "mandatory_training.reason.cohort",
    "learning_path": "mandatory_training.reason.learning_path",
    "recurring": "mandatory_training.reason.recurring",
    "auto": "mandatory_training.reason.auto",
}


def _normalize_reason_kind(value: str) -> str:
    return value if value in _REASON_CODES else "unknown"


def _source_name(
    projection: MandatoryTrainingProjection,
    *,
    position_names: dict[UUID, str],
    unit_names: dict[UUID, str],
) -> str | None:
    requirement = projection.requirement
    if requirement is None:
        return None
    if requirement.source == "position" and requirement.source_ref_id:
        return position_names.get(requirement.source_ref_id)
    if requirement.source == "department" and requirement.source_ref_id:
        return unit_names.get(requirement.source_ref_id)
    return None


def _row_from_projection(
    employee: EmployeeContext,
    projection: MandatoryTrainingProjection,
    *,
    course_title: str,
    delivery_type: str,
    position_names: dict[UUID, str],
    unit_names: dict[UUID, str],
) -> MandatoryTrainingRow:
    assignment_reason = _assignment_reason(
        projection,
        position_names=position_names,
        unit_names=unit_names,
    )
    return MandatoryTrainingRow(
        user_id=employee.user.id,
        full_name=f"{employee.user.first_name} {employee.user.last_name}".strip(),
        personnel_number=employee.user.personnel_number,
        is_active=bool(employee.user.is_active),
        organization_unit_id=employee.organization_unit_id,
        organization_unit_path=list(employee.organization_unit_path_names),
        position_id=employee.user.position_id,
        position_name=employee.position_name,
        course_id=projection.course_id,
        course_title=course_title,
        delivery_type=delivery_type,
        requirement_state=projection.requirement_state,
        assignment_reason=assignment_reason,
        action_required=projection.action_required,
        enrollment_id=projection.enrollment_id,
        enrollment_source=projection.enrollment_source,
        enrollment_status=projection.enrollment_status,
    )


def _assignment_reason(
    projection: MandatoryTrainingProjection,
    *,
    position_names: dict[UUID, str],
    unit_names: dict[UUID, str],
) -> AssignmentReason:
    requirement = projection.requirement
    kind = _normalize_reason_kind(projection.assignment_reason_source)
    matching_requirement = (
        requirement
        if requirement is not None and requirement.source == kind
        else None
    )
    scope_path_ids = list(matching_requirement.scope_path) if matching_requirement else []
    return AssignmentReason(
        kind=kind,
        source_ref_id=(
            matching_requirement.source_ref_id
            if matching_requirement is not None
            else None
        ),
        source_name=(
            _source_name(
                projection,
                position_names=position_names,
                unit_names=unit_names,
            )
            if matching_requirement is not None
            else None
        ),
        scope_path_ids=scope_path_ids,
        scope_path_names=[unit_names.get(unit_id, "") for unit_id in scope_path_ids],
        reason_code=_REASON_CODES.get(kind, "mandatory_training.reason.unknown"),
    )


async def build_mandatory_training_rows(
    db: AsyncSession,
    tenant_id: UUID,
    filters: MandatoryTrainingFilter,
) -> list[MandatoryTrainingRow]:
    employees = await list_employee_contexts(
        db,
        tenant_id,
        filters,
        max_users=MAX_SCOPE_USERS,
    )
    if not employees:
        return []
    users = [employee.user for employee in employees]
    requirements_by_user = await resolve_effective_requirements_for_users(db, users)
    enrollments_by_user = await list_current_enrollments(
        db,
        tenant_id,
        [user.id for user in users],
    )
    projections: list[tuple[EmployeeContext, MandatoryTrainingProjection]] = []
    for employee in employees:
        for projection in project_mandatory_training(
            requirements=requirements_by_user.get(employee.user.id, {}),
            enrollments=enrollments_by_user.get(employee.user.id, ()),
        ):
            if filters.course_id is not None and projection.course_id != filters.course_id:
                continue
            if filters.requirement_state is not None and projection.requirement_state != filters.requirement_state:
                continue
            if filters.action_required is not None and projection.action_required != filters.action_required:
                continue
            projections.append((employee, projection))

    course_ids = {projection.course_id for _, projection in projections}
    courses = await load_course_contexts(db, tenant_id, course_ids)
    position_ids = {
        requirement.source_ref_id
        for requirements in requirements_by_user.values()
        for requirement in requirements.values()
        if requirement.source == "position" and requirement.source_ref_id is not None
    }
    unit_ids = {
        unit_id
        for requirements in requirements_by_user.values()
        for requirement in requirements.values()
        for unit_id in (
            (*requirement.scope_path,)
            if requirement.source == "department"
            else ()
        )
    }
    position_names, unit_names = await load_source_names(
        db,
        tenant_id,
        position_ids=position_ids,
        unit_ids=unit_ids,
    )
    rows = [
        _row_from_projection(
            employee,
            projection,
            course_title=courses[projection.course_id].title,
            delivery_type=courses[projection.course_id].delivery_type,
            position_names=position_names,
            unit_names=unit_names,
        )
        for employee, projection in projections
        if projection.course_id in courses
    ]
    rows.sort(key=lambda row: (row.full_name.casefold(), row.course_title.casefold(), str(row.course_id)))
    return rows


async def get_mandatory_training_page(
    db: AsyncSession,
    tenant_id: UUID,
    filters: MandatoryTrainingFilter,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> MandatoryTrainingPage:
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    rows = await build_mandatory_training_rows(db, tenant_id, filters)
    page_rows = rows[offset:offset + limit]
    operational_by_enrollment = await list_training_log_by_enrollment_ids(
        db,
        tenant_id,
        (
            row.enrollment_id
            for row in page_rows
            if row.enrollment_id is not None
        ),
    )
    enriched_rows = [
        row.model_copy(update={
            field: operational_by_enrollment.get(row.enrollment_id, {}).get(field)
            for field in _OPERATIONAL_FIELDS
        })
        if row.enrollment_id is not None
        else row
        for row in page_rows
    ]
    return MandatoryTrainingPage(
        items=enriched_rows,
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_mandatory_training_summary(
    db: AsyncSession,
    tenant_id: UUID,
    filters: MandatoryTrainingFilter,
) -> MandatoryTrainingSummary:
    rows = await build_mandatory_training_rows(db, tenant_id, filters)
    states = Counter(row.requirement_state for row in rows)
    actions = Counter(row.action_required for row in rows)
    return MandatoryTrainingSummary(
        total=len(rows),
        materialized=states["materialized"],
        missing_enrollment=states["missing_enrollment"],
        protected_assignment=states["protected_assignment"],
        stale_managed_enrollment=states["stale_managed_enrollment"],
        action_materialize=actions["materialize"],
        action_review_stale=actions["review_stale"],
    )


async def enrich_training_log_rows(
    db: AsyncSession,
    tenant_id: UUID,
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the canonical requirement projection to persisted log rows.

    This is the shared producer for JSON and CSV training-log consumers. It
    intentionally receives already tenant-scoped rows and reloads users with
    the same tenant guard before resolving any organization rule.
    """

    row_list = [dict(row) for row in rows]
    if not row_list:
        return []
    user_ids = {row["user_id"] for row in row_list}
    users = list(
        (
            await db.scalars(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.id.in_(user_ids),
                )
            )
        ).all()
    )
    users_by_id = {user.id: user for user in users}
    if set(users_by_id) != user_ids:
        raise ValueError("mandatory_training_user_context_missing")

    requirements_by_user = await resolve_effective_requirements_for_users(db, users)
    position_ids = {
        requirement.source_ref_id
        for requirements in requirements_by_user.values()
        for requirement in requirements.values()
        if requirement.source == "position" and requirement.source_ref_id is not None
    }
    unit_ids = {
        unit_id
        for requirements in requirements_by_user.values()
        for requirement in requirements.values()
        if requirement.source == "department"
        for unit_id in requirement.scope_path
    }
    position_names, unit_names = await load_source_names(
        db,
        tenant_id,
        position_ids=position_ids,
        unit_ids=unit_ids,
    )

    enriched: list[dict[str, Any]] = []
    for row in row_list:
        enrollment = EnrollmentAssignment(
            enrollment_id=row["enrollment_id"],
            course_id=row["course_id"],
            source=row["enrollment_source"],
            status=row["enrollment_status"],
        )
        projections = project_mandatory_training(
            requirements=requirements_by_user.get(row["user_id"], {}),
            enrollments=(enrollment,),
        )
        projection = next(
            item
            for item in projections
            if item.enrollment_id == row["enrollment_id"]
        )
        reason = _assignment_reason(
            projection,
            position_names=position_names,
            unit_names=unit_names,
        )
        row.update(
            requirement_state=projection.requirement_state,
            action_required=projection.action_required,
            assignment_reason=reason.model_dump(mode="python"),
            assignment_reason_kind=reason.kind,
            assignment_reason_source_name=reason.source_name,
            assignment_reason_code=reason.reason_code,
        )
        enriched.append(row)
    return enriched
