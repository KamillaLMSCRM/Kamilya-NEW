from types import SimpleNamespace
from uuid import uuid4

from app.modules.quizzes.schemas import QuizResultResponse


def test_learner_quiz_result_schema_excludes_answer_key_and_evidence_fields():
    attempt = SimpleNamespace(
        id=uuid4(),
        quiz_id=uuid4(),
        user_id=uuid4(),
        enrollment_id=None,
        content_release_id=None,
        score_percent=80,
        total_points=5,
        earned_points=4,
        passed=True,
        answers=[
            {
                "correct_choice_ids": ["answer-key"],
                "is_correct": True,
            }
        ],
        evidence_sha256="immutable-evidence-hash",
        started_at="2026-08-09T00:00:00Z",
        completed_at="2026-08-09T00:01:00Z",
        time_spent_seconds=60,
    )

    result = QuizResultResponse.model_validate(
        {
            "attempt": attempt,
            "passed": True,
            "message": "Passed",
            "training_evidence_event_id": uuid4(),
        },
        from_attributes=True,
    ).model_dump(mode="json")

    assert set(result) == {"attempt", "passed", "message", "training_evidence_event_id"}
    assert "answers" not in result["attempt"]
    assert "evidence_sha256" not in result["attempt"]
    assert "correct_choice_ids" not in str(result)
