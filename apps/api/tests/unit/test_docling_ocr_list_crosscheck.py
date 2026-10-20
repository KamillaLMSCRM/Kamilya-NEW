from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SERVICE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docling-service" / "main.py"


def _load_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCLING_API_KEY", "test-docling-key")
    spec = importlib.util.spec_from_file_location("docling_list_crosscheck_test", SERVICE_PATH)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


class _Prov:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _Item:
    def __init__(self, text: str, page_no: int | None) -> None:
        self.text = text
        self.prov = [] if page_no is None else [_Prov(page_no)]


class _MultiPageItem(_Item):
    def __init__(self, text: str, page_nos: list[int]) -> None:
        self.text = text
        self.prov = [_Prov(page_no) for page_no in page_nos]


class _Document:
    def __init__(self, texts: list[_Item], pages: int = 3) -> None:
        self.texts = texts
        self.tables = []
        self.pages = {page_no: object() for page_no in range(1, pages + 1)}

    def export_to_markdown(self) -> str:
        return "\n".join(item.text for item in self.texts)


def _install_converter(service, document: _Document, monkeypatch: pytest.MonkeyPatch) -> None:
    result = type("Result", (), {"document": document})()
    monkeypatch.setattr(
        service,
        "get_converter",
        lambda: type("Converter", (), {"convert": lambda self, path: result})(),
    )


def _scanned_crosscheck(service):
    return service._scanned_pdf_percentage_crosscheck()


_OCR_BULLET = (
    "Запрещается:\n"
    "— хранить вещества класса 3 и\n"
    "смеси;\n"
    "— закрывать проходы;"
)

_ORIGINAL_MARKDOWN = "\n".join(
    [
        "Запрещается:",
        "6. - хранить вещества класса 3 и",
        "7. , xRg",
        "8. — закрывать проходы;",
        "UNRELATED_SOURCE_SENTINEL",
    ]
)


def _document() -> _Document:
    return _document_with_previous(_Item("6. - хранить вещества класса 3 и", 2))


def _document_with_previous(previous: _Item) -> _Document:
    return _Document(
        [
            _Item("Запрещается:", 2),
            previous,
            _Item("7. , xRg", 2),
            _Item("8. — закрывать проходы;", 2),
            _Item("UNRELATED_SOURCE_SENTINEL", 1),
        ]
    )


def test_docling_convert_repairs_ocr_list_continuation_only_when_two_page_ocr_passes_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _document()
    _install_converter(service, document, monkeypatch)
    calls: list[int] = []

    def page_ocr(path: str, page_no: int, budget):
        calls.append(page_no)
        return (_OCR_BULLET, _OCR_BULLET)

    monkeypatch.setattr(service, "_independent_page_list_ocr", page_ocr, raising=False)

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert calls == [2]
    assert "- хранить вещества класса 3 и смеси;" in markdown
    assert "xRg" not in markdown
    assert "8. — закрывать проходы;" in markdown
    assert "UNRELATED_SOURCE_SENTINEL" in markdown


@pytest.mark.parametrize("ocr", [None, ("Запрещается:\n6. - хранить вещества класса 3 и смеси;", "different")])
def test_docling_convert_keeps_list_when_independent_ocr_is_unavailable_or_disagrees(
    monkeypatch: pytest.MonkeyPatch, ocr
) -> None:
    service = _load_service(monkeypatch)
    document = _document()
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(service, "_independent_page_list_ocr", lambda path, page_no, budget: ocr, raising=False)

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert "xRg" in markdown
    assert "- хранить вещества класса 3 и смеси;" not in markdown


@pytest.mark.parametrize(
    "previous",
    [
        _Item("6. - хранить вещества класса 3 и", None),
        _MultiPageItem("6. - хранить вещества класса 3 и", [2, 3]),
        _Item("6. - хранить вещества класса 3 и", 1),
    ],
)
def test_docling_convert_does_not_repair_wrong_or_ambiguous_page(
    monkeypatch: pytest.MonkeyPatch, previous: _Item
):
    service = _load_service(monkeypatch)
    document = _document_with_previous(previous)
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (_OCR_BULLET, _OCR_BULLET),
        raising=False,
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert markdown == _ORIGINAL_MARKDOWN


def test_docling_convert_does_not_merge_numeric_ocr_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _document()
    _install_converter(service, document, monkeypatch)
    numeric_ocr = "Запрещается:\n— хранить вещества класса 3 и\n7. 25 смеси;\n— закрывать проходы;"
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (numeric_ocr, numeric_ocr),
        raising=False,
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert markdown == _ORIGINAL_MARKDOWN


def test_docling_convert_keeps_genuine_numbered_ocr_item_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _Document(
        [
            _Item("Запрещается:", 2),
            _Item("6. - хранить вещества класса 3 и", 2),
            _Item("7. xRg", 2),
            _Item("8. — закрывать проходы;", 2),
            _Item("UNRELATED_SOURCE_SENTINEL", 1),
        ]
    )
    _install_converter(service, document, monkeypatch)
    numbered_ocr = "Запрещается:\n— хранить вещества класса 3 и\n7. xRg\n— закрывать проходы;"
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (numbered_ocr, numbered_ocr),
        raising=False,
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert "7. xRg" in markdown
    assert "вещества класса 3 и смеси" not in markdown


def test_docling_convert_does_not_rewrite_mismatched_previous_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _document_with_previous(_Item("6. - хранить вещества класса 4 и", 2))
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (_OCR_BULLET, _OCR_BULLET),
        raising=False,
    )

    with _scanned_crosscheck(service):
        markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert "вещества класса 4" in markdown
    assert "7. , xRg" in markdown
    assert "вещества класса 3 и смеси" not in markdown


def test_docling_convert_never_calls_list_ocr_outside_scanned_pdf_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _document()
    _install_converter(service, document, monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: calls.append(page_no),
        raising=False,
    )

    markdown, _, _ = service._docling_convert("synthetic.pdf")

    assert calls == []
    assert "xRg" in markdown


def test_unscanned_conversion_does_not_report_list_crosscheck_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    _install_converter(service, _document(), monkeypatch)
    result = service._convert_sync(tmp_path="synthetic.txt", filename="synthetic.txt", suffix=".txt")
    assert result["markdown"] == _ORIGINAL_MARKDOWN
    assert result["warnings"] == []


def test_list_fragment_page_rejects_substring_previous_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    document = _Document(
        [
            _Item("6. - хранить вещества класса 3 и дополнительно", 2),
            _Item("7. , xRg", 2),
        ]
    )

    assert service._list_fragment_page(
        document, "хранить вещества класса 3 и", ", xRg"
    ) is None


@pytest.mark.parametrize(
    "previous,fragment",
    [
        (
            [_Item("6. - хранить вещества класса 3 и", 2), _Item("6. - хранить вещества класса 3 и", 2)],
            _Item("7. , xRg", 2),
        ),
        (
            [_Item("6. - хранить вещества класса 3 и", 2)],
            _Item("7. , xRg", 2),
        ),
    ],
)
def test_list_fragment_page_requires_unique_previous_and_fragment_items(
    monkeypatch: pytest.MonkeyPatch, previous, fragment: _Item
) -> None:
    service = _load_service(monkeypatch)
    texts = previous + [fragment]
    if len(previous) == 1:
        texts.append(_Item("7. , xRg", 2))
    document = _Document(texts)

    assert service._list_fragment_page(
        document, "хранить вещества класса 3 и", ", xRg"
    ) is None


@pytest.mark.parametrize(
    "ocr",
    [
        "— хранить вещества класса 3 и\nсмеси;\nдополнительная строка\n— закрывать проходы;",
        "— хранить вещества класса 3 и\nэто длинная unrelated строка без границы;",
        "— хранить вещества класса 3 и\nсмеси",
    ],
)
def test_confirmed_list_continuation_rejects_unbounded_or_nonterminal_text(
    monkeypatch: pytest.MonkeyPatch, ocr: str
) -> None:
    service = _load_service(monkeypatch)

    assert service._confirmed_list_continuation(
        ocr, "хранить вещества класса 3 и"
    ) is None


def test_repair_list_boundaries_requires_next_bullet_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    document = _document()
    markdown = "Запрещается:\n6. - хранить вещества класса 3 и\n7. , xRg\n"
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (_OCR_BULLET, _OCR_BULLET),
        raising=False,
    )

    assert service._repair_scanned_pdf_list_boundaries("synthetic.pdf", document, markdown) == markdown


def test_repair_list_boundaries_limits_distinct_pages_to_two(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    candidates = [
        (1, "хранить вещества класса 3 и", ", xRg"),
        (3, "хранить вещества класса 3 и", ", yRg"),
        (5, "хранить вещества класса 3 и", ", zRg"),
    ]
    monkeypatch.setattr(service, "_broken_list_continuations", lambda markdown: candidates)
    calls: list[int] = []
    monkeypatch.setattr(
        service,
        "_list_fragment_page",
        lambda document, previous, fragment: {", xRg": 1, ", yRg": 3, ", zRg": 5}[fragment],
    )
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: calls.append(page_no) or None,
        raising=False,
    )

    service._repair_scanned_pdf_list_boundaries("synthetic.pdf", _Document([]), "unused")

    assert calls == [1, 3]


def test_repair_list_boundaries_does_not_start_after_expired_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    candidate = [(1, "хранить вещества класса 3 и", ", xRg")]
    monkeypatch.setattr(service, "_broken_list_continuations", lambda markdown: candidate)
    monkeypatch.setattr(service, "_list_fragment_page", lambda document, previous, fragment: 1)
    calls: list[int] = []
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: calls.append(page_no) or (_OCR_BULLET, _OCR_BULLET),
        raising=False,
    )
    ticks = iter((100.0, 141.0))
    monkeypatch.setattr(service.time, "monotonic", lambda: next(ticks))

    service._repair_scanned_pdf_list_boundaries("synthetic.pdf", _Document([]), "unused")

    assert calls == []
