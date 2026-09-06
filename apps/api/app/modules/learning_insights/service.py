"""Immutable-evidence readers and annotation persistence for LI-API V1.

The reporting code deliberately does not consult live ``Question`` or
``QuizChoice`` rows.  A completed attempt is useful only when its frozen
snapshot verifies and agrees with the tenant-scoped database identities.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.learning_insights.schemas import (
    AttemptDetail,
    ChoiceDetail,
    CourseInsights,
    EnrollmentInsights,
    QuestionDetail,
    QuestionStats,
    Review,
    ReviewStatus,
    WrongChoice,
)
from app.modules.positions.models import Position
from app.modules.quizzes.models import QuizAttempt

MAX_ENROLLMENT_ATTEMPTS = 500
MAX_CANDIDATE_ATTEMPTS = 5_000


class LearningInsightsNotFoundError(LookupError):
    """The requested resource is absent from the caller's tenant."""


class LearningInsightsValidationError(ValueError):
    """A bounded reporting query cannot safely be fulfilled."""


class SnapshotUnavailableError(ValueError):
    """An annotation cannot be attached when immutable evidence is unavailable."""


class CompletedAttempt(Protocol):
    """Instance values read from the legacy untyped SQLAlchemy model.

    SQL expressions continue to use QuizAttempt; this read interface describes
    the completed rows admitted by the tenant-scoped query, not Column objects.
    """

    id: UUID
    tenant_id: UUID
    user_id: UUID
    enrollment_id: UUID | None
    quiz_id: UUID
    content_release_id: UUID | None
    completed_at: datetime
    score_percent: int
    passed: bool
    total_points: int
    earned_points: int
    evidence_snapshot: Any
    evidence_sha256: str | None


@dataclass(frozen=True, slots=True)
class VerifiedSnapshot:
    snapshot: dict[str, Any]
    questions_by_id: dict[str, dict[str, Any]]
    answers_by_question_id: dict[str, dict[str, Any]]


def _as_uuid_string(value: UUID | str | None) -> str | None:
    return str(value) if value is not None else None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _is_uuid_string(value: object) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _canonical_question_definition(question: dict[str, Any]) -> dict[str, Any]:
    """Copy every historical definition field except response/grade artefacts."""
    definition = copy.deepcopy(question)
    # Only top-level answer artefacts are excluded.  In particular,
    # ``choice.is_correct`` is part of the frozen question definition and must
    # therefore change the key when an answer key is corrected.
    for key in ("selected", "selected_choice_ids", "is_correct", "points_earned", "points_possible"):
        definition.pop(key, None)
    return definition


def question_key(*, quiz_id: UUID | str, content_release_id: UUID | str | None, question: dict[str, Any]) -> str:
    """Stable version-aware key; release changes and definition changes never mix."""
    payload = {
        "quiz_id": str(quiz_id),
        "content_release_id": _as_uuid_string(content_release_id),
        "question": _canonical_question_definition(question),
    }
    # ``canonical_json_sha256`` is the shared canonicalizer used by releases
    # and evidence snapshots; its digest is exactly the required SHA-256 key.
    return canonical_json_sha256(payload)


def validate_attempt_snapshot(
    attempt: CompletedAttempt,
    *,
    course_id: UUID,
    release: ContentRelease | None,
) -> VerifiedSnapshot | None:
    """Return verified evidence, ``None`` for absent evidence, or raise for corruption."""
    snapshot = attempt.evidence_snapshot
    evidence_sha256 = attempt.evidence_sha256
    if snapshot is None and evidence_sha256 is None:
        return None
    if not isinstance(snapshot, dict) or not isinstance(evidence_sha256, str) or len(evidence_sha256) != 64:
        raise ValueError("Attempt evidence snapshot is incomplete")
    if canonical_json_sha256(snapshot) != evidence_sha256:
        raise ValueError("Attempt evidence checksum does not match")
    if snapshot.get("schema_version") != 1:
        raise ValueError("Attempt evidence schema version is unsupported")

    attempt_data = snapshot.get("attempt")
    quiz_data = snapshot.get("quiz")
    graded_answers = snapshot.get("graded_answers")
    if not isinstance(attempt_data, dict) or not isinstance(quiz_data, dict) or not isinstance(graded_answers, list):
        raise ValueError("Attempt evidence snapshot has an unsupported structure")

    expected = {
        "id": attempt.id,
        "tenant_id": attempt.tenant_id,
        "user_id": attempt.user_id,
        "enrollment_id": attempt.enrollment_id,
        "course_id": course_id,
        "content_release_id": attempt.content_release_id,
        "quiz_id": attempt.quiz_id,
    }
    for name, value in expected.items():
        if _as_uuid_string(attempt_data.get(name)) != _as_uuid_string(value):
            raise ValueError(f"Attempt evidence {name} does not match the database record")
    if (
        _as_uuid_string(quiz_data.get("id")) != str(attempt.quiz_id)
        or not isinstance(quiz_data.get("title"), str)
        or not quiz_data["title"].strip()
    ):
        raise ValueError("Attempt evidence quiz does not match the database record")
    if attempt_data.get("score_percent") != attempt.score_percent or attempt_data.get("passed") != attempt.passed:
        raise ValueError("Attempt evidence outcome does not match the database record")
    completed_at = _parse_aware_timestamp(attempt_data.get("completed_at"))
    if (
        completed_at is None
        or not isinstance(attempt.completed_at, datetime)
        or attempt.completed_at.tzinfo is None
        or completed_at != attempt.completed_at.astimezone(UTC)
    ):
        raise ValueError("Attempt evidence completion time does not match the database record")
    if (
        attempt_data.get("total_points") != attempt.total_points
        or attempt_data.get("earned_points") != attempt.earned_points
    ):
        raise ValueError("Attempt evidence point totals do not match the database record")
    if attempt.content_release_id is not None:
        if release is None or release.id != attempt.content_release_id:
            raise ValueError("Attempt content release is unavailable")
        if release.tenant_id != attempt.tenant_id or release.course_id != course_id:
            raise ValueError("Attempt content release is outside the tenant course")
        release_snapshot = release.snapshot
        if not isinstance(release_snapshot, dict) or canonical_json_sha256(release_snapshot) != release.snapshot_sha256:
            raise ValueError("Content release checksum does not match")
        if attempt_data.get("content_release_sha256") != release.snapshot_sha256:
            raise ValueError("Attempt evidence release checksum does not match")

    questions = quiz_data.get("questions")
    if not isinstance(questions, list):
        raise ValueError("Attempt evidence questions are unavailable")
    questions_by_id: dict[str, dict[str, Any]] = {}
    for question in questions:
        if (
            not isinstance(question, dict)
            or not _is_uuid_string(question.get("id"))
            or not isinstance(question.get("text"), str)
            or not question["text"].strip()
            or not isinstance(question.get("type"), str)
            or not question["type"].strip()
            or not _is_int(question.get("points"))
            or question["points"] <= 0
            or (question.get("explanation") is not None and not isinstance(question.get("explanation"), str))
        ):
            raise ValueError("Attempt evidence question is invalid")
        question_id = question["id"]
        if question_id in questions_by_id or not isinstance(question.get("choices"), list):
            raise ValueError("Attempt evidence question is ambiguous")
        choice_ids = []
        for choice in question["choices"]:
            if (
                not isinstance(choice, dict)
                or not _is_uuid_string(choice.get("id"))
                or not isinstance(choice.get("text"), str)
                or not choice["text"].strip()
                or not isinstance(choice.get("is_correct"), bool)
            ):
                raise ValueError("Attempt evidence choice is invalid")
            choice_ids.append(choice["id"])
        if len(choice_ids) != len(set(choice_ids)):
            raise ValueError("Attempt evidence choices are ambiguous")
        questions_by_id[question_id] = question

    answers_by_question_id: dict[str, dict[str, Any]] = {}
    for answer in graded_answers:
        if not isinstance(answer, dict) or not isinstance(answer.get("question_id"), str):
            raise ValueError("Attempt evidence answer is invalid")
        answer_question_id = answer["question_id"]
        if answer_question_id not in questions_by_id or answer_question_id in answers_by_question_id:
            raise ValueError("Attempt evidence answer membership is invalid")
        if not isinstance(answer.get("selected_choice_ids"), list) or not isinstance(
            answer.get("correct_choice_ids"), list
        ):
            raise ValueError("Attempt evidence answer choices are invalid")
        if (
            not isinstance(answer.get("is_correct"), bool)
            or not _is_int(answer.get("points_earned"))
            or not _is_int(answer.get("points_possible"))
        ):
            raise ValueError("Attempt evidence answer grading is invalid")
        question = questions_by_id[answer_question_id]
        known_choice_ids = {choice["id"] for choice in question["choices"]}
        selected_ids = {str(value) for value in answer["selected_choice_ids"]}
        correct_ids = {str(value) for value in answer["correct_choice_ids"]}
        definition_correct_ids = {choice["id"] for choice in question["choices"] if choice["is_correct"]}
        if not selected_ids.issubset(known_choice_ids) or correct_ids != definition_correct_ids:
            raise ValueError("Attempt evidence answer choices do not match the question")
        expected_correct = selected_ids == correct_ids
        if answer["is_correct"] is not expected_correct:
            raise ValueError("Attempt evidence answer correctness is inconsistent")
        if answer["points_possible"] != question["points"] or answer["points_earned"] != (
            question["points"] if expected_correct else 0
        ):
            raise ValueError("Attempt evidence answer points are inconsistent")
        answers_by_question_id[answer_question_id] = answer
    if set(answers_by_question_id) != set(questions_by_id):
        raise ValueError("Attempt evidence is missing graded question answers")
    if sum(answer["points_possible"] for answer in answers_by_question_id.values()) != attempt.total_points:
        raise ValueError("Attempt evidence total points are inconsistent")
    if sum(answer["points_earned"] for answer in answers_by_question_id.values()) != attempt.earned_points:
        raise ValueError("Attempt evidence earned points are inconsistent")
    expected_score_percent = round(attempt.earned_points / attempt.total_points * 100) if attempt.total_points else 0
    if attempt.score_percent != expected_score_percent:
        raise ValueError("Attempt evidence score is inconsistent with points")
    return VerifiedSnapshot(snapshot, questions_by_id, answers_by_question_id)


def _snapshot_question_detail(
    *,
    attempt: CompletedAttempt,
    verified: VerifiedSnapshot,
    question: dict[str, Any],
    review: Review,
) -> QuestionDetail:
    question_id = question["id"]
    answer = verified.answers_by_question_id[question_id]
    selected = {str(item) for item in answer["selected_choice_ids"]}
    correct = {str(item) for item in answer["correct_choice_ids"]}
    choices: list[ChoiceDetail] = []
    for choice in question["choices"]:
        if (
            not isinstance(choice, dict)
            or not isinstance(choice.get("id"), str)
            or not isinstance(choice.get("text"), str)
        ):
            raise ValueError("Attempt evidence choice is invalid")
        choice_id = choice["id"]
        choices.append(
            ChoiceDetail(
                id=choice_id, text=choice["text"], selected=choice_id in selected, correct=choice_id in correct
            )
        )
    return QuestionDetail(
        question_id=question_id,
        question_key=question_key(
            quiz_id=attempt.quiz_id, content_release_id=attempt.content_release_id, question=question
        ),
        text=str(question.get("text", "")),
        type=str(question.get("type", "")),
        explanation=question.get("explanation") if isinstance(question.get("explanation"), str) else None,
        is_correct=answer["is_correct"],
        points_earned=answer["points_earned"],
        points_possible=answer["points_possible"],
        choices=choices,
        review=review,
    )


def _attempt_status(
    attempt: CompletedAttempt, course_id: UUID, release: ContentRelease | None
) -> tuple[str, VerifiedSnapshot | None]:
    try:
        verified = validate_attempt_snapshot(attempt, course_id=course_id, release=release)
    except ValueError:
        return "invalid", None
    return ("verified", verified) if verified is not None else ("unavailable", None)


def _release_quiz_metadata(release: ContentRelease | None, quiz_id: UUID) -> tuple[str | None, UUID | None]:
    """Find navigation metadata only in the immutable release snapshot."""
    if release is None or not isinstance(release.snapshot, dict):
        return None, None
    modules = release.snapshot.get("modules")
    if not isinstance(modules, list):
        return None, None
    for module in modules:
        if not isinstance(module, dict):
            continue
        lessons = module.get("lessons")
        if not isinstance(lessons, list):
            continue
        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue
            quizzes = lesson.get("quizzes")
            if not isinstance(quizzes, list):
                continue
            for quiz in quizzes:
                if isinstance(quiz, dict) and quiz.get("id") == str(quiz_id):
                    try:
                        lesson_id = UUID(str(lesson["id"]))
                    except (KeyError, TypeError, ValueError):
                        lesson_id = None
                    return (quiz.get("title") if isinstance(quiz.get("title"), str) else None, lesson_id)
    return None, None


async def _load_reviews(
    db: AsyncSession, *, tenant_id: UUID, course_id: UUID, keys: Iterable[str]
) -> dict[str, Review]:
    values = sorted(set(keys))
    if not values:
        return {}
    from app.modules.learning_insights.models import LearningQuestionReview

    rows = (
        (
            await db.execute(
                select(LearningQuestionReview).where(
                    LearningQuestionReview.tenant_id == tenant_id,
                    LearningQuestionReview.course_id == course_id,
                    LearningQuestionReview.question_key.in_(values),
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(row.question_key): Review(status=row.status, updated_at=row.updated_at) for row in rows}


def _unreviewed() -> Review:
    return Review(status="unreviewed", updated_at=None)


async def get_enrollment_insights(db: AsyncSession, *, tenant_id: UUID, enrollment_id: UUID) -> EnrollmentInsights:
    enrollment_row = await db.execute(
        select(Enrollment, Course, User)
        .join(Course, and_(Course.id == Enrollment.course_id, Course.tenant_id == Enrollment.tenant_id))
        .join(User, and_(User.id == Enrollment.user_id, User.tenant_id == Enrollment.tenant_id))
        .where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
    )
    enrollment, course, learner = enrollment_row.one_or_none() or (None, None, None)
    if enrollment is None or course is None or learner is None:
        raise LearningInsightsNotFoundError("Enrollment not found")
    rows = (
        await db.execute(
            select(QuizAttempt, ContentRelease)
            .outerjoin(
                ContentRelease,
                and_(
                    ContentRelease.id == QuizAttempt.content_release_id,
                    ContentRelease.tenant_id == QuizAttempt.tenant_id,
                    ContentRelease.course_id == course.id,
                ),
            )
            .where(
                QuizAttempt.enrollment_id == enrollment.id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.user_id == enrollment.user_id,
                QuizAttempt.completed_at.is_not(None),
            )
            .order_by(QuizAttempt.completed_at, QuizAttempt.id)
            .limit(MAX_ENROLLMENT_ATTEMPTS + 1)
        )
    ).all()
    if len(rows) > MAX_ENROLLMENT_ATTEMPTS:
        raise LearningInsightsValidationError("Enrollment attempt history exceeds 500")

    keys: list[str] = []
    verified_rows: list[tuple[CompletedAttempt, ContentRelease | None, VerifiedSnapshot | None, str]] = []
    for attempt, release in rows:
        status, verified = _attempt_status(attempt, course.id, release)
        verified_rows.append((attempt, release, verified, status))
        if verified:
            keys.extend(
                question_key(quiz_id=attempt.quiz_id, content_release_id=attempt.content_release_id, question=q)
                for q in verified.questions_by_id.values()
            )
    reviews = await _load_reviews(db, tenant_id=tenant_id, course_id=course.id, keys=keys)

    attempts: list[AttemptDetail] = []
    attempt_numbers: dict[tuple[UUID, UUID | None], int] = defaultdict(int)
    for attempt, release, verified, status in verified_rows:
        quiz_release = (attempt.quiz_id, attempt.content_release_id)
        attempt_numbers[quiz_release] += 1
        questions: list[QuestionDetail] = []
        if verified:
            questions = [
                _snapshot_question_detail(
                    attempt=attempt,
                    verified=verified,
                    question=question,
                    review=reviews.get(
                        question_key(
                            quiz_id=attempt.quiz_id, content_release_id=attempt.content_release_id, question=question
                        ),
                        _unreviewed(),
                    ),
                )
                for question in verified.questions_by_id.values()
            ]
        attempts.append(
            AttemptDetail(
                id=attempt.id,
                quiz_id=attempt.quiz_id,
                quiz_title=(verified.snapshot["quiz"].get("title", "") if verified else ""),
                content_release_id=attempt.content_release_id,
                completed_at=attempt.completed_at,
                attempt_number=attempt_numbers[quiz_release],
                score_percent=attempt.score_percent,
                passed=attempt.passed,
                evidence_status=status,
                lesson_id=_release_quiz_metadata(release, attempt.quiz_id)[1],
                questions=questions,
            )
        )
    return EnrollmentInsights(
        enrollment_id=enrollment.id,
        user_name=" ".join(part for part in (learner.first_name, learner.last_name) if part).strip(),
        course_id=course.id,
        course_title=course.title,
        attempts=attempts,
    )


@dataclass(frozen=True, slots=True)
class _QuestionOccurrence:
    attempt: CompletedAttempt
    question: dict[str, Any]
    answer: dict[str, Any]
    key: str
    quiz_title: str
    lesson_id: UUID | None


def _in_first_period(completed_at: datetime, *, date_from: datetime | None, date_to: datetime | None) -> bool:
    return (date_from is None or completed_at >= date_from) and (date_to is None or completed_at <= date_to)


def _aggregate_question_occurrences(
    occurrences_by_employee_question: dict[tuple[UUID, str], list[_QuestionOccurrence]],
    *,
    invalid_attempts_by_version: dict[tuple[UUID, UUID, UUID | None], list[datetime]],
    date_from: datetime | None,
    date_to: datetime | None,
    reviews: dict[str, Review],
    latest_attempts_by_version: dict[tuple[UUID, UUID, UUID | None], UUID] | None = None,
) -> tuple[int, list[QuestionStats]]:
    """Calculate first/latest statistics after immutable evidence is verified.

    The small pure core makes the period and retry rules executable without
    depending on database ordering or live question rows.
    """
    groups: dict[str, list[tuple[_QuestionOccurrence, _QuestionOccurrence | None]]] = defaultdict(list)
    included_employees: set[UUID] = set()
    for (employee_id, _key), occurrences in occurrences_by_employee_question.items():
        occurrences.sort(key=lambda item: (item.attempt.completed_at, item.attempt.id))
        first = occurrences[0]
        if any(
            invalid_at <= first.attempt.completed_at
            for invalid_at in invalid_attempts_by_version.get(
                (employee_id, first.attempt.quiz_id, first.attempt.content_release_id), []
            )
        ):
            # A corrupt/missing earlier attempt cannot be reconstructed from a
            # later valid retry.  Exclude rather than silently changing the
            # first-attempt denominator.
            continue
        if not _in_first_period(first.attempt.completed_at, date_from=date_from, date_to=date_to):
            continue
        eligible_latest = [item for item in occurrences if date_to is None or item.attempt.completed_at <= date_to]
        if not eligible_latest:
            continue
        latest: _QuestionOccurrence | None = eligible_latest[-1]
        if latest_attempts_by_version is not None:
            actual_id = latest_attempts_by_version.get(
                (employee_id, first.attempt.quiz_id, first.attempt.content_release_id)
            )
            latest = next((item for item in eligible_latest if item.attempt.id == actual_id), None)
        groups[first.key].append((first, latest))
        included_employees.add(employee_id)

    stats: list[QuestionStats] = []
    for key, pairs in groups.items():
        first, _ = pairs[0]
        respondents = len(pairs)
        incorrect = sum(not current.answer["is_correct"] for current, _latest in pairs)
        latest_respondents = sum(latest is not None for _current, latest in pairs)
        latest_incorrect = sum(not latest.answer["is_correct"] for _current, latest in pairs if latest is not None)
        improved = sum(
            not current.answer["is_correct"] and latest.answer["is_correct"]
            for current, latest in pairs
            if latest is not None
        )
        regressed = sum(
            current.answer["is_correct"] and not latest.answer["is_correct"]
            for current, latest in pairs
            if latest is not None
        )
        wrong_choices: dict[tuple[str, str], int] = defaultdict(int)
        for current, _latest in pairs:
            if current.answer["is_correct"]:
                continue
            selected_ids = {str(choice_id) for choice_id in current.answer["selected_choice_ids"]}
            correct_ids = {str(choice_id) for choice_id in current.answer["correct_choice_ids"]}
            for choice in current.question["choices"]:
                choice_id = str(choice.get("id", ""))
                if choice_id in selected_ids and choice_id not in correct_ids:
                    wrong_choices[(choice_id, str(choice.get("text", "")))] += 1
        stats.append(
            QuestionStats(
                question_key=key,
                question_id=first.question["id"],
                quiz_id=str(first.attempt.quiz_id),
                quiz_title=first.quiz_title,
                content_release_id=_as_uuid_string(first.attempt.content_release_id),
                text=str(first.question.get("text", "")),
                lesson_id=_as_uuid_string(first.lesson_id),
                respondents=respondents,
                incorrect=incorrect,
                incorrect_percent=round(incorrect * 100 / respondents, 2),
                latest_incorrect=latest_incorrect,
                latest_respondents=latest_respondents,
                latest_unavailable=respondents - latest_respondents,
                latest_incorrect_percent=round(latest_incorrect * 100 / latest_respondents, 2)
                if latest_respondents
                else None,
                improved=improved,
                regressed=regressed,
                wrong_choices=[
                    WrongChoice(id=choice_id, text=text, count=count)
                    for (choice_id, text), count in sorted(
                        wrong_choices.items(), key=lambda item: (-item[1], item[0][0])
                    )
                ],
                review=reviews.get(key, _unreviewed()),
                example_attempt_id=str(first.attempt.id),
            )
        )
    stats.sort(key=lambda item: (-item.incorrect_percent, -item.respondents, item.question_key))
    return len(included_employees), stats


async def get_course_insights(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    course_id: UUID,
    department_id: UUID | None = None,
    position_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> CourseInsights:
    if date_from and date_to and date_from > date_to:
        raise LearningInsightsValidationError("date_from must not be after date_to")
    course = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id))
    if course is None:
        raise LearningInsightsNotFoundError("Course not found")
    if department_id is not None:
        department_exists = await db.scalar(
            select(Position.id).where(Position.tenant_id == tenant_id, Position.department_id == department_id).limit(1)
        )
        # An empty valid department is a valid cohort; tenant ownership is
        # checked by its canonical table in the router's integration suite.
        if department_exists is None:
            from app.models.department import Department

            if (
                await db.scalar(
                    select(Department.id).where(Department.id == department_id, Department.tenant_id == tenant_id)
                )
                is None
            ):
                raise LearningInsightsNotFoundError("Department not found")
    if (
        position_id is not None
        and await db.scalar(select(Position.id).where(Position.id == position_id, Position.tenant_id == tenant_id))
        is None
    ):
        raise LearningInsightsNotFoundError("Position not found")

    conditions = [
        Enrollment.tenant_id == tenant_id,
        Enrollment.course_id == course_id,
        QuizAttempt.tenant_id == tenant_id,
        QuizAttempt.enrollment_id == Enrollment.id,
        QuizAttempt.user_id == Enrollment.user_id,
        QuizAttempt.completed_at.is_not(None),
        User.tenant_id == tenant_id,
    ]
    if position_id is not None:
        conditions.append(User.position_id == position_id)
    if department_id is not None:
        conditions.extend((Position.tenant_id == tenant_id, Position.department_id == department_id))
    statement = (
        select(QuizAttempt, ContentRelease)
        .join(
            Enrollment, and_(Enrollment.id == QuizAttempt.enrollment_id, Enrollment.tenant_id == QuizAttempt.tenant_id)
        )
        .join(User, and_(User.id == Enrollment.user_id, User.tenant_id == Enrollment.tenant_id))
        .outerjoin(Position, and_(Position.id == User.position_id, Position.tenant_id == User.tenant_id))
        .outerjoin(
            ContentRelease,
            and_(
                ContentRelease.id == QuizAttempt.content_release_id,
                ContentRelease.tenant_id == QuizAttempt.tenant_id,
                ContentRelease.course_id == course_id,
            ),
        )
        .where(*conditions)
        .order_by(QuizAttempt.user_id, QuizAttempt.completed_at, QuizAttempt.id)
        .limit(MAX_CANDIDATE_ATTEMPTS + 1)
    )
    rows = (await db.execute(statement)).all()
    if len(rows) > MAX_CANDIDATE_ATTEMPTS:
        raise LearningInsightsValidationError("Candidate completed attempts exceed 5000; narrow the cohort")

    by_employee_question: dict[tuple[UUID, str], list[_QuestionOccurrence]] = defaultdict(list)
    attempts_by_employee_quiz_release: dict[
        tuple[UUID, UUID, UUID | None], list[tuple[CompletedAttempt, ContentRelease | None, VerifiedSnapshot | None]]
    ] = defaultdict(list)
    excluded_attempts = 0
    for attempt, release in rows:
        _status, verified = _attempt_status(attempt, course_id, release)
        attempts_by_employee_quiz_release[(attempt.user_id, attempt.quiz_id, attempt.content_release_id)].append(
            (attempt, release, verified)
        )
        if not verified:
            excluded_attempts += 1

    latest_attempts_by_version = {}
    for (employee_id, _quiz_id, _release_id), version_attempts in attempts_by_employee_quiz_release.items():
        version_attempts.sort(key=lambda item: (item[0].completed_at, item[0].id))
        in_upper_bound = [item[0] for item in version_attempts if date_to is None or item[0].completed_at <= date_to]
        if in_upper_bound:
            latest_attempts_by_version[(employee_id, _quiz_id, _release_id)] = in_upper_bound[-1].id
        first_attempt, _first_release, first_verified = version_attempts[0]
        if first_verified is None:
            # Decide the historical baseline before looking at individual
            # questions. A later snapshot may be valid but cannot replace a
            # missing/corrupt first attempt for this quiz release.
            continue
        baseline_keys = {
            question_key(
                quiz_id=first_attempt.quiz_id, content_release_id=first_attempt.content_release_id, question=question
            )
            for question in first_verified.questions_by_id.values()
        }
        for attempt, release, verified in version_attempts:
            if verified is None:
                continue
            quiz_title = str(verified.snapshot["quiz"].get("title", ""))
            _release_title, lesson_id = _release_quiz_metadata(release, attempt.quiz_id)
            for question_id, question in verified.questions_by_id.items():
                key = question_key(
                    quiz_id=attempt.quiz_id, content_release_id=attempt.content_release_id, question=question
                )
                if key not in baseline_keys:
                    continue
                by_employee_question[(employee_id, key)].append(
                    _QuestionOccurrence(
                        attempt=attempt,
                        question=question,
                        answer=verified.answers_by_question_id[question_id],
                        key=key,
                        quiz_title=quiz_title,
                        lesson_id=lesson_id,
                    )
                )

    reviews = await _load_reviews(
        db, tenant_id=tenant_id, course_id=course_id, keys=(key for _, key in by_employee_question)
    )
    included_employees, stats = _aggregate_question_occurrences(
        by_employee_question,
        invalid_attempts_by_version={},
        date_from=date_from,
        date_to=date_to,
        reviews=reviews,
        latest_attempts_by_version=latest_attempts_by_version,
    )
    return CourseInsights(
        course_id=course.id,
        course_title=course.title,
        included_employees=included_employees,
        excluded_attempts=excluded_attempts,
        questions=stats,
    )


async def upsert_question_review(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    attempt_id: UUID,
    question_id: UUID,
    status: ReviewStatus,
) -> Review:
    row = (
        await db.execute(
            select(QuizAttempt, Enrollment, Course, ContentRelease)
            .join(
                Enrollment,
                and_(Enrollment.id == QuizAttempt.enrollment_id, Enrollment.tenant_id == QuizAttempt.tenant_id),
            )
            .join(Course, and_(Course.id == Enrollment.course_id, Course.tenant_id == Enrollment.tenant_id))
            .outerjoin(
                ContentRelease,
                and_(
                    ContentRelease.id == QuizAttempt.content_release_id,
                    ContentRelease.tenant_id == QuizAttempt.tenant_id,
                    ContentRelease.course_id == Enrollment.course_id,
                ),
            )
            .where(
                QuizAttempt.id == attempt_id,
                QuizAttempt.tenant_id == tenant_id,
                QuizAttempt.user_id == Enrollment.user_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise LearningInsightsNotFoundError("Attempt not found")
    attempt, enrollment, course, release = row
    try:
        verified = validate_attempt_snapshot(attempt, course_id=course.id, release=release)
    except ValueError as exc:
        raise SnapshotUnavailableError("Attempt evidence is invalid") from exc
    if verified is None:
        raise SnapshotUnavailableError("Attempt evidence is unavailable")
    question = verified.questions_by_id.get(str(question_id))
    if question is None:
        raise LearningInsightsNotFoundError("Question not found in attempt evidence")
    key = question_key(quiz_id=attempt.quiz_id, content_release_id=attempt.content_release_id, question=question)
    from app.modules.learning_insights.models import LearningQuestionReview

    statement = (
        pg_insert(LearningQuestionReview)
        .values(tenant_id=tenant_id, course_id=course.id, question_key=key, status=status, updated_by=actor_id)
        .on_conflict_do_update(
            index_elements=["tenant_id", "course_id", "question_key"],
            set_={"status": status, "updated_by": actor_id, "updated_at": func.now()},
        )
        .returning(LearningQuestionReview.status, LearningQuestionReview.updated_at)
    )
    saved_status, updated_at = (await db.execute(statement)).one()
    await db.flush()
    return Review(status=saved_status, updated_at=updated_at)
