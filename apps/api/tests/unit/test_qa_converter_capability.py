"""The QA path must receive a source-bound converter capability acknowledgement."""

import hashlib

import httpx
import pytest

from app.modules.ai.ingestion import DocumentConverter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "digital",
        "missing",
        "malformed",
        "wrong_source",
        "wrong_policy",
        "wrong_outcome",
        "missing_outcome",
        "non_qa",
    ],
)
async def test_qa_converter_requires_source_bound_capability(monkeypatch, tmp_path, case):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic pdf bytes")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    capability = {"policy": "qa-source-review-v1", "source_sha256": sha, "outcome": "applied"}
    if case == "missing" or case == "non_qa":
        capability = None
    elif case == "malformed":
        capability = "yes"
    elif case == "wrong_source":
        capability = {**capability, "source_sha256": "0" * 64}
    elif case == "wrong_policy":
        capability = {**capability, "policy": "unknown"}
    elif case == "digital":
        capability = {**capability, "outcome": "not_applicable_digital"}
    elif case == "wrong_outcome":
        capability = {**capability, "outcome": "unknown"}
    elif case == "missing_outcome":
        capability.pop("outcome")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "engine": "docling",
                "markdown": "Synthetic source",
                "conversion_metadata": {"source_review_capability": capability},
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    converter = DocumentConverter(base_url="http://fixture.invalid")
    if case in {"valid", "digital", "non_qa"}:
        result = await converter.convert(str(source), source_review_enabled=case != "non_qa")
        assert result["markdown"] == "Synthetic source"
    else:
        with pytest.raises(RuntimeError, match="qa_source_review_converter_unavailable"):
            await converter.convert(str(source), source_review_enabled=True)
