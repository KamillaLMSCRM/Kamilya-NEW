"""Training log repository — single SQL with JOINs, no N+1.

The training log joins 7 tables: users, courses, enrollments, positions,
departments, certificates, and (optionally) one aggregate subquery for quiz
stats. We keep it to **two** round-trips total:

1. **count** — same WHERE clause, different projection.
2. **rows** — main SELECT with LEFT JOINs and a LEFT JOIN LATERAL for quiz stats
   (MAX score, COUNT attempts) per (user, course).

Kiosk "last seen" is fetched in a third tiny query only if the user filter
includes a tenant scope and we want it (it's a LEFT JOIN on a derived table).

This keeps the page render bounded: even for a tenant with 10k users × 50 courses
the query plan should stay under 1s on the indexes we have
(ix_enrollments_tenant_user / ix_progress_tenant_user_course_completed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    Table,
    and_,
    case,
    desc,
    func,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.models import Course as CourseModel
from app.modules.learning_cycles.models import LearningPathCycleInstance, RecurringLearningAssignment
from app.modules.learning_paths.models import LearningPathAssignment
from app.modules.training_evidence.models import (
    TrainingEvidenceEvent,
    TrainingEvidenceLegalHold,
    TrainingEvidenceStepUpConfirmation,
)
from app.modules.training_log.deadline_policy import deadline_status_sql
from app.modules.training_log.schemas import TrainingLogFilter

logger = logging.getLogger(__name__)


# We build a runtime metadata table for `quiz_attempts` because the model is
# declared with `extend_existing=True` and a quick reflected Table avoids a
# possible import-order conflict between modules/certificates and modules/quizzes.
_quiz_attempts = Table(
    "quiz_attempts",
    MetaData(),
    Column("id", PG_UUID),
    Column("quiz_id", PG_UUID),
    Column("user_id", PG_UUID),
    Column("tenant_id", PG_UUID),
    Column("enrollment_id", PG_UUID),
    Column("score_percent", Integer),
    Column("passed", Boolean),
)


@dataclass(frozen=True)
class _CycleReadColumns:
    cycle_id: Any
    cycle_type: Any
    scheduled_for: Any
    due_at: Any
    eligible: Any

    def deadline_status(self) -> ColumnElement[str]:
        return deadline_status_sql(
            due_at=self.due_at,
            completed_at=Enrollment.completed_at,
            enrollment_status=Enrollment.status,
            eligible=self.eligible,
        )


def _join_cycle_read_model(stmt: Any, tenant_id: UUID) -> tuple[Any, _CycleReadColumns]:
    """Attach direct-course and learning-path cycle identity without writes."""
    stmt = stmt.outerjoin(
        RecurringLearningAssignment,
        and_(
            RecurringLearningAssignment.id == Enrollment.recurring_assignment_id,
            RecurringLearningAssignment.tenant_id == tenant_id,
            RecurringLearningAssignment.user_id == Enrollment.user_id,
            RecurringLearningAssignment.course_id == Enrollment.course_id,
        ),
    )
    stmt = stmt.outerjoin(
        LearningPathAssignment,
        and_(
            LearningPathAssignment.id == Enrollment.learning_path_assignment_id,
            LearningPathAssignment.tenant_id == tenant_id,
            LearningPathAssignment.user_id == Enrollment.user_id,
        ),
    )
    stmt = stmt.outerjoin(
        LearningPathCycleInstance,
        and_(
            LearningPathCycleInstance.id == LearningPathAssignment.recurrence_instance_id,
            LearningPathCycleInstance.tenant_id == tenant_id,
            LearningPathCycleInstance.user_id == Enrollment.user_id,
            LearningPathCycleInstance.path_id == LearningPathAssignment.path_id,
        ),
    )
    return stmt, _CycleReadColumns(
        cycle_id=func.coalesce(RecurringLearningAssignment.id, LearningPathCycleInstance.id),
        cycle_type=case(
            (RecurringLearningAssignment.id.is_not(None), literal("course")),
            (LearningPathCycleInstance.id.is_not(None), literal("learning_path")),
            else_=None,
        ),
        scheduled_for=func.coalesce(
            RecurringLearningAssignment.scheduled_for,
            LearningPathCycleInstance.scheduled_for,
        ),
        due_at=func.coalesce(
            RecurringLearningAssignment.due_at,
            LearningPathCycleInstance.due_at,
        ),
        eligible=case(
            (
                RecurringLearningAssignment.id.is_not(None),
                RecurringLearningAssignment.status.in_(("assigned", "completed")),
            ),
            else_=and_(
                LearningPathCycleInstance.status.in_(("active", "completed")),
                LearningPathAssignment.status.in_(("active", "completed")),
            ),
        ),
    )


def _apply_filters(stmt, f: TrainingLogFilter, tenant_id: UUID):
    """Apply WHERE clauses shared by count + rows queries.

    Status semantics (revised 2026-07-09 for honest filtering):
    - completed:   enrollment.status = completed OR completed_at IS NOT NULL
    - assigned:    not completed AND no native lesson progress AND no SCORM attempt
    - in_progress: not completed AND (native lesson progress OR SCORM attempt exists)
    - overdue:     unfinished enrollment linked to an immutable course/path cycle
                   whose effective due_at is before database UTC time.

    The 'assigned' / 'in_progress' filters rely on the LEFT-JOINed activity
    subqueries (`_native_activity`, `_scorm_activity`) added by the caller.
    """
    stmt = stmt.where(
        User.tenant_id == tenant_id,
        Enrollment.tenant_id == tenant_id,
        CourseModel.tenant_id == tenant_id,
    )
    stmt = stmt.where(User.role.in_(("student",)))  # HR doesn't want to see admins/methodologists in this log
    if f.course_id:
        stmt = stmt.where(CourseModel.id == f.course_id)
    if f.delivery_type:
        stmt = stmt.where(CourseModel.delivery_type == f.delivery_type)
    if f.date_from:
        stmt = stmt.where(Enrollment.enrolled_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Enrollment.enrolled_at <= f.date_to)
    if f.status == "completed":
        stmt = stmt.where(or_(Enrollment.status == "completed", Enrollment.completed_at.is_not(None)))
    # 'assigned' / 'in_progress' are applied by `list_training_log` / `count_training_log`
    # because they reference the LEFT-JOINed activity subqueries that live on the main
    # query, not on the count query.
    if f.search:
        like = f"%{f.search}%"
        stmt = stmt.where(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.personnel_number.ilike(like),
            )
        )
    return stmt


# Subqueries referenced from both list_training_log and count_training_log.
# Each returns aggregate per (user, course) used to compute activity status
# and progress percent.
def _build_activity_subqueries():
    """Return (native_activity, scorm_activity, course_lessons) subqueries.

    native_activity: per (user_id, course_id) — completed_lessons (int), has_progress (bool)
    scorm_activity:  per (user_id, course_id) — has_attempt (bool)
    course_lessons:  per course_id            — total_lessons (int)

    The "Progress" model is in app.models.progress; we reflect it as a Table to
    avoid an import cycle (training_log → progress → potentially back).
    The same pattern is already used for quiz_attempts above.
    """
    _progress = Table(
        "progress",
        MetaData(),
        Column("id", PG_UUID),
        Column("user_id", PG_UUID),
        Column("course_id", PG_UUID),
        Column("lesson_id", PG_UUID),
        Column("completed", Boolean),
        Column("enrollment_id", PG_UUID),
    )
    _scorm_attempts = Table(
        "scorm_attempts",
        MetaData(),
        Column("id", PG_UUID),
        Column("course_id", PG_UUID),
        Column("user_id", PG_UUID),
        Column("tenant_id", PG_UUID),
    )
    _lessons = Table(
        "lessons",
        MetaData(),
        Column("id", PG_UUID),
        Column("module_id", PG_UUID),
    )
    _modules = Table(
        "modules",
        MetaData(),
        Column("id", PG_UUID),
        Column("course_id", PG_UUID),
    )

    native_activity = (
        select(
            _progress.c.user_id.label("user_id"),
            _progress.c.course_id.label("course_id"),
            _progress.c.enrollment_id.label("enrollment_id"),
            func.coalesce(
                func.sum(case((_progress.c.completed.is_(True), 1), else_=0)),
                0,
            )
            .cast(Integer)
            .label("completed_lessons"),
            func.bool_or(_progress.c.completed).label("has_progress"),
        )
        .group_by(_progress.c.user_id, _progress.c.course_id, _progress.c.enrollment_id)
        .subquery()
    )

    scorm_activity = (
        select(
            _scorm_attempts.c.user_id.label("user_id"),
            _scorm_attempts.c.course_id.label("course_id"),
            func.bool_or(literal(True)).label("has_attempt"),
        )
        .group_by(_scorm_attempts.c.user_id, _scorm_attempts.c.course_id)
        .subquery()
    )

    # Lessons per course: join lessons → modules → course_id
    course_lessons = (
        select(
            _modules.c.course_id.label("course_id"),
            func.count(_lessons.c.id).cast(Integer).label("total_lessons"),
        )
        .select_from(_lessons.join(_modules, _modules.c.id == _lessons.c.module_id))
        .group_by(_modules.c.course_id)
        .subquery()
    )

    return native_activity, scorm_activity, course_lessons


def _apply_status_filter(stmt, f: TrainingLogFilter, native_activity, scorm_activity, cycle_columns):
    """Apply the assigned/in_progress filter using the activity subqueries.

    `completed` is already handled in `_apply_filters` (uses Enrollment columns).
    For `assigned` and `in_progress` we need the LEFT-JOINed activity columns.
    """
    if f.status == "in_progress":
        stmt = stmt.where(
            and_(
                Enrollment.completed_at.is_(None),
                Enrollment.status != "completed",
                or_(
                    native_activity.c.has_progress.is_(True),
                    scorm_activity.c.has_attempt.is_(True),
                ),
            )
        )
    elif f.status == "assigned":
        stmt = stmt.where(
            and_(
                Enrollment.completed_at.is_(None),
                Enrollment.status != "completed",
                native_activity.c.has_progress.isnot(True),
                scorm_activity.c.has_attempt.isnot(True),
            )
        )
    elif f.status == "overdue":
        stmt = stmt.where(cycle_columns.deadline_status() == "overdue")
    return stmt


async def count_training_log(
    db: AsyncSession,
    tenant_id: UUID,
    f: TrainingLogFilter,
) -> int:
    """Count rows matching the filter (same WHERE as list query)."""
    from app.modules.positions.models import Position as PositionModel

    stmt = (
        select(func.count())
        .select_from(User)
        .join(Enrollment, Enrollment.user_id == User.id)
        .join(CourseModel, CourseModel.id == Enrollment.course_id)
        .outerjoin(PositionModel, PositionModel.id == User.position_id)
    )
    stmt, cycle_columns = _join_cycle_read_model(stmt, tenant_id)
    stmt = _apply_filters(stmt, f, tenant_id)
    if f.department_id:
        stmt = stmt.where(PositionModel.department_id == f.department_id)
    if f.position_id:
        stmt = stmt.where(User.position_id == f.position_id)

    # Status filter for assigned/in_progress references activity subqueries
    # LEFT-JOINed in list_training_log. For the count query we don't need to
    # fetch those columns — just filter via correlated subqueries so the SQL
    # stays cheap.
    if f.status == "in_progress":
        stmt = stmt.where(
            and_(
                Enrollment.completed_at.is_(None),
                Enrollment.status != "completed",
                or_(
                    select(1)
                    .select_from(
                        Table(
                            "progress",
                            MetaData(),
                            Column("user_id", PG_UUID),
                            Column("course_id", PG_UUID),
                            Column("completed", Boolean),
                            Column("enrollment_id", PG_UUID),
                        )
                    )
                    .where(
                        and_(
                            text("progress.user_id = users.id"),
                            text("progress.course_id = courses.id"),
                            text("progress.completed = TRUE"),
                            text("((enrollments.recurring_assignment_id IS NULL AND progress.enrollment_id IS NULL) OR progress.enrollment_id = enrollments.id)"),
                        )
                    )
                    .exists(),
                    select(1)
                    .select_from(
                        Table("scorm_attempts", MetaData(), Column("user_id", PG_UUID), Column("course_id", PG_UUID))
                    )
                    .where(
                        and_(
                            text("scorm_attempts.user_id = users.id"),
                            text("scorm_attempts.course_id = courses.id"),
                        )
                    )
                    .exists(),
                ),
            )
        )
    elif f.status == "assigned":
        stmt = stmt.where(
            and_(
                Enrollment.completed_at.is_(None),
                Enrollment.status != "completed",
                ~select(1)
                .select_from(
                    Table(
                        "progress",
                        MetaData(),
                        Column("user_id", PG_UUID),
                        Column("course_id", PG_UUID),
                        Column("completed", Boolean),
                        Column("enrollment_id", PG_UUID),
                    )
                )
                .where(
                    and_(
                        text("progress.user_id = users.id"),
                        text("progress.course_id = courses.id"),
                        text("progress.completed = TRUE"),
                        text("((enrollments.recurring_assignment_id IS NULL AND progress.enrollment_id IS NULL) OR progress.enrollment_id = enrollments.id)"),
                    )
                )
                .exists(),
                ~select(1)
                .select_from(
                    Table("scorm_attempts", MetaData(), Column("user_id", PG_UUID), Column("course_id", PG_UUID))
                )
                .where(
                    and_(
                        text("scorm_attempts.user_id = users.id"),
                        text("scorm_attempts.course_id = courses.id"),
                    )
                )
                .exists(),
            )
        )
    elif f.status == "overdue":
        stmt = stmt.where(cycle_columns.deadline_status() == "overdue")

    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def _load_evidence_read_model(
    db: AsyncSession,
    tenant_id: UUID,
    rows,
) -> dict[UUID, dict[str, Any]]:
    """Batch-load evidence for a page; never issue one query per row.

    Events are reduced per enrollment and procedure type. The latest event in
    each correction/revocation chain is exposed, while the list preserves
    both ``training`` and ``knowledge_check`` when both exist.
    """
    enrollment_ids = {row["enrollment_id"] for row in rows}
    if not enrollment_ids:
        return {}
    events = list(
        (
            await db.scalars(
                select(TrainingEvidenceEvent).where(
                    TrainingEvidenceEvent.tenant_id == tenant_id,
                    TrainingEvidenceEvent.enrollment_id.in_(enrollment_ids),
                )
            )
        ).all()
    )
    if not events:
        return {enrollment_id: {"items": []} for enrollment_id in enrollment_ids}

    event_ids = [event.id for event in events]
    confirmations = list(
        (
            await db.scalars(
                select(TrainingEvidenceStepUpConfirmation).where(
                    TrainingEvidenceStepUpConfirmation.tenant_id == tenant_id,
                    TrainingEvidenceStepUpConfirmation.event_id.in_(event_ids),
                )
            )
        ).all()
    )
    holds = list(
        (
            await db.scalars(
                select(TrainingEvidenceLegalHold).where(
                    TrainingEvidenceLegalHold.tenant_id == tenant_id,
                    TrainingEvidenceLegalHold.event_id.in_(event_ids),
                )
            )
        ).all()
    )
    by_id = {event.id: event for event in events}
    confirmations_by_event: dict[UUID, list[TrainingEvidenceStepUpConfirmation]] = {}
    for confirmation in confirmations:
        confirmations_by_event.setdefault(confirmation.event_id, []).append(confirmation)
    holds_by_event: dict[UUID, list[TrainingEvidenceLegalHold]] = {}
    for hold in holds:
        holds_by_event.setdefault(hold.event_id, []).append(hold)

    def event_key(event: TrainingEvidenceEvent):
        return (event.occurred_at or event.created_at, event.created_at, str(event.id))

    def event_chain(event: TrainingEvidenceEvent) -> list[TrainingEvidenceEvent]:
        chain: list[TrainingEvidenceEvent] = []
        current: TrainingEvidenceEvent | None = event
        seen: set[UUID] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current)
            current = by_id.get(current.related_event_id) if current.related_event_id else None
        return chain

    grouped: dict[UUID, dict[str, list[TrainingEvidenceEvent]]] = {}
    for event in events:
        grouped.setdefault(event.enrollment_id, {}).setdefault(event.procedure_type, []).append(event)

    result: dict[UUID, dict[str, Any]] = {}
    for enrollment_id, procedures in grouped.items():
        items: list[dict[str, Any]] = []
        latest_events: list[tuple[TrainingEvidenceEvent, dict[str, Any]]] = []
        for procedure_type, procedure_events in procedures.items():
            latest = max(procedure_events, key=event_key)
            chain = event_chain(latest)
            chain_ids = {item.id for item in chain}
            root = chain[-1]
            required = isinstance(root.payload_snapshot, dict) and isinstance(
                root.payload_snapshot.get("confirmation"), dict
            )
            confirmed = any(confirmations_by_event.get(event_id) for event_id in chain_ids)
            active_hold = False
            for event_id in chain_ids:
                event_holds = sorted(
                    holds_by_event.get(event_id, []),
                    key=lambda hold: (hold.occurred_at or hold.created_at, hold.created_at, str(hold.id)),
                )
                if event_holds and event_holds[-1].action == "placed":
                    active_hold = True
                    break
            revoked = any(item.record_type == "revocation" for item in chain)
            if active_hold:
                evidence_state = "legal_hold"
            elif revoked:
                evidence_state = "revoked"
            elif required and not confirmed:
                evidence_state = "forming"
            else:
                evidence_state = "ready"
            confirmation_status = "not_required" if not required else "confirmed" if confirmed else "pending"
            item = {
                "event_id": latest.id,
                "procedure_type": procedure_type,
                "confirmation_status": confirmation_status,
                "evidence_state": evidence_state,
            }
            items.append(item)
            latest_events.append((latest, item))
        items.sort(key=lambda item: (item["procedure_type"], str(item["event_id"])))
        _, latest_item = max(latest_events, key=lambda pair: event_key(pair[0]))
        result[enrollment_id] = {
            "items": items,
            "latest_evidence_event_id": latest_item["event_id"],
            "evidence_procedure_type": latest_item["procedure_type"],
            "evidence_confirmation_status": latest_item["confirmation_status"],
            "evidence_state": latest_item["evidence_state"],
        }
    return result


async def list_training_log(
    db: AsyncSession,
    tenant_id: UUID,
    f: TrainingLogFilter,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return flat rows for the training log.

    Returns a list of dicts (not Pydantic) so the router can:
    - map to TrainingLogRow for JSON
    - stream to CSV for export
    without two separate codepaths.

    The query is a single SELECT with LEFT JOINs for org and (optional)
    aggregate subquery for quiz stats. Performance budget: <800 ms for
    a 10k × 50 page on Postgres with the existing indexes.
    """
    from app.models.kiosk_link import KioskAccessLog
    from app.modules.certificates.models import Certificate
    from app.modules.positions.models import Position as PositionModel

    # Position/Department join — LEFT JOIN so users without a position still appear.
    pos = (
        select(
            PositionModel.id.label("id"),
            PositionModel.name.label("name"),
            PositionModel.department_id.label("department_id"),
        )
        .where(PositionModel.tenant_id == tenant_id)
        .subquery()
    )
    dept = (
        select(
            Department.id.label("id"),
            Department.name.label("name"),
        )
        .where(Department.tenant_id == tenant_id)
        .subquery()
    )

    native_activity, scorm_activity, course_lessons = _build_activity_subqueries()

    stmt = (
        select(
            User.id.label("user_id"),
            (User.first_name + " " + User.last_name).label("full_name"),
            User.email,
            User.personnel_number,
            # Department comes from the user's position (Position.department_id),
            # NOT from User directly (User has no department_id column).
            pos.c.department_id.label("department_id"),
            dept.c.name.label("department_name"),
            User.position_id,
            pos.c.name.label("position_name"),
            CourseModel.id.label("course_id"),
            CourseModel.title.label("course_title"),
            CourseModel.delivery_type,
            Enrollment.status.label("enrollment_status"),
            Enrollment.source.label("enrollment_source"),
            Enrollment.id.label("enrollment_id"),
            Enrollment.content_release_id.label("content_release_id"),
            Enrollment.enrolled_at,
            Enrollment.completed_at,
            # Activity aggregates from the LEFT-JOINed subqueries.
            # COALESCE because LEFT JOIN yields NULL when no rows match.
            func.coalesce(native_activity.c.completed_lessons, 0).label("completed_lessons"),
            func.coalesce(course_lessons.c.total_lessons, 0).label("total_lessons"),
            func.coalesce(native_activity.c.has_progress, False).label("has_native_progress"),
            func.coalesce(scorm_activity.c.has_attempt, False).label("has_scorm_attempt"),
        )
        .select_from(User)
        .join(Enrollment, Enrollment.user_id == User.id)
        .join(CourseModel, CourseModel.id == Enrollment.course_id)
        .outerjoin(pos, pos.c.id == User.position_id)
        .outerjoin(dept, dept.c.id == pos.c.department_id)
        .outerjoin(
            native_activity,
            and_(
                native_activity.c.user_id == User.id,
                native_activity.c.course_id == CourseModel.id,
                or_(
                    native_activity.c.enrollment_id == Enrollment.id,
                    and_(
                        Enrollment.recurring_assignment_id.is_(None),
                        native_activity.c.enrollment_id.is_(None),
                    ),
                ),
            ),
        )
        .outerjoin(
            scorm_activity,
            and_(
                scorm_activity.c.user_id == User.id,
                scorm_activity.c.course_id == CourseModel.id,
            ),
        )
        .outerjoin(course_lessons, course_lessons.c.course_id == CourseModel.id)
    )

    stmt, cycle_columns = _join_cycle_read_model(stmt, tenant_id)
    stmt = stmt.add_columns(
        cycle_columns.cycle_id.label("cycle_id"),
        cycle_columns.cycle_type.label("cycle_type"),
        cycle_columns.scheduled_for.label("cycle_scheduled_for"),
        cycle_columns.due_at.label("cycle_due_at"),
        cycle_columns.deadline_status().label("deadline_status"),
    )

    stmt = _apply_filters(stmt, f, tenant_id)
    stmt = _apply_status_filter(stmt, f, native_activity, scorm_activity, cycle_columns)

    if f.department_id:
        stmt = stmt.where(pos.c.department_id == f.department_id)
    if f.position_id:
        stmt = stmt.where(User.position_id == f.position_id)

    # Multiple occurrences may share user/course/enrolled_at; identity breaks ties.
    stmt = stmt.order_by(desc(Enrollment.enrolled_at), User.id, CourseModel.id, Enrollment.id)
    stmt = stmt.limit(limit).offset(offset)

    rows = (await db.execute(stmt)).mappings().all()
    if not rows:
        return []

    evidence_by_enrollment = await _load_evidence_read_model(db, tenant_id, rows)

    # Batch-fetch extra fields: best quiz score, certificate, kiosk last-seen.
    user_ids = {r["user_id"] for r in rows}
    course_ids = {r["course_id"] for r in rows}

    # Quiz best score: max(score_percent) and count(*) per (user, course).
    quiz_stats_stmt = (
        select(
            _quiz_attempts.c.user_id.label("user_id"),
            _quiz_attempts.c.quiz_id.label("quiz_id"),
            _quiz_attempts.c.enrollment_id.label("enrollment_id"),
            func.max(_quiz_attempts.c.score_percent).label("best_score"),
            func.count(_quiz_attempts.c.id).label("attempts_count"),
        )
        .where(_quiz_attempts.c.tenant_id == tenant_id)
        .where(_quiz_attempts.c.user_id.in_(user_ids))
        .group_by(_quiz_attempts.c.user_id, _quiz_attempts.c.quiz_id, _quiz_attempts.c.enrollment_id)
        .subquery()
    )

    # For each (user, course) we need to know which quizzes belong to that
    # course. A quiz belongs to a lesson, and a lesson belongs to a module;
    # there is intentionally no quizzes.course_id column.
    _quizzes = Table(
        "quizzes",
        MetaData(),
        Column("id", PG_UUID),
        Column("lesson_id", PG_UUID),
        Column("tenant_id", PG_UUID),
    )
    _quiz_lessons = Table(
        "lessons",
        MetaData(),
        Column("id", PG_UUID),
        Column("module_id", PG_UUID),
    )
    _quiz_modules = Table(
        "modules",
        MetaData(),
        Column("id", PG_UUID),
        Column("course_id", PG_UUID),
    )
    quiz_course_stmt = (
        select(
            _quizzes.c.id.label("quiz_id"),
            _quiz_modules.c.course_id.label("course_id"),
        )
        .select_from(
            _quizzes.join(_quiz_lessons, _quiz_lessons.c.id == _quizzes.c.lesson_id).join(
                _quiz_modules, _quiz_modules.c.id == _quiz_lessons.c.module_id
            )
        )
        .where(_quizzes.c.tenant_id == tenant_id)
        .where(_quiz_modules.c.course_id.in_(course_ids))
        .subquery()
    )

    quiz_join_stmt = (
        select(
            quiz_course_stmt.c.course_id.label("course_id"),
            quiz_stats_stmt.c.user_id.label("user_id"),
            quiz_stats_stmt.c.enrollment_id.label("enrollment_id"),
            func.max(quiz_stats_stmt.c.best_score).label("best_score"),
            func.sum(quiz_stats_stmt.c.attempts_count).label("attempts_count"),
        )
        .select_from(quiz_course_stmt)
        .join(
            quiz_stats_stmt,
            quiz_stats_stmt.c.quiz_id == quiz_course_stmt.c.quiz_id,
        )
        .group_by(
            quiz_course_stmt.c.course_id,
            quiz_stats_stmt.c.user_id,
            quiz_stats_stmt.c.enrollment_id,
        )
    )
    quiz_rows = (await db.execute(quiz_join_stmt)).mappings().all()
    quiz_by_pair = {
        (r["user_id"], r["course_id"], r["enrollment_id"]): {
            "best_score": r["best_score"],
            "quiz_attempts_count": int(r["attempts_count"] or 0),
        }
        for r in quiz_rows
    }

    # Certificate: one row per (user, course).
    cert_stmt = select(
        Certificate.user_id,
        Certificate.course_id,
        Certificate.enrollment_id,
        Certificate.id.label("certificate_id"),
        Certificate.certificate_number,
        Certificate.issued_at,
    ).where(
        Certificate.tenant_id == tenant_id,
        Certificate.user_id.in_(user_ids),
        Certificate.course_id.in_(course_ids),
    )
    cert_rows = (await db.execute(cert_stmt)).mappings().all()
    cert_by_pair = {
        (r["user_id"], r["course_id"], r["enrollment_id"]): {
            "certificate_id": r["certificate_id"],
            "certificate_number": r["certificate_number"],
            "certificate_issued_at": r["issued_at"],
        }
        for r in cert_rows
    }

    # Kiosk last seen per user (most recent kiosk_access_log entry).
    kiosk_stmt = (
        select(
            KioskAccessLog.user_id,
            func.max(KioskAccessLog.created_at).label("last_seen"),
        )
        .where(
            KioskAccessLog.tenant_id == tenant_id,
            KioskAccessLog.user_id.in_(user_ids),
        )
        .group_by(KioskAccessLog.user_id)
    )
    kiosk_rows = (await db.execute(kiosk_stmt)).mappings().all()
    kiosk_by_user = {r["user_id"]: r["last_seen"] for r in kiosk_rows}

    # Assemble result.
    # progress_percent:
    #   - completed enrollment → 100
    #   - SCORM, not completed → 0 (no proper SCORM progress map yet — see
    #     schemas.py docstring)
    #   - native, not completed → completed_lessons / total_lessons * 100
    #     (0 if no lessons or no progress)
    # computed_status:
    #   - completed  if is_completed
    #   - in_progress if has_native_progress OR has_scorm_attempt
    #   - assigned   otherwise
    result: list[dict[str, Any]] = []
    for r in rows:
        is_completed = r["enrollment_status"] == "completed" or r["completed_at"] is not None
        is_scorm = r["delivery_type"] == "scorm"
        has_native_progress = bool(r["has_native_progress"])
        has_scorm_attempt = bool(r["has_scorm_attempt"])
        completed_lessons = int(r["completed_lessons"] or 0)
        total_lessons = int(r["total_lessons"] or 0)

        if is_completed:
            progress_percent = 100
            computed_status = "completed"
        elif is_scorm:
            # SCORM progress map is a known simplification (see schemas.py).
            # We have an attempt but no granular percent.
            progress_percent = 0
            computed_status = "in_progress" if has_scorm_attempt else "assigned"
        else:
            # Native course: percent = completed / total.
            if total_lessons > 0:
                progress_percent = int(round(completed_lessons * 100 / total_lessons))
            else:
                progress_percent = 0
            computed_status = "in_progress" if has_native_progress else "assigned"

        quiz_info = quiz_by_pair.get((r["user_id"], r["course_id"], r["enrollment_id"]), {})
        # Current certificates are bound to the exact enrollment for both
        # one-time and recurring assignments. Retain a fallback for legacy
        # one-time certificates created before enrollment binding existed.
        cert_info = cert_by_pair.get(
            (r["user_id"], r["course_id"], r["enrollment_id"]),
        )
        if cert_info is None and r["enrollment_source"] != "recurring":
            cert_info = cert_by_pair.get((r["user_id"], r["course_id"], None))
        cert_info = cert_info or {}
        evidence_info = evidence_by_enrollment.get(
            r["enrollment_id"],
            {
                "items": [],
                "latest_evidence_event_id": None,
                "evidence_procedure_type": None,
                "evidence_confirmation_status": "not_required",
                "evidence_state": "incomplete",
            },
        )
        result.append(
            {
                "user_id": r["user_id"],
                "full_name": (r["full_name"] or "").strip() or "—",
                "email": r["email"],
                "personnel_number": r["personnel_number"],
                "department_id": r["department_id"],
                "department_name": r["department_name"],
                "position_id": r["position_id"],
                "position_name": r["position_name"],
                "course_id": r["course_id"],
                "course_title": r["course_title"],
                "delivery_type": r["delivery_type"],
                "enrollment_status": r["enrollment_status"],
                "enrollment_source": r["enrollment_source"],
                "enrollment_id": r["enrollment_id"],
                "content_release_id": r["content_release_id"],
                "enrolled_at": r["enrolled_at"],
                "completed_at": r["completed_at"],
                "cycle_id": r["cycle_id"],
                "cycle_type": r["cycle_type"],
                "cycle_scheduled_for": r["cycle_scheduled_for"],
                "cycle_due_at": r["cycle_due_at"],
                "deadline_status": r["deadline_status"],
                "computed_status": computed_status,
                "progress_percent": progress_percent,
                "best_score": quiz_info.get("best_score"),
                "quiz_attempts_count": quiz_info.get("quiz_attempts_count", 0),
                "certificate_id": cert_info.get("certificate_id"),
                "certificate_number": cert_info.get("certificate_number"),
                "certificate_issued_at": cert_info.get("certificate_issued_at"),
                "kiosk_last_seen_at": kiosk_by_user.get(r["user_id"]),
                "latest_evidence_event_id": evidence_info.get("latest_evidence_event_id"),
                "evidence_procedure_type": evidence_info.get("evidence_procedure_type"),
                "evidence_confirmation_status": evidence_info.get("evidence_confirmation_status", "not_required"),
                "evidence_state": evidence_info.get("evidence_state", "incomplete"),
                "evidence_events": evidence_info.get("items", []),
            }
        )
    return result


async def stream_training_log_csv(
    db: AsyncSession,
    tenant_id: UUID,
    f: TrainingLogFilter,
    batch_size: int = 500,
):
    """Yield CSV rows in batches. Used by the export endpoint so the
    response streams instead of materializing 100k rows in memory."""

    offset = 0
    while True:
        rows = await list_training_log(db, tenant_id, f, limit=batch_size, offset=offset)
        if not rows:
            break
        yield rows
        if len(rows) < batch_size:
            break
        offset += batch_size
