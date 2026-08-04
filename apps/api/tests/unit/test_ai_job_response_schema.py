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


def test_ai_job_response_keeps_structured_and_legacy_errors():
    now = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
    structured = AIJobResponse(
        id="job-structured",
        status="failed",
        course_id=None,
        created_at=now,
        updated_at=now,
        errors=[{"code": "source_blob_missing", "message": "Upload a new version"}],
    )
    legacy = AIJobResponse(
        id="job-legacy",
        status="failed",
        course_id=None,
        created_at=now,
        updated_at=now,
        errors=["Provider unavailable"],
    )

    assert structured.errors == [
        {"code": "source_blob_missing", "message": "Upload a new version"}
    ]
    assert legacy.errors == ["Provider unavailable"]


def test_ai_job_response_uses_flat_queue_metadata_contract():
    now = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
    response = AIJobResponse(
        id="job-queued",
        status="pending",
        course_id=None,
        created_at=now,
        updated_at=now,
        queue_position=3,
        estimated_wait_seconds=510,
        tenant_active_jobs=2,
        tenant_active_limit=2,
    )

    assert response.queue_position == 3
    assert response.estimated_wait_seconds == 510
    assert response.tenant_active_jobs == 2
    assert response.tenant_active_limit == 2
    assert "queue_metadata" not in response.model_dump()
