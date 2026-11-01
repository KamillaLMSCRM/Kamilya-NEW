"""Owner-authorized Luna accounting must not silently change other model budgets."""

import json
from pathlib import Path

import httpx
import pytest
from scripts.dev import generation_quality_api as quality


@pytest.mark.asyncio
async def test_unbounded_luna_still_records_each_call_and_keeps_reasoning(monkeypatch, tmp_path: Path):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def post(self, _url, *, content, headers):
            calls.append(json.loads(content))
            return httpx.Response(200, json={"model": "gpt-6-luna", "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

        async def aclose(self):
            pass

    monkeypatch.setattr(quality, "load_api_key", lambda _path: "local-test-key")
    monkeypatch.setattr(quality.httpx, "AsyncClient", Client)
    ledger = tmp_path / "budget.json"
    client = quality.QualityAPISession(key_file=tmp_path / "unused", ledger=ledger,
                                       model="gpt-6-luna", output_tokens=512)
    try:
        for index in range(2):
            await client.ainvoke_validated([{"role": "user", "content": f"test {index}"}], json.loads)
    finally:
        await client.close()
    state = json.loads(ledger.read_text(encoding="utf8"))
    assert state["budget_micro_usd"] is None and len(state["calls"]) == 2
    assert all(call["status"] == "completed" and call["charged_micro_usd"] > 0 for call in state["calls"])
    assert all(call["reasoning_effort"] == "medium" and call["store"] is False for call in calls)


def test_unbounded_does_not_extend_to_other_models(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(quality, "load_api_key", lambda _path: "local-test-key")
    with pytest.raises(ValueError, match="quality_api_unbounded_model_not_authorized"):
        quality.QualityAPISession(key_file=tmp_path / "unused", ledger=tmp_path / "budget.json",
                                  model="gpt-5.6-luna", budget_micro_usd=None)


@pytest.mark.asyncio
async def test_existing_bounded_ledger_still_stops_before_network(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(quality, "load_api_key", lambda _path: "local-test-key")
    client = quality.QualityAPISession(key_file=tmp_path / "unused", ledger=tmp_path / "budget.json",
                                       model="gpt-6-luna", output_tokens=512, budget_micro_usd=1)
    try:
        with pytest.raises(quality.QualityBudgetStopped, match="quality_api_budget_exhausted"):
            await client.ainvoke_validated([{"role": "user", "content": "test"}], json.loads)
        assert client.state["calls"] == []
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["timeout", "artifact_collision", "completed"])
async def test_unknown_or_completed_call_never_silently_reissues(monkeypatch, tmp_path: Path, outcome):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def post(self, _url, *, content, headers):
            calls.append(1)
            if outcome == "timeout":
                raise TimeoutError("unknown response")
            return httpx.Response(200, json={"model": "gpt-6-luna", "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

        async def aclose(self):
            pass

    monkeypatch.setattr(quality, "load_api_key", lambda _path: "local-test-key")
    monkeypatch.setattr(quality.httpx, "AsyncClient", Client)
    ledger = tmp_path / "budget.json"
    client = quality.QualityAPISession(key_file=tmp_path / "unused", ledger=ledger,
                                       model="gpt-6-luna", output_tokens=512, budget_micro_usd=None)
    message = [{"role": "user", "content": "same request"}]
    if outcome == "artifact_collision":
        (tmp_path / "response-0000.json").write_text("other", encoding="utf8")
    try:
        if outcome == "timeout":
            with pytest.raises(TimeoutError):
                await client.ainvoke_validated(message, json.loads)
        elif outcome == "artifact_collision":
            with pytest.raises(FileExistsError):
                await client.ainvoke_validated(message, json.loads)
        else:
            await client.ainvoke_validated(message, json.loads)
        previous = client.state["calls"][0]
        assert previous["status"] == ("completed" if outcome == "completed" else "outcome_unknown")
        with pytest.raises(quality.QualityBudgetStopped, match="quality_api_prior_"):
            await client.ainvoke_validated(message, json.loads)
        if outcome == "completed":
            client.replay_requests = frozenset([previous["request_sha256"]])
            replay = await client.ainvoke_validated(message, json.loads)
            assert replay.attempt_count == 0
            client.replay_requests = frozenset()
            repeated = await client.ainvoke_validated(message, json.loads, allow_repeat_completed=True)
            assert repeated.attempt_count == 1 and calls == [1, 1]
            client.replay_requests = frozenset([previous["request_sha256"]])
            duplicate_replay = await client.ainvoke_validated(message, json.loads)
            assert duplicate_replay.attempt_count == 0 and calls == [1, 1]
        else:
            with pytest.raises(quality.QualityBudgetStopped, match="quality_api_prior_outcome_unknown"):
                await client.ainvoke_validated(message, json.loads, allow_repeat_completed=True)
            assert calls == [1]
    finally:
        await client.close()


def test_new_ledger_rejects_existing_response_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(quality, "load_api_key", lambda _path: "local-test-key")
    (tmp_path / "response-0000.json").write_text("existing", encoding="utf8")
    with pytest.raises(ValueError, match="quality_api_evidence_directory_not_empty"):
        quality.QualityAPISession(key_file=tmp_path / "unused", ledger=tmp_path / "other.json",
                                  model="gpt-6-luna", budget_micro_usd=None)


@pytest.mark.asyncio
async def test_different_saved_answers_for_same_request_are_never_chosen_arbitrarily(monkeypatch, tmp_path: Path):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def post(self, _url, *, content, headers):
            calls.append(1)
            return httpx.Response(200, json={"model": "gpt-6-luna",
                "choices": [{"message": {"content": json.dumps({"answer": len(calls)})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

        async def aclose(self):
            pass

    monkeypatch.setattr(quality, "load_api_key", lambda _path: "local-test-key")
    monkeypatch.setattr(quality.httpx, "AsyncClient", Client)
    client = quality.QualityAPISession(key_file=tmp_path / "unused", ledger=tmp_path / "budget.json", output_tokens=512)
    message = [{"role": "user", "content": "same request"}]
    try:
        await client.ainvoke_validated(message, json.loads)
        await client.ainvoke_validated(message, json.loads, allow_repeat_completed=True)
        client.replay_requests = frozenset([client.state["calls"][0]["request_sha256"]])
        with pytest.raises(ValueError, match="quality_api_replay_not_unique"):
            await client.ainvoke_validated(message, json.loads)
        assert calls == [1, 1]
    finally:
        await client.close()
