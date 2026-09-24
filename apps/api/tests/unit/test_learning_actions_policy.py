from types import SimpleNamespace

import pytest

from app.modules.learning_actions.policy import (
    LearningActionValidationError,
    classify_training_issue,
    select_weak_questions,
    validate_close_request,
)


def _row(**overrides):
    values = {
        "deadline_status": "active",
        "computed_status": "assigned",
        "progress_percent": 0,
        "quiz_attempts_count": 0,
        "best_score": None,
        "failed_required_quiz": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _question(*, respondents: int, incorrect_percent: float):
    return SimpleNamespace(
        respondents=respondents,
        incorrect_percent=incorrect_percent,
        question_key=f"q-{respondents}-{incorrect_percent}",
    )


def test_training_issue_priority_is_deterministic():
    assert classify_training_issue(_row(deadline_status="overdue")) == "overdue"
    assert (
        classify_training_issue(
            _row(
                computed_status="in_progress",
                progress_percent=70,
                quiz_attempts_count=2,
                best_score=40,
                failed_required_quiz=True,
            )
        )
        == "failed_required_quiz"
    )
    assert classify_training_issue(_row(computed_status="in_progress", progress_percent=20)) == "stalled"
    assert (
        classify_training_issue(
            _row(
                computed_status="in_progress",
                progress_percent=70,
                quiz_attempts_count=2,
                best_score=100,
                failed_required_quiz=False,
            )
        )
        == "stalled"
    )
    assert classify_training_issue(_row()) == "not_started"
    assert classify_training_issue(_row(computed_status="completed", progress_percent=100)) is None


def test_weak_question_policy_hides_small_or_weak_signals_and_sorts_by_risk():
    selected = select_weak_questions(
        [
            _question(respondents=4, incorrect_percent=100),
            _question(respondents=5, incorrect_percent=29.9),
            _question(respondents=5, incorrect_percent=30),
            _question(respondents=12, incorrect_percent=70),
        ]
    )

    assert [(item.respondents, item.incorrect_percent) for item in selected] == [(12, 70), (5, 30)]


def test_manual_or_cancelled_close_requires_a_human_reason():
    validate_close_request(resolution="observed", note=None)
    validate_close_request(resolution="manual", note="Question was replaced after expert review.")

    with pytest.raises(LearningActionValidationError):
        validate_close_request(resolution="manual", note=" ")
    with pytest.raises(LearningActionValidationError):
        validate_close_request(resolution="cancelled", note=None)
