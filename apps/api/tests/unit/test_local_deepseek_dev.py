"""The owner-operated local model cannot change ordinary or historical routing."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot
from app.modules.ai import llm_client
from app.modules.ai.llm_client import LLMClient
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3 import local_deepseek_dev as local
from app.modules.ai.v3.provider_profile import V3ProfiledClient
from app.modules.ai.v3.revision_policy import MATERIALITY_PRACTICAL_REVIEW_POLICY


def settings(**updates):
    values = {name: False for name in local.LUNA_FLAGS}
    values.update(AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED=True, DEPLOYMENT_ENVIRONMENT='vm-development-worker')
    values.update(updates)
    return SimpleNamespace(**values)


def create(**updates):
    values = dict(settings=settings(), tenant_id=QA_TENANT, course_id=None,
                  review_policy=MATERIALITY_PRACTICAL_REVIEW_POLICY, temperature=.2)
    values.update(updates)
    return local.create_local_deepseek_dev_client(**values)


@pytest.mark.parametrize('updates', [dict(tenant_id=uuid4()), dict(course_id=uuid4()),
                                    dict(review_policy='v3-practical-source-review-v24'),
                                    dict(settings=settings(AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED=False))])
def test_other_requests_do_not_select_local(updates):
    assert create(**updates) is None


@pytest.mark.parametrize('environment', ['production', 'local', 'vm-production-worker', ''])
def test_flag_cannot_enable_production(environment):
    with pytest.raises(ValueError, match='environment_invalid'):
        create(settings=settings(DEPLOYMENT_ENVIRONMENT=environment))


@pytest.mark.parametrize('flag', local.LUNA_FLAGS)
def test_other_qa_route_is_not_silently_overridden(flag):
    with pytest.raises(ValueError, match='route_conflict'):
        create(settings=settings(**{flag: True}))


def test_fixed_profile_has_no_cloud_key_fallback_or_retries():
    client = create()
    assert local.is_local_deepseek_dev_client(client)
    assert client.provider_names == [local.PROVIDER]
    assert client._clients[0].config.api_key == ''
    assert client._clients[0].config.max_retries == 0
    assert client._clients[0].config.base_url == 'http://127.0.0.1:18890/v1'
    assert client._clients[0].config.structured_output_mode == 'prompt_json'
    frozen = RuntimeSnapshot(9, {'provider.deepseek.timeout_seconds': 120.0})
    profiled = V3ProfiledClient(client, frozen, job_id=str(uuid4()), cooperative_deadline=True)
    assert profiled.generation_deadline_seconds == 300.0
    assert profiled.cache_fingerprint() != client.cache_fingerprint()
    client._clients[0].config = replace(client._clients[0].config, extra_body={})
    with pytest.raises(RuntimeError, match='route_changed'):
        profiled._assert_identity()


@pytest.mark.asyncio
async def test_profile_preserves_local_thinking_budget_on_wire(monkeypatch):
    seen = []
    async def request(_client, value):
        seen.append(value)
        return {'choices':[{'message':{'content':'{"ok":true}'}, 'finish_reason':'stop'}]}
    monkeypatch.setattr(LLMClient, '_request', request)
    profiled = V3ProfiledClient(create(), RuntimeSnapshot(9, {'provider.deepseek.timeout_seconds':120.0}),
                              job_id=str(uuid4()), cooperative_deadline=True)
    await profiled.ainvoke('synthetic')
    assert seen[0]['thinking_budget'] == 4096
    assert seen[0]['chat_template_kwargs']['enable_thinking'] is True
    assert seen[0]['max_tokens'] == 16384
    assert 'response_format' not in seen[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('key', ['', 'synthetic-private-key'])
async def test_real_http_transport_omits_empty_auth_and_preserves_configured_auth(monkeypatch, key):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]})
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(llm_client.httpx, 'AsyncClient', lambda **options:
                        actual_client(transport=httpx.MockTransport(handler), **options))
    config = replace(local.configuration(), api_key=key)
    value = await LLMClient(config, max_retries=0).ainvoke('synthetic')
    assert value.content == '{"ok":true}'
    assert requests[0].headers.get('authorization') == (f'Bearer {key}' if key else None)
