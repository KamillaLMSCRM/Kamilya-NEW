from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.ingestion import (
    DocumentChunker,
    DocumentConverter,
    DocumentIndexingTerminalError,
)
from app.modules.ai.pdf_table_layout import PDFTableLayoutError, preserve_pdf_tables


def _ruled_pdf(path: Path, tables: list[list[list[str]]], *, prose: str = "") -> str:
    """Create deterministic ruled tables with pypdf primitives only."""
    page_width, page_height = 612, 792
    left, col_width, row_height = 54, 118, 22
    y_top = 700

    def pdf_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    operators: list[str] = []
    if prose:
        operators.extend([f"BT /F1 10 Tf 1 0 0 1 {left} 750 Tm ({pdf_text(prose)}) Tj ET"])
    current_top = y_top
    for table in tables:
        rows = len(table)
        cols = len(table[0])
        right = left + cols * col_width
        bottom = current_top - rows * row_height
        for row in range(rows + 1):
            y = current_top - row * row_height
            operators.append(f"{left} {y} m {right} {y} l S")
        for col in range(cols + 1):
            x = left + col * col_width
            operators.append(f"{x} {current_top} m {x} {bottom} l S")
        for row_index, values in enumerate(table):
            for col_index, value in enumerate(values):
                if value:
                    x = left + col_index * col_width + 5
                    y = current_top - (row_index + 1) * row_height + 7
                    operators.append(f"BT /F1 10 Tf 1 0 0 1 {x} {y} Tm ({pdf_text(value)}) Tj ET")
        current_top = bottom - 36
    writer = PdfWriter()
    page = writer.add_blank_page(width=page_width, height=page_height)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = StreamObject()
    stream._data = ("\n".join(operators) + "\n").encode("latin-1")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _three_column_pdf(path: Path, *, blank: bool = False) -> str:
    value = "" if blank else "42"
    return _ruled_pdf(
        path,
        [[["Subject", "Attribute", "Value"], ["Orbita", "Capacity", value], ["Lumen", "Mode", "Active"]]],
    )


def test_preserve_pdf_tables_recovers_ruled_grid_into_markdown(tmp_path: Path) -> None:
    pdf = tmp_path / "grid.pdf"
    flattened = _three_column_pdf(pdf)

    normalized, recovered = preserve_pdf_tables(pdf, flattened)

    assert recovered == 1
    assert "| Subject | Attribute | Value |" in normalized
    assert "| Orbita | Capacity | 42 |" in normalized
    assert "| Lumen | Mode | Active |" in normalized


def test_duplicate_flattened_match_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "duplicate.pdf"
    flattened = _three_column_pdf(pdf)
    duplicated = flattened + "\n\n" + flattened

    with pytest.raises(PDFTableLayoutError, match="ambiguous"):
        preserve_pdf_tables(pdf, duplicated)


@pytest.mark.parametrize("flattened", ["Subject\nAttribute\nMissing", "Subject\nAttribute\nValue\nExtra"])
def test_wrong_or_missing_converter_cell_fails_closed(tmp_path: Path, flattened: str) -> None:
    pdf = tmp_path / "mismatch.pdf"
    _three_column_pdf(pdf)

    with pytest.raises(PDFTableLayoutError):
        preserve_pdf_tables(pdf, flattened)


def test_plain_prose_without_grid_is_unchanged(tmp_path: Path) -> None:
    pdf = tmp_path / "prose.pdf"
    _ruled_pdf(pdf, [], prose="A plain paragraph without any table.")
    prose = "A plain paragraph without any table.\nSecond line."

    normalized, recovered = preserve_pdf_tables(pdf, prose)

    assert normalized == prose
    assert recovered == 0


def test_table_on_later_page_is_recovered(tmp_path: Path) -> None:
    first = tmp_path / "table-only.pdf"
    flattened = _three_column_pdf(first)
    combined = tmp_path / "later-page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_page(PdfReader(first).pages[0])
    with combined.open("wb") as stream:
        writer.write(stream)
    normalized, recovered = preserve_pdf_tables(combined, flattened)
    assert recovered == 1
    assert "| Orbita | Capacity | 42 |" in normalized


@pytest.mark.parametrize("transform", ["1 0 0 1 25 15 cm", "0.5 0 0 0.5 20 20 cm"])
def test_translated_or_scaled_grid_is_recovered(tmp_path: Path, transform: str) -> None:
    source = tmp_path / "original.pdf"
    flattened = _three_column_pdf(source)
    transformed = tmp_path / "transformed.pdf"
    reader = PdfReader(source)
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    stream = StreamObject()
    stream._data = b"q\n" + transform.encode("ascii") + b"\n" + page.get_contents().get_data() + b"\nQ\n"
    page[NameObject("/Contents")] = writer._add_object(stream)
    with transformed.open("wb") as output:
        writer.write(output)
    normalized, recovered = preserve_pdf_tables(transformed, flattened)
    assert recovered == 1
    assert "| Orbita | Capacity | 42 |" in normalized


def test_existing_exact_markdown_table_is_unchanged(tmp_path: Path) -> None:
    pdf = tmp_path / "already-markdown.pdf"
    _three_column_pdf(pdf)
    markdown = (
        "| Subject | Attribute | Value |\n|---|---|---|\n"
        "| Orbita | Capacity | 42 |\n| Lumen | Mode | Active |"
    )

    normalized, recovered = preserve_pdf_tables(pdf, markdown)

    assert normalized == markdown
    assert recovered == 0


def test_incomplete_existing_markdown_table_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "incomplete-markdown.pdf"
    _three_column_pdf(pdf)
    markdown = "| Subject | Attribute | Value |\n|---|---|---|\n| Orbita | Capacity | 42 |"

    with pytest.raises(PDFTableLayoutError):
        preserve_pdf_tables(pdf, markdown)


def test_identical_source_tables_with_one_flattened_occurrence_fail_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "duplicate-source.pdf"
    table = [["Subject", "Attribute", "Value"], ["Orbita", "Capacity", "42"]]
    flattened = _ruled_pdf(pdf, [table, table]).splitlines()
    one_occurrence = "\n".join(flattened[:2])

    with pytest.raises(PDFTableLayoutError):
        preserve_pdf_tables(pdf, one_occurrence)


def test_identical_source_tables_with_two_exact_markdown_occurrences_unchanged(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "duplicate-source-exact.md.pdf"
    table = [["Subject", "Attribute", "Value"], ["Orbita", "Capacity", "42"]]
    _ruled_pdf(pdf, [table, table])
    one = "| Subject | Attribute | Value |\n|---|---|---|\n| Orbita | Capacity | 42 |"
    markdown = f"{one}\n\n{one}"

    normalized, recovered = preserve_pdf_tables(pdf, markdown)

    assert normalized == markdown
    assert recovered == 0


def test_whitespace_only_flattening_is_recovered(tmp_path: Path) -> None:
    pdf = tmp_path / "whitespace-flattened.pdf"
    flattened = _three_column_pdf(pdf).replace("\n", "  ")

    normalized, recovered = preserve_pdf_tables(pdf, flattened)

    assert recovered == 1
    assert "| Subject | Attribute | Value |" in normalized


def test_multiple_same_page_tables_are_recovered_independently(tmp_path: Path) -> None:
    pdf = tmp_path / "two-tables.pdf"
    flattened = _ruled_pdf(
        pdf,
        [
            [["A", "B", "C"], ["one", "two", "three"]],
            [["X", "Y", "Z"], ["red", "green", "blue"]],
        ],
    )

    normalized, recovered = preserve_pdf_tables(pdf, flattened)

    assert recovered == 2
    assert "| one | two | three |" in normalized
    assert "| red | green | blue |" in normalized


def test_blank_cell_is_preserved(tmp_path: Path) -> None:
    pdf = tmp_path / "blank-cell.pdf"
    flattened = _three_column_pdf(pdf, blank=True)

    normalized, recovered = preserve_pdf_tables(pdf, flattened)

    assert recovered == 1
    assert "| Orbita | Capacity |  |" in normalized


def test_wrapped_or_unsafe_table_text_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "wrapped.pdf"
    _three_column_pdf(pdf)
    unsafe = "Subject\nAttribute\nValue\nOrbita Capacity 42\nLumen Mode Disabled"

    with pytest.raises(PDFTableLayoutError):
        preserve_pdf_tables(pdf, unsafe)


@pytest.mark.asyncio
async def test_remote_converter_table_seam_reaches_evidence_without_network(
    tmp_path: Path, monkeypatch
) -> None:
    pdf = tmp_path / "remote.pdf"
    flattened = _three_column_pdf(pdf)

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"markdown": flattened, "pages": 1, "tables": 1, "engine": "markitdown"}

    class Client:
        def __init__(self, *args, **kwargs):
            self.headers = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, files, headers):
            assert headers == {"X-Docling-Key": "fixture-key"}
            assert url.endswith("/convert")
            return Response()

    monkeypatch.setattr("httpx.AsyncClient", Client)
    monkeypatch.setattr("app.modules.ai.ingestion.DOCLING_API_KEY", "fixture-key")
    converted = await DocumentConverter("https://converter.example").convert(str(pdf))
    normalized = converted["markdown"]
    chunks = DocumentChunker(chunk_size=10_000, chunk_overlap=0).chunk_markdown(
        normalized, "pdf-seam", "remote.pdf"
    )

    revision = "document:pdf-seam"
    source_chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"pdf-seam:{index}",
            doc_id="pdf-seam",
            doc_name="remote.pdf",
            title="Remote PDF",
            headings=(),
            text=item["text"],
            source_revision=revision,
            chunk_index=index,
        )
        for index, item in enumerate(chunks)
    )
    corpus = DirectSourceCorpus(
        tenant_id="synthetic-pdf",
        documents=(
            DirectSourceDocument(
                doc_id="pdf-seam",
                title="Remote PDF",
                filename="remote.pdf",
                category="training_material",
                source_revision=revision,
                chunks=source_chunks,
            ),
        ),
        total_chars=len(normalized),
        total_chunks=len(source_chunks),
    )
    bundle = build_evidence_source(corpus)
    generation_facts = {
        (fact.subject, fact.attribute, fact.value)
        for fact in bundle.generation_facts
    }

    assert converted["metadata"]["tables"] == 1
    assert converted["metadata"]["warnings"] == [
        "Ruled PDF tables restored from verified source geometry."
    ]
    assert ("Orbita", "Attribute", "Capacity") in generation_facts
    assert ("Orbita", "Value", "42") in generation_facts
    assert ("Lumen", "Value", "Active") in generation_facts


@pytest.mark.asyncio
async def test_remote_table_mismatch_is_terminal_without_local_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    pdf = tmp_path / "remote-mismatch.pdf"
    _three_column_pdf(pdf)

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "markdown": "Subject\nAttribute\nValue\nOrbita Capacity Wrong",
                "pages": 1,
                "tables": 1,
                "engine": "markitdown",
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, files, headers):
            return Response()

    async def unexpected_local_fallback(*args, **kwargs):
        raise AssertionError("PDF table mismatch must not fall back to local conversion")

    monkeypatch.setattr("httpx.AsyncClient", Client)
    monkeypatch.setattr("app.modules.ai.ingestion.DOCLING_API_KEY", "fixture-key")
    monkeypatch.setattr("app.modules.ai.ingestion._local_convert", unexpected_local_fallback)

    with pytest.raises(DocumentIndexingTerminalError):
        await DocumentConverter("https://converter.example").convert(str(pdf))
