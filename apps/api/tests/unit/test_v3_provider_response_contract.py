"""Versioned response contracts at real local mocked provider transports."""
import base64
import json
import socket
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.llm_client import LLMClient, LLMProviderConfig, ResilientLLMClient
from app.modules.ai.v3.author_response_schema import lesson_author_response_format
from app.modules.ai.v3.extraction_response_schema import rule_extraction_response_format
from app.modules.ai.v3.provider_profile import V3ProfiledClient
from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_v3_provider_profile import policy


def test_practical_concise_array_contract_registered_with_consumer_validation():
    from app.modules.ai.v3.practical_review import _format
    from app.modules.ai.v3.response_contracts import (
        matches_response_contract,
        response_contract,
    )

    fmt = _format(['src-a'], 'a' * 64, ['l'], {'q': 3}, [], concise=True)
    value = {'source_fingerprint': 'a' * 64, 'source_review': 'Reviewed.', 'source_notes': [],
             'findings': [], 'answer_keys': {'q': 0}, 'narrative_sources': {'l': ['src-a']},
             'answerability': [{'question_id': 'q', 'possible_options': [0], 'status': 'UNIQUE',
                                'source_refs': ['src-a'], 'reason': 'Only this answer applies.'}]}
    assert response_contract(fmt) == 'practical_review'
    assert response_contract_hash(fmt)
    assert matches_response_contract(value, fmt)
    value['answerability'][0]['source_refs'] = ['foreign']
    assert not matches_response_contract(value, fmt)


def config(name):
    return LLMProviderConfig(name=name, base_url="http://" + name + "/v1", api_key="test", model="test-model",
                             max_retries=0, trust_env=False)


def author():
    return {"lesson_id": "l", "title": "t", "module_title": "m", "content": '# Header\n"quote" \\ path', "cases": []}


def extraction():
    return {"document_title": "d", "overview": "", "rules": [{"rule_id": "r", "section": "", "title": "",
        "statement": "x", "conditions": ["if"], "exceptions": [], "actors": [], "timing": "",
        "consequences": "", "source_quote": "x"}]}


@pytest.fixture
def transport(monkeypatch):
    calls = []
    state = {"body": None, "failure": False}
    def handler(request):
        payload = json.loads(request.content)
        calls.append((request.url.host, payload))
        if state["failure"] and request.url.host == "deepseek":
            return httpx.Response(503)
        result = state["body"](request.url.host, payload) if callable(state["body"]) else state["body"]
        return httpx.Response(200, json=result)
    def deny(*args, **kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.llm_client.httpx.AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    return state, calls


def envelope(content, *, typed=None, usage=True, model="test-model"):
    body = {"model": model, "choices": [{"message": {"content": content}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 10, "completion_tokens": 5}
    if typed is not None:
        body.update(structured_output_policy="typed-json-object-v1", response_format_sha256=response_contract_hash(typed))
    return body


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "other-provider"])
async def test_native_wire_retains_exact_schema_as_trusted_instruction(transport, provider):
    state, calls = transport
    fmt = rule_extraction_response_format()
    state["body"] = envelope(json.dumps(extraction()))
    result = await LLMClient(config(provider), max_retries=0).ainvoke(
        [{"role": "user", "content": "untrusted example"}], response_format=fmt)
    sent = calls[0][1]
    assert sent["response_format"] == {"type": "json_object"} and "structured_output_policy" not in sent
    system = next(m["content"] for m in sent["messages"] if m["role"] == "system")
    assert json.dumps(fmt["json_schema"]["schema"], ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) in system
    assert json.loads(result.content) == extraction() and result.provider_name == provider
    assert result.model == "test-model" and result.usage_complete is True
    assert (result.prompt_tokens, result.completion_tokens) == (10, 5)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cli_typed_full_contract_ack_and_markdown_roundtrip(transport):
    state, calls = transport
    fmt = lesson_author_response_format()
    state["body"] = envelope(json.dumps(author(), ensure_ascii=False), typed=fmt)
    result = await LLMClient(config("chatgpt-reserve"), max_retries=0).ainvoke(
        [{"role": "user", "content": "request"}], response_format=fmt)
    assert calls[0][1]["response_format"] == fmt
    assert calls[0][1]["structured_output_policy"] == "typed-json-object-v1"
    assert json.loads(result.content) == author() and result.provider_name == "chatgpt-reserve"
    assert result.model == "test-model" and result.usage_complete is True and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["policy_missing", "policy_wrong", "hash_missing", "hash_wrong", "model_wrong"])
async def test_cli_requires_matching_ack_before_acceptance(transport, failure):
    state, calls = transport
    fmt = lesson_author_response_format()
    body = envelope(json.dumps(author()), typed=fmt)
    if failure == "policy_missing":
        del body["structured_output_policy"]
    elif failure == "policy_wrong":
        body["structured_output_policy"] = "other"
    elif failure == "hash_missing":
        del body["response_format_sha256"]
    elif failure == "hash_wrong":
        body["response_format_sha256"] = "0" * 64
    else:
        body["model"] = "other"
    state["body"] = body
    job_id = str(uuid4())
    chain = ResilientLLMClient([config("chatgpt-reserve"), config("fallback")], max_retries_per_provider=0)
    profiled = V3ProfiledClient(chain, policy(), job_id=job_id)
    messages = [{"role": "user", "content": "request"}]
    with pytest.raises(ModelArtifactRejectedError, match="v3_model_artifact_rejected") as caught:
        await profiled.ainvoke(messages, response_format=fmt)
    receipt = caught.value.checked_receipt(job_id=job_id, route=profiled.cache_fingerprint(),
                                          request=_digest([messages, fmt]))
    assert base64.b64decode(receipt["raw_base64"]).decode() == body["choices"][0]["message"]["content"]
    assert receipt["accepted"] is False and receipt["complete_http_response"] is False
    assert [host for host, _ in calls] == ["chatgpt-reserve"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["array_as_string", "duplicate", "nonfinite", "missing", "extra"])
async def test_complete_invalid_extraction_has_no_repair_or_retry(transport, failure):
    state, calls = transport
    fmt = rule_extraction_response_format()
    value = extraction()
    if failure == "array_as_string":
        value["rules"][0]["conditions"] = "if"
    elif failure == "missing":
        del value["rules"][0]["source_quote"]
    elif failure == "extra":
        value["rules"][0]["doc_id"] = "invented"
    content = json.dumps(value)
    if failure == "duplicate":
        content = content.replace('"overview": ""', '"overview": "", "overview": "other"')
    elif failure == "nonfinite":
        content = content.replace('"overview": ""', '"overview": NaN')
    state["body"] = envelope(content)
    with pytest.raises(ValueError):
        await LLMClient(config("deepseek"), max_retries=2).ainvoke("request", response_format=fmt)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_legacy_json_object_no_policy_and_missing_usage_marked_unknown(transport):
    state, calls = transport
    state["body"] = envelope('{"ok":true}', usage=False)
    result = await LLMClient(config("chatgpt-reserve"), max_retries=0).ainvoke(
        [{"role": "system", "content": "Return JSON"}], response_format={"type": "json_object"})
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert "structured_output_policy" not in calls[0][1]
    assert result.content == '{"ok":true}' and result.provider_name == "chatgpt-reserve"
    assert result.model == "test-model" and result.usage_complete is False


@pytest.mark.asyncio
async def test_fallback_transmits_provider_specific_wire_once_each(transport):
    state, calls = transport
    fmt = lesson_author_response_format()
    state["failure"] = True
    state["body"] = lambda host, payload: envelope(json.dumps(author()), typed=fmt)
    client = ResilientLLMClient([config("deepseek"), config("chatgpt-reserve")], max_retries_per_provider=0)
    result = await client.ainvoke("request", response_format=fmt)
    assert [host for host, _ in calls] == ["deepseek", "chatgpt-reserve"]
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert calls[1][1]["response_format"] == fmt and calls[1][1]["structured_output_policy"] == "typed-json-object-v1"
    assert result.provider_name == "chatgpt-reserve" and json.loads(result.content) == author()
