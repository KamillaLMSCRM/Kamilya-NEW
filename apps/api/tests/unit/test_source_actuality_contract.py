from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_policy_update_requires_timezone_and_monotonic_review_window() -> None:
    from app.modules.source_actuality.schemas import SourcePolicyUpdate

    reviewed_at = datetime.now(UTC)
    value = SourcePolicyUpdate(
        owner_id=uuid4(),
        reviewed_at=reviewed_at,
        next_review_at=reviewed_at + timedelta(days=90),
    )
    assert value.next_review_at > value.reviewed_at

    with pytest.raises(ValidationError):
        SourcePolicyUpdate(
            reviewed_at=reviewed_at,
            next_review_at=reviewed_at - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError):
        SourcePolicyUpdate(next_review_at=datetime.now())


def test_change_decision_is_explicit_and_retraining_deadline_is_scoped() -> None:
    from app.modules.source_actuality.schemas import SourceChangeDecisionRequest

    due_at = datetime.now(UTC) + timedelta(days=14)
    value = SourceChangeDecisionRequest(
        decision="update_and_retrain",
        reason="Требование изменилось и должно быть повторно подтверждено.",
        retraining_due_at=due_at,
    )
    assert value.retraining_due_at == due_at

    with pytest.raises(ValidationError):
        SourceChangeDecisionRequest(
            decision="no_learning_impact",
            reason="Недостаточно",
            retraining_due_at=due_at,
        )

    with pytest.raises(ValidationError):
        SourceChangeDecisionRequest(
            decision="update_future",
            reason="Изменение применяется только к новым назначениям.",
            retraining_due_at=due_at,
        )


def test_impact_record_never_claims_question_level_fact_binding() -> None:
    from app.modules.source_actuality.schemas import ImpactedCourse

    value = ImpactedCourse(
        course_id=uuid4(),
        title="Курс",
        status="published",
        impacted_lesson_ids=[uuid4()],
        assessment_questions_requiring_review=3,
        active_enrollments=2,
        completed_enrollments=4,
    )
    assert value.assessment_scope == "impacted_lessons"
