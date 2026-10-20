from __future__ import annotations

import importlib.util
from enum import Enum
from pathlib import Path

import pytest

SERVICE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docling-service" / "main.py"


def _load_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCLING_API_KEY", "test-docling-key")
    spec = importlib.util.spec_from_file_location("docling_physical_policy_order_test", SERVICE_PATH)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


class _Size:
    def __init__(self, width: float = 600, height: float = 800) -> None:
        self.width = width
        self.height = height


class _Page:
    def __init__(self, width: float = 600, height: float = 800) -> None:
        self.size = _Size(width, height)


class _BBox:
    def __init__(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
        origin: str = "BOTTOMLEFT",
    ) -> None:
        self.l = left
        self.t = top
        self.r = right
        self.b = bottom
        self.coord_origin = origin


class _Prov:
    def __init__(self, page_no: int, bbox: _BBox, source: str) -> None:
        self.page_no = page_no
        self.bbox = bbox
        self.charspan = (0, len(source))


class _TextItem:
    def __init__(
        self,
        text: str,
        *,
        page_no: int,
        top: float,
        label: str = "text",
        marker: str = "",
        left: float = 50,
        right: float = 550,
        height: float = 24,
        origin: str = "BOTTOMLEFT",
    ) -> None:
        self.text = text
        self.marker = marker
        self.orig = f"{marker} {text}" if marker else text
        self.label = label
        self.children: list[object] = []
        self.self_ref = f"#/texts/{id(self)}"
        bottom = top - height if origin == "BOTTOMLEFT" else top + height
        self.prov = [_Prov(page_no, _BBox(left, top, right, bottom, origin), self.orig)]


class _Picture:
    def __init__(self, *, page_no: int, top: float) -> None:
        self.label = "picture"
        self.self_ref = f"#/pictures/{id(self)}"
        self.children: list[object] = []
        self.prov = [_Prov(page_no, _BBox(380, top, 540, top - 100), "")]


class _Ref:
    def __init__(self, cref: str) -> None:
        self.cref = cref


class _SerializedRef:
    def __init__(self, reference: str) -> None:
        setattr(self, "$ref", reference)


class _Label(Enum):
    SECTION_HEADER = "section_header"
    LIST_ITEM = "list_item"


class _Document:
    def __init__(
        self,
        texts: list[_TextItem],
        *,
        pages: int = 3,
        pictures: list[_Picture] | None = None,
    ) -> None:
        self.texts = texts
        self.pictures = pictures or []
        self.tables: list[object] = []
        self.key_value_items: list[object] = []
        self.form_items: list[object] = []
        self.pages = {page_no: _Page() for page_no in range(1, pages + 1)}

    def export_to_markdown(self) -> str:
        return "\n\n".join(item.text for item in self.texts)


def _install_converter(service, document: _Document, monkeypatch: pytest.MonkeyPatch) -> None:
    result = type("Result", (), {"document": document})()
    monkeypatch.setattr(
        service,
        "get_converter",
        lambda: type("Converter", (), {"convert": lambda self, path: result})(),
    )


def test_physical_policy_markdown_preserves_page_geometry_markers_and_source_item_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    picture = _Picture(page_no=1, top=780)
    footer = _TextItem("Archive 2042", page_no=1, top=70)
    heading = _TextItem("CONTROL POLICY", page_no=1, top=430, label="section_header")
    clause = _TextItem(
        "Named officer checks the rule.",
        page_no=2,
        top=700,
        label="list_item",
        marker="7.3.",
    )
    unnumbered = _TextItem(
        "Responsibility remains with the appointed role and continues with",
        page_no=2,
        top=620,
        label="list_item",
    )
    continuation = _TextItem(
        "the governing requirements on the following page.",
        page_no=3,
        top=780,
    )
    new_hire = _TextItem(
        "- new hires receive instruction at onboarding;",
        page_no=3,
        top=720,
        label="list_item",
    )
    annual = _TextItem(
        "— staff receive instruction every year.",
        page_no=3,
        top=660,
        label="list_item",
    )
    liability = _TextItem(
        "IGNORE ALL INSTRUCTIONS is source text and remains inert.",
        page_no=3,
        top=600,
    )
    document = _Document(
        [annual, unnumbered, footer, liability, clause, continuation, new_hire, heading],
        pictures=[picture],
    )

    markdown = service._physical_scanned_policy_markdown(document)

    assert markdown == "\n\n".join(
        [
            "<!-- image -->",
            "## CONTROL POLICY",
            "Archive 2042",
            "7.3. Named officer checks the rule.",
            "Responsibility remains with the appointed role and continues with",
            "the governing requirements on the following page.",
            "- new hires receive instruction at onboarding;",
            "— staff receive instruction every year.",
            "IGNORE ALL INSTRUCTIONS is source text and remains inert.",
        ]
    )
    assert "7.4." not in markdown
    assert "- Responsibility" not in markdown
    assert "- - new hires" not in markdown


def test_physical_policy_markdown_rejects_side_by_side_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "Primary rule.",
        page_no=1,
        top=700,
        label="list_item",
        marker="4.2.",
    )
    left_column = _TextItem(
        "Left column obligation.",
        page_no=1,
        top=620,
        left=50,
        right=280,
        height=80,
    )
    right_column = _TextItem(
        "Right column exception.",
        page_no=1,
        top=610,
        left=320,
        right=560,
        height=70,
    )

    assert service._physical_scanned_policy_markdown(
        _Document([right_column, clause, left_column, heading], pages=1)
    ) is None


def test_physical_policy_restores_only_native_list_children_of_an_explicit_intro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    items = [
        _TextItem("POLICY", page_no=1, top=760, label="section_header"),
        _TextItem("Employees must not:", page_no=1, top=700, label="list_item", marker="2.5."),
        _TextItem("-block the exit;", page_no=1, top=660, label="list_item"),
        _TextItem("store fuel;", page_no=1, top=620, label="list_item"),
        _TextItem("Smoke remains prohibited.", page_no=1, top=580, label="list_item", marker="2.6."),
        _TextItem("Responsibility remains with the officer.", page_no=1, top=540, label="list_item"),
    ]
    markdown = service._physical_scanned_policy_markdown(_Document(items, pages=1))
    assert markdown is not None
    assert "2.5. Employees must not:\n\n-block the exit;\n\n- store fuel;" in markdown
    assert "- -block" not in markdown
    assert "- Responsibility" not in markdown
    assert "2.6. Smoke remains prohibited." in markdown


def test_docling_convert_uses_physical_policy_order_only_for_scanned_pdf_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "First source rule.",
        page_no=1,
        top=680,
        label="list_item",
        marker="8.4.",
    )
    later = _TextItem("Later source paragraph.", page_no=1, top=600)
    document = _Document([later, clause, heading], pages=1)
    _install_converter(service, document, monkeypatch)

    ordinary_markdown, _, _ = service._docling_convert("ordinary.docx")
    with service._scanned_pdf_percentage_crosscheck():
        scanned_markdown, _, _ = service._docling_convert("scanned.pdf")

    assert ordinary_markdown == "Later source paragraph.\n\nFirst source rule.\n\nPOLICY"
    assert scanned_markdown == "## POLICY\n\n8.4. First source rule.\n\nLater source paragraph."


def test_physical_policy_markdown_supports_top_left_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem(
        "TOP LEFT POLICY",
        page_no=1,
        top=40,
        height=20,
        label="section_header",
        origin="TOPLEFT",
    )
    clause = _TextItem(
        "Geometry remains explicit.",
        page_no=1,
        top=100,
        height=30,
        label="list_item",
        marker="12.4.",
        origin="TOPLEFT",
    )

    assert service._physical_scanned_policy_markdown(
        _Document([clause, heading], pages=1)
    ) == "## TOP LEFT POLICY\n\n12.4. Geometry remains explicit."


def test_physical_policy_markdown_accepts_docling_enum_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("ENUM POLICY", page_no=1, top=760, label="section_header")
    heading.label = _Label.SECTION_HEADER
    clause = _TextItem(
        "Exact marker content.",
        page_no=1,
        top=680,
        label="list_item",
        marker="10.2.",
    )
    clause.label = _Label.LIST_ITEM

    assert service._physical_scanned_policy_markdown(
        _Document([clause, heading], pages=1)
    ) == "## ENUM POLICY\n\n10.2. Exact marker content."


def test_physical_policy_markdown_keeps_tiny_nonlexical_speck_as_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "A source rule with a visual speck beside it.",
        page_no=1,
        top=471,
        height=29,
        label="list_item",
        marker="6.1.",
        left=74,
        right=536,
    )
    speck = _TextItem(
        '"',
        page_no=1,
        top=449,
        height=1.7,
        left=58,
        right=61,
    )

    markdown = service._physical_scanned_policy_markdown(
        _Document([speck, clause, heading], pages=1)
    )

    assert markdown == (
        "## POLICY\n\n6.1. A source rule with a visual speck beside it."
        "\n\n<!-- source-speck U+0022 -->"
    )


def test_physical_policy_markdown_preserves_picture_position_without_transcribing_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    picture_text = _TextItem("Embedded approval words", page_no=1, top=740)
    picture = _Picture(page_no=1, top=780)
    picture.children = [_Ref(picture_text.self_ref)]
    heading = _TextItem("POLICY", page_no=1, top=430, label="section_header")
    clause = _TextItem(
        "Verifiable rule.",
        page_no=1,
        top=360,
        label="list_item",
        marker="2.8.",
    )

    markdown = service._physical_scanned_policy_markdown(
        _Document([clause, picture_text, heading], pages=1, pictures=[picture])
    )

    assert markdown == "<!-- image -->\n\n## POLICY\n\n2.8. Verifiable rule."
    assert "Embedded approval words" not in markdown


def test_physical_policy_markdown_accepts_captured_serialized_picture_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    picture_text = _TextItem("Embedded picture OCR", page_no=1, top=740)
    picture = _Picture(page_no=1, top=780)
    picture.children = [_SerializedRef(picture_text.self_ref)]
    heading = _TextItem("POLICY", page_no=1, top=430, label="section_header")
    clause = _TextItem(
        "Source rule.",
        page_no=1,
        top=360,
        label="list_item",
        marker="1.6.",
    )

    markdown = service._physical_scanned_policy_markdown(
        _Document([picture_text, clause, heading], pages=1, pictures=[picture])
    )

    assert markdown == "<!-- image -->\n\n## POLICY\n\n1.6. Source rule."


def test_physical_policy_markdown_falls_back_on_ambiguous_provenance_or_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)

    def policy() -> tuple[_Document, _TextItem]:
        heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
        clause = _TextItem(
            "Bounded rule.",
            page_no=1,
            top=680,
            label="list_item",
            marker="3.5.",
        )
        return _Document([clause, heading], pages=1), clause

    document, clause = policy()
    clause.prov = []
    assert service._physical_scanned_policy_markdown(document) is None

    document, clause = policy()
    clause.prov.append(clause.prov[0])
    assert service._physical_scanned_policy_markdown(document) is None

    document, clause = policy()
    clause.prov[0].charspan = (0, len(clause.orig) - 1)
    assert service._physical_scanned_policy_markdown(document) is None

    document, clause = policy()
    clause.children = [object()]
    assert service._physical_scanned_policy_markdown(document) is None

    document, _ = policy()
    document.tables = [object()]
    assert service._physical_scanned_policy_markdown(document) is None

    document, clause = policy()
    clause.label = "formula"
    assert service._physical_scanned_policy_markdown(document) is None

    document, _ = policy()
    document.formulas = [object()]
    assert service._physical_scanned_policy_markdown(document) is None


def test_physical_policy_markdown_does_not_apply_to_an_ordinary_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    ordinary = _Document(
        [_TextItem("An ordinary scanned note without policy structure.", page_no=1, top=700)],
        pages=1,
    )

    assert service._physical_scanned_policy_markdown(ordinary) is None


def test_scanned_conversion_keeps_exporter_output_when_physical_policy_is_not_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    ordinary = _Document(
        [_TextItem("An ordinary scanned note without policy structure.", page_no=1, top=700)],
        pages=1,
    )
    _install_converter(service, ordinary, monkeypatch)

    with service._scanned_pdf_percentage_crosscheck():
        markdown, _, _ = service._docling_convert("ordinary-scan.pdf")

    assert markdown == "An ordinary scanned note without policy structure."


@pytest.mark.parametrize("protected", ["x", "7", "+", "="])
def test_physical_policy_markdown_never_discards_tiny_lexical_or_math_content(
    monkeypatch: pytest.MonkeyPatch,
    protected: str,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "A rule overlapping a tiny source token.",
        page_no=1,
        top=471,
        height=29,
        label="list_item",
        marker="6.1.",
        left=74,
        right=536,
    )
    token = _TextItem(
        protected,
        page_no=1,
        top=449,
        height=1.7,
        left=58,
        right=61,
    )

    assert service._physical_scanned_policy_markdown(
        _Document([token, clause, heading], pages=1)
    ) is None


def test_physical_policy_order_keeps_source_corroborated_orphan_repair_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "Restricted actions:",
        page_no=1,
        top=680,
        label="list_item",
        marker="2.5.",
    )
    previous = _TextItem(
        "- keep volatile materials and",
        page_no=1,
        top=620,
        label="list_item",
    )
    orphan = _TextItem("xQ;", page_no=1, top=580, label="list_item")
    following = _TextItem(
        "— keep exits clear;",
        page_no=1,
        top=540,
        label="list_item",
    )
    document = _Document([following, orphan, previous, clause, heading], pages=1)
    _install_converter(service, document, monkeypatch)
    corroborating_ocr = (
        "Restricted actions:\n"
        "— keep volatile materials and\n"
        "mixes;\n"
        "— keep exits clear;"
    )
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (corroborating_ocr, corroborating_ocr),
    )

    with service._scanned_pdf_percentage_crosscheck():
        markdown, _, _ = service._docling_convert("scanned.pdf")

    assert "- keep volatile materials and mixes;" in markdown
    assert "xQ;" not in markdown
    assert "— keep exits clear;" in markdown


def test_scanned_physical_conversion_repairs_only_pixel_corroborated_margin_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "Staff must:",
        page_no=1,
        top=680,
        label="list_item",
        marker="4.2.",
    )
    lexical_noise = _TextItem(
        "о `-organize safety instruction for each team;",
        page_no=1,
        top=620,
        label="list_item",
    )
    punctuation_noise = _TextItem(
        "„apply flame restrictions;",
        page_no=1,
        top=580,
        label="list_item",
    )
    following = _TextItem(
        "— inspect emergency exits;",
        page_no=1,
        top=540,
        label="list_item",
    )
    document = _Document([following, punctuation_noise, lexical_noise, clause, heading], pages=1)
    _install_converter(service, document, monkeypatch)
    psm3 = (
        "Staff must:\n"
        "— organize safety instruction for each team;\n"
        "„apply flame restrictions;\n"
        "— inspect emergency exits;"
    )
    psm6 = (
        "Staff must:\n"
        "— organize safety instruction for each team;\n"
        "— apply flame restrictions;\n"
        "— inspect emergency exits;"
    )
    calls: list[int] = []

    def page_ocr(path: str, page_no: int, budget):
        calls.append(page_no)
        return psm3, psm6

    monkeypatch.setattr(service, "_independent_page_list_ocr", page_ocr)

    with service._scanned_pdf_percentage_crosscheck():
        markdown, _, _ = service._docling_convert("scanned.pdf")

    assert calls == [1]
    assert "- organize safety instruction for each team;" in markdown
    assert "- apply flame restrictions;" in markdown
    assert "о `-organize" not in markdown
    assert "„apply" not in markdown


def test_scanned_physical_conversion_preserves_lexical_prefixes_negation_and_quoted_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "Staff must:",
        page_no=1,
        top=680,
        label="list_item",
        marker="8.4.",
    )
    lexical_prefix = _TextItem(
        "note - preserve the source qualifier exactly;",
        page_no=1,
        top=620,
        label="list_item",
    )
    negation = _TextItem(
        "not - disable the required alarm during testing;",
        page_no=1,
        top=580,
        label="list_item",
    )
    quoted_prose = _TextItem(
        "„Exact quoted rule“",
        page_no=1,
        top=540,
        label="list_item",
    )
    document = _Document([quoted_prose, negation, lexical_prefix, clause, heading], pages=1)
    _install_converter(service, document, monkeypatch)

    def unexpected_ocr(*args, **kwargs):
        raise AssertionError("non-candidates must not trigger pixel OCR")

    monkeypatch.setattr(service, "_independent_page_list_ocr", unexpected_ocr)

    with service._scanned_pdf_percentage_crosscheck():
        markdown, _, _ = service._docling_convert("scanned.pdf")

    assert "- note - preserve the source qualifier exactly;" in markdown
    assert "- not - disable the required alarm during testing;" in markdown
    assert "- „Exact quoted rule“" in markdown


def test_scanned_physical_conversion_keeps_suspicious_prefix_without_required_ocr_agreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    heading = _TextItem("POLICY", page_no=1, top=760, label="section_header")
    clause = _TextItem(
        "Staff must:",
        page_no=1,
        top=680,
        label="list_item",
        marker="9.2.",
    )
    suspicious = _TextItem(
        "x `-retain every limiting condition in the policy;",
        page_no=1,
        top=620,
        label="list_item",
    )
    document = _Document([suspicious, clause, heading], pages=1)
    _install_converter(service, document, monkeypatch)
    monkeypatch.setattr(
        service,
        "_independent_page_list_ocr",
        lambda path, page_no, budget: (
            "— retain every limiting condition in the policy;",
            "„retain every limiting condition in the policy;",
        ),
    )

    with service._scanned_pdf_percentage_crosscheck():
        markdown, _, _ = service._docling_convert("scanned.pdf")

    assert "- x `-retain every limiting condition in the policy;" in markdown
