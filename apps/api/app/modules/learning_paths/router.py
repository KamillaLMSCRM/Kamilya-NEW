from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortMember
from app.modules.enrollments.notification_outbox import (
    queue_learning_path_assignment_notification,
)
from app.modules.learning_paths.models import (
    LearningPath,
    LearningPathAssignment,
    LearningPathCourse,
)
from app.modules.learning_paths.schemas import (
    LearnerPathItem,
    LearnerPathStep,
    LearningPathAssignmentAudience,
    LearningPathAssignmentResponse,
    LearningPathAssignmentResult,
    LearningPathCourseItem,
    LearningPathCreate,
    LearningPathCurriculumReplace,
    LearningPathDetail,
    LearningPathSummary,
    LearningPathUpdate,
    _validate_policy_values,
)
from app.modules.learning_paths.service import (
    path_step_states,
    sync_assignment_enrollments,
)
from app.modules.learning_cycles.bridge import (
    reconcile_learning_path_assignment,
)
from app.modules.positions.models import Position


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/learning-paths",
    tags=["learning-paths"],
    dependencies=[Depends(require_tenant_user())],
)

PATH_MANAGER_ROLES = ("methodologist",)


async def _get_path(db: AsyncSession, path_id: UUID, tenant_id: UUID) -> LearningPath:
    result = await db.execute(
        select(LearningPath)
        .options(
            selectinload(LearningPath.courses).selectinload(LearningPathCourse.course),
            selectinload(LearningPath.assignments),
        )
        .where(LearningPath.id == path_id, LearningPath.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    path = result.scalar_one_or_none()
    if path is None:
        raise HTTPException(status_code=404, detail="Learning program not found")
    return path


def _require_draft(path: LearningPath) -> None:
    if path.status != "draft":
        raise HTTPException(
            status_code=409,
            detail={"code": "published_version_immutable", "message": "Only draft program versions can be changed"},
        )


def _summary(path: LearningPath) -> LearningPathSummary:
    return LearningPathSummary(
        id=path.id,
        family_id=path.family_id,
        version=path.version,
        title=path.title,
        description=path.description,
        status=path.status,
        sequencing_mode=path.sequencing_mode,
        scenario=getattr(path, "scenario", "custom"),
        responsible_user_id=getattr(path, "responsible_user_id", None),
        default_due_days=getattr(path, "default_due_days", None),
        certificate_mode=getattr(path, "certificate_mode", "none"),
        certificate_validity_months=getattr(path, "certificate_validity_months", None),
        recurrence_mode=getattr(path, "recurrence_mode", "none"),
        recurrence_cadence_days=getattr(path, "recurrence_cadence_days", None),
        recurrence_due_days=getattr(path, "recurrence_due_days", None),
        course_count=len(path.courses),
        assignment_count=sum(
            assignment.status != "cancelled"
            for assignment in getattr(path, "assignments", ())
        ),
        published_at=path.published_at,
        created_at=path.created_at,
    )


def _detail(path: LearningPath) -> LearningPathDetail:
    return LearningPathDetail(
        **_summary(path).model_dump(),
        courses=[
            LearningPathCourseItem(
                course_id=item.course_id,
                title=item.course.title,
                order_index=item.order_index,
                required=item.required,
            )
            for item in path.courses
            if item.course is not None
        ],
    )


async def _detail_then_commit(db: AsyncSession, path: LearningPath) -> LearningPathDetail:
    """Build the response before transaction-local tenant RLS context expires."""
    await db.flush()
    detail = _detail(await _get_path(db, path.id, path.tenant_id))
    await db.commit()
    return detail


def _assignment_response(
    item: LearningPathAssignment,
    learner: User | None = None,
) -> LearningPathAssignmentResponse:
    learner_name = None
    learner_email = None
    if learner is not None:
        learner_name = " ".join(
            part for part in (learner.first_name, learner.last_name) if part
        ) or None
        learner_email = learner.email
    return LearningPathAssignmentResponse(
        id=item.id,
        path_id=item.path_id,
        user_id=item.user_id,
        source=item.source,
        source_ref_id=item.source_ref_id,
        assigned_by=item.assigned_by,
        starts_at=item.starts_at,
        due_at=item.due_at,
        status=item.status,
        created_at=item.created_at,
        cancelled_at=item.cancelled_at,
        completed_at=item.completed_at,
        user_name=learner_name,
        user_email=learner_email,
    )


def _assignment_actor_id(user: User) -> UUID | None:
    """Return a tenant-valid assignment author.

    An impersonation token wraps the platform superadmin with the target tenant
    for authorization and filtering, but the underlying user row still has a
    NULL tenant. The database correctly rejects that platform user as a tenant
    assignment author. The real operator remains attributable through the
    impersonation audit trail, while the tenant-owned assignment keeps a null
    author instead of inventing a tenant identity.
    """
    if getattr(user, "is_impersonating", False):
        return None
    return cast(UUID, user.id)


async def _validate_responsible_user(
    db: AsyncSession,
    *,
    responsible_user_id: UUID | None,
    tenant_id: UUID,
) -> None:
    if responsible_user_id is None:
        return
    responsible_user = await db.scalar(
        select(User.id).where(
            User.id == responsible_user_id,
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.status == "active",
            User.role == "methodologist",
        )
    )
    if responsible_user is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "responsible_user_must_be_active_tenant_methodologist"},
        )


def _validate_dates(starts_at: datetime | None, due_at: datetime | None) -> None:
    if starts_at is not None and due_at is not None and due_at < starts_at:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_assignment_dates", "message": "due_at must be after starts_at"},
        )


@router.get("", response_model=list[LearningPathSummary])
async def list_paths(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    result = await db.execute(
        select(LearningPath)
        .options(
            selectinload(LearningPath.courses),
            selectinload(LearningPath.assignments),
        )
        .where(LearningPath.tenant_id == user.tenant_id)
        .order_by(LearningPath.family_id, LearningPath.version.desc())
    )
    return [_summary(path) for path in result.scalars().unique().all()]


@router.post("", response_model=LearningPathDetail, status_code=201)
async def create_path(
    payload: LearningPathCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail={"code": "blank_title"})
    _validate_policy_values(payload.model_dump())
    await _validate_responsible_user(
        db,
        responsible_user_id=payload.responsible_user_id,
        tenant_id=user.tenant_id,
    )
    path = LearningPath(
        id=uuid4(),
        tenant_id=user.tenant_id,
        family_id=uuid4(),
        version=1,
        title=title,
        description=payload.description.strip(),
        sequencing_mode=payload.sequencing_mode,
        scenario=payload.scenario,
        responsible_user_id=payload.responsible_user_id,
        default_due_days=payload.default_due_days,
        certificate_mode=payload.certificate_mode,
        certificate_validity_months=payload.certificate_validity_months,
        recurrence_mode=payload.recurrence_mode,
        recurrence_cadence_days=payload.recurrence_cadence_days,
        recurrence_due_days=payload.recurrence_due_days,
        status="draft",
        created_by=user.id,
    )
    db.add(path)
    path.family_id = path.id
    return await _detail_then_commit(db, path)


@router.get("/my", response_model=list[LearnerPathItem])
async def list_my_paths(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(LearningPathAssignment)
        .join(LearningPath, LearningPath.id == LearningPathAssignment.path_id)
        .options(
            selectinload(LearningPathAssignment.path)
            .selectinload(LearningPath.courses)
            .selectinload(LearningPathCourse.course)
        )
        .where(
            LearningPathAssignment.tenant_id == user.tenant_id,
            LearningPathAssignment.user_id == user.id,
            LearningPathAssignment.status.in_(("active", "completed")),
            LearningPath.status == "published",
            or_(LearningPathAssignment.starts_at.is_(None), LearningPathAssignment.starts_at <= now),
        )
        .order_by(LearningPathAssignment.created_at.desc())
    )
    assignments = result.scalars().unique().all()
    # Future-dated assignments intentionally do not create a course enrollment
    # at assignment time. The learner's first program read on or after its
    # start date materializes the initial available step in this transaction.
    for assignment in assignments:
        await sync_assignment_enrollments(db, assignment, now=now)
    await db.flush()
    course_ids = {
        step.course_id
        for assignment in assignments
        for step in assignment.path.courses
        if step.course is not None
    }
    completed: set[UUID] = set()
    if course_ids:
        completed_result = await db.execute(
            select(Enrollment.course_id).where(
                Enrollment.tenant_id == user.tenant_id,
                Enrollment.user_id == user.id,
                Enrollment.course_id.in_(course_ids),
                Enrollment.status == "completed",
            )
        )
        completed = set(completed_result.scalars().all())

    response: list[LearnerPathItem] = []
    for assignment in assignments:
        path = assignment.path
        steps = [step for step in path.courses if step.course is not None]
        states = {state.course_id: state.state for state in path_step_states(steps, completed, path.sequencing_mode)}
        required_steps = [step for step in steps if step.required]
        completed_required = sum(step.course_id in completed for step in required_steps)
        current = next((step.course_id for step in steps if states[step.course_id] == "available"), None)
        response.append(
            LearnerPathItem(
                id=path.id,
                assignment_id=assignment.id,
                family_id=path.family_id,
                version=path.version,
                title=path.title,
                description=path.description,
                sequencing_mode=path.sequencing_mode,
                starts_at=assignment.starts_at,
                due_at=assignment.due_at,
                total_required_courses=len(required_steps),
                completed_required_courses=completed_required,
                progress_percent=round(completed_required / len(required_steps) * 100) if required_steps else 100,
                current_course_id=current,
                steps=[
                    LearnerPathStep(
                        course_id=step.course_id,
                        title=step.course.title,
                        order_index=step.order_index,
                        required=step.required,
                        state=states[step.course_id],
                    )
                    for step in steps
                ],
            )
        )
    return response


@router.post("/assignments/{assignment_id}/cancel", response_model=LearningPathAssignmentResponse)
async def cancel_assignment(
    assignment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    assignment = await db.scalar(
        select(LearningPathAssignment).where(
            LearningPathAssignment.id == assignment_id,
            LearningPathAssignment.tenant_id == user.tenant_id,
        )
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Learning-program assignment not found")
    if assignment.status == "completed":
        raise HTTPException(status_code=409, detail={"code": "completed_assignment_immutable"})
    if assignment.status != "cancelled":
        assignment.status = "cancelled"
        assignment.cancelled_at = datetime.now(timezone.utc)
        await db.commit()
    return _assignment_response(assignment)


@router.get("/{path_id}", response_model=LearningPathDetail)
async def get_path(
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    return _detail(await _get_path(db, path_id, user.tenant_id))


@router.patch("/{path_id}", response_model=LearningPathDetail)
async def update_path(
    path_id: UUID,
    payload: LearningPathUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    path = await _get_path(db, path_id, user.tenant_id)
    _require_draft(path)
    changes = payload.model_dump(exclude_unset=True)
    if "responsible_user_id" in changes:
        await _validate_responsible_user(
            db,
            responsible_user_id=changes["responsible_user_id"],
            tenant_id=user.tenant_id,
        )
    current_policy = {
        "certificate_mode": getattr(path, "certificate_mode", "none"),
        "certificate_validity_months": getattr(path, "certificate_validity_months", None),
        "recurrence_mode": getattr(path, "recurrence_mode", "none"),
        "recurrence_cadence_days": getattr(path, "recurrence_cadence_days", None),
        "recurrence_due_days": getattr(path, "recurrence_due_days", None),
    }
    next_policy = {**current_policy, **{key: value for key, value in changes.items() if key in current_policy}}
    if changes.get("certificate_mode") == "none":
        next_policy["certificate_validity_months"] = None
    if changes.get("recurrence_mode") == "none":
        next_policy["recurrence_cadence_days"] = None
        next_policy["recurrence_due_days"] = None
    _validate_policy_values(next_policy)
    changes.update({key: next_policy[key] for key in current_policy if key in changes or key.endswith("mode") and key in changes})
    if "certificate_mode" in changes and changes["certificate_mode"] == "none":
        changes["certificate_validity_months"] = None
    if "recurrence_mode" in changes and changes["recurrence_mode"] == "none":
        changes["recurrence_cadence_days"] = None
        changes["recurrence_due_days"] = None
    for key, value in changes.items():
        if key == "title":
            value = value.strip()
            if not value:
                raise HTTPException(status_code=422, detail={"code": "blank_title"})
        elif key == "description":
            value = value.strip()
        setattr(path, key, value)
    return await _detail_then_commit(db, path)


@router.put("/{path_id}/curriculum", response_model=LearningPathDetail)
async def replace_path_curriculum(
    path_id: UUID,
    payload: LearningPathCurriculumReplace,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    path = await _get_path(db, path_id, user.tenant_id)
    _require_draft(path)
    course_ids = [step.course_id for step in payload.steps]
    if len(set(course_ids)) != len(course_ids):
        raise HTTPException(status_code=422, detail={"code": "duplicate_course_in_curriculum"})
    if course_ids:
        result = await db.execute(
            select(Course.id).where(
                Course.tenant_id == user.tenant_id,
                Course.id.in_(course_ids),
                Course.status == "published",
            )
        )
        allowed = set(result.scalars().all())
        missing = [str(course_id) for course_id in course_ids if course_id not in allowed]
        if missing:
            raise HTTPException(
                status_code=422,
                detail={"code": "curriculum_courses_must_be_published_tenant_courses", "course_ids": missing},
            )
    for item in list(path.courses):
        await db.delete(item)
    await db.flush()
    for index, step in enumerate(payload.steps):
        db.add(
            LearningPathCourse(
                path_id=path.id,
                course_id=step.course_id,
                order_index=index,
                required=step.required,
            )
        )
    return await _detail_then_commit(db, path)


@router.post("/{path_id}/publish", response_model=LearningPathDetail)
async def publish_path(
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    path = await _get_path(db, path_id, user.tenant_id)
    _require_draft(path)
    if not path.title.strip():
        raise HTTPException(status_code=422, detail={"code": "blank_title"})
    if not path.courses:
        raise HTTPException(status_code=422, detail={"code": "curriculum_required"})
    if not any(step.required for step in path.courses):
        raise HTTPException(
            status_code=422,
            detail={"code": "required_curriculum_step_required"},
        )
    path.status = "published"
    path.published_at = datetime.now(timezone.utc)
    return await _detail_then_commit(db, path)


@router.post("/{path_id}/versions", response_model=LearningPathDetail, status_code=201)
async def create_path_version(
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    source = await _get_path(db, path_id, user.tenant_id)
    if source.status != "published":
        raise HTTPException(status_code=409, detail={"code": "only_published_versions_can_be_cloned"})
    existing_draft = await db.scalar(
        select(LearningPath.id).where(
            LearningPath.tenant_id == user.tenant_id,
            LearningPath.family_id == source.family_id,
            LearningPath.status == "draft",
        )
    )
    if existing_draft is not None:
        raise HTTPException(status_code=409, detail={"code": "draft_version_already_exists"})
    latest_version = await db.scalar(
        select(LearningPath.version)
        .where(LearningPath.tenant_id == user.tenant_id, LearningPath.family_id == source.family_id)
        .order_by(LearningPath.version.desc())
        .limit(1)
    )
    clone = LearningPath(
        tenant_id=user.tenant_id,
        family_id=source.family_id,
        version=(latest_version or source.version) + 1,
        title=source.title,
        description=source.description,
        sequencing_mode=source.sequencing_mode,
        scenario=getattr(source, "scenario", "custom"),
        responsible_user_id=getattr(source, "responsible_user_id", None),
        default_due_days=getattr(source, "default_due_days", None),
        certificate_mode=getattr(source, "certificate_mode", "none"),
        certificate_validity_months=getattr(source, "certificate_validity_months", None),
        recurrence_mode=getattr(source, "recurrence_mode", "none"),
        recurrence_cadence_days=getattr(source, "recurrence_cadence_days", None),
        recurrence_due_days=getattr(source, "recurrence_due_days", None),
        status="draft",
        supersedes_id=source.id,
        created_by=user.id,
    )
    db.add(clone)
    await db.flush()
    for step in source.courses:
        db.add(
            LearningPathCourse(
                path_id=clone.id,
                course_id=step.course_id,
                order_index=step.order_index,
                required=step.required,
            )
        )
    return await _detail_then_commit(db, clone)


async def _require_audience_records(
    db: AsyncSession,
    *,
    ids: list[UUID],
    entity,
    tenant_id: UUID,
    code: str,
    extra_filter=None,
) -> None:
    if not ids:
        return
    statement = select(entity.id).where(entity.id.in_(ids), entity.tenant_id == tenant_id)
    if extra_filter is not None:
        statement = statement.where(extra_filter)
    found = set((await db.execute(statement)).scalars().all())
    if found != set(ids):
        raise HTTPException(status_code=422, detail={"code": code, "ids": [str(item) for item in set(ids) - found]})


async def _resolve_audience(
    db: AsyncSession, payload: LearningPathAssignmentAudience, tenant_id: UUID
) -> dict[UUID, tuple[str, UUID | None]]:
    """Resolve an audience with deterministic source precedence.

    A program has one assignment per learner/version. Direct assignment wins,
    then cohort, department and position, which makes the audit source stable
    even where audiences overlap.
    """
    if not any((payload.user_ids, payload.cohort_ids, payload.department_ids, payload.position_ids)):
        raise HTTPException(status_code=422, detail={"code": "empty_audience"})
    for values, code in (
        (payload.user_ids, "duplicate_user_ids"),
        (payload.cohort_ids, "duplicate_cohort_ids"),
        (payload.department_ids, "duplicate_department_ids"),
        (payload.position_ids, "duplicate_position_ids"),
    ):
        if len(values) != len(set(values)):
            raise HTTPException(status_code=422, detail={"code": code})

    await _require_audience_records(
        db, ids=payload.cohort_ids, entity=Cohort, tenant_id=tenant_id,
        code="cohorts_outside_tenant_or_inactive", extra_filter=Cohort.is_active.is_(True),
    )
    await _require_audience_records(
        db, ids=payload.department_ids, entity=Department, tenant_id=tenant_id,
        code="departments_outside_tenant",
    )
    await _require_audience_records(
        db, ids=payload.position_ids, entity=Position, tenant_id=tenant_id,
        code="positions_outside_tenant",
    )

    targets: dict[UUID, tuple[str, UUID | None]] = {}
    active_student = (
        User.tenant_id == tenant_id,
        User.role == "student",
        User.is_active.is_(True),
        User.status == "active",
    )

    if payload.position_ids:
        rows = await db.execute(
            select(User.id, Position.id)
            .join(Position, Position.id == User.position_id)
            .where(*active_student, Position.tenant_id == tenant_id, Position.id.in_(payload.position_ids))
        )
        for user_id, source_ref_id in rows.all():
            targets.setdefault(user_id, ("position", source_ref_id))
    if payload.department_ids:
        rows = await db.execute(
            select(User.id, Department.id)
            .join(Position, Position.id == User.position_id)
            .join(Department, Department.id == Position.department_id)
            .where(*active_student, Position.tenant_id == tenant_id, Department.tenant_id == tenant_id, Department.id.in_(payload.department_ids))
        )
        for user_id, source_ref_id in rows.all():
            targets[user_id] = ("department", source_ref_id)
    if payload.cohort_ids:
        rows = await db.execute(
            select(User.id, Cohort.id)
            .join(CohortMember, CohortMember.user_id == User.id)
            .join(Cohort, Cohort.id == CohortMember.cohort_id)
            .where(
                *active_student,
                CohortMember.tenant_id == tenant_id,
                Cohort.tenant_id == tenant_id,
                Cohort.id.in_(payload.cohort_ids),
            )
        )
        for user_id, source_ref_id in rows.all():
            targets[user_id] = ("cohort", source_ref_id)
    if payload.user_ids:
        rows = await db.execute(select(User.id).where(*active_student, User.id.in_(payload.user_ids)))
        direct_ids = set(rows.scalars().all())
        if direct_ids != set(payload.user_ids):
            raise HTTPException(
                status_code=422,
                detail={"code": "users_must_be_active_tenant_students", "ids": [str(item) for item in set(payload.user_ids) - direct_ids]},
            )
        for user_id in direct_ids:
            targets[user_id] = ("manual", None)
    return targets


@router.post("/{path_id}/assignments", response_model=LearningPathAssignmentResult, status_code=201)
async def assign_path_audience(
    path_id: UUID,
    payload: LearningPathAssignmentAudience,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    _validate_dates(payload.starts_at, payload.due_at)
    path = await _get_path(db, path_id, user.tenant_id)
    if path.status != "published":
        raise HTTPException(status_code=409, detail={"code": "only_published_versions_can_be_assigned"})
    starts_at = payload.starts_at
    due_at = payload.due_at
    default_due_days = getattr(path, "default_due_days", None)
    if due_at is None and default_due_days is not None:
        due_at = (starts_at or datetime.now(timezone.utc)) + timedelta(days=default_due_days)
    _validate_dates(starts_at, due_at)
    targets = await _resolve_audience(db, payload, user.tenant_id)
    existing = await db.execute(
        select(LearningPathAssignment).where(
            LearningPathAssignment.path_id == path.id,
            LearningPathAssignment.user_id.in_(targets),
            LearningPathAssignment.tenant_id == user.tenant_id,
        )
    )
    by_user = {}
    for candidate in existing.scalars().all():
        if getattr(candidate, "recurrence_instance_id", None) is None:
            by_user.setdefault(candidate.user_id, candidate)
    added: list[LearningPathAssignment] = []
    notification_ids: list[UUID] = []
    skipped = 0
    for user_id, (source, source_ref_id) in targets.items():
        assignment = by_user.get(user_id)
        # Re-applying an audience must not resurrect a completed program.
        # Completion is an immutable learner outcome; only a cancelled
        # assignment may be explicitly reactivated by a later assignment.
        if assignment is not None and assignment.status in {"active", "completed"}:
            skipped += 1
            continue
        if assignment is None or getattr(assignment, "recurrence_instance_id", None) is not None:
            assignment = LearningPathAssignment(
                tenant_id=user.tenant_id,
                path_id=path.id,
                user_id=user_id,
                source=source,
                source_ref_id=source_ref_id,
                assigned_by=_assignment_actor_id(user),
                starts_at=starts_at,
                due_at=due_at,
                status="active",
            )
            db.add(assignment)
        else:
            assignment.source = source
            assignment.source_ref_id = source_ref_id
            assignment.assigned_by = _assignment_actor_id(user)
            assignment.starts_at = starts_at
            assignment.due_at = due_at
            assignment.status = "active"
            assignment.cancelled_at = None
            assignment.completed_at = None
        added.append(assignment)
    await db.flush()
    for assignment in added:
        await sync_assignment_enrollments(db, assignment)
        if getattr(path, "recurrence_mode", "none") == "fixed_interval_after_completion":
            await reconcile_learning_path_assignment(
                db,
                path=path,
                user_id=assignment.user_id,
                created_by=_assignment_actor_id(user),
            )
        notification_id = await queue_learning_path_assignment_notification(
            db,
            tenant_id=user.tenant_id,
            learning_path_assignment_id=assignment.id,
            assigned_by=assignment.assigned_by,
        )
        if notification_id is not None:
            notification_ids.append(notification_id)
    await db.commit()
    for notification_id in notification_ids:
        try:
            from app.modules.enrollments.notification_tasks import (
                deliver_assignment_notification_task,
            )

            deliver_assignment_notification_task.apply_async(
                args=[str(user.tenant_id), str(notification_id)],
                kwargs={"notification_kind": "learning_path"},
            )
        except Exception:
            logger.warning(
                "Learning-path assignment notification dispatch failed; durable outbox recovery will retry",
                exc_info=True,
            )
    return LearningPathAssignmentResult(
        added=len(added),
        skipped=skipped,
        total=len(targets),
        assignments=[_assignment_response(assignment) for assignment in added],
    )


@router.get("/{path_id}/assignments", response_model=list[LearningPathAssignmentResponse])
async def list_path_assignments(
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    await _get_path(db, path_id, user.tenant_id)
    result = await db.execute(
        select(LearningPathAssignment)
        .options(selectinload(LearningPathAssignment.user))
        .where(
            LearningPathAssignment.path_id == path_id,
            LearningPathAssignment.tenant_id == user.tenant_id,
        )
        .order_by(LearningPathAssignment.created_at.desc())
    )
    return [
        _assignment_response(item, item.user)
        for item in result.scalars().all()
    ]
