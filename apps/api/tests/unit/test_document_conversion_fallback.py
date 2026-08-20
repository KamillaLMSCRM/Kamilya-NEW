from __future__ import annotations

import pytest
from docx import Document
from pypdf import PdfWriter

from app.modules.ai.ingestion import _local_convert


@pytest.mark.asyncio
async def test_binary_document_is_never_indexed_as_placeholder(tmp_path) -> None:
    source = tmp_path / "policy.pdf"
    source.write_bytes(b"%PDF-1.7")

    with pytest.raises(RuntimeError, match="conversion is unavailable"):
        await _local_convert(str(source))


@pytest.mark.asyncio
async def test_plain_text_document_keeps_local_fallback(tmp_path) -> None:
    source = tmp_path / "policy.md"
    source.write_text("# Approved policy", encoding="utf-8")

    converted = await _local_convert(str(source))

    assert converted["markdown"] == "# Approved policy"
    assert converted["metadata"] == {
        "filename": "policy.md",
        "size": len("# Approved policy"),
        "pages": 0,
        "tables": 0,
        "engine": "plain_text",
        "engine_version": None,
        "fallback_used": False,
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_docx_document_has_grounded_local_fallback(tmp_path) -> None:
    source = tmp_path / "policy.docx"
    document = Document()
    document.add_heading("Политика обучения", level=1)
    document.add_paragraph("Сотрудник должен набрать не менее 80 процентов.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Параметр"
    table.cell(0, 1).text = "Значение"
    table.cell(1, 0).text = "Срок"
    table.cell(1, 1).text = "30 минут"
    document.save(source)

    converted = await _local_convert(str(source))

    assert "# Политика обучения" in converted["markdown"]
    assert "Сотрудник должен набрать не менее 80 процентов." in converted["markdown"]
    assert "| Параметр | Значение |" in converted["markdown"]
    assert "| Срок | 30 минут |" in converted["markdown"]
    assert converted["metadata"]["engine"] == "python-docx"
    assert converted["metadata"]["fallback_used"] is True


@pytest.mark.asyncio
async def test_pdf_document_has_local_text_fallback(tmp_path) -> None:
    source = tmp_path / "policy.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as target:
        writer.write(target)

    converted = await _local_convert(str(source))

    assert converted["markdown"] == ""
    assert converted["metadata"]["pages"] == 1
    assert converted["metadata"]["engine"] == "pypdf"
    assert converted["metadata"]["fallback_used"] is True
