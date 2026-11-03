"""No-network tests for the owner-budgeted development transport."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.dev.generation_quality_api import QualityAPISession, QualityBudgetStopped


def session(tmp_path: Path, **kwargs):
    key = tmp_path / "key.txt"
    key.write_text("sk-proj-synthetic-not-a-secret", encoding="utf-8")
    return QualityAPISession(key_file=key, ledger=tmp_path / "ledger.json", **kwargs)


def reply(content='{"result":true}'):
    return {"model": "gpt-6-luna", "usage": {"prompt_tokens": 100, "completion_tokens": 200,
        "completion_tokens_details": {"reasoning_tokens": 120}},
        "choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_reservation_is_durable_before_post_and_settled_usage_survives_parser(tmp_path):
    client = session(tmp_path)
    calls = []

    async def post(url, **kwargs):
        ledger = json.loads(client.path.read_text())
        assert ledger["calls"][0]["status"] == "outcome_unknown"
        assert client.charged_micro_usd > 0
        calls.append(url)
        payload = json.loads(kwargs["content"])
        assert payload["reasoning_effort"] == "medium" and payload["service_tier"] == "default"
        assert "tools" not in payload
        assert any(row["role"] == "system" and "JSON" in row["content"] for row in payload["messages"])
        assert payload["messages"][-1] == {"role": "user", "content": "Synthetic JSON task"}
        return httpx.Response(200, json=reply())

    client._http.post = post
    try:
        result = await client.ainvoke_validated([{"role": "user", "content": "Synthetic JSON task"}], json.loads)
        assert result.value == {"result": True}
        record = client.state["calls"][0]
        assert record["charged_micro_usd"] == 200
        assert record["reasoning_tokens"] == 120
        assert record["estimated_cost_micro_usd"] == 110
        assert len(calls) == 1 and (tmp_path / "response-0000.json").is_file()
        assert "synthetic-not-a-secret" not in client.path.read_text()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_budget_stops_before_network(tmp_path):
    client = session(tmp_path, budget_micro_usd=1)
    async def forbidden(*args, **kwargs):
        pytest.fail("budget must stop before POST")
    client._http.post = forbidden
    try:
        with pytest.raises(QualityBudgetStopped, match="budget_exhausted"):
            await client.ainvoke_validated([{"role": "user", "content": "Synthetic"}], json.loads)
        assert client.state["calls"] == []
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "http", "parser", "usage", "model"])
async def test_failed_physical_attempts_are_retained_and_never_automatically_retried(tmp_path, failure):
    from app.modules.ai.llm_client import AllProvidersFailedError

    client = session(tmp_path)
    count = 0

    async def post(*args, **kwargs):
        nonlocal count
        count += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if failure == "http":
            return httpx.Response(401, json={"error": {"message": "not emitted"}})
        data = reply("not JSON" if failure == "parser" else '{"result":true}')
        if failure == "usage":
            data.pop("usage")
        if failure == "model":
            data["model"] = "unapproved-model"
        return httpx.Response(200, json=data)

    client._http.post = post
    try:
        with pytest.raises((httpx.ReadTimeout, QualityBudgetStopped, AllProvidersFailedError)):
            await client.ainvoke_validated([{"role": "user", "content": "Synthetic"}], json.loads)
        assert count == 1 and client.charged_micro_usd > 0
        assert len(client.state["calls"]) == 1
        row = client.state["calls"][0]
        if failure != "parser":
            assert row["charged_micro_usd"] == row["reserved_micro_usd"]
        else:
            assert row["parser_error_class"] == "JSONDecodeError"
            assert (tmp_path / "response-0000.json").is_file()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_second_writer_is_rejected_and_reopen_retains_prior_spend(tmp_path):
    client = session(tmp_path)
    with pytest.raises(FileExistsError):
        session(tmp_path)
    client.state["calls"].append({"charged_micro_usd": 4_990_000, "status": "outcome_unknown"})
    client._persist()
    await client.close()
    restored = session(tmp_path)
    try:
        assert restored.charged_micro_usd == 4_990_000
        with pytest.raises(QualityBudgetStopped, match="budget_exhausted"):
            await restored.ainvoke_validated([{"role": "user", "content": "Synthetic"}], json.loads)
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_explicit_exact_response_replay_runs_native_parser_without_network_or_recount(tmp_path):
    client = session(tmp_path)
    async def post(*args, **kwargs):
        return httpx.Response(200, json=reply())
    client._http.post = post
    messages = [{"role": "system", "content": "Return the required object."}, {"role": "user", "content": "Synthetic"}]
    try:
        await client.ainvoke_validated(messages, json.loads)
        charged = client.charged_micro_usd
        client.replay_requests = frozenset({client.state["calls"][0]["request_sha256"]})
        async def forbidden(*args, **kwargs):
            pytest.fail("exact explicit replay must not POST")
        client._http.post = forbidden
        restored = await client.ainvoke_validated(messages, json.loads)
        assert restored.value == {"result": True} and restored.attempt_count == 0
        assert len(client.state["calls"]) == 1 and client.charged_micro_usd == charged
        assert client.replayed == 1
        (tmp_path / "response-0000.json").write_text(json.dumps(reply('{"result":false}')))
        with pytest.raises(ValueError, match="replay_identity_changed"):
            await client.ainvoke_validated(messages, json.loads)
    finally:
        await client.close()


def test_a_plaintext_file_cannot_impersonate_a_protected_key(tmp_path):
    from scripts.dev.generation_quality_api import load_api_key

    target = tmp_path / "key.dpapi"
    target.write_bytes(b"sk-proj-synthetic-not-a-secret")
    with pytest.raises(ValueError, match="dpapi_requires_windows_user|protected_key"):
        load_api_key(target)
