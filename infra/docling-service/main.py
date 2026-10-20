"""Local document converter service running on the VPS."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import secrets
import shutil
import stat
import struct
import subprocess
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docling-service")

app = FastAPI(title="Document Converter", version="1.2")

ROUTING_VERSION = "1.2"
MARKITDOWN_VERSION = "0.1.6"
MARKITDOWN_OFFICE_EXTENSIONS = {".docx", ".xls", ".xlsx"}
MARKITDOWN_DIGITAL_FALLBACK_EXTENSIONS = {".pdf"}
OCR_LANGUAGES = [
    language.strip()
    for language in os.getenv("DOCLING_OCR_LANGUAGES", "kaz,rus,eng").split(",")
    if language.strip()
]
DOCLING_API_KEY = os.getenv("DOCLING_API_KEY", "")
DOCLING_ENV = os.getenv("DOCLING_ENV", "development").strip().lower()
LEGACY_DOC_TIMEOUT_SECONDS = int(os.getenv("DOCLING_LEGACY_DOC_TIMEOUT_SECONDS", "120"))
MAX_UPLOAD_BYTES = max(
    1, int(os.getenv("CONVERTER_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
)
MAX_CONCURRENCY = max(1, int(os.getenv("CONVERTER_MAX_CONCURRENCY", "1")))
QUEUE_WAIT_TIMEOUT_SECONDS = max(
    0.1,
    float(os.getenv("CONVERTER_QUEUE_WAIT_TIMEOUT_SECONDS", "30")),
)
UPLOAD_CHUNK_BYTES = max(
    64 * 1024, int(os.getenv("CONVERTER_UPLOAD_CHUNK_BYTES", str(1024 * 1024)))
)
PDF_SAMPLE_PAGES = max(1, int(os.getenv("CONVERTER_PDF_SAMPLE_PAGES", "3")))
PDF_MIN_EMBEDDED_TEXT_CHARS = max(
    1,
    int(os.getenv("CONVERTER_PDF_MIN_EMBEDDED_TEXT_CHARS", "80")),
)
PDF_MIN_TEXT_PAGE_RATIO = min(
    1.0,
    max(0.0, float(os.getenv("CONVERTER_PDF_MIN_TEXT_PAGE_RATIO", "0.6"))),
)
OOXML_MAX_ENTRIES = max(1, int(os.getenv("OOXML_MAX_ENTRIES", "5000")))
OOXML_MAX_ENTRY_BYTES = max(1, int(os.getenv("OOXML_MAX_ENTRY_BYTES", str(64 * 1024 * 1024))))
OOXML_MAX_TOTAL_BYTES = max(1, int(os.getenv("OOXML_MAX_TOTAL_BYTES", str(256 * 1024 * 1024))))
OOXML_MAX_COMPRESSION_RATIO = max(1.0, float(os.getenv("OOXML_MAX_COMPRESSION_RATIO", "100")))
PERCENTAGE_CROSSCHECK_MAX_PAGES = 12
PERCENTAGE_CROSSCHECK_MAX_PIXELS = 8_000_000
PERCENTAGE_CROSSCHECK_MAX_TOTAL_PIXELS = 32_000_000
PERCENTAGE_CROSSCHECK_TIMEOUT_SECONDS = 12
PERCENTAGE_CROSSCHECK_TOTAL_TIMEOUT_SECONDS = 60
UNREADABLE_PERCENTAGE_VALUE = "[UNREADABLE_PERCENTAGE_VALUE]"
_PERCENTAGE_RE = re.compile(r"(?<![\w-])-?\d+(?:[.,]\d+)?\s*%")


def validate_runtime_config(environment: str = DOCLING_ENV, api_key: str = DOCLING_API_KEY) -> None:
    if environment == "production" and len(api_key) < 32:
        raise RuntimeError("DOCLING_API_KEY must contain at least 32 characters in production")


validate_runtime_config()

# One process should own the Docling models on a small VPS. A semaphore keeps
# requests asynchronous while preventing concurrent model-sized allocations.
_conversion_slots = asyncio.Semaphore(MAX_CONCURRENCY)

_converter = None
_markitdown_converter = None
_SCANNED_PDF_PERCENTAGE_CROSSCHECK: ContextVar[bool] = ContextVar(
    "scanned_pdf_percentage_crosscheck", default=False
)


@contextmanager
def _scanned_pdf_percentage_crosscheck():
    token = _SCANNED_PDF_PERCENTAGE_CROSSCHECK.set(True)
    try:
        yield
    finally:
        _SCANNED_PDF_PERCENTAGE_CROSSCHECK.reset(token)


def get_converter():
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TesseractCliOcrOptions,
        )
        from docling.document_converter import DocumentConverter as DoclingConverter
        from docling.document_converter import PdfFormatOption

        pdf_options = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            ocr_options=TesseractCliOcrOptions(lang=OCR_LANGUAGES),
            artifacts_path=Path(os.environ["DOCLING_ARTIFACTS_PATH"])
            if os.environ.get("DOCLING_ARTIFACTS_PATH") else None,
        )
        _converter = DoclingConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)
            }
        )
        logger.info(
            "Docling converter loaded with OCR enabled (engine=tesseract-cli, languages=%s)",
            ",".join(OCR_LANGUAGES),
        )
    return _converter


def get_markitdown_converter():
    """Create the local-only MarkItDown converter lazily."""
    global _markitdown_converter
    if _markitdown_converter is None:
        from markitdown import MarkItDown

        _markitdown_converter = MarkItDown(enable_plugins=False)
        logger.info(
            "MarkItDown converter loaded (version=%s, plugins=disabled)",
            MARKITDOWN_VERSION,
        )
    return _markitdown_converter


def _package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def _usable_markdown(markdown: object) -> bool:
    """Reject empty/binary output while allowing short valid documents."""
    if not isinstance(markdown, str):
        return False
    text = markdown.strip()
    if not text:
        return False
    printable = sum(char.isprintable() or char in "\n\r\t" for char in text)
    return printable / len(text) >= 0.8 and any(char.isalnum() for char in text)


def preflight_ooxml(path: str, suffix: str) -> None:
    """Reject archive traversal and expansion abuse before parser invocation."""
    required = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml"}.get(suffix)
    if required is None:
        return
    with open(path, "rb") as source:
        source.seek(0, 2)
        size = source.tell()
        source.seek(max(0, size - (22 + 65_535)))
        tail = source.read(22 + 65_535)
    directory_offset = tail.rfind(b"PK\x05\x06")
    if directory_offset < 0 or len(tail) - directory_offset < 22:
        raise HTTPException(status_code=400, detail="Invalid OOXML document")
    _, disk_number, directory_disk, disk_entries, declared_entries, _, _, comment_length = struct.unpack_from(
        "<4s4H2LH", tail, directory_offset
    )
    if (
        directory_offset + 22 + comment_length != len(tail)
        or disk_number
        or directory_disk
        or disk_entries != declared_entries
        or declared_entries == 0xFFFF
    ):
        raise HTTPException(status_code=400, detail="Invalid OOXML document directory")
    if declared_entries > OOXML_MAX_ENTRIES:
        raise HTTPException(status_code=413, detail="OOXML archive has too many entries")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise HTTPException(status_code=400, detail="Invalid OOXML document") from exc
    if len(entries) > OOXML_MAX_ENTRIES:
        raise HTTPException(status_code=413, detail="OOXML archive has too many entries")
    if len(entries) != declared_entries:
        raise HTTPException(status_code=400, detail="Invalid OOXML document directory")

    names: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    for entry in entries:
        name = entry.filename
        parsed = PurePosixPath(name)
        if (
            not name
            or len(name) > 512
            or "\x00" in name
            or "\\" in name
            or name.startswith("/")
            or parsed.is_absolute()
            or ".." in parsed.parts
        ):
            raise HTTPException(status_code=400, detail="OOXML archive contains an unsafe path")
        if entry.flag_bits & 0x1 or stat.S_ISLNK(entry.external_attr >> 16):
            raise HTTPException(status_code=400, detail="OOXML archive contains an unsupported entry")
        if entry.file_size > OOXML_MAX_ENTRY_BYTES:
            raise HTTPException(status_code=413, detail="OOXML entry is too large")
        if entry.file_size and entry.file_size / max(entry.compress_size, 1) > OOXML_MAX_COMPRESSION_RATIO:
            raise HTTPException(status_code=413, detail="OOXML compression ratio is too high")
        names.add(name.rstrip("/"))
        total_uncompressed += entry.file_size
        total_compressed += entry.compress_size
        if total_uncompressed > OOXML_MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="OOXML expanded size is too large")
    if total_uncompressed and total_uncompressed / max(total_compressed, 1) > OOXML_MAX_COMPRESSION_RATIO:
        raise HTTPException(status_code=413, detail="OOXML compression ratio is too high")
    if "[Content_Types].xml" not in names or required not in names:
        raise HTTPException(status_code=400, detail="Invalid OOXML document structure")


def _markitdown_convert(path: str) -> str:
    """Use only MarkItDown's local-path API; URLs and plugins are never accepted."""
    result = get_markitdown_converter().convert_local(path)
    markdown = getattr(result, "markdown", None)
    if not _usable_markdown(markdown):
        raise ValueError("MarkItDown returned unusable output")
    if Path(path).suffix.lower() == ".docx":
        return _docx_insert_cell_breaks(path, markdown)
    return markdown


_DOCX_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_TAG = f"{{{_DOCX_W_NS}}}"


def _docx_paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == _DOCX_TAG + "t":
            parts.append(node.text or "")
        elif node.tag in {_DOCX_TAG + "br", _DOCX_TAG + "cr"}:
            parts.append("<br>")
        elif node.tag == _DOCX_TAG + "tab":
            parts.append("\t")
    return "".join(parts).strip()


def _docx_table_paragraphs(path: str) -> list[list[list[list[str]]]] | None:
    """Read only direct DOCX table cells; return None for ambiguous structure."""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
            if (
                b"\x00" in xml
                or b"<!DOCTYPE" in xml.upper()
                or b"<!ENTITY" in xml.upper()
                or re.search(rb"encoding\s*=\s*['\"]utf-(?:16|32)", xml[:256], re.IGNORECASE)
            ):
                return None
            root = ET.fromstring(xml)
    except (KeyError, ET.ParseError, zipfile.BadZipFile):
        return None

    body = root.find("./" + _DOCX_TAG + "body")
    if body is None:
        return None
    tables: list[list[list[list[str]]]] = []
    for table in body.findall("./" + _DOCX_TAG + "tbl"):
        rows: list[list[list[str]]] = []
        for row in table.findall("./" + _DOCX_TAG + "tr"):
            cells: list[list[str]] = []
            for cell in row.findall("./" + _DOCX_TAG + "tc"):
                properties = cell.find("./" + _DOCX_TAG + "tcPr")
                if (
                    cell.find("./" + _DOCX_TAG + "tbl") is not None
                    or properties is not None
                    and (
                        properties.find("./" + _DOCX_TAG + "gridSpan") is not None
                        or properties.find("./" + _DOCX_TAG + "vMerge") is not None
                    )
                    or any(
                        child.tag not in {_DOCX_TAG + "tcPr", _DOCX_TAG + "p"}
                        for child in cell
                    )
                ):
                    return None
                paragraphs = [
                    _docx_paragraph_text(paragraph)
                    for paragraph in cell.findall("./" + _DOCX_TAG + "p")
                ]
                cells.append(paragraphs)
            if cells:
                rows.append(cells)
        if not rows:
            return None
        tables.append(rows)
    return tables or None


def _markdown_row_cells(line: str) -> list[str] | None:
    content = line.rstrip("\r\n").strip()
    if not content.startswith("|") or not content.endswith("|"):
        return None
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in content[1:-1]:
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    cells.append("".join(current).strip())
    return cells


def _markdown_visible_alnum(value: str) -> tuple[list[str], list[int]]:
    breaks = [match.span() for match in re.finditer(r"<br\s*/?>", value, flags=re.IGNORECASE)]
    characters: list[str] = []
    offsets: list[int] = []
    for match in re.finditer(r"[^\W_]", value, re.UNICODE):
        if any(start <= match.start() < end for start, end in breaks):
            continue
        normalized = match.group(0).casefold().replace("ё", "е")
        for character in normalized:
            characters.append(character)
            offsets.append(match.start())
    return characters, offsets


def _markdown_visible_punctuation(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    return "".join(character for character in value if not character.isspace())


def _allowed_converter_gap(value: str) -> bool:
    """Permit whitespace/markup and one generated list marker, never words."""
    value = re.sub(r"<br\s*/?>", "", value, flags=re.IGNORECASE)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = re.sub(r"^\s*(?:\d+[.)]|[-—–*•])\s*", "", value, count=1)
    return not re.search(r"[^\W_]", value, re.UNICODE)


def _insert_cell_breaks(markdown_cell: str, paragraphs: list[str]) -> str | None:
    segments = [segment for paragraph in paragraphs for segment in paragraph.split("<br>") if segment.strip()]
    if not segments:
        return markdown_cell
    actual, actual_offsets = _markdown_visible_alnum(markdown_cell)
    offsets: list[int] = []
    cursor = 0
    raw_cursor = 0
    # MarkItDown may add list markers that are not literal DOCX text.  Match
    # each source segment's visible characters in order, retaining converter
    # markup and labels. Character mapping also handles markup inside numbers.
    for segment_index, segment in enumerate(segments):
        wanted, _ = _markdown_visible_alnum(segment)
        found = None
        if wanted:
            for start in range(cursor, len(actual) - len(wanted) + 1):
                if actual[start:start + len(wanted)] != wanted:
                    continue
                candidate_offset = actual_offsets[start]
                if _allowed_converter_gap(markdown_cell[raw_cursor:candidate_offset]):
                    found = start
                    break
            if found is None:
                return None
            offset = actual_offsets[found]
            raw_cursor = actual_offsets[found + len(wanted) - 1] + 1
        else:
            punctuation = _markdown_visible_punctuation(segment)
            if not punctuation:
                continue
            raw_offset = markdown_cell.find(punctuation, raw_cursor)
            if raw_offset < 0 or not _allowed_converter_gap(markdown_cell[raw_cursor:raw_offset]):
                return None
            offset = raw_offset
            raw_cursor = raw_offset + len(punctuation)
        if segment_index:
            marker = re.search(r"(?:^|\s)((?:\d+[.)])|[-—–*•])\s*$", markdown_cell[:offset])
            if marker:
                offset = marker.start(1)
            offsets.append(offset)
        if found is not None:
            cursor = found + len(wanted)
    if not _allowed_converter_gap(markdown_cell[raw_cursor:]):
        return None
    for offset in reversed(offsets):
        markdown_cell = markdown_cell[:offset].rstrip() + "<br>" + markdown_cell[offset:]
    return markdown_cell


def _docx_insert_cell_breaks(path: str, markdown: str) -> str:
    tables = _docx_table_paragraphs(path)
    if not tables:
        return markdown
    lines = markdown.splitlines(keepends=True)
    parsed_tables: list[tuple[list[int], list[list[str]]]] = []
    index = 0
    while index < len(lines) - 1:
        header = _markdown_row_cells(lines[index])
        separator = _markdown_row_cells(lines[index + 1])
        if header is None or separator is None or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            index += 1
            continue
        row_indexes = [index]
        rows = [header]
        index += 2
        while index < len(lines):
            row = _markdown_row_cells(lines[index])
            if row is None:
                break
            row_indexes.append(index)
            rows.append(row)
            index += 1
        if rows and all(not cell for cell in rows[0]):
            row_indexes = row_indexes[1:]
            rows = rows[1:]
        parsed_tables.append((row_indexes, rows))
    if len(parsed_tables) != len(tables):
        return markdown
    replacements: dict[int, str] = {}
    for (row_indexes, markdown_rows), source_rows in zip(parsed_tables, tables):
        if len(markdown_rows) != len(source_rows) or any(
            len(markdown_row) != len(source_row)
            for markdown_row, source_row in zip(markdown_rows, source_rows)
        ):
            return markdown
        for line_index, markdown_row, source_row in zip(row_indexes, markdown_rows, source_rows):
            updated: list[str] = []
            for markdown_cell, source_paragraphs in zip(markdown_row, source_row):
                cell = _insert_cell_breaks(markdown_cell, source_paragraphs)
                if cell is None:
                    return markdown
                updated.append(cell)
            newline = "\r\n" if lines[line_index].endswith("\r\n") else "\n"
            replacements[line_index] = "| " + " | ".join(updated) + " |" + newline
    for line_index, replacement in replacements.items():
        lines[line_index] = replacement
    return "".join(lines)


def _normalized_percentages(value: str) -> set[str]:
    normalized: set[str] = set()
    for match in _PERCENTAGE_RE.finditer(value):
        try:
            number = Decimal(match.group(0).rstrip("%").strip().replace(",", "."))
        except InvalidOperation:
            continue
        normalized.add(format(number.normalize(), "f"))
    return normalized


def _page_no(item: object) -> int | None:
    for provenance in getattr(item, "prov", ()) or ():
        page_no = getattr(provenance, "page_no", None)
        if isinstance(page_no, int) and page_no > 0:
            return page_no
    return None


def _page_nos(item: object) -> set[int]:
    return {
        page_no
        for provenance in getattr(item, "prov", ()) or ()
        if isinstance((page_no := getattr(provenance, "page_no", None)), int) and page_no > 0
    }


def _percentage_text_slots(document: object) -> list[tuple[object, int | None]]:
    slots: list[tuple[object, int | None]] = []
    for item in getattr(document, "texts", ()) or ():
        if isinstance(getattr(item, "text", None), str) and _PERCENTAGE_RE.search(item.text):
            slots.append((item, _page_no(item)))
    for table in getattr(document, "tables", ()) or ():
        for cell in getattr(getattr(table, "data", None), "table_cells", ()) or ():
            if isinstance(getattr(cell, "text", None), str) and _PERCENTAGE_RE.search(cell.text):
                cell_page_no = _page_no(cell)
                table_page_nos = _page_nos(table)
                slots.append(
                    (cell, cell_page_no if cell_page_no is not None else next(iter(table_page_nos), None) if len(table_page_nos) == 1 else None)
                )
    return slots


def _mask_unconfirmed_percentages(value: str, confirmed: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            number = Decimal(match.group(0).rstrip("%").strip().replace(",", "."))
        except InvalidOperation:
            return UNREADABLE_PERCENTAGE_VALUE
        return match.group(0) if format(number.normalize(), "f") in confirmed else UNREADABLE_PERCENTAGE_VALUE

    return _PERCENTAGE_RE.sub(replace, value)


def _close_resource(resource: object | None) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _independent_page_ocr(
    path: str, page_no: int, budget: dict[str, float],
    *, psms: tuple[str, str] = ("6", "11"), languages: tuple[str, ...] = ("rus",),
) -> tuple[str, str] | None:
    """Run two bounded full-page OCR passes; absence means uncertainty, not falsity."""
    pdf = page = bitmap = image = None
    image_path: str | None = None
    try:
        if time.monotonic() >= budget["deadline"]:
            return None
        from pypdfium2 import PdfDocument

        pdf = PdfDocument(path)
        page = pdf[page_no - 1]
        width, height = page.get_size()
        width = float(width)
        height = float(height)
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            return None
        scale = 2
        pixels = math.ceil(width * scale) * math.ceil(height * scale)
        if (
            pixels > PERCENTAGE_CROSSCHECK_MAX_PIXELS
            or budget["pixels"] + pixels > PERCENTAGE_CROSSCHECK_MAX_TOTAL_PIXELS
        ):
            return None
        budget["pixels"] += pixels
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", dir=tempfile.gettempdir()) as temporary:
            image_path = temporary.name
        image.save(image_path)
        outputs: list[str] = []
        for psm in psms:
            remaining = budget["deadline"] - time.monotonic()
            if remaining <= 0:
                return None
            completed = subprocess.run(
                ["tesseract", image_path, "stdout", "-l", "+".join(languages), "--psm", psm],
                capture_output=True,
                text=True,
                timeout=min(PERCENTAGE_CROSSCHECK_TIMEOUT_SECONDS, remaining),
                check=False,
            )
            if completed.returncode != 0:
                return None
            outputs.append(completed.stdout or "")
        return outputs[0], outputs[1]
    except Exception as exc:  # noqa: BLE001 - an unavailable independent check is explicit uncertainty
        logger.warning("Independent page OCR unavailable page=%s error_type=%s", page_no, type(exc).__name__)
        return None
    finally:
        if image_path:
            Path(image_path).unlink(missing_ok=True)
        _close_resource(image)
        _close_resource(bitmap)
        _close_resource(page)
        _close_resource(pdf)


def _independent_page_percentage_ocr(
    path: str, page_no: int, budget: dict[str, float],
) -> tuple[str, str] | None:
    return _independent_page_ocr(path, page_no, budget)


def _independent_page_list_ocr(
    path: str, page_no: int, budget: dict[str, float],
) -> tuple[str, str] | None:
    return _independent_page_ocr(path, page_no, budget, psms=("3", "6"), languages=tuple(OCR_LANGUAGES))


_PHYSICAL_POLICY_TEXT_LABELS = {"text", "list_item", "section_header"}
_HIERARCHICAL_MARKER = re.compile(r"^\d+(?:\.\d+)+[.)]?$")
_PROTECTED_MATH_SIGNS = frozenset("+-−–—=*/%<>≤≥×÷")


def _physical_page_size(pages: object, page_no: int) -> tuple[float, float] | None:
    page = pages.get(page_no) if hasattr(pages, "get") else None
    size = getattr(page, "size", None)
    width = getattr(size, "width", None)
    height = getattr(size, "height", None)
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value) and value > 0
        for value in (width, height)
    ):
        return None
    return float(width), float(height)


def _physical_item_position(
    item: object, pages: object, *, picture: bool = False,
) -> tuple[int, float, float, float, float, float, float] | None:
    provenance = list(getattr(item, "prov", ()) or ())
    if len(provenance) != 1:
        return None
    source = provenance[0]
    page_no = getattr(source, "page_no", None)
    if not isinstance(page_no, int) or page_no <= 0:
        return None
    page_size = _physical_page_size(pages, page_no)
    if page_size is None:
        return None
    page_width, page_height = page_size
    bbox = getattr(source, "bbox", None)
    values = tuple(getattr(bbox, name, None) for name in ("l", "t", "r", "b"))
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        return None
    left, top, right, bottom = (float(value) for value in values)
    if not 0 <= left < right <= page_width:
        return None
    origin = getattr(getattr(bbox, "coord_origin", None), "value", getattr(bbox, "coord_origin", None))
    origin = str(origin).upper().rsplit(".", 1)[-1]
    if origin == "BOTTOMLEFT":
        if not 0 <= bottom < top <= page_height:
            return None
        physical_top = page_height - top
        physical_bottom = page_height - bottom
    elif origin == "TOPLEFT":
        if not 0 <= top < bottom <= page_height:
            return None
        physical_top = top
        physical_bottom = bottom
    else:
        return None
    span = list(getattr(source, "charspan", ()) or ())
    if len(span) != 2 or not all(isinstance(value, int) for value in span):
        return None
    expected_end = 0 if picture else len(getattr(item, "orig", ""))
    if span != [0, expected_end]:
        return None
    return page_no, physical_top, left, right, physical_bottom, page_width, page_height


def _physical_scanned_policy_markdown(document: object) -> str | None:
    """Serialize a provenance-complete, single-column scanned policy in physical order."""
    pages = getattr(document, "pages", None)
    texts = list(getattr(document, "texts", ()) or ())
    pictures = list(getattr(document, "pictures", ()) or ())
    if not pages or not texts:
        return None
    if any(
        getattr(document, collection, ())
        for collection in ("tables", "key_value_items", "form_items", "formulas", "codes")
    ):
        return None

    picture_child_refs: set[str] = set()
    positioned: list[tuple[int, float, float, float, float, float, float, str, bool, str, str]] = []
    for picture in pictures:
        position = _physical_item_position(picture, pages, picture=True)
        if position is None:
            return None
        for child in getattr(picture, "children", ()) or ():
            reference = (
                getattr(child, "cref", None)
                or getattr(child, "ref", None)
                or getattr(child, "$ref", None)
            )
            if not isinstance(reference, str) or not reference:
                return None
            picture_child_refs.add(reference)
        positioned.append((*position, "<!-- image -->", False, "picture", ""))

    section_headers = 0
    hierarchical_markers = 0
    for item in texts:
        if getattr(item, "self_ref", None) in picture_child_refs:
            continue
        if getattr(item, "children", ()):
            return None
        raw_label = getattr(item, "label", "")
        label = str(getattr(raw_label, "value", raw_label))
        if label not in _PHYSICAL_POLICY_TEXT_LABELS:
            return None
        text = getattr(item, "text", None)
        original = getattr(item, "orig", None)
        marker = getattr(item, "marker", "") or ""
        if not isinstance(text, str) or not text.strip() or not isinstance(original, str):
            return None
        if not isinstance(marker, str):
            return None
        if marker:
            if not original.startswith(marker) or original[len(marker):].lstrip() != text:
                return None
            rendered = text if text.lstrip().startswith(marker) else f"{marker} {text}"
            hierarchical_markers += bool(_HIERARCHICAL_MARKER.fullmatch(marker))
        else:
            if original != text:
                return None
            rendered = text
        if label == "section_header":
            section_headers += 1
            rendered = f"## {rendered}"
        position = _physical_item_position(item, pages)
        if position is None:
            return None
        _, physical_top, left, right, physical_bottom, _, _ = position
        stripped = text.strip()
        tiny_nonlexical = (
            len(stripped) <= 3
            and right - left <= 6
            and physical_bottom - physical_top <= 4
            and not any(char.isalnum() or char in _PROTECTED_MATH_SIGNS for char in stripped)
        )
        if tiny_nonlexical:
            codepoints = " ".join(f"U+{ord(char):04X}" for char in stripped)
            rendered = f"<!-- source-speck {codepoints} -->"
        positioned.append((*position, rendered, not tiny_nonlexical, label, marker))

    if section_headers == 0 or hierarchical_markers == 0:
        return None
    for index, first in enumerate(positioned):
        if not first[8]:
            continue
        for second in positioned[index + 1:]:
            if second[0] != first[0] or not second[8]:
                continue
            vertical_overlap = min(first[4], second[4]) - max(first[1], second[1])
            side_by_side = first[3] <= second[2] or second[3] <= first[2]
            if vertical_overlap > 0 and side_by_side:
                return None
    positioned.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    rendered_items: list[str] = []
    list_intro_active = False
    for entry in positioned:
        rendered, lexical, label, marker = entry[7:]
        if label == "section_header" or _HIERARCHICAL_MARKER.fullmatch(marker):
            list_intro_active = rendered.rstrip().endswith(":")
        elif lexical and label != "list_item":
            list_intro_active = False
        elif label == "list_item" and list_intro_active and not marker:
            # A native list child may have lost its visual dash during OCR.
            # Restore only Markdown structure under a source-explicit colon
            # introduction, never a fabricated ordinal or a new lexical word.
            if not re.match(r"^\s*[-—–*•‣]", rendered):
                rendered = f"- {rendered}"
        rendered_items.append(rendered)
    return "\n\n".join(rendered_items)


_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]\s*[-—–*]?\s*|[-—–*]\s*)")
_CONTINUATION_END = re.compile(r"\b(?:и|или|and|or|және|немесе)\s*$", re.IGNORECASE)
_OCR_BULLET_PREFIX = re.compile(r"^\s*[-—–*•‣]\s*")
_LETTER_TICK_DASH_PREFIX = re.compile(
    r"^(?P<noise>[^\W\d_])\s+[`´]\s*[-—–]\s*(?P<body>\S.*)$",
)
_LOW_QUOTE_PREFIX = re.compile(r"^(?P<noise>[„‚`´])\s*(?P<body>\S.*)$")
_QUOTE_CHARACTERS = frozenset("\"'«»“”„‟‚‘’‹›`´")


def _normalized_line(value: str) -> str:
    return " ".join(value.split()).casefold()


def _list_body(value: str) -> str:
    return _LIST_MARKER.sub("", value, count=1).strip()


def _margin_prefix_body(value: str) -> tuple[str, bool] | None:
    """Return the unchanged body and whether both OCR readings must show a bullet."""
    match = _LETTER_TICK_DASH_PREFIX.fullmatch(value)
    if match is not None:
        body = match.group("body").strip()
        return (body, True) if body else None
    match = _LOW_QUOTE_PREFIX.fullmatch(value)
    if match is None:
        return None
    body = match.group("body").strip()
    # A closing quote is evidence of quoted source prose, not margin noise.
    if not body or any(character in _QUOTE_CHARACTERS for character in body):
        return None
    return body, False


def _margin_anchor(value: str) -> tuple[str, ...]:
    words = tuple(re.findall(r"[^\W_]+", value.casefold()))
    if len(words) == 3:
        # A short candidate must match its complete lexical span in each OCR
        # reading; it is never reduced to a collision-prone prefix.
        return words
    return words[:6] if len(words) >= 4 else ()


def _list_margin_prefix_candidates(
    document: object, markdown: str,
) -> list[tuple[int, int, str, bool]]:
    """Map a suspicious list margin prefix to one exact, single-page source item."""
    pages = getattr(document, "pages", {}) or {}
    candidates: list[tuple[int, int, str, bool]] = []
    for line_index, line in enumerate(markdown.splitlines(keepends=True)):
        if not _LIST_MARKER.match(line):
            continue
        source_text = _list_body(line)
        repair = _margin_prefix_body(source_text)
        if repair is None:
            continue
        body, require_two_bullets = repair
        if not _margin_anchor(body):
            continue
        matches: list[tuple[object, tuple[int, float, float, float, float, float, float]]] = []
        for item in getattr(document, "texts", ()) or ():
            raw_label = getattr(item, "label", "")
            label = str(getattr(raw_label, "value", raw_label))
            if (
                label != "list_item"
                or getattr(item, "marker", "")
                or getattr(item, "text", None) != source_text
                or getattr(item, "orig", None) != source_text
            ):
                continue
            position = _physical_item_position(item, pages)
            if position is not None:
                matches.append((item, position))
        if len(matches) != 1:
            continue
        page_no = matches[0][1][0]
        candidates.append((line_index, page_no, body, require_two_bullets))
    return candidates


def _confirmed_margin_prefix(ocr: str, body: str) -> bool | None:
    """Return whether one uniquely matching OCR line has a real bullet."""
    anchor = _margin_anchor(body)
    if not anchor:
        return None
    matches: list[bool] = []
    for line in ocr.splitlines():
        stripped = line.strip()
        bullet = _OCR_BULLET_PREFIX.match(stripped)
        if bullet is not None:
            ocr_body = stripped[bullet.end():].strip()
            has_bullet = True
        else:
            quote = _LOW_QUOTE_PREFIX.fullmatch(stripped)
            if quote is None:
                continue
            ocr_body = quote.group("body").strip()
            has_bullet = False
        if _margin_anchor(ocr_body) == anchor:
            matches.append(has_bullet)
    return matches[0] if len(matches) == 1 else None


def _broken_list_continuations(markdown: str) -> list[tuple[int, str, str]]:
    """Locate only a short orphan between a dangling conjunction and a new item."""
    lines = markdown.splitlines(keepends=True)
    candidates: list[tuple[int, str, str]] = []
    nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    for position in range(1, len(nonempty_indexes) - 1):
        previous_index = nonempty_indexes[position - 1]
        index = nonempty_indexes[position]
        next_index = nonempty_indexes[position + 1]
        previous = _list_body(lines[previous_index])
        fragment = _list_body(lines[index])
        words = re.findall(r"[^\W\d_]+", fragment)
        if (
            _LIST_MARKER.match(lines[previous_index])
            and len(previous) >= 24 and _CONTINUATION_END.search(previous)
            and len(fragment) <= 16
            and len(words) == 1 and len(words[0]) <= 8 and not re.search(r"\d", fragment)
            and words[0].casefold() not in {"не", "нет", "not", "no"}
            and _LIST_MARKER.match(lines[next_index]) and len(_list_body(lines[next_index])) >= 12
        ):
            candidates.append((index, previous, fragment))
    return candidates


def _list_fragment_page(document: object, previous: str, fragment: str) -> int | None:
    previous_items: list[object] = []
    fragment_items: list[object] = []
    for item in getattr(document, "texts", ()) or ():
        text = getattr(item, "text", "")
        if not isinstance(text, str):
            continue
        normalized = _normalized_line(_list_body(text))
        if _normalized_line(previous) == normalized:
            previous_items.append(item)
        if re.findall(r"[^\W\d_]+", fragment.casefold()) == re.findall(r"[^\W\d_]+", _list_body(text).casefold()):
            fragment_items.append(item)
    if len(previous_items) != 1 or len(fragment_items) != 1:
        return None
    previous_pages = _page_nos(previous_items[0])
    fragment_pages = _page_nos(fragment_items[0])
    if len(previous_pages) != 1 or fragment_pages != previous_pages:
        return None
    page_no = next(iter(previous_pages))
    return page_no if page_no in (getattr(document, "pages", {}) or {}) else None


def _confirmed_list_continuation(ocr: str, previous: str) -> str | None:
    lines = [line for line in ocr.splitlines() if line.strip()]
    candidates: list[str] = []
    for index, line in enumerate(lines):
        if not _LIST_MARKER.match(line) or _normalized_line(_list_body(line)) != _normalized_line(previous):
            continue
        # Accept only the shape that triggered this check: one short orphan
        # between two list items. Never append arbitrary following paragraphs.
        if index + 2 >= len(lines) or not _LIST_MARKER.match(lines[index + 2]):
            continue
        text = lines[index + 1].strip()
        words = re.findall(r"[^\W\d_]+", text)
        if (
            not _LIST_MARKER.match(text) and len(text) <= 16
            and len(words) == 1 and len(words[0]) <= 8
            and words[0].casefold() not in {"не", "нет", "not", "no"}
            and not re.search(r"\d", text) and text.endswith((";", ".", ":"))
        ):
            candidates.append(text)
    return candidates[0] if len(candidates) == 1 else None


def _repair_scanned_pdf_list_boundaries(path: str, document: object, markdown: str) -> str:
    """Corroborate narrow list defects with two pixel readings; never guess."""
    orphan_candidates = _broken_list_continuations(markdown)
    margin_candidates = _list_margin_prefix_candidates(document, markdown)
    if not orphan_candidates and not margin_candidates:
        return markdown
    lines = markdown.splitlines(keepends=True)
    readings: dict[int, tuple[str, str] | None] = {}
    budget = {"pixels": 0.0, "deadline": time.monotonic() + 40}

    def page_readings(page_no: int) -> tuple[str, str] | None:
        if time.monotonic() >= budget["deadline"]:
            return None
        if page_no not in readings:
            if len(readings) >= 2:
                return None
            readings[page_no] = _independent_page_list_ocr(path, page_no, budget)
        return readings[page_no]

    for index, page_no, body, require_two_bullets in margin_candidates:
        ocr = page_readings(page_no)
        if ocr is None:
            continue
        first = _confirmed_margin_prefix(ocr[0], body)
        second = _confirmed_margin_prefix(ocr[1], body)
        if first is None or second is None or not (first or second):
            continue
        if require_two_bullets and not (first and second):
            continue
        newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
        lines[index] = "- " + body + newline

    for index, previous, fragment in orphan_candidates:
        if time.monotonic() >= budget["deadline"]:
            break
        page_no = _list_fragment_page(document, previous, fragment)
        if page_no is None:
            continue
        ocr = page_readings(page_no)
        if ocr is None:
            continue
        first, second = (_confirmed_list_continuation(text, previous) for text in ocr)
        if first is None or second is None or _normalized_line(first) != _normalized_line(second):
            continue
        word = "".join(re.findall(r"[^\W\d_]+", fragment))
        if re.search(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]", word) and len(word) > 3 and word.casefold() not in first.casefold():
            continue
        # Only this source-corroborated boundary changes. All unrelated bytes and
        # the complete existing body/conditions/numbers remain untouched.
        newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
        previous_index = next(
            (line_index for line_index in range(index - 1, -1, -1) if lines[line_index].strip()),
            None,
        )
        if previous_index is None:
            continue
        lines[previous_index] = "- " + previous + " " + first + newline
        lines[index] = ""
    return "".join(lines)


def _crosscheck_docling_percentages(path: str, document: object) -> None:
    slots_by_page: dict[int | None, list[object]] = {}
    for item, page_no in _percentage_text_slots(document):
        slots_by_page.setdefault(page_no, []).append(item)
    budget = {"pixels": 0.0, "deadline": time.monotonic() + PERCENTAGE_CROSSCHECK_TOTAL_TIMEOUT_SECONDS}
    for index, (page_no, items) in enumerate(slots_by_page.items()):
        ocr = None
        if page_no is not None and index < PERCENTAGE_CROSSCHECK_MAX_PAGES:
            ocr = _independent_page_percentage_ocr(path, page_no, budget)
        confirmed = set.intersection(*(_normalized_percentages(output) for output in ocr)) if ocr is not None else set()
        for item in items:
            item.text = _mask_unconfirmed_percentages(item.text, confirmed)


def _percentage_crosscheck_warnings(markdown: str) -> list[str]:
    if UNREADABLE_PERCENTAGE_VALUE not in markdown:
        return []
    return [
        "Some percentage values are marked unreadable because independent page OCR did not confirm them."
    ]


def _docling_convert(path: str) -> tuple[str, int, int]:
    result = get_converter().convert(path)
    document = getattr(result, "document", None)
    if document is not None and _SCANNED_PDF_PERCENTAGE_CROSSCHECK.get():
        _crosscheck_docling_percentages(path, document)
    markdown = document.export_to_markdown() if document is not None else str(result)
    if document is not None and _SCANNED_PDF_PERCENTAGE_CROSSCHECK.get():
        physical_markdown = _physical_scanned_policy_markdown(document)
        if physical_markdown is not None:
            markdown = physical_markdown
    # Docling's Markdown serializer escapes brackets/underscores in text items.
    # Keep the machine-readable uncertainty token stable across that boundary.
    markdown = re.sub(r"\\?\[UNREADABLE\\?_PERCENTAGE\\?_VALUE\\?\]", UNREADABLE_PERCENTAGE_VALUE, markdown)
    if document is not None and _SCANNED_PDF_PERCENTAGE_CROSSCHECK.get():
        markdown = _repair_scanned_pdf_list_boundaries(path, document, markdown)
    if not _usable_markdown(markdown):
        raise ValueError("Docling returned unusable output")
    tables = len(getattr(document, "tables", [])) if document is not None else 0
    pages = len(getattr(document, "pages", [])) if document is not None else 0
    return markdown, pages, tables


def _profile_pdf(path: str) -> dict[str, Any]:
    """Classify a PDF without initializing Docling or rendering page images."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(path, strict=False)
        page_count = len(reader.pages)
        sample_count = min(PDF_SAMPLE_PAGES, page_count)
        if sample_count == 0:
            return {
                "profile": "unknown",
                "is_digital": False,
                "pages": 0,
                "sample_pages": 0,
                "text_pages": 0,
                "embedded_chars": 0,
                "routing_reason": "pdf-empty",
            }

        text_pages = 0
        embedded_chars = 0
        for page in reader.pages[:sample_count]:
            text = page.extract_text() or ""
            meaningful = sum(char.isalnum() for char in text)
            embedded_chars += meaningful
            if meaningful >= PDF_MIN_EMBEDDED_TEXT_CHARS:
                text_pages += 1

        ratio = text_pages / sample_count
        is_digital = (
            ratio >= PDF_MIN_TEXT_PAGE_RATIO
            and embedded_chars >= PDF_MIN_EMBEDDED_TEXT_CHARS
        )
        return {
            "profile": "digital_text" if is_digital else "scanned_or_low_text",
            "is_digital": is_digital,
            "pages": page_count,
            "sample_pages": sample_count,
            "text_pages": text_pages,
            "embedded_chars": embedded_chars,
            "routing_reason": "embedded-text-sufficient"
            if is_digital
            else "embedded-text-insufficient",
        }
    except Exception as exc:  # noqa: BLE001 - malformed PDFs must fall through to Docling
        logger.info("PDF preflight unavailable for %s: %s", path, exc)
        return {
            "profile": "unknown",
            "is_digital": False,
            "pages": 0,
            "sample_pages": 0,
            "text_pages": 0,
            "embedded_chars": 0,
            "routing_reason": "pdf-preflight-unavailable",
        }


def _payload(
    *,
    filename: str,
    markdown: str,
    engine: str,
    engine_version: str | None,
    pages: int = 0,
    tables: int = 0,
    fallback_used: bool = False,
    warnings: list[str] | None = None,
    profile: str | None = None,
    routing_reason: str | None = None,
) -> dict:
    return {
        "markdown": markdown,
        "pages": pages,
        "tables": tables,
        "filename": filename,
        "engine": engine,
        "engine_version": engine_version,
        "fallback_used": fallback_used,
        "warnings": warnings or [],
        "profile": profile,
        "routing_reason": routing_reason,
    }


def _convert_sync(*, tmp_path: str, filename: str, suffix: str) -> dict:
    """Run all blocking conversion work in a worker thread."""
    conversion_dir: str | None = None
    try:
        conversion_input = tmp_path
        warnings: list[str] = []
        if suffix == ".doc":
            libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
            if not libreoffice:
                raise HTTPException(
                    status_code=503,
                    detail="Legacy DOC conversion is unavailable on this server",
                )
            conversion_dir = tempfile.mkdtemp(prefix="docling-docx-")
            try:
                # LibreOffice otherwise resolves the container user's passwd
                # home (/nonexistent) and fails before conversion while trying
                # to create its per-user profile.  A unique profile inside the
                # already isolated conversion directory also prevents parallel
                # requests from sharing lock/state files.
                user_installation = (Path(conversion_dir) / "lo-profile").as_uri()
                process = subprocess.run(
                    [
                        libreoffice,
                        f"-env:UserInstallation={user_installation}",
                        "--headless",
                        "--convert-to",
                        "docx",
                        "--outdir",
                        conversion_dir,
                        tmp_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=LEGACY_DOC_TIMEOUT_SECONDS,
                    check=False,
                )
                candidate = Path(conversion_dir) / f"{Path(tmp_path).stem}.docx"
                if process.returncode != 0 or not candidate.exists():
                    logger.error(
                        "Legacy DOC conversion failed returncode=%s stderr=%s",
                        process.returncode,
                        process.stderr[-500:],
                    )
                    raise HTTPException(
                        status_code=422,
                        detail="The legacy DOC file could not be converted to DOCX",
                    )
                preflight_ooxml(str(candidate), ".docx")
                conversion_input = str(candidate)
                warnings.append("Legacy DOC pre-converted to DOCX with LibreOffice.")
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(
                    status_code=504, detail="Legacy DOC conversion timed out"
                ) from exc

        office_route = suffix in MARKITDOWN_OFFICE_EXTENSIONS or suffix == ".doc"
        if office_route:
            try:
                return _payload(
                    filename=filename,
                    markdown=_markitdown_convert(conversion_input),
                    engine="markitdown",
                    engine_version=_package_version("markitdown") or MARKITDOWN_VERSION,
                    warnings=warnings,
                    profile="office",
                    routing_reason="office-markitdown-primary",
                )
            except Exception as primary_error:  # noqa: BLE001 - provider fallback boundary
                logger.warning(
                    "MarkItDown primary conversion failed for %s: %s",
                    filename,
                    primary_error,
                )
                try:
                    markdown, pages, tables = _docling_convert(conversion_input)
                    return _payload(
                        filename=filename,
                        markdown=markdown,
                        engine="docling",
                        engine_version=_package_version("docling"),
                        pages=pages,
                        tables=tables,
                        fallback_used=True,
                        warnings=warnings
                        + [
                            "MarkItDown primary conversion failed; Docling fallback used."
                        ],
                        profile="office",
                        routing_reason="office-docling-fallback",
                    )
                except Exception:
                    logger.exception(
                        "Office conversion failed after MarkItDown primary for %s",
                        filename,
                    )
                    raise HTTPException(
                        status_code=422, detail="Document could not be converted"
                    ) from primary_error

        profile = (
            _profile_pdf(conversion_input)
            if suffix == ".pdf"
            else {
                "profile": "ocr_document"
                if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
                else "document",
                "is_digital": False,
                "pages": 0,
                "routing_reason": "docling-primary",
            }
        )

        if suffix == ".pdf" and profile["is_digital"]:
            try:
                return _payload(
                    filename=filename,
                    markdown=_markitdown_convert(conversion_input),
                    engine="markitdown",
                    engine_version=_package_version("markitdown") or MARKITDOWN_VERSION,
                    pages=profile["pages"],
                    warnings=warnings,
                    profile=profile["profile"],
                    routing_reason="digital-pdf-markitdown-primary",
                )
            except Exception as primary_error:  # noqa: BLE001 - provider fallback boundary
                logger.warning(
                    "MarkItDown digital PDF route failed for %s: %s",
                    filename,
                    primary_error,
                )
                try:
                    markdown, pages, tables = _docling_convert(conversion_input)
                    return _payload(
                        filename=filename,
                        markdown=markdown,
                        engine="docling",
                        engine_version=_package_version("docling"),
                        pages=pages or profile["pages"],
                        tables=tables,
                        fallback_used=True,
                        warnings=warnings
                        + [
                            "MarkItDown digital PDF route failed; Docling fallback used."
                        ],
                        profile=profile["profile"],
                        routing_reason="digital-pdf-docling-fallback",
                    )
                except Exception:
                    logger.exception(
                        "Digital PDF conversion failed after MarkItDown route for %s",
                        filename,
                    )
                    raise HTTPException(
                        status_code=422, detail="Document could not be converted"
                    ) from primary_error

        try:
            if suffix == ".pdf" and not profile.get("is_digital", False):
                with _scanned_pdf_percentage_crosscheck():
                    markdown, pages, tables = _docling_convert(conversion_input)
            else:
                markdown, pages, tables = _docling_convert(conversion_input)
            return _payload(
                filename=filename,
                markdown=markdown,
                engine="docling",
                engine_version=_package_version("docling"),
                pages=pages or profile.get("pages", 0),
                tables=tables,
                warnings=warnings + _percentage_crosscheck_warnings(markdown) + (
                    ["Some OCR list boundaries could not be corroborated by independent page readings."]
                    if suffix == ".pdf" and not profile.get("is_digital", False)
                    and _broken_list_continuations(markdown) else []
                ),
                profile=profile.get("profile"),
                routing_reason="scanned-pdf-docling-ocr"
                if suffix == ".pdf"
                else profile.get("routing_reason"),
            )
        except Exception as docling_error:
            logger.warning(
                "Docling primary conversion failed for %s: %s", filename, docling_error
            )
            if suffix not in MARKITDOWN_DIGITAL_FALLBACK_EXTENSIONS:
                logger.exception("Document conversion failed for %s", filename)
                raise HTTPException(
                    status_code=422, detail="Document could not be converted"
                ) from docling_error
            try:
                return _payload(
                    filename=filename,
                    markdown=_markitdown_convert(conversion_input),
                    engine="markitdown",
                    engine_version=_package_version("markitdown") or MARKITDOWN_VERSION,
                    fallback_used=True,
                    warnings=warnings
                    + [
                        "Degraded fallback: Docling failed; MarkItDown handled digital text only. OCR, layout, and table fidelity may be reduced."
                    ],
                    profile=profile.get("profile"),
                    routing_reason="docling-failed-markitdown-degraded-fallback",
                )
            except Exception as fallback_error:
                logger.exception(
                    "Document conversion failed after fallback for %s", filename
                )
                raise HTTPException(
                    status_code=422, detail="Document could not be converted"
                ) from fallback_error
    finally:
        if conversion_dir:
            shutil.rmtree(conversion_dir, ignore_errors=True)


async def _save_upload(file: UploadFile, suffix: str) -> str:
    """Stream an upload to disk so queued requests do not accumulate in RAM."""
    tmp_path: str | None = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Document exceeds the {MAX_UPLOAD_BYTES} byte upload limit",
                    )
                tmp.write(chunk)
        return tmp_path
    except Exception:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
        raise


async def _acquire_conversion_slot() -> None:
    try:
        await asyncio.wait_for(
            _conversion_slots.acquire(), timeout=QUEUE_WAIT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="Document converter is busy; retry later",
            headers={"Retry-After": str(max(1, math.ceil(QUEUE_WAIT_TIMEOUT_SECONDS)))},
        ) from exc


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "docling",
        "routing_version": ROUTING_VERSION,
        "engines": {
            "docling": _package_version("docling"),
            "markitdown": _package_version("markitdown"),
            "libreoffice": bool(shutil.which("libreoffice") or shutil.which("soffice")),
        },
        "ocr": {"enabled": True, "engine": "tesseract-cli", "languages": OCR_LANGUAGES},
        "limits": {
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "max_concurrency": MAX_CONCURRENCY,
            "queue_wait_timeout_seconds": QUEUE_WAIT_TIMEOUT_SECONDS,
        },
    }


@app.post("/convert")
async def convert_document(
    file: Annotated[UploadFile, File()],
    x_docling_key: Annotated[str | None, Header()] = None,
):
    """Convert uploaded document while keeping the event loop responsive."""
    if not DOCLING_API_KEY or (
        x_docling_key is None
        or not secrets.compare_digest(x_docling_key, DOCLING_API_KEY)
    ):
        raise HTTPException(status_code=401, detail="Invalid Docling API key")

    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower() or ".pdf"
    tmp_path: str | None = None
    acquired = False
    try:
        tmp_path = await _save_upload(file, suffix)
        preflight_ooxml(tmp_path, suffix)
        await _acquire_conversion_slot()
        acquired = True
        payload = await asyncio.to_thread(
            _convert_sync, tmp_path=tmp_path, filename=filename, suffix=suffix
        )
        return JSONResponse(payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Conversion failed for %s", filename)
        raise HTTPException(
            status_code=500, detail="Document conversion failed"
        ) from exc
    finally:
        if acquired:
            _conversion_slots.release()
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8600)
