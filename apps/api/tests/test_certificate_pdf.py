"""Tests for localized certificate PDF generation."""

from datetime import UTC, datetime
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
        issued_at=datetime(2026, 7, 23, tzinfo=UTC),
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
        issued_at=datetime(2026, 6, 24, tzinfo=UTC),
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
        issued_at=datetime(2026, 7, 23, tzinfo=UTC),
    )

    assert key == f"{tenant_id}/{cert_id}-{CERTIFICATE_TEMPLATE_VERSION}.pdf"
    assert key == certificate_storage_key(tenant_id, cert_id)
    read_back = read_certificate_pdf(tenant_id, cert_id)
    assert read_back is not None
    assert read_back[:4] == b"%PDF"


def test_read_pdf_missing_returns_none():
    assert read_certificate_pdf("missing-tenant", "missing-cert") is None


def test_v3_long_content_stays_on_one_page_and_contains_verification_link():
    verification_url = "https://app.kml.kz/verify/certificate/KML-2026-LONG"
    pdf_bytes = render_certificate_pdf(
        user_name=(
            "Александр-Станислав Нурланович "
            "Абдрахманов-Кудайбергенов"
        ),
        course_title=(
            "Комплексная программа по промышленной безопасности, охране труда, "
            "пожарной безопасности и действиям при чрезвычайных ситуациях"
        ),
        certificate_number="KML-2026-LONG",
        issued_at=datetime(2026, 7, 29, tzinfo=UTC),
        organization=(
            "ТОО Международный учебно-методический центр "
            "профессионального развития и безопасности"
        ),
        signer_name=(
            "Александр-Станислав Нурланович "
            "Абдрахманов-Кудайбергенов"
        ),
        signer_title=(
            "Генеральный директор и руководитель "
            "учебно-методического центра"
        ),
        footer_note=(
            "Сертификат подтверждает успешное завершение обязательной "
            "программы обучения."
        ),
        verification_url=verification_url,
    )

    reader = PdfReader(BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Абдрахманов-Кудайбергенов" in text
    assert "чрезвычайных ситуациях" in text
    annotations = reader.pages[0].get("/Annots") or []
    uris = [
        annotation.get_object().get("/A", {}).get("/URI")
        for annotation in annotations
    ]
    assert verification_url in uris


def test_v2_storage_key_remains_addressable_after_template_upgrade():
    tenant_id = str(uuid4())
    cert_id = str(uuid4())
    assert certificate_storage_key(tenant_id, cert_id, "v2").endswith("-v2.pdf")
    assert certificate_storage_key(tenant_id, cert_id).endswith(
        f"-{CERTIFICATE_TEMPLATE_VERSION}.pdf"
    )
