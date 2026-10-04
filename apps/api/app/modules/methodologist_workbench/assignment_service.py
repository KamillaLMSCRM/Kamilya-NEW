"""Resolve, persist and execute one-time assignments with truthful receipts.

Caller owns commit/rollback. No model output can provide actor/tenant context.
The guarded audience re-read is the one-time selection point, not a future rule.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.enrollments.service import enroll_users
from app.modules.organization_scope.resolver import resolve_employee_scope
from app.modules.positions.models import Position

from .assignment_intent import parse_assignment_instruction
from .assignment_models import AssignmentPlan
from .assignment_schemas import (
    AssignmentPreview,
    AssignmentPreviewRequest,
    AssignmentReceipt,
    Choice,
    Clarification,
    CreatedAssignment,
    PlanResponse,
    PreviewResponse,
    Recipient,
)
from .natural_assignment_intent import candidate_to_parsed
from .plan_contract import (
    ActorContext,
    AssignCourse,
    ConfirmationDecision,
    ConfirmationRequest,
    PlanSnapshot,
    ReferenceSnapshot,
    evaluate_confirmation,
    plan_fingerprint,
)


class WorkbenchNotFound(LookupError):  # noqa: N818 - short transport-independent domain outcome
    pass


class WorkbenchConflict(ValueError):  # noqa: N818 - short transport-independent domain outcome
    pass


@dataclass(frozen=True)
class ConfirmationOutcome:
    receipt: AssignmentReceipt
    dispatch_ids: tuple[UUID, ...]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _assert_actor(actor: ActorContext) -> None:
    if actor.active_role != "methodologist":
        raise WorkbenchConflict("role_denied")


def _choose(rows: list[Any], selected: UUID | None) -> Any | None:
    if selected is not None:
        return next((row for row in rows if row.id == selected), None)
    return rows[0] if len(rows) == 1 else None


def _resource_query_spellings(query: str, *, candidate_mode: bool) -> tuple[str, ...]:
    """Exact original first; one syntactic wrapper only after an exact miss."""
    raw = query.strip()
    pairs = (("«", "»"), ("“", "”"), ('"', '"'), ("'", "'"))
    if candidate_mode and len(raw) > 2 and (raw[0], raw[-1]) in pairs:
        inner = raw[1:-1].strip()
        if inner and not any(inner.startswith(left) or inner.endswith(right) for left, right in pairs):
            return raw, inner
    return (raw,)


async def _bindings(
    db: AsyncSession,
    actor: ActorContext,
    course_id: UUID,
    department_id: UUID,
    *,
    timezone_name: str,
    include_descendants: bool,
    lock: bool,
) -> tuple[Course, Department, ContentRelease, tuple[Recipient, ...], str]:
    course_query = select(Course).where(Course.id == course_id, Course.tenant_id == actor.tenant_id)
    department_query = select(Department).where(
        Department.id == department_id,
        Department.tenant_id == actor.tenant_id,
        Department.is_active.is_(True),
        Department.archived_at.is_(None),
    )
    if lock:
        course_query = course_query.with_for_update().execution_options(populate_existing=True)
    course = await db.scalar(course_query)
    if lock:
        await db.scalars(
            select(Department.id)
            .where(Department.tenant_id == actor.tenant_id)
            .order_by(Department.id)
            .with_for_update()
        )
        department_query = department_query.execution_options(populate_existing=True)
    department = await db.scalar(department_query)
    if course is None or department is None:
        raise WorkbenchNotFound("resource_not_found")
    if course.status != "published":
        raise WorkbenchConflict("course_not_published")
    release = await db.scalar(
        select(ContentRelease).where(
            ContentRelease.id == course.current_release_id,
            ContentRelease.course_id == course.id,
            ContentRelease.tenant_id == actor.tenant_id,
        )
    )
    if release is None:
        # Preview must not backfill a legacy published release or mutate course.
        raise WorkbenchConflict("course_release_missing")
    scope = (
        await resolve_employee_scope(db, actor.tenant_id, [department_id]) if include_descendants else {department_id}
    )
    position_query = (
        select(Position)
        .where(
            Position.tenant_id == actor.tenant_id,
            Position.department_id.in_(scope),
            Position.is_active.is_(True),
        )
        .order_by(Position.id)
    )
    if lock:
        # Position eagerly joins its optional department. Lock only positions;
        # PostgreSQL rejects locking the nullable side of that outer join.
        await db.scalars(position_query.with_for_update(of=Position).execution_options(populate_existing=True))
    user_query = (
        select(User)
        .outerjoin(Position, and_(Position.id == User.position_id, Position.tenant_id == actor.tenant_id))
        .where(
            User.tenant_id == actor.tenant_id,
            User.role == "student",
            User.is_active.is_(True),
            User.status == "active",
            or_(
                User.organization_unit_id.in_(scope),
                and_(
                    User.organization_unit_id.is_(None), Position.is_active.is_(True), Position.department_id.in_(scope)
                ),
            ),
        )
        .order_by(User.id)
        .limit(5001)
    )
    if lock:
        user_query = user_query.with_for_update(of=User).execution_options(populate_existing=True)
    members = list((await db.scalars(user_query)).all())
    if len(members) > 5000:
        raise WorkbenchConflict("audience_limit")
    if not members:
        raise WorkbenchConflict("audience_empty")
    duplicate_query = (
        select(Enrollment)
        .where(
            Enrollment.tenant_id == actor.tenant_id,
            Enrollment.course_id == course_id,
            Enrollment.user_id.in_([user.id for user in members]),
            Enrollment.recurring_assignment_id.is_(None),
            Enrollment.status.in_(("enrolled", "in_progress", "completed")),
        )
        .order_by(Enrollment.id)
    )
    if lock:
        duplicate_query = duplicate_query.with_for_update().execution_options(populate_existing=True)
    existing = list((await db.scalars(duplicate_query)).all())
    already = {row.user_id for row in existing}
    recipients = tuple(
        Recipient(
            user_id=cast(UUID, user.id),
            label=f"{user.last_name} {user.first_name}".strip(),
            already_assigned=user.id in already,
            access_warning=not user.has_login_access,
        )
        for user in members
    )
    token = _digest(
        {
            "timezone_name": timezone_name,
            "include_descendants": include_descendants,
            "scope": sorted(str(item) for item in scope),
            "course_title": course.title,
            "department_name": department.name,
            "recipients": [item.model_dump(mode="json") for item in recipients],
            "members": [
                {
                    "id": str(user.id),
                    "unit": str(user.organization_unit_id),
                    "position": str(user.position_id),
                    "email_hash": _digest(user.email or ""),
                }
                for user in members
            ],
            "existing": sorted(str(row.id) for row in existing),
        }
    )
    return course, department, release, recipients, token


def _operation(
    course: Course,
    department: Department,
    release: ContentRelease,
    recipients: tuple[Recipient, ...],
    token: str,
    due_at: datetime,
    notify: bool,
) -> AssignCourse:
    return AssignCourse(
        action="assign_course",
        course=ReferenceSnapshot(
            object_id=cast(UUID, course.id), version_token=f"{release.id}:{release.snapshot_sha256}"
        ),
        department_id=cast(UUID, department.id),
        audience_version_token=token,
        recipients=tuple(item.user_id for item in recipients),
        due_at=due_at,
        notify=notify,
    )


async def create_assignment_preview(
    db: AsyncSession,
    actor: ActorContext,
    body: AssignmentPreviewRequest,
    *,
    now: datetime | None = None,
) -> PreviewResponse:
    _assert_actor(actor)
    now = now or datetime.now(UTC)
    try:
        parsed = (
            candidate_to_parsed(body.candidate, body.timezone_name, now)
            if body.candidate is not None
            else parse_assignment_instruction(body.instruction, body.timezone_name, now)
        )
    except ValueError as exc:
        return Clarification(code=str(exc))
    if body.candidate is not None:
        # Candidate fields are untrusted input, not an authorization or plan.
        # Resolution and confirmation remain exactly the server-owned path below.
        body = body.model_copy(
            update={"notify": body.candidate.notify, "include_descendants": body.candidate.include_descendants}
        )
    courses = []
    for course_query in _resource_query_spellings(parsed.course_query, candidate_mode=body.candidate is not None):
        courses = list(
            (
                await db.scalars(
                    select(Course)
                    .where(
                        Course.tenant_id == actor.tenant_id,
                        Course.status == "published",
                        func.lower(func.btrim(Course.title)) == course_query.lower(),
                    )
                    .order_by(Course.id)
                    .limit(21)
                )
            ).all()
        )
        if courses:
            break
    departments = []
    for department_query in _resource_query_spellings(
        parsed.department_query, candidate_mode=body.candidate is not None
    ):
        departments = list(
            (
                await db.scalars(
                    select(Department)
                    .where(
                        Department.tenant_id == actor.tenant_id,
                        Department.is_active.is_(True),
                        Department.archived_at.is_(None),
                        func.lower(func.btrim(Department.name)) == department_query.lower(),
                    )
                    .order_by(Department.id)
                    .limit(21)
                )
            ).all()
        )
        if departments:
            break
    if len(courses) > 20 or len(departments) > 20:
        return Clarification(code="too_many_matches")
    course, department = _choose(courses, body.course_id), _choose(departments, body.department_id)
    if course is None or department is None:
        return Clarification(
            code="choose_exact_resources" if courses and departments else "resource_not_found",
            course_choices=tuple(Choice(id=row.id, label=row.title) for row in courses),
            department_choices=tuple(Choice(id=row.id, label=row.name) for row in departments),
        )
    course, department, release, recipients, token = await _bindings(
        db,
        actor,
        course.id,
        department.id,
        timezone_name=parsed.timezone_name,
        include_descendants=body.include_descendants,
        lock=False,
    )
    # Limit outstanding owned previews without deleting audit/receipts.
    active = await db.scalar(
        select(func.count())
        .select_from(AssignmentPlan)
        .where(
            AssignmentPlan.tenant_id == actor.tenant_id,
            AssignmentPlan.actor_id == actor.actor_id,
            AssignmentPlan.status == "ready",
            AssignmentPlan.expires_at > now,
        )
    )
    if active is not None and active >= 20:
        raise WorkbenchConflict("preview_limit")
    plan = PlanSnapshot(
        plan_id=uuid4(),
        revision=1,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        expires_at=now + timedelta(minutes=15),
        operation=_operation(course, department, release, recipients, token, parsed.due_at, body.notify),
    )
    skipped = sum(item.already_assigned for item in recipients)
    preview = AssignmentPreview(
        plan_id=plan.plan_id,
        revision=plan.revision,
        fingerprint=plan_fingerprint(plan),
        expires_at=plan.expires_at,
        course_id=cast(UUID, course.id),
        course_title=course.title,
        release_id=cast(UUID, release.id),
        department_id=cast(UUID, department.id),
        department_name=department.name,
        timezone_name=parsed.timezone_name,
        due_at=parsed.due_at,
        notify=body.notify,
        include_descendants=body.include_descendants,
        recipients=recipients,
        new_count=len(recipients) - skipped,
        skipped_count=skipped,
    )
    db.add(
        AssignmentPlan(
            id=plan.plan_id,
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            snapshot=plan.model_dump(mode="json"),
            preview=preview.model_dump(mode="json"),
            fingerprint=preview.fingerprint,
            expires_at=plan.expires_at,
            status="ready",
        )
    )
    await db.flush()
    return preview


async def _owned_plan(db: AsyncSession, actor: ActorContext, plan_id: UUID, *, lock: bool) -> AssignmentPlan:
    _assert_actor(actor)
    query = select(AssignmentPlan).where(
        AssignmentPlan.id == plan_id,
        AssignmentPlan.tenant_id == actor.tenant_id,
        AssignmentPlan.actor_id == actor.actor_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise WorkbenchNotFound("plan_not_found")
    return row


async def get_assignment_plan(db: AsyncSession, actor: ActorContext, plan_id: UUID) -> PlanResponse:
    row = await _owned_plan(db, actor, plan_id, lock=False)
    if row.status == "succeeded":
        return AssignmentReceipt.model_validate(row.receipt)
    if datetime.now(UTC) >= row.expires_at:
        raise WorkbenchConflict("expired")
    return AssignmentPreview.model_validate(row.preview)


async def confirm_assignment_plan(
    db: AsyncSession,
    actor: ActorContext,
    request: ConfirmationRequest,
    *,
    now: datetime | None = None,
) -> ConfirmationOutcome:
    row = await _owned_plan(db, actor, request.plan_id, lock=True)
    plan = PlanSnapshot.model_validate(row.snapshot)
    if request.revision != plan.revision or request.fingerprint != row.fingerprint:
        raise WorkbenchConflict("confirmation_mismatch")
    if row.status == "succeeded":
        return ConfirmationOutcome(AssignmentReceipt.model_validate(row.receipt), ())
    preview = AssignmentPreview.model_validate(row.preview)
    if not isinstance(plan.operation, AssignCourse):
        raise WorkbenchConflict("operation_unsupported")
    course, department, release, recipients, token = await _bindings(
        db,
        actor,
        plan.operation.course.object_id,
        plan.operation.department_id,
        timezone_name=preview.timezone_name,
        include_descendants=preview.include_descendants,
        lock=True,
    )
    current = PlanSnapshot(
        plan_id=plan.plan_id,
        revision=plan.revision,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        expires_at=plan.expires_at,
        operation=_operation(
            course, department, release, recipients, token, plan.operation.due_at, plan.operation.notify
        ),
    )
    decision = evaluate_confirmation(plan, request, actor, plan_fingerprint(current), now or datetime.now(UTC))
    if decision != ConfirmationDecision.ACCEPTED:
        raise WorkbenchConflict(decision.value)
    skipped = tuple(item.user_id for item in recipients if item.already_assigned)
    expected = {item.user_id for item in recipients if not item.already_assigned}
    enrollments = await enroll_users(
        db,
        cast(UUID, course.id),
        actor.tenant_id,
        list(plan.operation.recipients),
        assigned_by=actor.actor_id if plan.operation.notify else None,
        delivery_mode="email",
        due_at=plan.operation.due_at,
    )
    if {item.user_id for item in enrollments} != expected:
        raise WorkbenchConflict("audience_changed_during_execution")
    created = tuple(
        CreatedAssignment(
            user_id=cast(UUID, item.user_id),
            enrollment_id=cast(UUID, item.id),
            notification_id=getattr(item, "notification_outbox_id", None),
        )
        for item in enrollments
    )
    receipt = AssignmentReceipt(
        plan_id=plan.plan_id,
        created=created,
        skipped=skipped,
        notification_state="queued" if any(item.notification_id for item in created) else "not_requested",
    )
    row.status = "succeeded"
    row.receipt = receipt.model_dump(mode="json")
    await db.flush()
    return ConfirmationOutcome(
        receipt, tuple(item.notification_id for item in created if item.notification_id is not None)
    )
