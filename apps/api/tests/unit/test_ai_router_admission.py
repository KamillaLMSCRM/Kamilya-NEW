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

    with pytest.raises(HTTPException) as error:
        await router.generate_course(request, db=SimpleNamespace(), user=user)

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
