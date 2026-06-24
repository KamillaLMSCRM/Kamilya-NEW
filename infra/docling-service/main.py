"""Docling microservice — runs on VPS as HTTP API."""
import os
import tempfile
import logging
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docling-service")

app = FastAPI(title="Docling Converter", version="1.0")

# Lazy load converter
_converter = None


def get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter as DoclingConverter
        _converter = DoclingConverter()
        logger.info("Docling converter loaded")
    return _converter


@app.get("/health")
async def health():
    return {"status": "ok", "service": "docling"}


@app.post("/convert")
async def convert_document(file: UploadFile = File(...)):
    """Convert uploaded document to markdown."""
    suffix = Path(file.filename or "doc").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        converter = get_converter()
        result = converter.convert(tmp_path)

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
    except Exception as e:
        logger.exception(f"Conversion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8600)
