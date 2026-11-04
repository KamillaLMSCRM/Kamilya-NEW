"""Prompt-only structured output keeps the same local V3 contract."""
import hashlib
import json
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.llm_client import LLMClient, LLMProviderConfig, ResilientLLMClient
from app.modules.ai.v3.practical_atomic_audit import atomic_audit_format
from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
from tests.unit.test_v3_practical_atomic_audit import audit_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
MODEL = 'DeepSeek-V4.1-Flash-1017'


def provider(**kwargs):
    return LLMProviderConfig(name='tensorfold', base_url='http://synthetic.invalid/v1',
                             api_key='synthetic-credential', model=MODEL, **kwargs)


def envelope(value, *, finish='stop'):
    return {'model': MODEL, 'choices': [{'message': {'content': json.dumps(value)}, 'finish_reason': finish}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['native', 'prompt_json'])
async def test_real_client_wire_and_closed_contract(case, mode):
    _, packet, course = case
    fmt = atomic_audit_format(packet, course, typed_findings=True, strict_owners=True)
    result = audit_value(packet, course)
    client = LLMClient(provider(structured_output_mode=mode))
    client._request = AsyncMock(return_value=envelope(result))
    messages = [{'role': 'system', 'content': 'Act on the provided data.'}, {'role': 'user', 'content': 'Question.'}]
    returned = await client.ainvoke(messages, response_format=fmt)
    payload = client._request.await_args.args[0]
    assert json.loads(returned.content) == result
    assert ('response_format' in payload) is (mode == 'native')
    if mode == 'native':
        assert payload['response_format'] == {'type': 'json_object'}
    schema_text = json.dumps(fmt['json_schema']['schema'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert 'Required response JSON schema:\n' + schema_text in payload['messages'][0]['content']
    assert 'Return the required response as JSON.' in payload['messages'][0]['content']
    assert messages[0]['content'] == 'Act on the provided data.'
    assert 'synthetic-credential' not in json.dumps(payload)


@pytest.mark.asyncio
async def test_prompt_json_invalid_response_is_still_rejected(case):
    _, packet, course = case
    fmt = atomic_audit_format(packet, course, typed_findings=True, strict_owners=True)
    result = audit_value(packet, course)
    result['source_checks'][0]['lesson_ids'] = []
    client = LLMClient(provider(structured_output_mode='prompt_json'))
    client._request = AsyncMock(return_value=envelope(result))
    with pytest.raises(ModelArtifactRejectedError):
        await client.ainvoke('Question.', response_format=fmt)
    assert client._request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('fmt', [{'type': 'json_object'}, {'type': 'json_schema', 'json_schema': {'name': 'unknown'}}])
async def test_unregistered_structured_format_never_dispatches(fmt):
    client = LLMClient(provider(structured_output_mode='prompt_json'))
    client._request = AsyncMock()
    with pytest.raises(ValueError, match='prompt_json_response_format_unregistered'):
        await client.ainvoke('Question.', response_format=fmt)
    client._request.assert_not_awaited()


@pytest.mark.asyncio
async def test_plain_request_stays_plain_and_length_reason_is_not_coerced(case):
    _, packet, course = case
    client = LLMClient(provider(structured_output_mode='prompt_json'))
    client._request = AsyncMock(return_value=envelope({'anything': True}))
    await client.ainvoke('Plain question.')
    payload = client._request.await_args.args[0]
    assert 'response_format' not in payload and payload['messages'] == [{'role': 'user', 'content': 'Plain question.'}]
    client._request = AsyncMock(return_value=envelope(audit_value(packet, course), finish='length'))
    result = await client.ainvoke('Question.', response_format=atomic_audit_format(packet, course, typed_findings=True))
    assert result.finish_reason == 'length'


@pytest.mark.parametrize('key', ['response_format', 'guided_json', 'guided_regex', 'structured_outputs', 'structured_output_policy'])
def test_prompt_json_rejects_vendor_structured_extras(key):
    with pytest.raises(ValueError, match='prompt_json_provider_config_invalid'):
        provider(structured_output_mode='prompt_json', extra_body={key: {}})


@pytest.mark.asyncio
async def test_late_mutation_of_vendor_extra_is_rejected_before_dispatch():
    config = provider(structured_output_mode='prompt_json')
    client = LLMClient(config)
    client._request = AsyncMock()
    config.extra_body['guided_json'] = {}
    with pytest.raises(ValueError, match='prompt_json_provider_config_invalid'):
        await client.ainvoke('Question.')
    client._request.assert_not_awaited()


def test_native_fingerprint_matches_historical_serialization_and_mode_change_fences_replay():
    config = provider()
    serialized = asdict(config)
    del serialized['structured_output_mode']
    expected = hashlib.sha256(json.dumps({'providers': [serialized], 'temperature': 0.7, 'max_tokens': 8192},
                                         sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert ResilientLLMClient([config]).cache_fingerprint() == expected
    assert ResilientLLMClient([provider(structured_output_mode='prompt_json')]).cache_fingerprint() != expected
    with pytest.raises(ValueError, match='structured_output_mode_invalid'):
        provider(structured_output_mode='unknown')
    with pytest.raises(ValueError, match='prompt_json_provider_config_invalid'):
        LLMProviderConfig(name='chatgpt-reserve', base_url='http://synthetic.invalid', api_key='', model=MODEL,
                          structured_output_mode='prompt_json')
