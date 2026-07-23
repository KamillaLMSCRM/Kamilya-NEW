from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


SERVICE_PATH = (
    Path(__file__).resolve().parents[4] / "infra" / "docling-service" / "main.py"
)


def _load_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DOCLING_OCR_LANGUAGES", raising=False)
    spec = importlib.util.spec_from_file_location("docling_service_main_test", SERVICE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pdf_converter_enables_multilingual_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)

    base_models = ModuleType("docling.datamodel.base_models")
    pipeline_options = ModuleType("docling.datamodel.pipeline_options")
    document_converter = ModuleType("docling.document_converter")

    class InputFormat:
        PDF = "pdf"

    class EasyOcrOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class PdfPipelineOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class PdfFormatOption:
        def __init__(self, *, pipeline_options):
            self.pipeline_options = pipeline_options

    class DocumentConverter:
        def __init__(self, *, format_options):
            self.format_options = format_options

    base_models.InputFormat = InputFormat
    pipeline_options.EasyOcrOptions = EasyOcrOptions
    pipeline_options.PdfPipelineOptions = PdfPipelineOptions
    document_converter.DocumentConverter = DocumentConverter
    document_converter.PdfFormatOption = PdfFormatOption

    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter)

    converter = service.get_converter()
    pdf_options = converter.format_options[InputFormat.PDF].pipeline_options

    assert pdf_options.kwargs["do_ocr"] is True
    assert pdf_options.kwargs["do_table_structure"] is True
    assert pdf_options.kwargs["ocr_options"].kwargs == {
        "lang": ["ru", "en"],
        "download_enabled": True,
    }


@pytest.mark.asyncio
async def test_health_reports_ocr_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)

    assert await service.health() == {
        "status": "ok",
        "service": "docling",
        "ocr": {
            "enabled": True,
            "engine": "easyocr",
            "languages": ["ru", "en"],
        },
    }
