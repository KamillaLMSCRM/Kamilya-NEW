"""Docling microservice — runs on VPS as HTTP API."""
import os
import secrets
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docling-service")

app = FastAPI(title="Docling Converter", version="1.0")

# Lazy load converter
_converter = None
OCR_LANGUAGES = [
    language.strip()
    for language in os.getenv("DOCLING_OCR_LANGUAGES", "kaz,rus,eng").split(",")
    if language.strip()
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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "docling",
        "ocr": {
            "enabled": True,
            "engine": "tesseract-cli",
            "languages": OCR_LANGUAGES,
        },
    }


@app.post("/convert")
async def convert_document(
    file: UploadFile = File(...),
    x_docling_key: str | None = Header(default=None),
):
    """Convert uploaded document to markdown."""
    if DOCLING_API_KEY and (
        x_docling_key is None
        or not secrets.compare_digest(x_docling_key, DOCLING_API_KEY)
    ):
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
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(
                    status_code=504,
                    detail="Legacy DOC conversion timed out",
                ) from exc

        converter = get_converter()
        result = converter.convert(conversion_input)

        md = result.document.export_to_markdown() if hasattr(result, "document") else str(result)

        # Count tables if possible
        tables = 0
        pages = 0
        if hasattr(result, "document") and hasattr(result.document, "tables"):
            tables = len(result.document.tables)
        if hasattr(result, "document") and hasattr(result.document, "pages"):
            pages = len(result.document.pages)

        return JSONResponse({
            "markdown": md,
            "pages": pages,
            "tables": tables,
            "filename": file.filename,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Conversion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)
        if conversion_dir:
            shutil.rmtree(conversion_dir, ignore_errors=True)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8600)
