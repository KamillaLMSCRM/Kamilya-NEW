"""Managed author format is opt-in, request-bound, and checked on receipt."""
import json
import socket
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.managed_luna_client import ManagedLunaClient, ManagedLunaError
from app.modules.ai.v3.author_response_schema import lesson_author_response_format, lesson_author_schema_hash
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def lesson():
    variant = {"variant_id": "v", "branch_context": "", "scenario_premise": "example", "prompt": "question",
               "correct_option": {"text": "correct"}, "distractor_pool": [
                   {"text": "incorrect", "distractor_category": "procedural_confusion"} for _ in range(3)],
               "explanation": "explanation", "source_quote": "example"}
    return {"lesson_id": "id", "title": "title", "module_title": "module", "content": '# Тест\n"quoted" \\ path',
            "cases": [{"case_id": "c", "rule_id": "r", "learning_objective": "aim", "variants": [variant]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_author_opt_in_only_leaves_extraction_and_review_legacy(enabled):
    calls = []
    async def invoke(messages, response_format):
        calls.append(response_format)
        return lesson()
    engine = V3GenerationPipeline(invoke, structured_author_output=enabled)
    await engine.extract_rule_model("d", "example", "a" * 64)
    generated = await engine.generate_lesson_with_scenarios("module", "title", [])
    await engine.review_lesson(generated, [])
    assert calls == [{"type": "json_object"},
                     lesson_author_response_format() if enabled else {"type": "json_object"},
                     {"type": "json_object"}]
    assert generated.content == lesson()["content"]


@pytest.fixture
def managed(monkeypatch):
    tenant, user, job = uuid4(), uuid4(), str(uuid4())
    requests = []
    body = {"model": "gpt-5.6-luna", "choices": [{"message": {"content": json.dumps(lesson(), ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
            "structured_output_policy": "typed-json-object-v1", "response_format_sha256": lesson_author_schema_hash()}
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(body, ensure_ascii=False).encode()
    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=Stream())
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.managed_luna_client.httpx.AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    client = ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="synthetic",
                               tenant_id=tenant, user_id=user, job_id=job, credential_revision="r1")
    return client, tenant, user, job, body, requests


async def prepare(client, response_format):
    return await client.prepare([{"role": "user", "content": "example"}], max_output_tokens=20,
                                ownership_checkpoint=AsyncMock(return_value=True), response_format=response_format)


async def invoke(client, tenant, user, job, capability):
    return await client.invoke(capability, tenant_id=tenant, user_id=user, job_id=job,
                               stage_id="a" * 64, ownership_checkpoint=AsyncMock(return_value=True))


@pytest.mark.asyncio
async def test_actual_managed_client_freezes_request_and_roundtrips_once(managed):
    client, tenant, user, job, _, requests = managed
    fmt = lesson_author_response_format()
    capability = await prepare(client, fmt)
    fmt["json_schema"]["name"] = "mutated"
    assert not requests
    result = await invoke(client, tenant, user, job, capability)
    sent = json.loads(requests[0].content)
    assert sent["response_format"] == lesson_author_response_format()
    assert sent["structured_output_policy"] == "typed-json-object-v1" and result.content == lesson()
    with pytest.raises(ManagedLunaError):
        await invoke(client, tenant, user, job, capability)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_policy", "wrong_policy", "missing_hash", "wrong_hash", "wrong_shape"])
async def test_wrong_receipt_or_shape_fails_closed_without_retry(managed, failure):
    client, tenant, user, job, body, requests = managed
    if failure == "missing_policy":
        del body["structured_output_policy"]
    elif failure == "wrong_policy":
        body["structured_output_policy"] = "wrong"
    elif failure == "missing_hash":
        del body["response_format_sha256"]
    elif failure == "wrong_hash":
        body["response_format_sha256"] = "0" * 64
    else:
        body["choices"][0]["message"]["content"] = '{"title":"incomplete"}'
    capability = await prepare(client, lesson_author_response_format())
    with pytest.raises(ManagedLunaError) as caught:
        await invoke(client, tenant, user, job, capability)
    if failure == "wrong_shape":
        record = caught.value.checked_receipt(tenant_id=str(tenant), user_id=user, job_id=job,
                                              stage="a" * 64, route_fingerprint=client.cache_fingerprint())
        assert record["phase"] == "structured_shape" and record["accepted"] is False
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_invalid_format_fails_before_http(managed):
    client, _, _, _, _, requests = managed
    fmt = lesson_author_response_format()
    fmt["json_schema"]["schema"]["additionalProperties"] = True
    with pytest.raises(ValueError, match="managed_luna_structured_format_invalid"):
        await prepare(client, fmt)
    assert not requests


@pytest.mark.asyncio
async def test_stage_once_binds_typed_hash_and_denies_wrong_stage_or_client(monkeypatch, managed):
    client, tenant, user, job, _, _ = managed
    journal = PendingStageJournal(str(tenant), user, job, None, verify_source=AsyncMock(return_value=True))
    messages, fmt = [{"role": "user", "content": "example"}], lesson_author_response_format()
    run = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("app.modules.ai.v3.direct_luna_owned_stage.run_direct_owned_stage", run)
    options = dict(journal=journal, stage="lesson", group_id="g", source_sha256="a" * 64,
                   route_fingerprint="b" * 64, messages=messages, response_format=fmt,
                   invoke=AsyncMock(), direct_client=client)
    assert await stage_once(**options) == {"ok": True}
    sent = run.await_args.kwargs
    assert sent["response_format"] == fmt and sent["plan"]["request_sha256"] == _digest([messages, fmt])
    run.reset_mock()
    with pytest.raises(ValueError, match="direct_owned_format_invalid"):
        await stage_once(**{**options, "stage": "review"})
    direct = object.__new__(DirectLunaResponsesClient)
    with pytest.raises(ValueError, match="direct_owned_format_invalid"):
        await stage_once(**{**options, "direct_client": direct})
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_stage_rejects_changed_plan_hash_before_inspection(monkeypatch, managed):
    client, tenant, user, job, _, _ = managed
    journal = PendingStageJournal(str(tenant), user, job, None, verify_source=AsyncMock(return_value=True))
    inspect = AsyncMock(side_effect=AssertionError("must not inspect or claim"))
    monkeypatch.setattr("app.modules.ai.v3.direct_luna_owned_stage.inspect_owned_stage", inspect)
    with pytest.raises(ValueError, match="managed_structured_plan_invalid"):
        await run_direct_owned_stage(journal=journal, client=client, plan={"stage": "lesson", "request_sha256": "0" * 64},
            result_key="r", claim_key="c", validate_value=lambda x: x, validate_response=lambda x: x,
            messages=[{"role": "user", "content": "example"}], max_output_tokens=20,
            response_format=lesson_author_response_format())
    inspect.assert_not_awaited()


@pytest.mark.asyncio
async def test_typed_batch_stage_is_bound_and_other_scopes_fail_before_claim(monkeypatch, managed):
    from app.modules.ai.v3.batch_review_response_schema import batch_review_response_format
    client, tenant, user, job, _, _ = managed
    journal = PendingStageJournal(str(tenant), user, job, None, verify_source=AsyncMock(return_value=True))
    messages = [{"role": "user", "content": "review exact input"}]
    fmt = batch_review_response_format()
    run = AsyncMock(return_value={"items": []})
    monkeypatch.setattr("app.modules.ai.v3.direct_luna_owned_stage.run_direct_owned_stage", run)
    options = dict(journal=journal, stage="review", group_id="batched-review:g", source_sha256="a" * 64,
                   route_fingerprint="b" * 64, messages=messages, response_format=fmt,
                   invoke=AsyncMock(), direct_client=client)
    assert await stage_once(**options) == {"items": []}
    sent = run.await_args.kwargs
    assert sent["response_format"] == fmt and sent["plan"]["request_sha256"] == _digest([messages, fmt])
    run.reset_mock()
    for change in ({"stage": "lesson"}, {"stage": "repair"}, {"group_id": "ordinary-review"},
                   {"direct_client": object.__new__(DirectLunaResponsesClient)}):
        with pytest.raises(ValueError, match="direct_owned_format_invalid"):
            await stage_once(**(options | change))
    run.assert_not_awaited()
