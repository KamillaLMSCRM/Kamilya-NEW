"""DEV input equivalence gate: never quietly replay another source or OCR tool."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.dev.run_evidence_course_application import (  # noqa: E402
    _dev_generation_config,
    _converted_pdf_corpus,
    _filter_corpus_by_headings,
    _validate_pdf_conversion_config,
)
from scripts.dev.run_axis_owned_assessment_smoke import _CapturedReplay  # noqa: E402


class _ReplayFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            value=parser('{"blocks":[{"heading":"Fresh","text":"Fresh","fact_ids":["fact-1"]}]}'),
            attempt_count=1,
            failure_reasons=(),
            model_id="live-test",
            provider="live-test",
        )


def _realization_messages(value: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": json.dumps({
        "task": "realization",
        "lesson_title": "Rule",
        "facts": [{"fact_id": "fact-1", "value": value}],
    }, ensure_ascii=False)}]


@pytest.mark.asyncio
async def test_realization_replay_fails_closed_when_legacy_trace_has_no_request_hash(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "legacy-trace.json"
    trace.write_text(json.dumps([{
        "task": "realization",
        "responses": [{"raw": '{"blocks":[{"heading":"Stale","text":"Stale","fact_ids":["fact-1"]}]}'}],
    }]), encoding="utf-8")
    fallback = _ReplayFallback()
    replay = _CapturedReplay(trace, fallback=fallback)

    result = await replay.ainvoke_validated(
        _realization_messages("Current source fact"),
        parser=json.loads,
    )

    assert result.value["blocks"][0]["text"] == "Fresh"
    assert fallback.calls == 1
    assert replay.captured_calls == 0


@pytest.mark.asyncio
async def test_realization_replay_requires_exact_full_request_fingerprint(tmp_path: Path) -> None:
    matching_messages = _realization_messages("Original source fact")
    request = json.loads(matching_messages[-1]["content"])
    request_sha256 = hashlib.sha256(
        json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    trace = tmp_path / "fingerprinted-trace.json"
    trace.write_text(json.dumps([{
        "task": "realization",
        "request_sha256": request_sha256,
        "responses": [{"raw": '{"blocks":[{"heading":"Captured","text":"Captured","fact_ids":["fact-1"]}]}'}],
    }]), encoding="utf-8")
    fallback = _ReplayFallback()
    replay = _CapturedReplay(trace, fallback=fallback)

    captured = await replay.ainvoke_validated(matching_messages, parser=json.loads)
    changed = await replay.ainvoke_validated(
        _realization_messages("Corrected source fact"),
        parser=json.loads,
    )

    assert captured.value["blocks"][0]["text"] == "Captured"
    assert changed.value["blocks"][0]["text"] == "Fresh"
    assert fallback.calls == 1
    assert replay.captured_calls == 1


def test_dev_deepseek_flash_route_is_single_cheap_non_thinking_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    config = _dev_generation_config("deepseek-flash")

    assert config.name == "deepseek-flash-dev"
    assert config.model == "deepseek-flash"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.extra_body == {"thinking": {"type": "disabled"}}
    assert config.max_retries == 0


def test_dev_deepseek_flash_route_fails_closed_without_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="deepseek_api_key_required"):
        _dev_generation_config("deepseek-flash")


def test_live_pdf_run_fails_before_local_fallback_without_docling_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCLING_URL", raising=False)
    monkeypatch.delenv("DOCLING_API_KEY", raising=False)

    with pytest.raises(
        ValueError,
        match="live_docling_not_configured:DOCLING_URL,DOCLING_API_KEY",
    ):
        _validate_pdf_conversion_config("pdf", None, None)


def test_pdf_capture_replay_does_not_require_live_docling_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DOCLING_URL", raising=False)
    monkeypatch.delenv("DOCLING_API_KEY", raising=False)

    _validate_pdf_conversion_config("pdf", None, tmp_path / "capture.json")


@pytest.mark.asyncio
async def test_replay_tries_next_same_identity_response_before_live_fallback(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "assessment-retries.json"
    trace.write_text(json.dumps([
        {
            "task": "assessment_review",
            "responses": [{"raw": json.dumps({
                "accept": False,
                "reviews": [{"question_id": "question-1"}],
            })}],
        },
        {
            "task": "assessment_review",
            "responses": [{"raw": json.dumps({
                "accept": True,
                "reviews": [{"question_id": "question-1"}],
            })}],
        },
    ]), encoding="utf-8")
    fallback = _ReplayFallback()
    replay = _CapturedReplay(trace, fallback=fallback)
    messages = [{"role": "user", "content": json.dumps({
        "task": "assessment_review",
        "questions": [{"question_id": "question-1"}],
    })}]

    def parser(raw: str):
        value = json.loads(raw)
        if not value["accept"]:
            raise ValueError("captured_retry_rejected")
        return value

    result = await replay.ainvoke_validated(messages, parser=parser)

    assert result.value["accept"] is True
    assert replay.captured_calls == 2
    assert fallback.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "hash", "bytes", "mode", "fallback", "engine"])
async def test_capture_matches_source_and_production_converter(tmp_path, monkeypatch, fault):
    from app.modules.ai.ingestion import DocumentConverter

    async def forbidden(*args, **kwargs):
        raise AssertionError("network conversion forbidden for capture replay")
    monkeypatch.setattr(DocumentConverter, "convert", forbidden)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic-original")
    capture = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "source_bytes": source.stat().st_size,
               "capture_mode": "deployed_application_converter",
               "converted": {"markdown": "# Policy\n\nUse approved channels only.",
                             "metadata": {"engine": "docling", "fallback_used": False}}}
    if fault == "hash":
        capture["source_sha256"] = "other"
    if fault == "bytes":
        capture["source_bytes"] += 1
    if fault == "mode":
        capture["capture_mode"] = "local_ocr"
    if fault == "fallback":
        capture["converted"]["metadata"]["fallback_used"] = True
    if fault == "engine":
        capture["converted"]["metadata"]["engine"] = "windows_ocr"
    artifact = tmp_path / "capture.json"
    artifact.write_text(json.dumps(capture), encoding="utf-8")
    if fault:
        with pytest.raises(ValueError):
            await _converted_pdf_corpus(source, artifact)
    else:
        result = await _converted_pdf_corpus(source, artifact)
        assert result.total_chunks > 0
        assert "approved channels" in result.documents[0].chunks[0].text


@pytest.mark.asyncio
async def test_heading_filter_keeps_source_identity_and_recalculates_bounds(
    tmp_path, monkeypatch,
):
    from app.modules.ai.ingestion import DocumentConverter

    async def forbidden(*args, **kwargs):
        raise AssertionError("network conversion forbidden for capture replay")

    monkeypatch.setattr(DocumentConverter, "convert", forbidden)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic-original")
    markdown = (
        "# Policy\n\n## 1. General\n\nGeneral rule.\n\n"
        "## 7. Calculation\n\nFormula rule.\n\n"
        "## 8. Repayment\n\nRepayment rule."
    )
    capture = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_bytes": source.stat().st_size,
        "capture_mode": "deployed_application_converter",
        "converted": {
            "markdown": markdown,
            "metadata": {"engine": "docling", "fallback_used": False},
        },
    }
    artifact = tmp_path / "capture.json"
    artifact.write_text(json.dumps(capture), encoding="utf-8")

    corpus = await _converted_pdf_corpus(source, artifact)
    filtered = _filter_corpus_by_headings(corpus, ("calculation", "repayment"))

    assert filtered.documents[0].doc_id == corpus.documents[0].doc_id
    assert filtered.documents[0].source_revision == corpus.documents[0].source_revision
    assert filtered.total_chunks == len(filtered.documents[0].chunks) == 2
    assert filtered.total_chars == sum(
        len(chunk.text) for chunk in filtered.documents[0].chunks
    )
    assert all(
        any(term in " ".join(chunk.headings).casefold()
            for term in ("calculation", "repayment"))
        for chunk in filtered.documents[0].chunks
    )


def test_heading_filter_rejects_empty_selection(tmp_path):
    from app.modules.ai.direct_source import DirectSourceCorpus

    corpus = DirectSourceCorpus(tenant_id="local", documents=(), total_chars=0, total_chunks=0)
    with pytest.raises(ValueError, match="no_source_chunks_match_heading_filter"):
        _filter_corpus_by_headings(corpus, ("missing",))
