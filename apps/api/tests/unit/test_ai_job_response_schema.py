from datetime import UTC, datetime

from app.modules.ai.schemas import AIJobResponse


def test_ai_job_response_exposes_last_update_for_stalled_detection():
    created_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    updated_at = datetime(2026, 7, 27, 10, 1, tzinfo=UTC)

    response = AIJobResponse(
        id="job-1",
        status="running",
        course_id=None,
        created_at=created_at,
        updated_at=updated_at,
        progress=25,
        stage="architect",
        message="Working",
    )

    assert response.created_at == created_at
    assert response.updated_at == updated_at
    assert response.started_at is None
