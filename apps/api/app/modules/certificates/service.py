"""Certificate generation, storage, verification, and lifecycle service."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.tenants import Tenant
from app.modules.certificates.models import Certificate
from app.modules.certificates.pdf import (
    CERTIFICATE_TEMPLATE_VERSION,
    certificate_storage_key,
    read_certificate_pdf,
    render_certificate_pdf,
    store_certificate_pdf,
)
from app.modules.certificates.schemas import (
    CertificatePreviewRequest,
    CertificateSettings,
)

logger = logging.getLogger(__name__)


def generate_certificate_number() -> str:
    """Generate a low-collision certificate number."""
    year = datetime.now(UTC).year
    short_id = uuid.uuid4().hex[:12].upper()
    return f"KML-{year}-{short_id}"


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(
        dt.day,
        [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ][month - 1],
    )
    return dt.replace(year=year, month=month, day=day)


async def get_certificate_settings(
    db: AsyncSession,
    tenant_id: UUID,
) -> CertificateSettings:
    tenant = await db.get(Tenant, tenant_id)
    raw = ((tenant.settings or {}) if tenant else {}).get("certificate_settings") or {}
    if tenant and not raw:
        raw = {"organization_name": tenant.name}
    return CertificateSettings(**raw)


async def update_certificate_settings(
    db: AsyncSession,
    tenant_id: UUID,
    payload: CertificateSettings,
) -> CertificateSettings:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")
    settings = dict(tenant.settings or {})
    settings["certificate_settings"] = payload.model_dump()
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await db.flush()
    return payload


def _verification_url(
    settings: CertificateSettings,
    certificate_number: str,
) -> str:
    if not settings.show_verification_url:
        return ""
    base = (settings.verification_base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/{certificate_number}"


def _certificate_snapshot(cert: Certificate) -> tuple[str, str, dict, str]:
    metadata = cert.metadata_ or {}
    raw_settings = metadata.get("certificate_settings")
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    user_name = str(metadata.get("user_name") or "Обучающийся")
    course_title = str(metadata.get("course_title") or "Учебный курс")
    verification_url = str(metadata.get("verification_url") or "")

    if not verification_url and settings.get("show_verification_url", True):
        base = str(settings.get("verification_base_url") or "").rstrip("/")
        if base:
            separator = "?verify=" if (getattr(cert, "template_version", "v2") or "v2") == "v2" else "/"
            verification_url = f"{base}{separator}{cert.certificate_number}"
    return user_name, course_title, settings, verification_url


def _render_certificate_artifact(cert: Certificate) -> bytes:
    user_name, course_title, settings, verification_url = _certificate_snapshot(cert)
    return render_certificate_pdf(
        user_name=user_name,
        course_title=course_title,
        certificate_number=cert.certificate_number,
        issued_at=cert.issued_at or datetime.now(UTC),
        expires_at=cert.expires_at,
        organization=str(settings.get("organization_name") or "Kamilya LMS"),
        signer_name=str(settings.get("signer_name") or ""),
        signer_title=str(settings.get("signer_title") or ""),
        footer_note=str(settings.get("footer_note") or ""),
        verification_url=verification_url,
        template_version=getattr(cert, "template_version", "v2") or "v2",
    )


def render_certificate_preview(payload: CertificatePreviewRequest) -> bytes:
    """Render unsaved settings without creating database or storage records."""
    issued_at = datetime.now(UTC)
    settings = payload.settings
    expires_at = _add_months(issued_at, settings.validity_months) if settings.validity_months else None
    preview_number = f"KML-{issued_at.year}-PREVIEW"
    return render_certificate_pdf(
        user_name=payload.sample_user_name,
        course_title=payload.sample_course_title,
        certificate_number=preview_number,
        issued_at=issued_at,
        expires_at=expires_at,
        organization=settings.organization_name,
        signer_name=settings.signer_name,
        signer_title=settings.signer_title,
        footer_note=settings.footer_note,
        verification_url=_verification_url(settings, preview_number),
        template_version=CERTIFICATE_TEMPLATE_VERSION,
    )


async def _generate_and_store_pdf(
    db: AsyncSession,
    cert: Certificate,
) -> None:
    """Store the issue-time snapshot; a storage outage must not undo completion."""
    try:
        pdf_bytes = _render_certificate_artifact(cert)
        template_version = cert.template_version or CERTIFICATE_TEMPLATE_VERSION
        key = store_certificate_pdf(
            pdf_bytes,
            cert_id=str(cert.id),
            tenant_id=str(cert.tenant_id),
            template_version=template_version,
        )
        cert.pdf_path = key
        cert.pdf_sha256 = sha256(pdf_bytes).hexdigest()
        await db.flush()
    except Exception as exc:
        logger.exception("Failed to render/store PDF for cert %s: %s", cert.id, exc)


async def issue_certificate(
    db: AsyncSession,
    user_id: UUID,
    course_id: UUID,
    tenant_id: UUID,
    user_name: str = "",
    course_title: str = "",
    enrollment_id: UUID | None = None,
) -> Certificate:
    """Issue one immutable certificate after the enrollment is completed."""
    from app.models.enrollment import Enrollment

    if enrollment_id is not None:
        enrollment = await db.scalar(
            select(Enrollment).where(
                Enrollment.id == enrollment_id,
                Enrollment.user_id == user_id,
                Enrollment.course_id == course_id,
                Enrollment.tenant_id == tenant_id,
            )
        )
    else:
        from app.modules.enrollments.context import current_enrollment

        enrollment = await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course_id)
    if not enrollment:
        raise ValueError("Not enrolled in this course")
    if enrollment.status != "completed":
        raise ValueError("Course is not completed yet")
    # Completion flows pass an explicit enrollment and need an artifact bound
    # to that exact attempt (including one-time personal-link assignments).
    # Legacy/manual account issuance keeps the historical one-per-course rule.
    certificate_enrollment_id = (
        enrollment.id if enrollment_id is not None or enrollment.recurring_assignment_id else None
    )
    existing = await db.scalar(
        select(Certificate).where(
            Certificate.user_id == user_id,
            Certificate.course_id == course_id,
            Certificate.tenant_id == tenant_id,
            Certificate.enrollment_id == certificate_enrollment_id,
        )
    )
    if existing:
        return existing

    if not user_name or not course_title:
        from app.models.courses import Course
        from app.models.users import User

        if not user_name:
            user = await db.get(User, user_id)
            if user:
                user_name = f"{user.first_name} {user.last_name}".strip() or user.email
        if not course_title:
            course = await db.get(Course, course_id)
            if course:
                course_title = course.title

    issued_at = datetime.now(UTC)
    settings = await get_certificate_settings(db, tenant_id)
    expires_at = _add_months(issued_at, settings.validity_months) if settings.validity_months else None
    certificate_number = generate_certificate_number()
    cert = Certificate(
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        enrollment_id=certificate_enrollment_id,
        certificate_number=certificate_number,
        issued_at=issued_at,
        expires_at=expires_at,
        template_version=CERTIFICATE_TEMPLATE_VERSION,
        metadata_={
            "user_name": user_name or "",
            "course_title": course_title or "",
            "certificate_settings": settings.model_dump(),
            "verification_url": _verification_url(settings, certificate_number),
        },
    )
    db.add(cert)
    await db.flush()
    await db.refresh(cert)
    await _generate_and_store_pdf(db, cert)
    return cert


async def issue_learning_path_certificate(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user: Any,
    learning_path_assignment_id: UUID,
) -> Certificate | None:
    """Issue the immutable certificate for one completed LearningPath assignment."""
    from app.models.courses import Course
    from app.models.enrollment import Enrollment
    from app.modules.learning_paths.models import LearningPath, LearningPathAssignment, LearningPathCourse

    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise ValueError("Certificate tenant not found")

    assignment = await db.scalar(
        select(LearningPathAssignment)
        .where(
            LearningPathAssignment.id == learning_path_assignment_id,
            LearningPathAssignment.tenant_id == tenant.id,
            LearningPathAssignment.user_id == user.id,
            LearningPathAssignment.status == "completed",
        )
    )
    if assignment is None:
        raise ValueError("Completed learning program assignment not found")

    path = await db.scalar(
        select(LearningPath)
        .where(
            LearningPath.id == assignment.path_id,
            LearningPath.tenant_id == tenant.id,
            LearningPath.status == "published",
        )
    )
    if path is None:
        raise ValueError("Published learning program not found")
    if getattr(path, "certificate_mode", "none") == "none":
        return None

    steps = list(
        (
            await db.execute(
                select(LearningPathCourse)
                .where(LearningPathCourse.path_id == path.id)
                .order_by(LearningPathCourse.order_index)
            )
        ).scalars().all()
    )
    if not steps:
        raise ValueError("Learning program curriculum is empty")
    required_steps = [step for step in steps if step.required]
    final_step = (required_steps or steps)[-1]
    course = await db.scalar(
        select(Course).where(
            Course.id == final_step.course_id,
            Course.tenant_id == tenant.id,
            Course.status == "published",
        )
    )
    if course is None:
        raise ValueError("Final learning program course not found")
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.tenant_id == tenant.id,
            Enrollment.user_id == user.id,
            Enrollment.course_id == course.id,
            Enrollment.status == "completed",
        ).order_by(Enrollment.completed_at.desc().nullslast(), Enrollment.id.desc())
    )
    if enrollment is None:
        raise ValueError("Final learning program course is not completed")

    existing = cast(Certificate | None, await db.scalar(
        select(Certificate).where(
            Certificate.tenant_id == tenant.id,
            Certificate.user_id == user.id,
            Certificate.learning_path_assignment_id == assignment.id,
        )
    ))
    if existing:
        return existing

    issued_at = datetime.now(UTC)
    validity_months = getattr(path, "certificate_validity_months", None)
    expires_at = _add_months(issued_at, validity_months) if validity_months else None
    certificate_number = generate_certificate_number()
    cert = Certificate(
        tenant_id=tenant.id,
        user_id=user.id,
        course_id=course.id,
        enrollment_id=enrollment.id,
        learning_path_assignment_id=assignment.id,
        certificate_number=certificate_number,
        issued_at=issued_at,
        expires_at=expires_at,
        template_version=CERTIFICATE_TEMPLATE_VERSION,
        metadata_={
            "user_name": f"{user.first_name} {user.last_name}".strip() or user.email,
            "course_title": path.title,
            "certificate_subject": "learning_program",
            "program_title": path.title,
            "program_version": path.version,
            "program_family_id": str(path.family_id),
            "final_course_title": course.title,
            "learning_path_assignment_id": str(assignment.id),
            "certificate_settings": {},
        },
    )
    savepoint = await db.begin_nested()
    db.add(cert)
    try:
        await db.flush()
    except IntegrityError:
        await savepoint.rollback()
        existing = cast(Certificate | None, await db.scalar(
            select(Certificate).where(
                Certificate.tenant_id == tenant.id,
                Certificate.user_id == user.id,
                Certificate.learning_path_assignment_id == assignment.id,
            )
        ))
        if existing:
            return existing
        raise
    else:
        await savepoint.commit()
    await db.refresh(cert)
    settings = await get_certificate_settings(db, cast(UUID, tenant.id))
    cert.metadata_["certificate_settings"] = settings.model_dump()
    cert.metadata_["verification_url"] = _verification_url(settings, cast(str, cert.certificate_number))
    await db.flush()
    await _generate_and_store_pdf(db, cert)
    return cert


async def get_user_certificates(
    db: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    *,
    enrollment_id: UUID | None = None,
) -> list[Certificate]:
    query = (
        select(Certificate)
        .where(
            Certificate.user_id == user_id,
            Certificate.tenant_id == tenant_id,
        )
        .order_by(Certificate.issued_at.desc())
    )
    if enrollment_id is not None:
        query = query.where(Certificate.enrollment_id == enrollment_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_certificate(
    db: AsyncSession,
    cert_id: UUID,
    tenant_id: UUID,
) -> Certificate | None:
    cert = await db.get(Certificate, cert_id)
    if cert and cert.tenant_id == tenant_id:
        return cert
    return None


async def read_pdf_bytes(
    db: AsyncSession,
    cert_id: UUID,
    tenant_id: UUID,
) -> bytes | None:
    """Read and integrity-check a PDF, recovering only from its snapshot."""
    cert = await get_certificate(db, cert_id, tenant_id)
    if not cert:
        return None

    template_version = cert.template_version or "v2"
    pdf_bytes = read_certificate_pdf(
        str(tenant_id),
        str(cert_id),
        template_version,
    )
    if pdf_bytes:
        digest = sha256(pdf_bytes).hexdigest()
        if cert.pdf_sha256 and cert.pdf_sha256 != digest:
            logger.error("Certificate PDF hash mismatch for %s", cert.id)
            return None
        if not cert.pdf_sha256:
            cert.pdf_sha256 = digest
            await db.flush()
        return pdf_bytes

    try:
        pdf_bytes = _render_certificate_artifact(cert)
        key = store_certificate_pdf(
            pdf_bytes,
            cert_id=str(cert.id),
            tenant_id=str(tenant_id),
            template_version=template_version,
        )
        cert.pdf_path = key
        cert.pdf_sha256 = sha256(pdf_bytes).hexdigest()
        await db.flush()
        return pdf_bytes
    except Exception as exc:
        logger.exception("PDF regeneration failed for %s: %s", cert_id, exc)
        return None


async def get_pdf_url(
    db: AsyncSession,
    cert_id: UUID,
    tenant_id: UUID,
    expires_in: int = 300,
) -> str | None:
    from app.core.storage import get_storage

    cert = await get_certificate(db, cert_id, tenant_id)
    if not cert:
        return None
    pdf_bytes = await read_pdf_bytes(db, cert_id, tenant_id)
    if not pdf_bytes:
        return None
    key = certificate_storage_key(
        str(tenant_id),
        str(cert_id),
        cert.template_version or "v2",
    )
    return get_storage().get_url(key, expires_in=expires_in)


async def verify_certificate(
    db: AsyncSession,
    certificate_number: str,
) -> dict | None:
    result = await db.execute(
        select(Certificate).where(Certificate.certificate_number == certificate_number.strip().upper())
    )
    cert = result.scalar_one_or_none()
    if not cert:
        return None

    _, _, settings, _ = _certificate_snapshot(cert)
    status = cert.status
    return {
        "valid": status == "active",
        "status": status,
        "certificate_number": cert.certificate_number,
        "issued_at": cert.issued_at,
        "expires_at": cert.expires_at,
        "user_name": cert.user_name,
        "course_title": cert.course_title,
        "organization_name": str(settings.get("organization_name") or "Kamilya LMS"),
        # The operational reason stays in tenant audit data and is not public.
        "revoked_reason": None,
    }


async def revoke_certificate(
    db: AsyncSession,
    cert_id: UUID,
    tenant_id: UUID,
    reason: str,
) -> Certificate:
    cert = await get_certificate(db, cert_id, tenant_id)
    if not cert:
        raise ValueError("Certificate not found")
    if cert.revoked_at is not None:
        if cert.revoked_reason == reason:
            return cert
        raise ValueError("Certificate is already revoked")
    cert.revoked_at = datetime.now(UTC)
    cert.revoked_reason = reason
    await db.flush()
    return cert
