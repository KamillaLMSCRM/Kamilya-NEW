import pytest

from app.modules.ai.llm_client import LLMProviderConfig
from app.modules.source_editorial_review.analysis import select_visual_config
from app.modules.source_editorial_review.domain import ReviewConflictError


def provider(name):
    return LLMProviderConfig(name, 'https://example.invalid/v1', '', 'fixture')


def test_source_visual_qa_selects_luna_and_never_silently_falls_back():
    deepseek, luna = provider('deepseek'), provider('chatgpt-reserve')
    chosen = select_visual_config([deepseek, luna], luna_qa=True)
    assert chosen.name == luna.name and chosen.extra_body == {'reasoning_effort': 'low'}
    with pytest.raises(ReviewConflictError, match='source_visual_provider_unavailable'):
        select_visual_config([deepseek], luna_qa=True)


def test_source_visual_default_keeps_deepseek_precedence_and_allows_luna_only():
    deepseek, luna = provider('deepseek'), provider('chatgpt-reserve')
    assert select_visual_config([luna, deepseek], luna_qa=False).extra_body['thinking'] == {'type': 'enabled'}
    assert select_visual_config([luna], luna_qa=False).name == luna.name
    assert not deepseek.extra_body and not luna.extra_body



def test_visual_route_stops_when_the_same_provider_has_two_identities():
    with pytest.raises(ReviewConflictError, match='source_visual_provider_unavailable'):
        select_visual_config([provider('deepseek'), provider('deepseek'), provider('chatgpt-reserve')], luna_qa=False)
