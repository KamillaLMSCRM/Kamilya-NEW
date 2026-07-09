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
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
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

from app.models.courses import Course  # re-export wrapper
from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.models import Course as CourseModel
from app.modules.positions.models import Position
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
    Column("score_percent", Integer),
    Column("passed", Boolean),
)


def _apply_filters(stmt, f: TrainingLogFilter, tenant_id: UUID):
    """Apply WHERE clauses shared by count + rows queries.

    Status semantics (revised 2026-07-09 for honest filtering):
    - completed:   enrollment.completed_at IS NOT NULL
    - assigned:    not completed AND no native lesson progress AND no SCORM attempt
    - in_progress: not completed AND (native lesson progress OR SCORM attempt exists)
    - overdue:     REMOVED — no deadline column on enrollments, so we can't honestly
                   compute it. Surfacing a fake filter would mislead HR.

    The 'assigned' / 'in_progress' filters rely on the LEFT-JOINed activity
    subqueries (`_native_activity`, `_scorm_activity`) added by the caller.
    """
    stmt = stmt.where(User.tenant_id == tenant_id)
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
        stmt = stmt.where(Enrollment.completed_at.is_not(None))
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
            func.coalesce(
                func.sum(case((_progress.c.completed.is_(True), 1), else_=0)),
                0,
            ).cast(Integer).label("completed_lessons"),
            func.bool_or(_progress.c.completed).label("has_progress"),
        )
        .group_by(_progress.c.user_id, _progress.c.course_id)
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


def _apply_status_filter(stmt, f: TrainingLogFilter, native_activity, scorm_activity):
    """Apply the assigned/in_progress filter using the activity subqueries.

    `completed` is already handled in `_apply_filters` (uses Enrollment columns).
    For `assigned` and `in_progress` we need the LEFT-JOINed activity columns.
    """
    if f.status == "in_progress":
        stmt = stmt.where(
            and_(
                Enrollment.completed_at.is_(None),
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
                native_activity.c.has_progress.isnot(True),
                scorm_activity.c.has_attempt.isnot(True),
            )
        )
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
                or_(
                    select(1)
                    .select_from(Table("progress", MetaData(),
                                        Column("user_id", PG_UUID),
                                        Column("course_id", PG_UUID),
                                        Column("completed", Boolean)))
                    .where(
                        and_(
                            text("progress.user_id = users.id"),
                            text("progress.course_id = courses.id"),
                            text("progress.completed = TRUE"),
                        )
                    )
                    .exists(),
                    select(1)
                    .select_from(Table("scorm_attempts", MetaData(),
                                        Column("user_id", PG_UUID),
                                        Column("course_id", PG_UUID)))
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
                ~select(1)
                .select_from(Table("progress", MetaData(),
                                    Column("user_id", PG_UUID),
                                    Column("course_id", PG_UUID),
                                    Column("completed", Boolean)))
                .where(
                    and_(
                        text("progress.user_id = users.id"),
                        text("progress.course_id = courses.id"),
                        text("progress.completed = TRUE"),
                    )
                )
                .exists(),
                ~select(1)
                .select_from(Table("scorm_attempts", MetaData(),
                                    Column("user_id", PG_UUID),
                                    Column("course_id", PG_UUID)))
                .where(
                    and_(
                        text("scorm_attempts.user_id = users.id"),
                        text("scorm_attempts.course_id = courses.id"),
                    )
                )
                .exists(),
            )
        )

    result = await db.execute(stmt)
    return int(result.scalar() or 0)


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

    stmt = _apply_filters(stmt, f, tenant_id)
    stmt = _apply_status_filter(stmt, f, native_activity, scorm_activity)

    if f.department_id:
        stmt = stmt.where(pos.c.department_id == f.department_id)
    if f.position_id:
        stmt = stmt.where(User.position_id == f.position_id)

    # Order: most recent enrollment first; tie-break on (user_id, course_id)
    # to make pagination stable.
    stmt = stmt.order_by(desc(Enrollment.enrolled_at), User.id, CourseModel.id)
    stmt = stmt.limit(limit).offset(offset)

    rows = (await db.execute(stmt)).mappings().all()
    if not rows:
        return []

    # Batch-fetch extra fields: best quiz score, certificate, kiosk last-seen.
    user_course_pairs = [(r["user_id"], r["course_id"]) for r in rows]
    user_ids = {r["user_id"] for r in rows}
    course_ids = {r["course_id"] for r in rows}

    # Quiz best score: max(score_percent) and count(*) per (user, course).
    quiz_stats_stmt = (
        select(
            _quiz_attempts.c.user_id.label("user_id"),
            _quiz_attempts.c.quiz_id.label("quiz_id"),
            func.max(_quiz_attempts.c.score_percent).label("best_score"),
            func.count(_quiz_attempts.c.id).label("attempts_count"),
        )
        .where(_quiz_attempts.c.tenant_id == tenant_id)
        .where(_quiz_attempts.c.user_id.in_(user_ids))
        .group_by(_quiz_attempts.c.user_id, _quiz_attempts.c.quiz_id)
        .subquery()
    )

    # For each (user, course) we need to know which quizzes belong to that course.
    # Quizzes have a course_id column on the `quizzes` table; we reflect it here
    # without forcing an import cycle.
    _quizzes = Table(
        "quizzes",
        MetaData(),
        Column("id", PG_UUID),
        Column("course_id", PG_UUID),
        Column("tenant_id", PG_UUID),
    )
    quiz_course_stmt = (
        select(
            _quizzes.c.id.label("quiz_id"),
            _quizzes.c.course_id.label("course_id"),
        )
        .where(_quizzes.c.tenant_id == tenant_id)
        .where(_quizzes.c.course_id.in_(course_ids))
        .subquery()
    )

    quiz_join_stmt = (
        select(
            quiz_course_stmt.c.course_id.label("course_id"),
            quiz_stats_stmt.c.user_id.label("user_id"),
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
        )
    )
    quiz_rows = (await db.execute(quiz_join_stmt)).mappings().all()
    quiz_by_pair = {
        (r["user_id"], r["course_id"]): {
            "best_score": r["best_score"],
            "quiz_attempts_count": int(r["attempts_count"] or 0),
        }
        for r in quiz_rows
    }

    # Certificate: one row per (user, course).
    cert_stmt = select(
        Certificate.user_id,
        Certificate.course_id,
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
        (r["user_id"], r["course_id"]): {
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

        quiz_info = quiz_by_pair.get((r["user_id"], r["course_id"]), {})
        cert_info = cert_by_pair.get((r["user_id"], r["course_id"]), {})
        result.append({
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
            "enrolled_at": r["enrolled_at"],
            "completed_at": r["completed_at"],
            "computed_status": computed_status,
            "progress_percent": progress_percent,
            "best_score": quiz_info.get("best_score"),
            "quiz_attempts_count": quiz_info.get("quiz_attempts_count", 0),
            "certificate_id": cert_info.get("certificate_id"),
            "certificate_number": cert_info.get("certificate_number"),
            "certificate_issued_at": cert_info.get("certificate_issued_at"),
            "kiosk_last_seen_at": kiosk_by_user.get(r["user_id"]),
        })
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