from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.modules.ai.ingestion import DocumentConverter, DocumentChunker
from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.document_passport import SectionRole, build_document_passport


@pytest.mark.asyncio
async def test_xlsx_conversion_preserves_visible_worksheet_boundaries(tmp_path: Path) -> None:
    workbook = Workbook()
    collections = workbook.active
    collections.title = "Collections"
    collections.append(["Collection", "Benefit"])
    collections.append(["Chicago", "Modular storage"])
    catalog = workbook.create_sheet("SKU catalog")
    catalog.append(["SKU", "Item", "Price"])
    catalog.append(["SKU-1", "Wardrobe", 199000])
    hidden = workbook.create_sheet("Hidden calculations")
    hidden.sheet_state = "hidden"
    hidden.append(["internal", "formula"])
    source = tmp_path / "source.xlsx"
    workbook.save(source)

    converter = DocumentConverter()
    converter.base_url = ""
    converted = await converter.convert(str(source))

    assert "# [Worksheet] Collections" in converted["markdown"]
    assert "# [Worksheet] SKU catalog" in converted["markdown"]
    assert "Hidden calculations" not in converted["markdown"]
    assert [item["name"] for item in converted["metadata"]["worksheets"]] == [
        "Collections",
        "SKU catalog",
    ]
    assert converted["metadata"]["fallback_used"] is False
    chunks = DocumentChunker(chunk_size=120, chunk_overlap=0).chunk_markdown(
        converted["markdown"],
        "doc-1",
        "source.xlsx",
    )
    catalog_chunks = [
        chunk
        for chunk in chunks
        if "SKU-1" in chunk["text"]
    ]
    assert catalog_chunks
    assert "SKU catalog" in catalog_chunks[0]["metadata"]["headings"]
    assert "Collections" not in catalog_chunks[0]["metadata"]["headings"]

    direct_chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"direct:doc-1:{index}",
            doc_id="doc-1",
            doc_name="source.xlsx",
            title="Product source",
            headings=tuple(json.loads(chunk["metadata"]["headings"])),
            text=chunk["text"],
            source_revision="document:" + "a" * 64,
            chunk_index=index,
        )
        for index, chunk in enumerate(chunks)
    )
    passport = build_document_passport(
        DirectSourceCorpus(
            tenant_id="tenant-1",
            documents=(
                DirectSourceDocument(
                    doc_id="doc-1",
                    title="Product source",
                    filename="source.xlsx",
                    category="general",
                    source_revision="document:" + "a" * 64,
                    chunks=direct_chunks,
                ),
            ),
            total_chars=len(converted["markdown"]),
            total_chunks=len(direct_chunks),
        )
    )
    roles = {section.name: section.role for section in passport.sections}
    assert roles == {
        "Collections": SectionRole.PRIMARY,
        "SKU catalog": SectionRole.SUPPORTING,
    }


@pytest.mark.asyncio
async def test_xlsx_conversion_rejects_rows_beyond_streaming_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.ai import ingestion

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Collection", "Benefit"])
    sheet.append(["Chicago", "Modular storage"])
    sheet.append(["Jagger", "Compact storage"])
    source = tmp_path / "oversized.xlsx"
    workbook.save(source)
    monkeypatch.setattr(ingestion, "MAX_XLSX_ROWS_PER_SHEET", 2)

    converter = DocumentConverter()
    converter.base_url = ""
    with pytest.raises(RuntimeError, match="safe conversion limits"):
        await converter.convert(str(source))
