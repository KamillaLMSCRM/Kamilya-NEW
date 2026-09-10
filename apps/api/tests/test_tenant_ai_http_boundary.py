"""HTTP role boundary and write-only key response, without external services."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import get_current_active_user
from app.modules.admin.tenant_ai_providers import router as adapter


@pytest.mark.asyncio
@pytest.mark.parametrize('role,has_tenant,expected', [
    ('student', True, 403), ('methodologist', True, 403),
    ('superadmin', False, 403), ('admin', True, 200),
])
async def test_http_authorizes_active_tenant_admin_only(role, has_tenant, expected):
    tenant_id = uuid4() if has_tenant else None
    app = FastAPI()
    app.include_router(adapter.router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role, tenant_id=tenant_id)
    service = SimpleNamespace(list=AsyncMock(return_value={'providers': []}))
    app.dependency_overrides[adapter._service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/admin/ai-providers')
    assert response.status_code == expected
    if expected == 200:
        service.list.assert_awaited_once_with(tenant_id)
    else:
        service.list.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_response_excludes_key_and_client_tenant_cannot_select_owner():
    tenant_id = uuid4()
    app = FastAPI()
    app.include_router(adapter.router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role='admin', tenant_id=tenant_id)
    service = SimpleNamespace(put=AsyncMock(return_value={
        'purpose': 'generation', 'provider': 'openrouter', 'model': 'openrouter/free',
        'enabled': True, 'free_only': True, 'has_key': True, 'output_dimensions': None,
        'api_key': 'synthetic-private-key', 'encrypted_key': 'synthetic-ciphertext',
    }))
    app.dependency_overrides[adapter._service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/admin/ai-providers/generation', json={
            'provider': 'openrouter', 'model': 'openrouter/free', 'api_key': 'synthetic-private-key',
            'tenant_id': str(uuid4()),
        })
    assert response.status_code == 200
    assert 'synthetic-private-key' not in response.text
    assert 'synthetic-ciphertext' not in response.text
    assert service.put.await_args.args[0] == tenant_id
