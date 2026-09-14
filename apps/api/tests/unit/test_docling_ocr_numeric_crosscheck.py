from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SERVICE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docling-service" / "main.py"


def _load_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCLING_API_KEY", "test-docling-key")
    spec = importlib.util.spec_from_file_location("docling_numeric_crosscheck_test", SERVICE_PATH)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


class _Prov:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _Item:
    def __init__(self, text: str, page_no: int) -> None:
        self.text = text
        self.prov = [_Prov(page_no)]


class _Cell(_Item):
    pass


class _Table:
    def __init__(self, cell: _Cell) -> None:
        self.data = type("TableData", (), {"table_cells": [cell]})()


class _Document:
    def __init__(self, texts: list[_Item], tables: list[_Table] | None = None) -> None:
        self.texts = texts
        self.tables = tables or []
        self.pages = {1: object(), 2: object()}

    def export_to_markdown(self) -> str:
        cells = [cell.text for table in self.tables for cell in table.data.table_cells]
        return "\n".join([item.text for item in self.texts] + cells)


def _install_converter(service, document: _Document, monkeypatch: pytest.MonkeyPatch) -> None:
    result = type("Result", (), {"document": document})()
    monkeypatch.setattr(service, "get_converter", lambda: type("Converter", (), {"convert": lambda self, path: result})())


@pytest.mark.parametrize("serialized", [
    r"[UNREADABLE\_PERCENTAGE\_VALUE]",
    r"\[UNREADABLE\_PERCENTAGE\_VALUE\]",
    r"\[UNREADABLE_PERCENTAGE_VALUE\]",
])
def test_uncertainty_marker_survives_docling_markdown_escaping(monkeypatch, serialized):
    service = _load_service(monkeypatch)
    document = _Document([])
    document.export_to_markdown = lambda: "Rate " + serialized
    _install_converter(service, document, monkeypatch)
    markdown, _, _ = service._docling_convert("synthetic.pdf")
    assert service.UNREADABLE_PERCENTAGE_VALUE in markdown
    assert service._percentage_crosscheck_warnings(markdown)


def _scanned_crosscheck(service):
    return service._scanned_pdf_percentage_crosscheck()


def test_docling_convert_masks_unconfirmed_percentage_on_its_own_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _Document([_Item("Ставка 7% годовых.", 2)])
    _install_converter(service, document, monkeypatch)
    rendered_pages: list[int] = []

    monkeypatch.setattr(
        service,
        "_independent_page_percentage_ocr",
        lambda path, page_no, budget: (rendered_pages.append(page_no) or ("ставка не заполнена", "ставка не заполнена")),
    )

    with _scanned_crosscheck(service):
        markdown, pages, tables = service._docling_convert("synthetic.pdf")

    assert "[UNREADABLE_PERCENTAGE_VALUE]" in markdown
    assert "7%" not in markdown
    assert rendered_pages == [2]
    assert (pages, tables) == (2, 0)


def test_docling_convert_accepts_dot_comma_equivalent_percentage_when_both_ocr_passes_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _Document([_Item("Ставка 7,0 % годовых.", 1)])
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(
        service,
        "_independent_page_percentage_ocr",
        lambda path, page_no, budget: ("ставка 7.00% годовых", "ставка 7% годовых"),
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert markdown == "Ставка 7,0 % годовых."


def test_docling_convert_uses_item_and_table_cell_page_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    text_page_one = _Item("Ставка 5% годовых.", 1)
    text_page_two = _Item("Ставка 7% годовых.", 2)
    table_cell_page_two = _Cell("Лимит 9%.", 2)
    document = _Document([text_page_one, text_page_two], [_Table(table_cell_page_two)])
    _install_converter(service, document, monkeypatch)

    def independent_ocr(path: str, page_no: int, budget):
        return ("ставка 5%", "ставка 5%") if page_no == 1 else ("пустое поле", "пустое поле")

    monkeypatch.setattr(service, "_independent_page_percentage_ocr", independent_ocr)

    with _scanned_crosscheck(service):
        markdown, _, tables = service._docling_convert("synthetic.pdf")

    assert "5%" in markdown
    assert markdown.count("[UNREADABLE_PERCENTAGE_VALUE]") == 2
    assert tables == 1


def test_docling_convert_masks_percentage_when_independent_ocr_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _Document([_Item("Ставка 7% годовых.", 1)])
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(service, "_independent_page_percentage_ocr", lambda path, page_no, budget: None)

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert markdown == "Ставка [UNREADABLE_PERCENTAGE_VALUE] годовых."


@pytest.mark.parametrize("path", ["synthetic.docx", "synthetic.pdf"])
def test_docling_convert_does_not_crosscheck_outside_scanned_pdf_context(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    service = _load_service(monkeypatch)
    document = _Document([_Item("Ставка 7% годовых.", 1)])
    _install_converter(service, document, monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(
        service,
        "_independent_page_percentage_ocr",
        lambda path, page_no, budget: calls.append(page_no),
    )

    markdown, _, _ = service._docling_convert(path)

    assert markdown == "Ставка 7% годовых."
    assert calls == []


def test_table_cell_without_own_provenance_uses_single_page_table_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    cell = _Cell("Лимит 7%.", 1)
    del cell.prov
    table = _Table(cell)
    table.prov = [_Prov(2)]
    document = _Document([], [table])
    _install_converter(service, document, monkeypatch)
    seen_pages: list[int] = []
    monkeypatch.setattr(
        service,
        "_independent_page_percentage_ocr",
        lambda path, page_no, budget: (seen_pages.append(page_no) or ("пусто", "пусто")),
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert seen_pages == [2]
    assert markdown == "Лимит [UNREADABLE_PERCENTAGE_VALUE]."


def test_table_cell_without_provenance_in_multipage_table_is_marked_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    cell = _Cell("Лимит 7%.", 1)
    del cell.prov
    table = _Table(cell)
    table.prov = [_Prov(1), _Prov(2)]
    document = _Document([], [table])
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(
        service,
        "_independent_page_percentage_ocr",
        lambda path, page_no, budget: (_ for _ in ()).throw(AssertionError("ambiguous table must not render")),
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert markdown == "Лимит [UNREADABLE_PERCENTAGE_VALUE]."


def test_scanned_pdf_payload_warns_when_crosscheck_marks_uncertain_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(
        service,
        "_profile_pdf",
        lambda path: {"profile": "scanned_or_low_text", "is_digital": False, "pages": 1},
    )
    monkeypatch.setattr(
        service,
        "_docling_convert",
        lambda path: ("Ставка [UNREADABLE_PERCENTAGE_VALUE] годовых.", 1, 0),
    )

    payload = service._convert_sync(tmp_path="synthetic.pdf", filename="synthetic.pdf", suffix=".pdf")

    assert payload["warnings"] == [
        "Some percentage values are marked unreadable because independent page OCR did not confirm them."
    ]


def test_independent_ocr_closes_pdf_page_bitmap_and_removes_temp_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _load_service(monkeypatch)
    closed: list[str] = []

    class Image:
        width = 20
        height = 10

        def save(self, path: str) -> None:
            Path(path).write_bytes(b"synthetic")

        def close(self) -> None:
            closed.append("image")

    class Bitmap:
        width = 20
        height = 10

        def to_pil(self):
            return Image()

        def close(self) -> None:
            closed.append("bitmap")

    class Page:
        def get_size(self):
            return (10, 5)

        def render(self, scale: float):
            assert scale > 0
            return Bitmap()

        def close(self) -> None:
            closed.append("page")

    class PdfDocument:
        def __init__(self, path: str) -> None:
            assert path == "synthetic.pdf"

        def __getitem__(self, index: int):
            assert index == 0
            return Page()

        def close(self) -> None:
            closed.append("pdf")

    fake_pdfium = ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = PdfDocument
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda args, **kwargs: type("Completed", (), {"returncode": 0, "stdout": "ставка 7%", "stderr": ""})(),
    )
    monkeypatch.setattr(service.tempfile, "gettempdir", lambda: str(tmp_path))

    result = service._independent_page_percentage_ocr(
        "synthetic.pdf", 1, {"pixels": 0, "deadline": service.time.monotonic() + 1}
    )

    assert result == ("ставка 7%", "ставка 7%")
    assert closed == ["image", "bitmap", "page", "pdf"]
    assert list(tmp_path.iterdir()) == []


def test_independent_ocr_rejects_giant_page_before_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    rendered = False

    class Page:
        def get_size(self):
            return (100_000, 100_000)

        def render(self, scale: float):
            nonlocal rendered
            rendered = True
            raise AssertionError("giant page must not render")

        def close(self) -> None:
            pass

    class PdfDocument:
        def __init__(self, path: str) -> None:
            pass

        def __getitem__(self, index: int):
            return Page()

        def close(self) -> None:
            pass

    fake_pdfium = ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = PdfDocument
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)

    assert service._independent_page_percentage_ocr(
        "synthetic.pdf", 1, {"pixels": 0, "deadline": service.time.monotonic() + 1}
    ) is None
    assert rendered is False
