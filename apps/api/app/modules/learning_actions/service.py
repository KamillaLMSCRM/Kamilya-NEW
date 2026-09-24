from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.modules.learning_actions.models import LearningAction, LearningActionEvent
from app.modules.learning_actions.policy import (
    LearningActionValidationError,
    classify_training_issue,
    select_weak_questions,
    validate_close_request,
)
from app.modules.learning_actions.schemas import (
    ActionType,
    LearningActionCreate,
    LearningActionList,
    LearningActionRecord,
    LearningActionSummary,
    TrainingActionSuggestion,
    WeakQuestionSuggestion,
)
from app.modules.learning_insights.schemas import CourseInsights
from app.modules.learning_insights.service import (
    LearningInsightsNotFoundError,
    get_course_insights,
    get_enrollment_insights,
)
from app.modules.training_log.schemas import TrainingLogFilter, TrainingLogRow
from app.modules.training_log.service import get_training_log_page, get_training_log_summary

MAX_ACTION_ROWS = 500


class LearningActionNotFoundError(LookupError):
    """The requested action or tenant-owned signal does not exist."""


class LearningActionConflictError(RuntimeError):
    """An action is stale, already closed, or duplicates an active action."""


def _canonical_id(value: UUID | str | None) -> str | None:
    return str(UUID(str(value))) if value is not None else None


def enrollment_target_key(enrollment_id: UUID | str) -> str:
    return f"enrollment:{_canonical_id(enrollment_id)}"


def question_target_key(
    *,
    course_id: UUID | str,
    quiz_id: UUID | str,
    content_release_id: UUID | str | None,
    question_id: UUID | str,
    question_key: str,
) -> str:
    return ":".join(
        (
            "question",
            _canonical_id(course_id) or "",
            _canonical_id(quiz_id) or "",
            _canonical_id(content_release_id) or "-",
            _canonical_id(question_id) or "",
            question_key,
        )
    )


def _question_target_key(question: Any, course_id: UUID | str) -> str:
    return question_target_key(
        course_id=course_id,
        quiz_id=question.quiz_id,
        content_release_id=question.content_release_id,
        question_id=question.question_id,
        question_key=question.question_key,
    )


def _enrollment_signal(row: Any) -> dict[str, Any]:
    return {
        "enrollment_id": str(row.enrollment_id),
        "course_id": str(row.course_id),
        "computed_status": row.computed_status,
        "deadline_status": row.deadline_status,
        "progress_percent": row.progress_percent,
        "quiz_attempts_count": row.quiz_attempts_count,
        "best_score": row.best_score,
        "failed_required_quiz": row.failed_required_quiz,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _attempt_signal(insights: Any) -> dict[str, Any]:
    attempts = insights.attempts
    return {
        "attempt_count": len(attempts),
        "best_score": max((attempt.score_percent for attempt in attempts), default=None),
        "latest_score": attempts[-1].score_percent if attempts else None,
        "passed_attempts": sum(1 for attempt in attempts if attempt.passed),
        "verified_attempts": sum(1 for attempt in attempts if attempt.evidence_status == "verified"),
    }


def _question_signal(question: Any) -> dict[str, Any]:
    return {
        "question_id": question.question_id,
        "question_key": question.question_key,
        "quiz_id": question.quiz_id,
        "content_release_id": question.content_release_id,
        "respondents": question.respondents,
        "incorrect": question.incorrect,
        "incorrect_percent": question.incorrect_percent,
        "latest_respondents": question.latest_respondents,
        "latest_incorrect_percent": question.latest_incorrect_percent,
        "review_status": question.review.status,
    }


async def _get_enrollment_row(
    db: AsyncSession, *, tenant_id: UUID, enrollment_id: UUID, history: bool
) -> TrainingLogRow | None:
    page = await get_training_log_page(
        db,
        tenant_id,
        TrainingLogFilter(enrollment_id=enrollment_id, history=history),
        limit=1,
        offset=0,
    )
    return page.items[0] if page.items else None


async def _capture_enrollment_snapshot(
    db: AsyncSession, *, tenant_id: UUID, enrollment_id: UUID, require_current: bool
) -> tuple[UUID, dict[str, Any]]:
    row = await _get_enrollment_row(db, tenant_id=tenant_id, enrollment_id=enrollment_id, history=not require_current)
    if row is None:
        raise LearningActionNotFoundError("Enrollment occurrence not found")
    try:
        insights = await get_enrollment_insights(db, tenant_id=tenant_id, enrollment_id=enrollment_id)
    except LearningInsightsNotFoundError as exc:
        raise LearningActionNotFoundError("Enrollment occurrence not found") from exc
    return row.course_id, {"training": _enrollment_signal(row), "assessment": _attempt_signal(insights)}


async def _capture_question_snapshot(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    course_id: UUID,
    quiz_id: UUID,
    content_release_id: UUID | None,
    question_id: UUID,
    question_key: str,
    require_weak: bool,
) -> dict[str, Any]:
    try:
        course: CourseInsights = await get_course_insights(db, tenant_id=tenant_id, course_id=course_id)
    except LearningInsightsNotFoundError as exc:
        raise LearningActionNotFoundError("Course not found") from exc
    matches = [
        question
        for question in course.questions
        if question.question_key == question_key
        and _canonical_id(question.quiz_id) == str(quiz_id)
        and _canonical_id(question.content_release_id) == _canonical_id(content_release_id)
        and _canonical_id(question.question_id) == str(question_id)
    ]
    if not matches:
        raise LearningActionNotFoundError("Question evidence not found in the selected course")
    question = matches[0]
    if require_weak and question not in select_weak_questions(course.questions):
        raise LearningActionConflictError("Question is no longer a weak-question signal")
    return _question_signal(question)


async def list_learning_actions(
    db: AsyncSession, *, tenant_id: UUID, course_id: UUID | None, status: str
) -> LearningActionList:
    training_filter = TrainingLogFilter(course_id=course_id)
    training_page = await get_training_log_page(db, tenant_id, training_filter, limit=MAX_ACTION_ROWS, offset=0)
    training_summary = await get_training_log_summary(db, tenant_id, training_filter)
    issue_rows = []
    issue_counts: dict[str, int] = {}
    for row in training_page.items:
        issue = classify_training_issue(row)
        if issue is not None:
            issue_rows.append((row, issue))
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    action_query = select(LearningAction).where(
        LearningAction.tenant_id == tenant_id,
        LearningAction.status == status,
    )
    if course_id is not None:
        action_query = action_query.where(LearningAction.course_id == course_id)
    action_rows = list(
        (
            await db.scalars(
                action_query.order_by(LearningAction.created_at.desc(), LearningAction.id).limit(MAX_ACTION_ROWS)
            )
        ).all()
    )
    weak_question_rows = []
    if course_id is not None:
        selected_course_id = course_id
        try:
            insights = await get_course_insights(db, tenant_id=tenant_id, course_id=selected_course_id)
        except LearningInsightsNotFoundError as exc:
            raise LearningActionNotFoundError("Course not found") from exc
        weak_question_rows = select_weak_questions(insights.questions)

    question_course_id = cast(UUID, course_id)
    target_keys = {enrollment_target_key(row.enrollment_id) for row, _issue in issue_rows} | {
        _question_target_key(question, question_course_id) for question in weak_question_rows
    }
    active_by_target: dict[tuple[str, str], UUID] = {}
    active_types_by_target: dict[tuple[str, str], list[ActionType]] = {}
    if target_keys:
        active_rows = list(
            (
                await db.scalars(
                    select(LearningAction)
                    .where(
                        LearningAction.tenant_id == tenant_id,
                        LearningAction.status == "open",
                        LearningAction.target_key.in_(target_keys),
                    )
                    .order_by(LearningAction.created_at.desc(), LearningAction.id)
                )
            ).all()
        )
        for action in active_rows:
            key = (action.target_key, action.issue_type)
            active_by_target.setdefault(key, action.id)
            active_types = active_types_by_target.setdefault(key, [])
            typed_action = cast(ActionType, action.action_type)
            if typed_action not in active_types:
                active_types.append(typed_action)

    training_items = [
        TrainingActionSuggestion.model_validate(
            {
                **row.model_dump(),
                "issue_type": issue,
                "active_action_id": active_by_target.get((enrollment_target_key(row.enrollment_id), issue)),
                "active_action_types": active_types_by_target.get(
                    (enrollment_target_key(row.enrollment_id), issue), []
                ),
            }
        )
        for row, issue in issue_rows
    ]
    weak_questions = [
        WeakQuestionSuggestion.model_validate(
            {
                **question.model_dump(),
                "active_action_id": active_by_target.get(
                    (_question_target_key(question, question_course_id), "weak_question")
                ),
                "active_action_types": active_types_by_target.get(
                    (_question_target_key(question, question_course_id), "weak_question"), []
                ),
            }
        )
        for question in weak_question_rows
    ]

    action_count_query = (
        select(func.count())
        .select_from(LearningAction)
        .where(
            LearningAction.tenant_id == tenant_id,
            LearningAction.status == status,
            *([LearningAction.course_id == course_id] if course_id is not None else []),
        )
    )
    open_action_count_query = (
        select(func.count())
        .select_from(LearningAction)
        .where(
            LearningAction.tenant_id == tenant_id,
            LearningAction.status == "open",
            *([LearningAction.course_id == course_id] if course_id is not None else []),
        )
    )
    action_count = int(await db.scalar(action_count_query) or 0)
    open_action_count = int(await db.scalar(open_action_count_query) or 0)
    overdue_action_count_query = (
        select(func.count())
        .select_from(LearningAction)
        .where(
            LearningAction.tenant_id == tenant_id,
            LearningAction.status == "open",
            LearningAction.due_at.is_not(None),
            LearningAction.due_at < datetime.now(UTC),
            *([LearningAction.course_id == course_id] if course_id is not None else []),
        )
    )
    overdue_action_count = int(await db.scalar(overdue_action_count_query) or 0)
    # Lists are bounded; explicit flags distinguish a clipped view from a full one.
    return LearningActionList(
        summary=LearningActionSummary(
            training_log=training_summary,
            training_issue_count=len(issue_rows),
            training_issue_counts=issue_counts,
            training_items_truncated=training_page.total > len(training_page.items),
            weak_question_count=len(weak_questions),
            action_count=action_count,
            actions_truncated=action_count > len(action_rows),
            open_action_count=open_action_count,
            overdue_action_count=overdue_action_count,
        ),
        training_items=training_items,
        weak_questions=weak_questions,
        actions=[LearningActionRecord.model_validate(row) for row in action_rows],
    )


async def create_learning_action(
    db: AsyncSession, *, tenant_id: UUID, actor_id: UUID | None, body: LearningActionCreate
) -> LearningActionRecord:
    owner_id = body.owner_id or actor_id
    if owner_id is None:
        raise LearningActionConflictError("Choose an action owner when acting through platform impersonation")
    owner = await db.scalar(
        select(User.id).where(User.id == owner_id, User.tenant_id == tenant_id, User.is_active.is_(True))
    )
    if owner is None:
        raise LearningActionNotFoundError("Action owner not found")

    if body.target_type == "enrollment":
        assert body.enrollment_id is not None
        course_id, snapshot = await _capture_enrollment_snapshot(
            db, tenant_id=tenant_id, enrollment_id=body.enrollment_id, require_current=True
        )
        if body.course_id is not None and body.course_id != course_id:
            raise LearningActionNotFoundError("Enrollment does not belong to the selected course")
        row = await _get_enrollment_row(db, tenant_id=tenant_id, enrollment_id=body.enrollment_id, history=False)
        if row is None or classify_training_issue(row) != body.issue_type:
            raise LearningActionConflictError("The enrollment no longer has the requested training issue")
        target_key = enrollment_target_key(body.enrollment_id)
        enrollment_id = body.enrollment_id
        quiz_id = content_release_id = question_id = question_key = None
    else:
        assert body.course_id is not None and body.quiz_id is not None and body.question_id is not None
        assert body.question_key is not None
        snapshot = {
            "question": await _capture_question_snapshot(
                db,
                tenant_id=tenant_id,
                course_id=body.course_id,
                quiz_id=body.quiz_id,
                content_release_id=body.content_release_id,
                question_id=body.question_id,
                question_key=body.question_key,
                require_weak=True,
            )
        }
        target_key = question_target_key(
            course_id=body.course_id,
            quiz_id=body.quiz_id,
            content_release_id=body.content_release_id,
            question_id=body.question_id,
            question_key=body.question_key,
        )
        course_id = body.course_id
        enrollment_id = None
        quiz_id = body.quiz_id
        content_release_id = body.content_release_id
        question_id = body.question_id
        question_key = body.question_key

    now = datetime.now(UTC)
    duplicate_id = await db.scalar(
        select(LearningAction.id).where(
            LearningAction.tenant_id == tenant_id,
            LearningAction.target_key == target_key,
            LearningAction.issue_type == body.issue_type,
            LearningAction.action_type == body.action_type,
            LearningAction.status == "open",
        )
    )
    if duplicate_id is not None:
        raise LearningActionConflictError("An active action already exists for this target, issue and action")
    action = LearningAction(
        id=uuid4(),
        tenant_id=tenant_id,
        target_type=body.target_type,
        target_key=target_key,
        enrollment_id=enrollment_id,
        course_id=course_id,
        quiz_id=quiz_id,
        content_release_id=content_release_id,
        question_id=question_id,
        question_key=question_key,
        issue_type=body.issue_type,
        action_type=body.action_type,
        owner_id=owner_id,
        created_by=actor_id,
        due_at=body.due_at,
        comment=body.comment,
        baseline_snapshot=snapshot,
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(action)
    try:
        await db.flush()
    except IntegrityError as exc:
        # A concurrent create can win after the pre-check. The request
        # transaction is rolled back by the session boundary after this error;
        # never issue another query from the failed transaction here.
        raise LearningActionConflictError("An active action already exists for this target, issue and action") from exc
    db.add(
        LearningActionEvent(
            tenant_id=tenant_id,
            action_id=action.id,
            event_type="created",
            actor_id=actor_id,
            payload={"baseline_snapshot": snapshot},
        )
    )
    await db.flush()
    return LearningActionRecord.model_validate(action)


async def _capture_outcome(db: AsyncSession, *, tenant_id: UUID, action: LearningAction) -> dict[str, Any]:
    captured_at = datetime.now(UTC).isoformat()
    try:
        if action.target_type == "enrollment":
            assert action.enrollment_id is not None
            course_id, snapshot = await _capture_enrollment_snapshot(
                db, tenant_id=tenant_id, enrollment_id=action.enrollment_id, require_current=False
            )
            return {"captured_at": captured_at, "available": True, "course_id": str(course_id), **snapshot}
        assert action.quiz_id is not None and action.question_id is not None and action.question_key is not None
        snapshot = await _capture_question_snapshot(
            db,
            tenant_id=tenant_id,
            course_id=action.course_id,
            quiz_id=action.quiz_id,
            content_release_id=action.content_release_id,
            question_id=action.question_id,
            question_key=action.question_key,
            require_weak=False,
        )
        return {"captured_at": captured_at, "available": True, "question": snapshot}
    except LearningActionNotFoundError:
        return {"captured_at": captured_at, "available": False, "reason": "target_evidence_unavailable"}


async def close_learning_action(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    action_id: UUID,
    resolution: str,
    note: str | None,
) -> LearningActionRecord:
    try:
        validate_close_request(resolution=resolution, note=note)  # type: ignore[arg-type]
    except LearningActionValidationError as exc:
        raise LearningActionConflictError(str(exc)) from exc
    action = await db.scalar(
        select(LearningAction)
        .where(LearningAction.id == action_id, LearningAction.tenant_id == tenant_id)
        .with_for_update()
    )
    if action is None:
        raise LearningActionNotFoundError("Action not found")
    if action.status != "open":
        raise LearningActionConflictError("Action is already closed")
    outcome = await _capture_outcome(db, tenant_id=tenant_id, action=action)
    if resolution == "observed" and not outcome.get("available"):
        raise LearningActionConflictError("Observed closure requires an available outcome snapshot")
    now = datetime.now(UTC)
    action.status = "cancelled" if resolution == "cancelled" else "completed"
    action.resolution = resolution
    action.resolution_note = note.strip() if note else None
    action.outcome_snapshot = outcome
    action.closed_at = now
    action.updated_at = now
    db.add(
        LearningActionEvent(
            tenant_id=tenant_id,
            action_id=action.id,
            event_type="closed",
            actor_id=actor_id,
            payload={"resolution": resolution, "note": action.resolution_note, "outcome_snapshot": outcome},
        )
    )
    await db.flush()
    return LearningActionRecord.model_validate(action)
