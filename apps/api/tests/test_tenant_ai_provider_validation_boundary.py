"""HTTP validation boundary for write-only BYOK API keys."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import get_current_active_user
from app.modules.admin.tenant_ai_providers import router as adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", ["bad\r\nkey", "k" * 513])
async def test_http_invalid_api_key_is_never_echoed_by_tenant_ai_provider_routes(api_key: str):
    app = FastAPI()
    app.include_router(adapter.router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        role="admin",
        tenant_id=uuid4(),
    )
    service = SimpleNamespace(put=AsyncMock())
    app.dependency_overrides[adapter._service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.put(
            "/admin/ai-providers/generation",
            json={
                "provider": "openrouter",
                "model": "google/gemma-4-26b-a4b-it:free",
                "api_key": api_key,
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "message": "Invalid AI provider configuration",
    }
    assert api_key not in response.text
    assert "input" not in response.text.lower()
    assert "ctx" not in response.text.lower()
    service.put.assert_not_awaited()
