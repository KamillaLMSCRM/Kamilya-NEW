"""Local document converter service running on the VPS."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import secrets
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile
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


def validate_runtime_config(environment: str = DOCLING_ENV, api_key: str = DOCLING_API_KEY) -> None:
    if environment == "production" and len(api_key) < 32:
        raise RuntimeError("DOCLING_API_KEY must contain at least 32 characters in production")


validate_runtime_config()

# One process should own the Docling models on a small VPS. A semaphore keeps
# requests asynchronous while preventing concurrent model-sized allocations.
_conversion_slots = asyncio.Semaphore(MAX_CONCURRENCY)

_converter = None
_markitdown_converter = None


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
    return markdown


def _docling_convert(path: str) -> tuple[str, int, int]:
    result = get_converter().convert(path)
    document = getattr(result, "document", None)
    markdown = document.export_to_markdown() if document is not None else str(result)
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
                process = subprocess.run(
                    [
                        libreoffice,
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
            markdown, pages, tables = _docling_convert(conversion_input)
            return _payload(
                filename=filename,
                markdown=markdown,
                engine="docling",
                engine_version=_package_version("docling"),
                pages=pages or profile.get("pages", 0),
                tables=tables,
                warnings=warnings,
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
