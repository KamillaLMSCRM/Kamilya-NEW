"""An absent converter address must never select a historical external host."""
from __future__ import annotations

import runpy

import pytest
from docx import Document


@pytest.mark.asyncio
async def test_remote_adapter_without_configuration_stays_local(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCLING_URL", raising=False)
    adapter = runpy.run_module("app.modules.ai.converter_remote")
    converter = adapter["DocumentConverter"]()
    assert converter.base_url == ""
    network_calls = []

    def unexpected_client(*args, **kwargs):
        network_calls.append(True)
        raise AssertionError("unconfigured converter must not use HTTP")

    monkeypatch.setattr("httpx.AsyncClient", unexpected_client)
    source = tmp_path / "policy.txt"
    source.write_text("A local operational rule.", encoding="utf-8")
    result = await converter.convert(str(source))
    assert result["markdown"] == "A local operational rule."
    assert network_calls == []
    scanned = tmp_path / "scanned.pdf"
    scanned.write_bytes(b"scanned PDF fixture")
    with pytest.raises(RuntimeError, match="Document conversion is unavailable"):
        await converter.convert(str(scanned))
    assert network_calls == []


def test_remote_adapter_keeps_an_explicit_address(monkeypatch):
    monkeypatch.setenv("DOCLING_URL", "http://private-converter.example:8600/")
    adapter = runpy.run_module("app.modules.ai.converter_remote")
    assert adapter["DocumentConverter"]().base_url == "http://private-converter.example:8600"
    assert adapter["DocumentConverter"]("http://127.0.0.1:18600/").base_url == "http://127.0.0.1:18600"


@pytest.mark.asyncio
async def test_active_ingestion_without_endpoint_parses_office_locally(tmp_path, monkeypatch):
    from app.modules.ai import ingestion

    monkeypatch.setattr(ingestion, "DOCLING_URL", "")
    network_calls = []

    def unexpected_client(*args, **kwargs):
        network_calls.append(True)
        raise AssertionError("unconfigured ingestion must not use HTTP")

    monkeypatch.setattr("httpx.AsyncClient", unexpected_client)
    source = tmp_path / "policy.docx"
    document = Document()
    document.add_paragraph("Verify the approval before issuing a loan.")
    document.save(source)
    result = await ingestion.DocumentConverter().convert(str(source))
    assert "Verify the approval before issuing a loan." in result["markdown"]
    assert result["metadata"]["engine"] == "python-docx"
    assert network_calls == []
