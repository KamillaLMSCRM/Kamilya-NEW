from uuid import uuid4

import pytest

from app.modules.ai.llm_client import LLMProviderConfig
from app.modules.ai.managed_luna_client import LUNA6_MODEL, ManagedLunaClient
from app.modules.source_editorial_review.analysis import select_visual_config
from app.modules.source_editorial_review.domain import ReviewConflictError


def provider(name):
    return LLMProviderConfig(name, 'https://example.invalid/v1', '', 'fixture')


def test_managed_source_visual_route_reuses_verified_luna_model_and_effort():
    managed = ManagedLunaClient(
        base_url='http://172.17.0.1:19000/v1',
        api_key='fixture-token',
        tenant_id=uuid4(),
        user_id=uuid4(),
        job_id=str(uuid4()),
        credential_revision='fixture',
        model=LUNA6_MODEL,
        reasoning_effort='high',
        deadline_seconds=300,
    )
    chosen = managed.visual_provider_config()
    assert chosen.name == 'chatgpt-reserve'
    assert chosen.base_url == 'http://172.17.0.1:19000/v1'
    assert chosen.model == LUNA6_MODEL
    assert chosen.extra_body == {'reasoning_effort': 'high'}
    assert chosen.timeout == 300 and chosen.max_retries == 0 and not chosen.trust_env


def test_source_visual_default_keeps_deepseek_precedence_and_allows_luna_only():
    deepseek, luna = provider('deepseek'), provider('chatgpt-reserve')
    assert select_visual_config([luna, deepseek]).extra_body['thinking'] == {'type': 'enabled'}
    assert select_visual_config([luna]).name == luna.name
    assert not deepseek.extra_body and not luna.extra_body


def test_visual_route_stops_when_the_same_provider_has_two_identities():
    with pytest.raises(ReviewConflictError, match='source_visual_provider_unavailable'):
        select_visual_config([provider('deepseek'), provider('deepseek'), provider('chatgpt-reserve')])
