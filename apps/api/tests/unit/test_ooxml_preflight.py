from __future__ import annotations

import io
import zipfile

import pytest

from app.core.storage import LocalStorageBackend
from app.modules.documents.archive_preflight import (
    ArchiveBudget,
    ArchivePreflightError,
    _safe_member_name,
    preflight_ooxml,
)


def _archive(entries: dict[str, bytes]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(zipfile.ZipInfo(name), content, compress_type=zipfile.ZIP_DEFLATED)
    buffer.seek(0)
    return buffer


def test_preflight_accepts_minimal_docx_and_xlsx():
    docx = _archive({"[Content_Types].xml": b"types", "word/document.xml": b"document"})
    xlsx = _archive({"[Content_Types].xml": b"types", "xl/workbook.xml": b"workbook"})

    assert preflight_ooxml(docx, ".docx").entry_count == 2
    assert preflight_ooxml(xlsx, ".xlsx").entry_count == 2


@pytest.mark.parametrize("name", ["../escape.xml", "/absolute.xml"])
def test_preflight_rejects_unsafe_archive_paths(name: str):
    payload = _archive({"[Content_Types].xml": b"types", "word/document.xml": b"ok", name: b"bad"})

    with pytest.raises(ArchivePreflightError, match="path"):
        preflight_ooxml(payload, ".docx")


def test_preflight_rejects_windows_style_archive_path():
    assert _safe_member_name("word\\document.xml", max_length=512) is False


def test_preflight_rejects_entry_count_and_expansion_budgets():
    payload = _archive(
        {
            "[Content_Types].xml": b"types",
            "word/document.xml": b"A" * 4096,
            "word/extra.xml": b"B",
        }
    )

    with pytest.raises(ArchivePreflightError, match="entries"):
        preflight_ooxml(payload, ".docx", budget=ArchiveBudget(max_entries=2))
    with pytest.raises(ArchivePreflightError, match="uncompressed"):
        preflight_ooxml(
            payload,
            ".docx",
            budget=ArchiveBudget(max_total_uncompressed_bytes=1024, max_compression_ratio=10_000),
        )
    with pytest.raises(ArchivePreflightError, match="compression ratio"):
        preflight_ooxml(payload, ".docx", budget=ArchiveBudget(max_compression_ratio=2))


def test_preflight_rejects_generic_zip_disguised_as_ooxml():
    payload = _archive({"[Content_Types].xml": b"types", "payload.bin": b"not office"})

    with pytest.raises(ArchivePreflightError, match="required OOXML"):
        preflight_ooxml(payload, ".docx")


def test_preflight_checks_declared_entry_budget_before_opening_zip(monkeypatch):
    payload = _archive(
        {"[Content_Types].xml": b"types", "word/document.xml": b"ok", "word/extra.xml": b"extra"}
    )

    def must_not_open(*args, **kwargs):
        raise AssertionError("ZipFile must not materialize entries after the EOCD budget fails")

    monkeypatch.setattr(zipfile, "ZipFile", must_not_open)
    with pytest.raises(ArchivePreflightError, match="entries"):
        preflight_ooxml(payload, ".docx", budget=ArchiveBudget(max_entries=2))


def test_local_storage_put_file_accepts_spooled_upload_stream(tmp_path):
    storage = LocalStorageBackend(tmp_path)
    source = io.BytesIO(b"streamed document")

    assert storage.put_file("tenant/document.bin", source) == "tenant/document.bin"
    assert (tmp_path / "tenant" / "document.bin").read_bytes() == b"streamed document"
