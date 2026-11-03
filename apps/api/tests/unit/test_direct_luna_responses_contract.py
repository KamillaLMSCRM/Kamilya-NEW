import json

import httpx
import pytest

from app.modules.ai.direct_luna_responses_contract import (
    COUNT_ENDPOINT,
    GENERATION_ENDPOINT,
    ResponsesRequest,
    build_request,
    validate_count,
)


def test_exact_payload_and_redacted_immutable_copies():
    messages = [{"role": "user", "content": "private text"}]
    request = build_request(messages, max_output_tokens=100)
    expected = {"model": "gpt-6-luna", "input": [{"role": "system", "content": "Return a JSON object."}, *messages],
                "reasoning": {"effort": "medium"}, "text": {"format": {"type": "json_object"}},
                "max_output_tokens": 100, "store": False}
    expected_count = {key: value for key, value in expected.items() if key not in {"store", "max_output_tokens"}}
    assert request.count_payload() == expected_count and request.generation_payload() == expected
    request.count_payload()["input"][1]["content"] = "mutated"
    assert request.generation_payload() == expected and messages[0]["content"] == "private text"
    assert "private text" not in repr(request)


@pytest.mark.asyncio
async def test_fake_count_and_generation_share_only_input_fields():
    request = build_request([{"role": "user", "content": "synthetic"}], max_output_tokens=50)
    captured = []
    def handler(message):
        captured.append((str(message.url), json.loads(message.content)))
        return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 12})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        counted = await client.post(COUNT_ENDPOINT, json=request.count_payload())
        await client.post(GENERATION_ENDPOINT, json=request.generation_payload())
    assert captured[0][1] == {key: value for key, value in captured[1][1].items()
                              if key not in {"store", "max_output_tokens"}}
    assert "store" not in captured[0][1] and "max_output_tokens" not in captured[0][1]
    assert validate_count(request, raw_response=counted.text, request_sha256=request.input_sha256) == 12


@pytest.mark.parametrize("raw", ['{}', '{"object":"response.input_tokens","input_tokens":true}',
    '{"object":"response.input_tokens","input_tokens":-1}',
    '{"object":"response.input_tokens","input_tokens":1,"input_tokens":2}',
    '{"object":"response.input_tokens","input_tokens":NaN}'])
def test_bad_or_unknown_count_fails_closed(raw):
    request = build_request([{"role": "user", "content": "x"}], max_output_tokens=1)
    with pytest.raises(ValueError):
        validate_count(request, raw_response=raw, request_sha256=request.input_sha256)


def test_count_bound_and_request_identity():
    request = build_request([{"role": "user", "content": "x"}], max_output_tokens=128000)
    with pytest.raises(ValueError, match="context_limit"):
        validate_count(request, raw_response='{"object":"response.input_tokens","input_tokens":922001}',
                       request_sha256=request.input_sha256)
    with pytest.raises(ValueError, match="request_mismatch"):
        validate_count(request, raw_response='{"object":"response.input_tokens","input_tokens":1}', request_sha256="other")


@pytest.mark.parametrize("limit", [True, 0, 128001])
def test_output_limit_validation(limit):
    with pytest.raises(ValueError):
        build_request([{"role": "user", "content": "x"}], max_output_tokens=limit)


def test_forged_constructor_output_mismatch_rejected():
    original = build_request([{"role": "user", "content": "x"}], max_output_tokens=128000)
    forged = ResponsesRequest(original._canonical, original.input_sha256, 1)
    with pytest.raises(ValueError, match="request_mismatch"):
        validate_count(forged, raw_response='{"object":"response.input_tokens","input_tokens":1}',
                       request_sha256=forged.input_sha256)


def test_forged_canonical_payload_rejected_even_with_matching_hash():
    import hashlib
    original = build_request([{"role": "user", "content": "x"}], max_output_tokens=100)
    payload = original.generation_payload()
    payload["model"] = "untrusted"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    forged = ResponsesRequest(raw, digest, 100)
    with pytest.raises(ValueError, match="request_mismatch"):
        validate_count(forged, raw_response='{"object":"response.input_tokens","input_tokens":1}', request_sha256=digest)
