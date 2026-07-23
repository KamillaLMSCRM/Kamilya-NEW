"""Tests for localized certificate PDF generation."""

from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader

from app.core.storage import reset_storage_for_tests
from app.modules.certificates.pdf import (
    CERTIFICATE_TEMPLATE_VERSION,
    _safe_text,
    certificate_storage_key,
    read_certificate_pdf,
    render_certificate_pdf,
    write_certificate_pdf,
)


@pytest.fixture(autouse=True)
def _reset_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CERTIFICATE_STORAGE_DIR", str(tmp_path))
    reset_storage_for_tests()
    yield
    reset_storage_for_tests()


def test_safe_text_preserves_cyrillic_and_normalizes_dashes():
    assert _safe_text("Ерлан QA") == "Ерлан QA"
    assert _safe_text("Охрана труда — вводный курс") == "Охрана труда - вводный курс"
    assert _safe_text("") == ""


def test_render_certificate_pdf_contains_localized_identity():
    pdf_bytes = render_certificate_pdf(
        user_name="Ерлан QA",
        course_title="Безопасное начало смены на складе",
        certificate_number="KML-2026-ABC123",
        issued_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 10_000
    text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "СЕРТИФИКАТ" in text
    assert "Ерлан QA" in text
    assert "Безопасное начало смены на складе" in text
    assert "23 июля 2026 г." in text
    assert "KML-2026-ABC123" in text


def test_render_certificate_pdf_empty_names_fallback():
    pdf_bytes = render_certificate_pdf(
        user_name="",
        course_title="",
        certificate_number="KML-2026-EMPTY",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "Обучающийся" in text
    assert "Учебный курс" in text


def test_write_and_read_pdf_roundtrip_uses_versioned_key():
    cert_id = str(uuid4())
    tenant_id = str(uuid4())
    key = write_certificate_pdf(
        cert_id=cert_id,
        tenant_id=tenant_id,
        user_name="Ерлан QA",
        course_title="Безопасность на складе",
        certificate_number="KML-2026-ROUND",
        issued_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )

    assert key == f"{tenant_id}/{cert_id}-{CERTIFICATE_TEMPLATE_VERSION}.pdf"
    assert key == certificate_storage_key(tenant_id, cert_id)
    read_back = read_certificate_pdf(tenant_id, cert_id)
    assert read_back is not None
    assert read_back[:4] == b"%PDF"


def test_read_pdf_missing_returns_none():
    assert read_certificate_pdf("missing-tenant", "missing-cert") is None
