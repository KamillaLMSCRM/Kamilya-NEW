from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.courses.release_service import canonical_json_sha256
from app.modules.learning_insights import router
from app.modules.learning_insights.service import (
    _aggregate_question_occurrences,
    _QuestionOccurrence,
    question_key,
    validate_attempt_snapshot,
)


def _attempt(*, completed_at: datetime | None = None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        enrollment_id=uuid4(),
        quiz_id=uuid4(),
        content_release_id=uuid4(),
        completed_at=completed_at or datetime.now(UTC),
        score_percent=0,
        passed=False,
        total_points=1,
        earned_points=0,
    )


def _question(*, multiple: bool = False):
    choices = [
        {"id": str(uuid4()), "text": "Correct A", "is_correct": True},
        {"id": str(uuid4()), "text": "Wrong B", "is_correct": False},
    ]
    if multiple:
        choices.append({"id": str(uuid4()), "text": "Correct C", "is_correct": True})
    return {
        "id": str(uuid4()),
        "text": "Question",
        "type": "multiple" if multiple else "single",
        "points": 1,
        "explanation": None,
        "choices": choices,
    }


def _release(attempt, course_id):
    snapshot = {"modules": []}
    return SimpleNamespace(
        id=attempt.content_release_id,
        tenant_id=attempt.tenant_id,
        course_id=course_id,
        snapshot=snapshot,
        snapshot_sha256=canonical_json_sha256(snapshot),
    )


def _snapshot(*, attempt, course_id, question, answer, release):
    return {
        "schema_version": 1,
        "attempt": {
            "id": str(attempt.id),
            "tenant_id": str(attempt.tenant_id),
            "user_id": str(attempt.user_id),
            "enrollment_id": str(attempt.enrollment_id),
            "course_id": str(course_id),
            "content_release_id": str(attempt.content_release_id),
            "content_release_sha256": release.snapshot_sha256,
            "quiz_id": str(attempt.quiz_id),
            "score_percent": attempt.score_percent,
            "passed": attempt.passed,
            "total_points": attempt.total_points,
            "earned_points": attempt.earned_points,
            "completed_at": attempt.completed_at.isoformat(),
        },
        "quiz": {"id": str(attempt.quiz_id), "title": "Frozen quiz", "questions": [question]},
        "graded_answers": [answer],
    }


def _wrong_answer(question):
    return {
        "question_id": question["id"],
        "selected_choice_ids": [question["choices"][1]["id"]],
        "correct_choice_ids": [choice["id"] for choice in question["choices"] if choice["is_correct"]],
        "is_correct": False,
        "points_earned": 0,
        "points_possible": 1,
    }


def test_snapshot_validator_rejects_checksum_and_identity_tampering():
    attempt, course_id = _attempt(), uuid4()
    question = _question()
    release = _release(attempt, course_id)
    snapshot = _snapshot(
        attempt=attempt, course_id=course_id, question=question, answer=_wrong_answer(question), release=release
    )
    attempt.evidence_snapshot = snapshot
    attempt.evidence_sha256 = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        validate_attempt_snapshot(attempt, course_id=course_id, release=release)

    snapshot["attempt"]["user_id"] = str(uuid4())
    attempt.evidence_sha256 = canonical_json_sha256(snapshot)
    with pytest.raises(ValueError, match="user_id"):
        validate_attempt_snapshot(attempt, course_id=course_id, release=release)


def test_snapshot_validator_normalizes_timezone_offsets_and_rejects_point_mismatch():
    attempt, course_id = _attempt(), uuid4()
    question = _question()
    release = _release(attempt, course_id)
    snapshot = _snapshot(
        attempt=attempt, course_id=course_id, question=question, answer=_wrong_answer(question), release=release
    )
    snapshot["attempt"]["completed_at"] = attempt.completed_at.astimezone(timezone(timedelta(hours=5))).isoformat()
    attempt.evidence_snapshot = snapshot
    attempt.evidence_sha256 = canonical_json_sha256(snapshot)
    assert validate_attempt_snapshot(attempt, course_id=course_id, release=release) is not None

    snapshot["attempt"]["total_points"] = 2
    attempt.evidence_sha256 = canonical_json_sha256(snapshot)
    with pytest.raises(ValueError, match="point totals"):
        validate_attempt_snapshot(attempt, course_id=course_id, release=release)


def test_missing_snapshot_is_unavailable_and_duplicate_answers_are_invalid():
    attempt = _attempt()
    attempt.evidence_snapshot = None
    attempt.evidence_sha256 = None
    assert validate_attempt_snapshot(attempt, course_id=uuid4(), release=None) is None

    course_id, question = uuid4(), _question()
    release = _release(attempt, course_id)
    snapshot = _snapshot(
        attempt=attempt, course_id=course_id, question=question, answer=_wrong_answer(question), release=release
    )
    snapshot["graded_answers"].append(dict(snapshot["graded_answers"][0]))
    attempt.evidence_snapshot = snapshot
    attempt.evidence_sha256 = canonical_json_sha256(snapshot)
    with pytest.raises(ValueError, match="membership"):
        validate_attempt_snapshot(attempt, course_id=course_id, release=release)


def test_partial_multi_answer_is_correctly_kept_as_incorrect_evidence():
    attempt, course_id, question = _attempt(), uuid4(), _question(multiple=True)
    release = _release(attempt, course_id)
    partial = {
        "question_id": question["id"],
        "selected_choice_ids": [question["choices"][0]["id"]],
        "correct_choice_ids": [question["choices"][0]["id"], question["choices"][2]["id"]],
        "is_correct": False,
        "points_earned": 0,
        "points_possible": 1,
    }
    snapshot = _snapshot(attempt=attempt, course_id=course_id, question=question, answer=partial, release=release)
    attempt.evidence_snapshot = snapshot
    attempt.evidence_sha256 = canonical_json_sha256(snapshot)
    verified = validate_attempt_snapshot(attempt, course_id=course_id, release=release)
    assert verified is not None
    assert verified.answers_by_question_id[question["id"]]["is_correct"] is False


def test_question_key_keeps_correct_definition_and_separates_release_versions():
    quiz_id, release_one, release_two = uuid4(), uuid4(), uuid4()
    question = _question()
    response_artifacts = {
        **question,
        "selected_choice_ids": [question["choices"][1]["id"]],
        "is_correct": False,
        "points_earned": 0,
    }
    changed_definition = {
        **question,
        "choices": [{**question["choices"][0], "is_correct": False}, *question["choices"][1:]],
    }
    assert question_key(quiz_id=quiz_id, content_release_id=release_one, question=question) == question_key(
        quiz_id=quiz_id, content_release_id=release_one, question=response_artifacts
    )
    assert question_key(quiz_id=quiz_id, content_release_id=release_one, question=question) != question_key(
        quiz_id=quiz_id, content_release_id=release_two, question=question
    )
    assert question_key(quiz_id=quiz_id, content_release_id=release_one, question=question) != question_key(
        quiz_id=quiz_id, content_release_id=release_one, question=changed_definition
    )


def _occurrence(*, attempt, question, answer):
    return _QuestionOccurrence(
        attempt=attempt,
        question=question,
        answer=answer,
        key=question_key(quiz_id=attempt.quiz_id, content_release_id=attempt.content_release_id, question=question),
        quiz_title="Frozen quiz",
        lesson_id=None,
    )


def test_first_latest_statistics_handle_duplicate_retries_period_and_invalid_history():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    employee, question = uuid4(), _question()
    first, latest = _attempt(completed_at=start), _attempt(completed_at=start + timedelta(days=10))
    first.user_id = latest.user_id = employee
    latest.quiz_id, latest.content_release_id = first.quiz_id, first.content_release_id
    correct_answer = {
        "question_id": question["id"],
        "selected_choice_ids": [question["choices"][0]["id"]],
        "correct_choice_ids": [question["choices"][0]["id"]],
        "is_correct": True,
        "points_earned": 1,
        "points_possible": 1,
    }
    first_occurrence = _occurrence(attempt=first, question=question, answer=_wrong_answer(question))
    latest_occurrence = _occurrence(attempt=latest, question=question, answer=correct_answer)
    by_employee_question = {(employee, first_occurrence.key): [latest_occurrence, first_occurrence]}

    included, stats = _aggregate_question_occurrences(
        by_employee_question, invalid_attempts_by_version={}, date_from=None, date_to=None, reviews={}
    )
    assert included == 1
    assert (stats[0].respondents, stats[0].incorrect, stats[0].latest_incorrect, stats[0].improved) == (1, 1, 0, 1)
    assert stats[0].wrong_choices[0].id == question["choices"][1]["id"]

    included, stats = _aggregate_question_occurrences(
        by_employee_question,
        invalid_attempts_by_version={},
        date_from=start + timedelta(days=1),
        date_to=None,
        reviews={},
    )
    assert included == 0 and stats == []  # A later retry must not become the first attempt.

    invalid = {(employee, first.quiz_id, first.content_release_id): [start - timedelta(seconds=1)]}
    included, stats = _aggregate_question_occurrences(
        by_employee_question, invalid_attempts_by_version=invalid, date_from=None, date_to=None, reviews={}
    )
    assert included == 0 and stats == []


def test_router_declares_active_methodologist_role_and_tenant_filtered_service_queries():
    router_source = inspect.getsource(router)
    service_source = inspect.getsource(__import__("app.modules.learning_insights.service", fromlist=["*"]))
    assert 'require_role("methodologist")' in router_source
    assert "Learning insights requires a tenant context" in router_source
    assert "Enrollment.tenant_id == tenant_id" in service_source
    assert "QuizAttempt.tenant_id == tenant_id" in service_source
    assert "User.tenant_id == tenant_id" in service_source


def test_missing_actual_latest_never_carries_forward_an_older_answer():
    first = _attempt()
    question = _question()
    occurrence = _occurrence(attempt=first, question=question, answer=_wrong_answer(question))
    version = (first.user_id, first.quiz_id, first.content_release_id)
    included, stats = _aggregate_question_occurrences(
        {(first.user_id, occurrence.key): [occurrence]},
        invalid_attempts_by_version={},
        date_from=None,
        date_to=None,
        reviews={},
        latest_attempts_by_version={version: uuid4()},
    )
    assert included == 1
    assert stats[0].respondents == 1 and stats[0].incorrect == 1
    assert stats[0].latest_respondents == 0 and stats[0].latest_unavailable == 1
    assert stats[0].latest_incorrect_percent is None
    assert stats[0].improved == stats[0].regressed == 0
