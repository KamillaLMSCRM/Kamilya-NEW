"""Certificate integrity and public verification behavior."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfReader

from app.modules.certificates.schemas import (
    PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL,
    CertificatePreviewRequest,
    CertificateSettings,
)
from app.modules.certificates.service import (
    _render_certificate_artifact,
    get_certificate_settings,
    render_certificate_preview,
    verify_certificate,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Database:
    def __init__(self, value):
        self.value = value

    async def execute(self, _query):
        return _ScalarResult(self.value)


class _TenantDatabase:
    def __init__(self, tenant):
        self.tenant = tenant

    async def get(self, _model, _identifier):
        return self.tenant


def _certificate(**overrides):
    issued_at = datetime(2026, 7, 29, tzinfo=UTC)
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "certificate_number": "KML-2026-SNAPSHOT",
        "issued_at": issued_at,
        "expires_at": None,
        "revoked_at": None,
        "revoked_reason": None,
        "template_version": "v3",
        "metadata_": {
            "user_name": "Snapshot Learner",
            "course_title": "Snapshot Course",
            "certificate_settings": {
                "organization_name": "Snapshot Organization",
                "signer_name": "Snapshot Signer",
                "signer_title": "Snapshot Title",
                "footer_note": "Snapshot note",
                "show_verification_url": True,
                "verification_base_url": PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL,
            },
            "verification_url": (
                f"{PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL}/KML-2026-SNAPSHOT"
            ),
        },
    }
    values.update(overrides)
    certificate = SimpleNamespace(**values)
    certificate.user_name = str(certificate.metadata_.get("user_name", ""))
    certificate.course_title = str(certificate.metadata_.get("course_title", ""))
    if certificate.revoked_at is not None:
        certificate.status = "revoked"
    elif certificate.expires_at and certificate.expires_at <= datetime.now(UTC):
        certificate.status = "expired"
    else:
        certificate.status = "active"
    return certificate


def test_settings_force_the_canonical_public_verification_url():
    settings = CertificateSettings(verification_base_url="https://example.invalid")
    assert (
        settings.verification_base_url
        == PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL
    )


@pytest.mark.asyncio
async def test_new_tenant_uses_its_name_as_certificate_issuer():
    tenant = SimpleNamespace(name="ТОО Тестовая компания", settings={})
    settings = await get_certificate_settings(_TenantDatabase(tenant), uuid4())
    assert settings.organization_name == "ТОО Тестовая компания"


def test_preview_uses_production_renderer_without_persistence():
    pdf_bytes = render_certificate_preview(
        CertificatePreviewRequest(
            settings=CertificateSettings(
                organization_name="Preview Organization",
                signer_name="Preview Signer",
            ),
            sample_user_name="Preview Learner",
            sample_course_title="Preview Course",
        )
    )
    text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "Preview Organization" in text
    assert "Preview Learner" in text
    assert "Preview Course" in text
    assert "KML-2026-PREVIEW" in text


def test_recovery_renderer_uses_issue_time_snapshot():
    certificate = _certificate()
    pdf_bytes = _render_certificate_artifact(certificate)
    text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "Snapshot Organization" in text
    assert "Snapshot Signer" in text
    assert "Snapshot Course" in text


@pytest.mark.asyncio
async def test_public_verification_reports_expired_certificate_as_invalid():
    certificate = _certificate(
        expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    result = await verify_certificate(_Database(certificate), "kml-2026-snapshot")
    assert result is not None
    assert result["status"] == "expired"
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_public_verification_hides_internal_revocation_reason():
    certificate = _certificate(
        revoked_at=datetime.now(UTC),
        revoked_reason="Issued in error",
    )
    result = await verify_certificate(_Database(certificate), "KML-2026-SNAPSHOT")
    assert result is not None
    assert result["status"] == "revoked"
    assert result["valid"] is False
    assert result["revoked_reason"] is None
