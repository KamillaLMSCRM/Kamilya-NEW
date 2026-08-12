"""HTTP admission regressions for AI course generation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import router
from app.modules.ai.job_service import AIJobAdmissionLimitReachedError
from app.modules.ai.schemas import AIGenerateRequest


@pytest.mark.asyncio
async def test_full_tenant_queue_maps_submission_limit_to_http_429(monkeypatch):
    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    request = AIGenerateRequest(documents=[uuid4()])
    analysis = SimpleNamespace(
        status="compatible",
        score=1.0,
        requires_decision=False,
        clusters=[],
    )

    analyze = AsyncMock(return_value=analysis)
    check_quota = AsyncMock()
    submit = AsyncMock(
        side_effect=AIJobAdmissionLimitReachedError(
            tenant_id=tenant_id,
            active_count=2,
            active_limit=2,
        )
    )

    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", analyze)
    monkeypatch.setattr("app.core.demo_limits.check_ai_generation_quota", check_quota)
    monkeypatch.setattr(router, "submit_ai_job", submit)

    empty_courses = SimpleNamespace(all=lambda: [])
    with pytest.raises(HTTPException) as error:
        await router.generate_course(request, db=SimpleNamespace(execute=AsyncMock(return_value=empty_courses)), user=user)

    assert error.value.status_code == 429
    assert error.value.detail == {
        "code": "tenant_ai_job_limit_reached",
        "message": "Tenant AI job limit reached",
        "current": 2,
        "limit": 2,
        "retry_after_seconds": 510,
    }
    assert error.value.headers == {"Retry-After": "510"}
    check_quota.assert_awaited_once()


@pytest.mark.asyncio
async def test_reused_source_requires_reason_and_returns_only_existing_course_projection(monkeypatch):
    tenant_id = uuid4()
    document_id = uuid4()
    existing_course_id = uuid4()
    request = AIGenerateRequest(documents=[document_id])
    analysis = SimpleNamespace(status="compatible", score=1.0, requires_decision=False, clusters=[])
    rows = SimpleNamespace(all=lambda: [(existing_course_id, "Existing course", "published")])

    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", AsyncMock(return_value=analysis))

    with pytest.raises(HTTPException) as error:
        await router.generate_course(
            request,
            db=SimpleNamespace(execute=AsyncMock(return_value=rows)),
            user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
        )

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "source_documents_already_used",
        "message": "Selected source documents are already linked to existing courses",
        "existing_courses": [{"id": str(existing_course_id), "title": "Existing course", "status": "published"}],
    }


@pytest.mark.asyncio
async def test_reuse_reason_is_persisted_and_starts_an_independent_draft(monkeypatch):
    tenant_id = uuid4()
    request = AIGenerateRequest(documents=[uuid4()], reuse_reason="different_audience")
    analysis = SimpleNamespace(status="compatible", score=1.0, requires_decision=False, clusters=[])
    submit = AsyncMock(return_value=(SimpleNamespace(), {}))

    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", AsyncMock(return_value=analysis))
    monkeypatch.setattr("app.core.demo_limits.check_ai_generation_quota", AsyncMock())
    monkeypatch.setattr(router, "submit_ai_job", submit)
    monkeypatch.setattr(router, "_job_response", AsyncMock(return_value={"id": "job-1"}))

    response = await router.generate_course(request, db=SimpleNamespace(), user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id))

    assert response == {"id": "job-1"}
    assert submit.await_args.kwargs["course_id"] is None
    assert submit.await_args.kwargs["params"]["reuse_reason"] == "different_audience"
    assert submit.await_args.kwargs["task_kwargs"](SimpleNamespace(id="job-1"))["reuse_reason"] == "different_audience"


def test_reuse_reason_cannot_silently_replace_an_existing_course_regeneration() -> None:
    with pytest.raises(ValueError, match="new independent course"):
        AIGenerateRequest(
            documents=[uuid4()],
            course_id=uuid4(),
            reuse_reason="different_audience",
        )


@pytest.mark.asyncio
async def test_existing_course_regeneration_does_not_enter_new_course_reuse_flow(monkeypatch):
    tenant_id = uuid4()
    existing_course_id = uuid4()
    request = AIGenerateRequest(documents=[uuid4()], course_id=existing_course_id)
    analysis = SimpleNamespace(status="compatible", score=1.0, requires_decision=False, clusters=[])
    submit = AsyncMock(return_value=(SimpleNamespace(), {}))
    db = SimpleNamespace(execute=AsyncMock())

    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", AsyncMock(return_value=analysis))
    monkeypatch.setattr("app.core.demo_limits.check_ai_generation_quota", AsyncMock())
    monkeypatch.setattr(router, "submit_ai_job", submit)
    monkeypatch.setattr(router, "_job_response", AsyncMock(return_value={"id": "job-1"}))

    response = await router.generate_course(
        request,
        db=db,
        user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
    )

    assert response == {"id": "job-1"}
    db.execute.assert_not_awaited()
    assert submit.await_args.kwargs["course_id"] == existing_course_id
    assert submit.await_args.kwargs["reserve_course_generation"] is False
