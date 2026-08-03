from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest
from starlette.datastructures import UploadFile

SERVICE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docling-service" / "main.py"


def _load_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DOCLING_OCR_LANGUAGES", raising=False)
    monkeypatch.delenv("DOCLING_API_KEY", raising=False)
    for name in (
        "CONVERTER_MAX_UPLOAD_BYTES",
        "CONVERTER_MAX_CONCURRENCY",
        "CONVERTER_QUEUE_WAIT_TIMEOUT_SECONDS",
        "CONVERTER_UPLOAD_CHUNK_BYTES",
        "CONVERTER_PDF_SAMPLE_PAGES",
        "CONVERTER_PDF_MIN_EMBEDDED_TEXT_CHARS",
        "CONVERTER_PDF_MIN_TEXT_PAGE_RATIO",
    ):
        monkeypatch.delenv(name, raising=False)
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

    class TesseractCliOcrOptions:
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
    pipeline_options.TesseractCliOcrOptions = TesseractCliOcrOptions
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
        "lang": ["kaz", "rus", "eng"],
    }


@pytest.mark.asyncio
async def test_health_reports_ocr_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(service, "_package_version", lambda name: f"{name}-version")
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/libreoffice")

    assert await service.health() == {
        "status": "ok",
        "service": "docling",
        "routing_version": "1.2",
        "engines": {
            "docling": "docling-version",
            "markitdown": "markitdown-version",
            "libreoffice": True,
        },
        "ocr": {
            "enabled": True,
            "engine": "tesseract-cli",
            "languages": ["kaz", "rus", "eng"],
        },
        "limits": {
            "max_upload_bytes": 50 * 1024 * 1024,
            "max_concurrency": 1,
            "queue_wait_timeout_seconds": 30.0,
        },
    }


@pytest.mark.asyncio
async def test_convert_rejects_invalid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCLING_API_KEY", "expected-key")
    spec = importlib.util.spec_from_file_location("docling_service_main_auth_test", SERVICE_PATH)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)

    with pytest.raises(service.HTTPException) as exc_info:
        await service.convert_document(file=None, x_docling_key="wrong-key")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_convert_legacy_doc_uses_libreoffice_before_docling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    converted_inputs: list[Path] = []

    class Completed:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        output_dir = Path(args[args.index("--outdir") + 1])
        source = Path(args[-1])
        (output_dir / f"{source.stem}.docx").write_bytes(b"PK converted")
        return Completed()

    class Document:
        tables = []
        pages = {1: object()}

        def export_to_markdown(self):
            return "# Expert appraiser"

    class Converter:
        def convert(self, path):
            converted_inputs.append(Path(path))
            return type("Result", (), {"document": Document()})()

    monkeypatch.setattr(service.shutil, "which", lambda command: "/usr/bin/libreoffice")
    monkeypatch.setattr(service.subprocess, "run", fake_run)
    monkeypatch.setattr(service, "get_converter", lambda: Converter())

    response = await service.convert_document(
        file=UploadFile(filename="expert.doc", file=io.BytesIO(b"legacy-doc")),
        x_docling_key=None,
    )
    payload = json.loads(response.body)

    assert payload["markdown"] == "# Expert appraiser"
    assert payload["pages"] == 1
    assert len(converted_inputs) == 1
    assert converted_inputs[0].suffix == ".docx"
    assert not converted_inputs[0].exists()


@pytest.mark.asyncio
async def test_convert_legacy_doc_fails_honestly_without_libreoffice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(service.shutil, "which", lambda command: None)

    with pytest.raises(service.HTTPException) as exc_info:
        await service.convert_document(
            file=UploadFile(filename="expert.doc", file=io.BytesIO(b"legacy-doc")),
            x_docling_key=None,
        )

    assert exc_info.value.status_code == 503


def test_markitdown_is_local_only_and_plugins_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    markitdown = ModuleType("markitdown")
    captured: dict[str, object] = {}

    class MarkItDown:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    markitdown.MarkItDown = MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", markitdown)
    service._markitdown_converter = None

    service.get_markitdown_converter()

    assert captured == {"enable_plugins": False}


@pytest.mark.asyncio
async def test_docx_uses_markitdown_primary_and_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(service, "_markitdown_convert", lambda path: "# Office document")

    response = await service.convert_document(
        file=UploadFile(filename="policy.docx", file=io.BytesIO(b"docx")),
        x_docling_key=None,
    )
    payload = json.loads(response.body)

    assert payload["markdown"] == "# Office document"
    assert payload["engine"] == "markitdown"
    assert payload["engine_version"] == "0.1.6"
    assert payload["fallback_used"] is False
    assert payload["warnings"] == []


@pytest.mark.asyncio
async def test_docx_falls_back_to_docling_without_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(
        service,
        "_markitdown_convert",
        lambda path: (_ for _ in ()).throw(RuntimeError("private parser detail")),
    )
    monkeypatch.setattr(service, "_docling_convert", lambda path: ("# Fallback", 2, 1))

    response = await service.convert_document(
        file=UploadFile(filename="policy.xlsx", file=io.BytesIO(b"xlsx")),
        x_docling_key=None,
    )
    payload = json.loads(response.body)

    assert payload["engine"] == "docling"
    assert payload["fallback_used"] is True
    assert payload["pages"] == 2
    assert payload["tables"] == 1
    assert "private parser detail" not in json.dumps(payload)
    assert payload["warnings"] == ["MarkItDown primary conversion failed; Docling fallback used."]


@pytest.mark.asyncio
async def test_digital_pdf_uses_markitdown_without_docling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(
        service,
        "_profile_pdf",
        lambda path: {
            "profile": "digital_text",
            "is_digital": True,
            "pages": 2,
            "routing_reason": "embedded-text-sufficient",
        },
    )
    monkeypatch.setattr(service, "_markitdown_convert", lambda path: "# Digital text")
    monkeypatch.setattr(
        service, "_docling_convert", lambda path: (_ for _ in ()).throw(AssertionError("Docling must not run"))
    )

    response = await service.convert_document(
        file=UploadFile(filename="policy.pdf", file=io.BytesIO(b"pdf")),
        x_docling_key=None,
    )
    payload = json.loads(response.body)

    assert payload["engine"] == "markitdown"
    assert payload["fallback_used"] is False
    assert payload["profile"] == "digital_text"
    assert payload["routing_reason"] == "digital-pdf-markitdown-primary"


@pytest.mark.asyncio
async def test_scanned_pdf_uses_docling_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(
        service,
        "_profile_pdf",
        lambda path: {
            "profile": "scanned_or_low_text",
            "is_digital": False,
            "pages": 3,
            "routing_reason": "embedded-text-insufficient",
        },
    )
    monkeypatch.setattr(service, "_docling_convert", lambda path: ("# OCR text", 3, 1))
    monkeypatch.setattr(
        service, "_markitdown_convert", lambda path: (_ for _ in ()).throw(AssertionError("fallback must not run"))
    )

    response = await service.convert_document(
        file=UploadFile(filename="scan.pdf", file=io.BytesIO(b"pdf")),
        x_docling_key=None,
    )
    payload = json.loads(response.body)

    assert payload["engine"] == "docling"
    assert payload["profile"] == "scanned_or_low_text"
    assert payload["routing_reason"] == "scanned-pdf-docling-ocr"


def test_pdf_profile_uses_embedded_text_without_docling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _load_service(monkeypatch)
    fake_pypdf = ModuleType("pypdf")

    class Page:
        def __init__(self, text: str):
            self.text = text

        def extract_text(self):
            return self.text

    class PdfReader:
        def __init__(self, path, strict=False):
            self.pages = [Page("Embedded policy text " * 10), Page("Embedded policy text " * 10)]

    fake_pypdf.PdfReader = PdfReader
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    pdf_path = tmp_path / "digital.pdf"
    pdf_path.write_bytes(b"not parsed by fake reader")

    profile = service._profile_pdf(str(pdf_path))

    assert profile["is_digital"] is True
    assert profile["profile"] == "digital_text"
    assert profile["pages"] == 2
    assert profile["routing_reason"] == "embedded-text-sufficient"


@pytest.mark.asyncio
async def test_upload_size_limit_returns_413_and_cleans_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 3)

    with pytest.raises(service.HTTPException) as exc_info:
        await service.convert_document(
            file=UploadFile(filename="large.txt", file=io.BytesIO(b"1234")),
            x_docling_key=None,
        )

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_conversion_queue_timeout_returns_503_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    service._conversion_slots = asyncio.Semaphore(0)
    monkeypatch.setattr(service, "QUEUE_WAIT_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(service.HTTPException) as exc_info:
        await service.convert_document(
            file=UploadFile(filename="queued.txt", file=io.BytesIO(b"queued")),
            x_docling_key=None,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "1"}


@pytest.mark.asyncio
async def test_blocking_conversion_runs_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _load_service(monkeypatch)
    started = threading.Event()

    def slow_conversion(**kwargs):
        started.set()
        time.sleep(0.05)
        return service._payload(
            filename=kwargs["filename"],
            markdown="# Converted",
            engine="markitdown",
            engine_version="0.1.6",
        )

    monkeypatch.setattr(service, "_convert_sync", slow_conversion)
    conversion = asyncio.create_task(
        service.convert_document(
            file=UploadFile(filename="policy.docx", file=io.BytesIO(b"docx")),
            x_docling_key=None,
        )
    )
    assert await asyncio.to_thread(started.wait, 1) is True

    health_payload = await service.health()
    await conversion

    assert health_payload["status"] == "ok"


@pytest.mark.asyncio
async def test_pdf_markitdown_fallback_is_marked_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    monkeypatch.setattr(
        service,
        "_docling_convert",
        lambda path: (_ for _ in ()).throw(RuntimeError("ocr unavailable")),
    )
    monkeypatch.setattr(service, "_markitdown_convert", lambda path: "digital text")

    response = await service.convert_document(
        file=UploadFile(filename="digital.pdf", file=io.BytesIO(b"pdf")),
        x_docling_key=None,
    )
    payload = json.loads(response.body)

    assert payload["engine"] == "markitdown"
    assert payload["fallback_used"] is True
    assert payload["warnings"] == [
        "Degraded fallback: Docling failed; MarkItDown handled digital text only. OCR, layout, and table fidelity may be reduced."
    ]


@pytest.mark.asyncio
async def test_failed_conversion_has_safe_error_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _load_service(monkeypatch)
    paths: list[Path] = []

    def fail(path):
        paths.append(Path(path))
        raise RuntimeError("traceback must not reach client")

    monkeypatch.setattr(service, "_docling_convert", fail)

    with pytest.raises(service.HTTPException) as exc_info:
        await service.convert_document(
            file=UploadFile(filename="notes.txt", file=io.BytesIO(b"not sent to service")),
            x_docling_key=None,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Document could not be converted"
    assert paths and not paths[0].exists()
