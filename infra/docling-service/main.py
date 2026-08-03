"""Local document converter service running on the VPS."""

import logging
import os
import secrets
import shutil
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docling-service")

app = FastAPI(title="Document Converter", version="1.1")

# Lazy load converter
_converter = None
_markitdown_converter = None
MARKITDOWN_VERSION = "0.1.6"
MARKITDOWN_OFFICE_EXTENSIONS = {".docx", ".xls", ".xlsx"}
# MarkItDown's non-OCR PDF path is an allowed degraded fallback. Images stay
# Docling-only because sending them through MarkItDown would not provide OCR.
MARKITDOWN_DIGITAL_FALLBACK_EXTENSIONS = {".pdf"}
OCR_LANGUAGES = [
    language.strip() for language in os.getenv("DOCLING_OCR_LANGUAGES", "kaz,rus,eng").split(",") if language.strip()
]
DOCLING_API_KEY = os.getenv("DOCLING_API_KEY", "")
LEGACY_DOC_TIMEOUT_SECONDS = int(os.getenv("DOCLING_LEGACY_DOC_TIMEOUT_SECONDS", "120"))


def get_converter():
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TesseractCliOcrOptions,
        )
        from docling.document_converter import (
            DocumentConverter as DoclingConverter,
        )
        from docling.document_converter import (
            PdfFormatOption,
        )

        pdf_options = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            ocr_options=TesseractCliOcrOptions(
                lang=OCR_LANGUAGES,
            ),
        )
        _converter = DoclingConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
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
        logger.info("MarkItDown converter loaded (version=%s, plugins=disabled)", MARKITDOWN_VERSION)
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
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "docling",
        "routing_version": "1.1",
        "engines": {
            "docling": _package_version("docling"),
            "markitdown": _package_version("markitdown"),
            "libreoffice": bool(shutil.which("libreoffice") or shutil.which("soffice")),
        },
        "ocr": {
            "enabled": True,
            "engine": "tesseract-cli",
            "languages": OCR_LANGUAGES,
        },
    }


@app.post("/convert")
async def convert_document(
    file: Annotated[UploadFile, File()],
    x_docling_key: Annotated[str | None, Header()] = None,
):
    """Convert uploaded document to markdown."""
    if DOCLING_API_KEY and (x_docling_key is None or not secrets.compare_digest(x_docling_key, DOCLING_API_KEY)):
        raise HTTPException(status_code=401, detail="Invalid Docling API key")

    suffix = Path(file.filename or "doc").suffix.lower() or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    converted_path: str | None = None
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
                converted_path = str(candidate)
                conversion_input = converted_path
                warnings.append("Legacy DOC pre-converted to DOCX with LibreOffice.")
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(
                    status_code=504,
                    detail="Legacy DOC conversion timed out",
                ) from exc

        office_route = suffix in MARKITDOWN_OFFICE_EXTENSIONS or suffix == ".doc"
        primary_error: Exception | None = None

        if office_route:
            try:
                markdown = _markitdown_convert(conversion_input)
                return JSONResponse(
                    _payload(
                        filename=file.filename or "document",
                        markdown=markdown,
                        engine="markitdown",
                        engine_version=_package_version("markitdown") or MARKITDOWN_VERSION,
                        warnings=warnings,
                    )
                )
            except Exception as exc:
                primary_error = exc
                logger.warning("MarkItDown primary conversion failed for %s: %s", file.filename, exc)

            try:
                markdown, pages, tables = _docling_convert(conversion_input)
                fallback_warnings = warnings + [
                    "MarkItDown primary conversion failed; Docling fallback used.",
                ]
                return JSONResponse(
                    _payload(
                        filename=file.filename or "document",
                        markdown=markdown,
                        engine="docling",
                        engine_version=_package_version("docling"),
                        pages=pages,
                        tables=tables,
                        fallback_used=True,
                        warnings=fallback_warnings,
                    )
                )
            except Exception:
                logger.exception("Office conversion failed after MarkItDown primary for %s", file.filename)
                raise HTTPException(status_code=422, detail="Document could not be converted") from primary_error

        try:
            markdown, pages, tables = _docling_convert(conversion_input)
            return JSONResponse(
                _payload(
                    filename=file.filename or "document",
                    markdown=markdown,
                    engine="docling",
                    engine_version=_package_version("docling"),
                    pages=pages,
                    tables=tables,
                    warnings=warnings,
                )
            )
        except Exception as docling_error:
            logger.warning("Docling primary conversion failed for %s: %s", file.filename, docling_error)
            if suffix not in MARKITDOWN_DIGITAL_FALLBACK_EXTENSIONS:
                logger.exception("Document conversion failed for %s", file.filename)
                raise HTTPException(status_code=422, detail="Document could not be converted") from docling_error
            try:
                markdown = _markitdown_convert(conversion_input)
                return JSONResponse(
                    _payload(
                        filename=file.filename or "document",
                        markdown=markdown,
                        engine="markitdown",
                        engine_version=_package_version("markitdown") or MARKITDOWN_VERSION,
                        fallback_used=True,
                        warnings=warnings
                        + [
                            "Degraded fallback: Docling failed; MarkItDown handled digital text only. OCR, layout, and table fidelity may be reduced.",
                        ],
                    )
                )
            except Exception as fallback_error:
                logger.exception("Document conversion failed after fallback for %s", file.filename)
                raise HTTPException(status_code=422, detail="Document could not be converted") from fallback_error
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Conversion failed for %s", file.filename)
        raise HTTPException(status_code=500, detail="Document conversion failed") from e
    finally:
        os.unlink(tmp_path)
        if conversion_dir:
            shutil.rmtree(conversion_dir, ignore_errors=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8600)
