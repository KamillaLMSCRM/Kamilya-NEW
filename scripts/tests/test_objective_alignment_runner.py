"""Harness safety checks independent of provider/network availability."""
import asyncio
from types import SimpleNamespace

import pytest

from scripts.dev.objective_alignment.run import Recorder, experiment_fingerprint, fingerprint


class FakeClient:
    def __init__(self):
        async def request(payload):
            return {"usage": {"prompt_tokens": 10, "completion_tokens": 2}}

        self._clients = [SimpleNamespace(_request=request)]

    async def ainvoke_validated(self, messages, parser, **kwargs):
        await self._clients[0]._request({})
        return SimpleNamespace(value=parser('{"ok":true}'), provider="fake", model_id="synthetic")


def test_physical_request_budget_is_not_hidden_by_validated_calls():
    async def exercise():
        recorder = Recorder(FakeClient(), max_calls=1)
        request = [{"role": "user", "content": '{"task":"test"}'}]
        await recorder.ainvoke_validated(request, parser=lambda raw: raw)
        with pytest.raises(RuntimeError, match="budget"):
            await recorder.ainvoke_validated(request, parser=lambda raw: raw)
        assert recorder.calls == 1
        assert recorder.usage == {"prompt_tokens": 10, "completion_tokens": 2}
        assert recorder.trace[-1]["error"] == "RuntimeError"

    asyncio.run(exercise())


def test_parser_failure_is_retained_not_reported_success():
    async def exercise():
        recorder = Recorder(FakeClient())

        def reject(raw):
            raise ValueError("no")

        with pytest.raises(ValueError):
            await recorder.ainvoke_validated([{"content": '{"task":"test"}'}], parser=reject)
        assert recorder.trace[0]["responses"][0]["parser_error"] == "ValueError"
        assert "provider" not in recorder.trace[0]

    asyncio.run(exercise())


def test_fingerprints_cover_active_seam_and_frozen_prompts():
    current = fingerprint()
    assert "apps/api/app/modules/ai/evidence_engine/application.py" in current
    assert "apps/api/app/modules/ai/evidence_engine/semantic_assessment.py" in current
    assert "scripts/dev/objective_alignment/engine.py" in experiment_fingerprint()
    assert all(len(value) == 64 for value in current.values())


def test_http_failure_preserves_only_status_not_secret_bearing_message():
    class Failure(Exception):
        last_exc = SimpleNamespace(response=SimpleNamespace(status_code=402))

    async def exercise():
        client = FakeClient()

        async def fail(payload):
            raise Failure("unsafe raw response should not be logged")

        client._clients[0]._request = fail
        recorder = Recorder(client)
        with pytest.raises(Failure):
            await recorder.ainvoke_validated([{"content": '{"task":"test"}'}], parser=lambda raw: raw)
        assert recorder.http_errors == [402]
        assert "unsafe" not in str(recorder.trace)

    asyncio.run(exercise())


def test_cache_usage_is_retained_per_request_and_missing_is_not_zero():
    async def exercise():
        client = FakeClient()

        async def response(payload):
            return {"usage": {"prompt_tokens": 10, "completion_tokens": 8,
                              "prompt_cache_hit_tokens": 6, "prompt_cache_miss_tokens": 4,
                              "completion_tokens_details": {"reasoning_tokens": 5}}}

        client._clients[0]._request = response
        recorder = Recorder(client)
        await recorder.ainvoke_validated([{"content": '{"task":"test"}'}], parser=lambda raw: raw)
        assert recorder.token_details == {"cache_hit_tokens": 6, "cache_miss_tokens": 4,
                                          "reasoning_tokens": 5}
        assert recorder.requests[0]["cache_hit_tokens"] == 6
        assert len(recorder.requests[0]["payload_sha256"]) == 64
        assert "messages" not in recorder.requests[0]
        unknown = Recorder(FakeClient())
        await unknown.ainvoke_validated([{"content": '{"task":"test"}'}], parser=lambda raw: raw)
        assert all(value is None for value in unknown.token_details.values())

    asyncio.run(exercise())


def test_asus_route_is_explicit_no_paid_fallback_or_ambient_credentials(monkeypatch):
    import app.modules.ai.llm_client as llm
    from scripts.dev.objective_alignment.run import provider_config

    def paid_provider_must_not_be_resolved():
        raise AssertionError("ASUS must not resolve paid credentials")

    monkeypatch.setattr(llm, "_deepseek_llm_provider", paid_provider_must_not_be_resolved)
    cfg = provider_config({"provider": "asus-glm", "thinking": "native"})
    assert cfg.base_url == "http://10.66.66.28:8888/v1"
    assert cfg.model == "GLM-5.3-Flash-EXL3"
    assert cfg.max_retries == 0
    assert cfg.timeout == 600
    assert cfg.extra_body == {}
    selective = provider_config({"provider": "asus-glm", "thinking": "selective"})
    assert selective.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_asus_selective_thinking_is_bounded_by_role():
    from scripts.dev.objective_alignment.run import thinking_profile

    assert thinking_profile("asus-glm", "objective_plan", "selective") == (
        {"chat_template_kwargs": {"enable_thinking": False}}, 4096,
    )
    assert thinking_profile("asus-glm", "objective_teaching", "selective") == (
        {"chat_template_kwargs": {"enable_thinking": False}}, 4096,
    )
    assert thinking_profile("asus-glm", "blind_audit", "selective") == (
        {"chat_template_kwargs": {"enable_thinking": True}, "reasoning_effort": "low"}, 8192,
    )
    assert thinking_profile("asus-glm", "objective_assessment_contract_repair", "selective") == (
        {"chat_template_kwargs": {"enable_thinking": True}, "reasoning_effort": "low"}, 8192,
    )
