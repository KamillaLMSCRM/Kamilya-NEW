"""Certificate integrity and public verification behavior."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
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


def _program_fixture(*, certificate_mode="final_course", validity_months=6):
    tenant_id, user_id, assignment_id = uuid4(), uuid4(), uuid4()
    final_course_id, enrollment_id = uuid4(), uuid4()
    tenant = SimpleNamespace(id=tenant_id, name="Tenant", settings={})
    user = SimpleNamespace(id=user_id, first_name="Program", last_name="Learner", email="learner@example.test")
    assignment = SimpleNamespace(id=assignment_id, tenant_id=tenant_id, user_id=user_id, path_id=uuid4(), status="completed")
    path = SimpleNamespace(
        id=assignment.path_id,
        tenant_id=tenant_id,
        status="published",
        title="Onboarding Program",
        version=3,
        family_id=uuid4(),
        certificate_mode=certificate_mode,
        certificate_validity_months=validity_months,
    )
    step = SimpleNamespace(course_id=final_course_id, order_index=2, required=True)
    course = SimpleNamespace(id=final_course_id, tenant_id=tenant_id, status="published", title="Final Course")
    enrollment = SimpleNamespace(id=enrollment_id, tenant_id=tenant_id, user_id=user_id, course_id=final_course_id, status="completed", completed_at=datetime.now(UTC))
    return tenant, user, assignment, path, step, course, enrollment


def _program_db(values):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=values)
    db.execute = AsyncMock(return_value=MagicMock())
    db.get = AsyncMock(return_value=values[0])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    savepoint = MagicMock()
    savepoint.rollback = AsyncMock()
    savepoint.commit = AsyncMock()
    db.begin_nested = AsyncMock(return_value=savepoint)
    return db


@pytest.mark.asyncio
async def test_program_certificate_contract_loads_tenant_and_none_mode_is_non_persistent():
    from app.modules.certificates.service import issue_learning_path_certificate

    tenant, user, assignment, path, step, course, enrollment = _program_fixture(certificate_mode="none")
    db = _program_db([tenant, assignment, path, course])
    with patch("app.modules.certificates.service._generate_and_store_pdf", new=AsyncMock()) as artifact:
        result = await issue_learning_path_certificate(
            db, tenant_id=tenant.id, user=user, learning_path_assignment_id=assignment.id
        )
    assert result is None
    db.add.assert_not_called()
    artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_program_certificate_is_one_dual_purpose_row_with_program_snapshot():
    from app.modules.certificates.service import issue_learning_path_certificate

    tenant, user, assignment, path, step, course, enrollment = _program_fixture()
    db = _program_db([tenant, assignment, path, course, enrollment, None])
    db.execute.return_value.scalars.return_value.all.return_value = [step]
    created = SimpleNamespace(id=uuid4(), certificate_number="KML-2026-PROGRAM", metadata_={}, issued_at=datetime.now(UTC))
    db.refresh.side_effect = lambda value: setattr(value, "id", created.id)
    with patch("app.modules.certificates.service._generate_and_store_pdf", new=AsyncMock()):
        result = await issue_learning_path_certificate(
            db, tenant_id=tenant.id, user=user, learning_path_assignment_id=assignment.id
        )
    row = db.add.call_args.args[0]
    assert row.course_id == course.id
    assert row.enrollment_id == enrollment.id
    assert row.learning_path_assignment_id == assignment.id
    assert row.metadata_["certificate_subject"] == "learning_program"
    assert row.metadata_["course_title"] == path.title
    assert row.metadata_["program_title"] == path.title
    assert row.metadata_["program_version"] == path.version
    assert row.metadata_["program_family_id"] == str(path.family_id)
    assert row.metadata_["final_course_title"] == course.title
    assert result is row
    # Existing uq_certificates_enrollment makes this one row serve both program
    # and final-course completion semantics; a second legacy row is forbidden.


@pytest.mark.asyncio
async def test_program_certificate_uses_program_validity_and_null_means_no_expiry():
    from app.modules.certificates.service import issue_learning_path_certificate

    for validity, expected_expiry in ((6, True), (None, False)):
        tenant, user, assignment, path, step, course, enrollment = _program_fixture(validity_months=validity)
        db = _program_db([tenant, assignment, path, course, enrollment, None])
        db.execute.return_value.scalars.return_value.all.return_value = [step]
        with patch("app.modules.certificates.service._generate_and_store_pdf", new=AsyncMock()):
            result = await issue_learning_path_certificate(
                db, tenant_id=tenant.id, user=user, learning_path_assignment_id=assignment.id
            )
        assert (result.expires_at is not None) is expected_expiry


@pytest.mark.asyncio
async def test_program_certificate_returns_existing_row_idempotently():
    from app.modules.certificates.service import issue_learning_path_certificate

    tenant, user, assignment, path, step, course, enrollment = _program_fixture()
    existing = SimpleNamespace(id=uuid4())
    db = _program_db([tenant, assignment, path, course, enrollment, existing])
    db.execute.return_value.scalars.return_value.all.return_value = [step]
    with patch("app.modules.certificates.service._generate_and_store_pdf", new=AsyncMock()) as artifact:
        result = await issue_learning_path_certificate(
            db, tenant_id=tenant.id, user=user, learning_path_assignment_id=assignment.id
        )
    assert result is existing
    db.add.assert_not_called()
    artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_program_certificate_unique_race_uses_nested_savepoint_and_rereads_winner():
    from sqlalchemy.exc import IntegrityError

    from app.modules.certificates.service import issue_learning_path_certificate

    tenant, user, assignment, path, step, course, enrollment = _program_fixture()
    winner = SimpleNamespace(id=uuid4())
    db = _program_db([tenant, assignment, path, course, enrollment, None, winner])
    db.execute.return_value.scalars.return_value.all.return_value = [step]
    nested = MagicMock()
    nested.rollback = AsyncMock()
    nested.commit = AsyncMock()
    db.begin_nested.return_value = nested
    db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    with patch("app.modules.certificates.service._generate_and_store_pdf", new=AsyncMock()):
        result = await issue_learning_path_certificate(
            db, tenant_id=tenant.id, user=user, learning_path_assignment_id=assignment.id
        )
    assert result is winner
    db.begin_nested.assert_awaited_once_with()
    db.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_program_certificate_rejects_invalid_scope_before_artifact_generation():
    from app.modules.certificates.service import issue_learning_path_certificate

    tenant, user, assignment, path, step, course, enrollment = _program_fixture()
    db = _program_db([tenant, None])
    with patch("app.modules.certificates.service._generate_and_store_pdf", new=AsyncMock()) as artifact:
        with pytest.raises(ValueError):
            await issue_learning_path_certificate(
                db, tenant_id=tenant.id, user=user, learning_path_assignment_id=assignment.id
            )
    artifact.assert_not_awaited()


def test_certificate_response_keeps_program_anchor_internal_to_tenant_api():
    from app.modules.certificates.schemas import CertificateResponse

    certificate = _certificate(
        course_id=uuid4(),
        learning_path_assignment_id=uuid4(),
    )
    response = CertificateResponse.model_validate(certificate)
    assert response.learning_path_assignment_id == certificate.learning_path_assignment_id


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
