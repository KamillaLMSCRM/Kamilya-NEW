from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.ops import ai_architect_replay as replay  # noqa: E402


def _request(content: str) -> dict:
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}]
    value = {"messages": messages, "kwargs": {}}
    return {
        "request": value,
        "request_sha256": replay._sha256(json.dumps(value, ensure_ascii=False, sort_keys=True)),
        "response": {"content": content},
        "response_sha256": replay._sha256(content),
    }


@pytest.mark.asyncio
async def test_replay_rejects_request_drift_and_requires_all_calls_consumed() -> None:
    llm = replay._ReplayLLM({"calls": [_request("first"), _request("second")]})
    assert (await llm.ainvoke([{"role": "system", "content": "system"}, {"role": "user", "content": "user"}])).content == "first"
    with pytest.raises(AssertionError, match="replay_unconsumed_calls:1"):
        llm.assert_consumed()
    with pytest.raises(AssertionError, match="replay_request_hash_mismatch_at_call_1"):
        await llm.ainvoke([{"role": "user", "content": "different"}])


@pytest.mark.asyncio
async def test_capture_writes_complete_private_call_trace(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"

    class LLM:
        async def ainvoke(self, _messages, **_kwargs):
            return SimpleNamespace(content="complete response")

    trace = {"calls": []}
    capture = replay._CaptureLLM(LLM(), trace, trace_path)
    response = await capture.ainvoke([{"role": "user", "content": "complete request"}])

    saved = json.loads(trace_path.read_text(encoding="utf-8"))
    assert response.content == "complete response"
    assert saved["calls"][0]["request"]["messages"][0]["content"] == "complete request"
    assert saved["calls"][0]["response"]["content"] == "complete response"
    assert isinstance(saved["calls"][0]["elapsed_ms"], float)


@pytest.mark.asyncio
async def test_capture_reserves_unique_ordered_entries_before_concurrent_responses(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    release = asyncio.Event()

    class LLM:
        async def ainvoke(self, messages, **_kwargs):
            await release.wait()
            return SimpleNamespace(content=messages[-1]["content"])

    capture = replay._CaptureLLM(LLM(), {"calls": []}, trace_path)
    first = asyncio.create_task(capture.ainvoke([{"role": "user", "content": "first"}]))
    second = asyncio.create_task(capture.ainvoke([{"role": "user", "content": "second"}]))
    await asyncio.sleep(0)

    reserved = json.loads(trace_path.read_text(encoding="utf-8"))["calls"]
    assert [entry["index"] for entry in reserved] == [0, 1]
    assert all("response" not in entry for entry in reserved)

    release.set()
    await asyncio.gather(first, second)
    completed = json.loads(trace_path.read_text(encoding="utf-8"))["calls"]
    assert [entry["index"] for entry in completed] == [0, 1]
    assert all(entry["elapsed_ms"] >= 0 for entry in completed)


@pytest.mark.asyncio
async def test_original_xlsx_uses_canonical_converter_passport_and_sizing(tmp_path: Path) -> None:
    source = tmp_path / "products.xlsx"
    workbook = Workbook()
    collections = workbook.active
    collections.title = "Коллекции"
    collections.append(["Коллекция", "Особенность"])
    collections.append(["Phoenix", "Лаконичная форма"])
    collections.append(["Chicago Neo", "Модульная система"])
    catalog = workbook.create_sheet("Номенклатура")
    catalog.append(["Артикул", "Пример"])
    catalog.append(["SKU-1", "Шкаф"])
    workbook.save(source)

    corpus = await replay._build_corpus(
        source,
        document_id="synthetic-document",
        document_title="Synthetic products",
        tenant_id="synthetic-tenant",
    )
    from app.modules.ai.document_passport import build_document_passport
    from app.modules.ai.source_analysis import recommend_course_structure

    passport = build_document_passport(corpus)
    sizing = recommend_course_structure(
        total_chunks=corpus.total_chunks, document_count=1, source_passport=passport
    )

    assert {section.name: section.role.value for section in passport.sections} == {
        "Коллекции": "primary", "Номенклатура": "supporting"
    }
    assert sizing.recommended_total_lessons >= 1
    assert corpus.tenant_id == "synthetic-tenant"
    assert corpus.documents[0].doc_id == "synthetic-document"
    assert corpus.documents[0].title == "Synthetic products"


def test_private_evidence_allows_authorized_release_scope_only(tmp_path: Path) -> None:
    future = replay.REPOSITORY_ROOT / ".release-evidence" / "v0.5.99" / "trace.json"
    assert replay._private_output_path(future) == future.resolve()
    evidence = replay.AUTHORIZED_RELEASE_EVIDENCE / "architect-trace.json"
    assert replay._private_output_path(evidence) == evidence.resolve()
    with pytest.raises(ValueError, match="private_evidence_path_not_authorized"):
        replay._private_output_path(replay.REPOSITORY_ROOT / "trace.json")
    assert replay._private_output_path(tmp_path / "trace.json") == (tmp_path / "trace.json").resolve()


def test_create_only_private_evidence_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    replay._write_private_json(path, {"first": True}, create_only=True)
    with pytest.raises(FileExistsError):
        replay._write_private_json(path, {"second": True}, create_only=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"first": True}


def test_course_structure_hash_uses_dataclass_contract() -> None:
    assert len(replay._course_structure_schema_hash()) == 64


def test_architecture_stage_uses_only_architect_requests_and_captured_prefix() -> None:
    map_call = {"request": {"messages": [{"role": "system", "content": "source map"}]}}
    architect_call = {
        "request": {
            "messages": [
                {"role": "system", "content": "You are the course architect for a source-grounded generation task."},
                {"role": "user", "content": "options\nSELECTED SOURCES:\ncaptured map context"},
            ]
        }
    }

    calls, context = replay._architecture_stage({"calls": [map_call, architect_call]})

    assert calls == [architect_call]
    assert context == "captured map context"


def test_job_options_selects_unique_document_job_without_embedding_customer_data(tmp_path: Path) -> None:
    options = tmp_path / "job-options.json"
    options.write_text(
        json.dumps(
            {"jobs": [
                {"id": "other", "params": {"documents": ["other-document"]}},
                {"id": "synthetic-job", "params": {"documents": ["synthetic-document"]}},
            ]}
        ),
        encoding="utf-8",
    )

    job_id, params = replay._selected_job_params(options, job_id=None, document_id="synthetic-document")

    assert job_id == "synthetic-job"
    assert params == {"documents": ["synthetic-document"]}


def test_main_returns_nonzero_for_architect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay, "_parser", lambda: SimpleNamespace(parse_args=lambda: SimpleNamespace()))

    def failed_run(awaitable):
        awaitable.close()
        return {"outcome": "direct_source_error"}

    monkeypatch.setattr(replay.asyncio, "run", failed_run)

    assert replay.main() == 1


def test_offline_replay_sets_only_a_process_local_synthetic_jwt_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)

    replay._prepare_offline_replay_environment("replay-architecture")

    assert os.environ["JWT_SECRET"] == replay.OFFLINE_REPLAY_JWT_SECRET

    monkeypatch.delenv("JWT_SECRET", raising=False)
    replay._prepare_offline_replay_environment("capture")
    assert "JWT_SECRET" not in os.environ

    monkeypatch.setenv("JWT_SECRET", "operator-configured-value")
    replay._prepare_offline_replay_environment("replay")
    assert os.environ["JWT_SECRET"] == "operator-configured-value"


def test_capture_uses_first_synchronous_configured_provider_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import llm_client

    first = llm_client.LLMProviderConfig(name="primary", base_url="http://primary", api_key="secret", model="m-1")
    second = llm_client.LLMProviderConfig(name="fallback", base_url="http://fallback", api_key="secret", model="m-2")
    monkeypatch.setattr(
        llm_client.ResilientLLMClient,
        "from_settings",
        classmethod(lambda cls, **kwargs: cls([first, second], **kwargs)),
    )

    client = replay._primary_resilient_client_from_settings(max_tokens=123)

    assert client.provider_names == ["primary"]
    assert client._clients[0].config.model == "m-1"
    assert client.max_tokens == 123
