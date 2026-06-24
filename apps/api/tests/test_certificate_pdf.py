"""Tests for certificate PDF generation."""
import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.storage import reset_storage_for_tests
from app.modules.certificates.pdf import (
    render_certificate_pdf,
    write_certificate_pdf,
    read_certificate_pdf,
    _safe_text,
)


@pytest.fixture(autouse=True)
def _reset_storage(monkeypatch, tmp_path):
    """Use a fresh local storage rooted at tmp_path for every test."""
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CERTIFICATE_STORAGE_DIR", str(tmp_path))
    reset_storage_for_tests()
    yield
    reset_storage_for_tests()


def test_safe_text_transliterates_cyrillic():
    """Cyrillic gets transliterated to latin for Helvetica core font."""
    assert _safe_text("Иванов") == "Ivanov"
    assert _safe_text("Петров") == "Petrov"
    assert _safe_text("Курс по охране труда") == "Kurs po ohrane truda"
    # Preserves latin
    assert _safe_text("Hello World") == "Hello World"
    # Mixed case preserved
    assert _safe_text("Senior Разработчик") == "Senior Razrabotchik"


def test_render_certificate_pdf_basic():
    """Renders non-empty PDF bytes starting with %PDF magic."""
    pdf_bytes = render_certificate_pdf(
        user_name="Test User",
        course_title="Test Course",
        certificate_number="KML-2026-ABC123",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100  # non-trivial size
    assert pdf_bytes[:4] == b"%PDF"  # PDF magic


def test_render_certificate_pdf_cyrillic():
    """Cyrrilic input is transliterated; PDF still renders."""
    pdf_bytes = render_certificate_pdf(
        user_name="Иванов Иван",
        course_title="Охрана труда и техника безопасности",
        certificate_number="KML-2026-XYZ789",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    assert pdf_bytes[:4] == b"%PDF"
    # Streamed content should not error; transliteration must be safe
    assert len(pdf_bytes) > 100


def test_render_certificate_pdf_empty_names_fallback():
    """Empty names fall back to defaults without error."""
    pdf_bytes = render_certificate_pdf(
        user_name="",
        course_title="",
        certificate_number="KML-2026-EMPTY",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    assert pdf_bytes[:4] == b"%PDF"


def test_write_and_read_pdf_roundtrip():
    """write_certificate_pdf + read_certificate_pdf round-trip via storage backend."""
    cert_id = str(uuid4())
    tenant_id = str(uuid4())
    key = write_certificate_pdf(
        cert_id=cert_id,
        tenant_id=tenant_id,
        user_name="Round Trip",
        course_title="Test Course",
        certificate_number="KML-2026-ROUND",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    assert key == f"{tenant_id}/{cert_id}.pdf"

    # Read back via the same storage abstraction
    read_back = read_certificate_pdf(tenant_id, cert_id)
    assert read_back is not None
    assert read_back[:4] == b"%PDF"


def test_read_pdf_missing_returns_none():
    """Reading non-existent cert returns None, doesn't raise."""
    result = read_certificate_pdf("missing-tenant", "missing-cert")
    assert result is None
