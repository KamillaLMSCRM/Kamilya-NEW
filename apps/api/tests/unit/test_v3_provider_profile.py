"""Request-local V3 provider profile contract."""

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot
from app.modules.ai import llm_client
from app.modules.ai.v3.provider_profile import V3ProfiledClient
from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
from app.modules.ai.v3.stage_checkpoint import _digest


def policy(*, revision: int = 7, seconds: float = 120.0) -> RuntimeSnapshot:
    return RuntimeSnapshot(revision, {
        "provider.deepseek.timeout_seconds": seconds,
    })


def client() -> llm_client.ResilientLLMClient:
    return llm_client.ResilientLLMClient([
        llm_client.LLMProviderConfig(
            "deepseek", "https://primary.invalid/v1", "synthetic", "deepseek-test",
            max_retries=2, extra_body={"thinking": {"type": "disabled"}},
            managed_evidence_profile=True,
        ),
        llm_client.LLMProviderConfig("fallback", "https://fallback.invalid/v1", "synthetic", "fallback"),
    ], max_tokens=2000)


@pytest.mark.asyncio
async def test_profile_enables_reasoning_without_mutating_client(monkeypatch):
    seen: list[dict] = []

    async def request(_client, payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = client()
    before = [item.config for item in raw._clients]
    profiled = V3ProfiledClient(raw, policy(), job_id=str(uuid4()))
    result = await profiled.ainvoke("synthetic", response_format={"type": "json_object"})
    assert result.content == '{"ok":true}'
    assert seen[0]["thinking"] == {"type": "enabled"}
    assert seen[0]["reasoning_effort"] == "low"
    assert seen[0]["max_tokens"] == 16384
    assert [item.config for item in raw._clients] == before


@pytest.mark.asyncio
async def test_profile_does_not_change_next_unprofiled_request(monkeypatch):
    seen: list[dict] = []

    async def request(_client, payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = client()
    await V3ProfiledClient(raw, policy(), job_id="not-a-secret").ainvoke("synthetic")
    await raw.ainvoke("synthetic")
    assert seen[0]["thinking"] == {"type": "enabled"}
    assert seen[1]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in seen[1]


@pytest.mark.asyncio
async def test_profile_keeps_existing_fallback_limits_and_order(monkeypatch):
    seen: list[tuple[str, dict, int]] = []

    async def invoke(self, _messages, **kwargs):
        seen.append((self.config.name, {**self.config.extra_body, **kwargs}, self.max_tokens))
        if self.config.name == "deepseek":
            raise llm_client.ProviderFailedError("deepseek", RuntimeError("synthetic"))
        return SimpleNamespace(content='{"fallback":true}', finish_reason="stop", content_is_reasoning=False)

    monkeypatch.setattr(llm_client.LLMClient, "ainvoke", invoke)
    raw = client()
    response = await V3ProfiledClient(raw, policy(), job_id=str(uuid4())).ainvoke("synthetic")
    assert response.content == '{"fallback":true}'
    assert seen[0][0] == "deepseek" and seen[0][1]["thinking"] == {"type": "enabled"}
    assert seen[0][1]["reasoning_effort"] == "low" and seen[0][2] == 16384
    assert seen[1][0] == "fallback" and seen[1][2] == 2000
    assert "thinking" not in seen[1][1] and "reasoning_effort" not in seen[1][1]


@pytest.mark.asyncio
async def test_profile_does_not_upgrade_unmanaged_tenant_named_deepseek(monkeypatch):
    seen: list[dict] = []

    async def request(_client, payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": '{"tenant":true}'}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = llm_client.ResilientLLMClient([
        llm_client.LLMProviderConfig(
            "deepseek", "https://tenant.invalid/v1", "synthetic", "tenant-model",
            extra_body={"thinking": {"type": "disabled"}}, managed_evidence_profile=False,
        ),
    ], max_tokens=2000)
    await V3ProfiledClient(raw, policy(), job_id=str(uuid4())).ainvoke("synthetic")
    assert seen[0]["thinking"] == {"type": "disabled"}
    assert seen[0]["max_tokens"] == 2000
    assert "reasoning_effort" not in seen[0]


def test_profile_fingerprint_binds_effective_policy():
    raw = client()
    first = V3ProfiledClient(raw, policy(seconds=120), job_id=str(uuid4()))
    second = V3ProfiledClient(raw, policy(seconds=90), job_id=str(uuid4()))
    assert first.cache_fingerprint() != raw.cache_fingerprint()
    assert first.cache_fingerprint() != second.cache_fingerprint()
    same_effective = V3ProfiledClient(raw, policy(revision=999, seconds=120), job_id=str(uuid4()))
    assert first.cache_fingerprint() == same_effective.cache_fingerprint()


@pytest.mark.asyncio
async def test_route_mutation_fails_before_provider(monkeypatch):
    calls = 0

    async def request(_client, _payload):
        nonlocal calls
        calls += 1
        return {"choices": [{"message": {"content": "unexpected"}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = client()
    profiled = V3ProfiledClient(raw, policy(), job_id=str(uuid4()))
    original = raw.cache_fingerprint
    monkeypatch.setattr(raw, "cache_fingerprint", lambda: "f" * 64)
    with pytest.raises(RuntimeError, match="v3_provider_profile_route_changed"):
        await profiled.ainvoke("synthetic")
    assert calls == 0
    monkeypatch.setattr(raw, "cache_fingerprint", original)


@pytest.mark.asyncio
async def test_policy_mutation_fails_before_provider(monkeypatch):
    calls = 0

    async def request(_client, _payload):
        nonlocal calls
        calls += 1
        return {"choices": [{"message": {"content": "unexpected"}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = client()
    frozen = policy()
    profiled = V3ProfiledClient(raw, frozen, job_id=str(uuid4()))
    frozen.values["provider.deepseek.timeout_seconds"] = 90  # type: ignore[index]
    with pytest.raises(RuntimeError, match="v3_provider_profile_policy_changed"):
        await profiled.ainvoke("synthetic")
    assert calls == 0


@pytest.mark.asyncio
async def test_logging_is_metadata_only(monkeypatch, caplog):
    async def request(_client, _payload):
        return {"choices": [{"message": {"content": '{"value":"SECRET_BODY"}'}}]}

    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    with caplog.at_level("INFO"):
        await V3ProfiledClient(client(), policy(), job_id="bad/secret").ainvoke("SECRET_PROMPT")
    assert "SECRET_BODY" not in caplog.text
    assert "SECRET_PROMPT" not in caplog.text
    assert "bad/secret" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["length", "content_filter", "reasoning", "malformed"])
async def test_rejected_profile_output_is_bound_and_never_falls_back(monkeypatch, failure):
    job_id = str(uuid4())
    raw = client()
    profiled = V3ProfiledClient(raw, policy(), job_id=job_id)
    messages = [{"role": "user", "content": "synthetic request"}]
    response_format = {"type": "json_object"}
    content = '{"partial":"data"}' if failure != "malformed" else '{"partial":'
    seen = []
    async def invoke(provider, _messages, **kwargs):
        seen.append(provider.config.name)
        return SimpleNamespace(content=content, finish_reason=failure if failure in {"length", "content_filter"} else "stop",
                               content_is_reasoning=failure == "reasoning", provider_name=provider.config.name,
                               model="deepseek-test", usage_complete=True, prompt_tokens=4, completion_tokens=2)
    monkeypatch.setattr(llm_client.LLMClient, "ainvoke", invoke)
    with pytest.raises(ModelArtifactRejectedError, match="v3_model_artifact_rejected") as caught:
        await profiled.ainvoke(messages, response_format=response_format)
    receipt = caught.value.checked_receipt(job_id=job_id, route=profiled.cache_fingerprint(),
                                           request=_digest([messages, response_format]))
    assert base64.b64decode(receipt["raw_base64"]).decode() == content
    assert receipt["accepted"] is False and receipt["complete_http_response"] is False
    assert (receipt["input_tokens"], receipt["output_tokens"]) == (4, 2)
    assert seen == ["deepseek"]


@pytest.mark.asyncio
async def test_reasoning_only_response_from_provider_is_bound_not_replayed(monkeypatch):
    job_id = str(uuid4())
    chain = client()
    profiled = V3ProfiledClient(chain, policy(), job_id=job_id)
    messages = [{"role": "user", "content": "request"}]
    calls = []
    async def request(provider, payload):
        calls.append(provider.config.name)
        return {"model": "deepseek-test", "choices": [{"message": {"reasoning": '{"partial":true}'},
                                                          "finish_reason": "stop"}]}
    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    with pytest.raises(ModelArtifactRejectedError) as caught:
        await profiled.ainvoke(messages, response_format={"type": "json_object"})
    record = caught.value.checked_receipt(job_id=job_id, route=profiled.cache_fingerprint(),
        request=_digest([messages, {"type": "json_object"}]))
    assert base64.b64decode(record["raw_base64"]) == b'{"partial":true}'
    assert calls == ["deepseek"]
