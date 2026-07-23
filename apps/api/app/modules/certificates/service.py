"""Certificate service — generation, PDF rendering, and management."""
import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.tenants import Tenant
from app.modules.certificates.models import Certificate
from app.modules.certificates.pdf import write_certificate_pdf, read_certificate_pdf
from app.modules.certificates.schemas import CertificateSettings

logger = logging.getLogger(__name__)


def generate_certificate_number() -> str:
    """Generate unique certificate number like KML-2026-XXXXXX."""
    year = datetime.now().year
    short_id = uuid.uuid4().hex[:6].upper()
    return f"KML-{year}-{short_id}"


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


async def get_certificate_settings(db: AsyncSession, tenant_id: UUID) -> CertificateSettings:
    tenant = await db.get(Tenant, tenant_id)
    raw = ((tenant.settings or {}) if tenant else {}).get("certificate_settings") or {}
    return CertificateSettings(**raw)


async def update_certificate_settings(
    db: AsyncSession, tenant_id: UUID, payload: CertificateSettings
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


def _verification_url(settings: CertificateSettings, certificate_number: str) -> str:
    if not settings.show_verification_url:
        return ""
    base = (settings.verification_base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}?verify={certificate_number}"


async def _generate_and_store_pdf(
    db: AsyncSession,
    cert: Certificate,
    user_name: str,
    course_title: str,
) -> None:
    """Render PDF and store via the active backend. Best-effort — logs but does not raise."""
    try:
        settings = await get_certificate_settings(db, cert.tenant_id)
        key = write_certificate_pdf(
            cert_id=str(cert.id),
            tenant_id=str(cert.tenant_id),
            user_name=user_name,
            course_title=course_title,
            certificate_number=cert.certificate_number,
            issued_at=cert.issued_at or datetime.now(timezone.utc),
            organization=settings.organization_name,
            signer_name=settings.signer_name,
            signer_title=settings.signer_title,
            footer_note=settings.footer_note,
            verification_url=_verification_url(settings, cert.certificate_number),
        )
        cert.pdf_path = key
        await db.flush()
    except Exception as e:
        logger.exception(f"Failed to render/store PDF for cert {cert.id}: {e}")


async def issue_certificate(
    db: AsyncSession,
    user_id: UUID,
    course_id: UUID,
    tenant_id: UUID,
    user_name: str = "",
    course_title: str = "",
) -> Certificate:
    """Issue a certificate for completing a course.

    Enforces that the user has actually completed the course.
    Idempotent — returns existing cert if already issued.
    """
    # Idempotency: already issued?
    existing_result = await db.execute(
        select(Certificate).where(
            Certificate.user_id == user_id,
            Certificate.course_id == course_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing

    # Enforce: enrollment must be completed
    from app.models.enrollment import Enrollment
    enr_result = await db.execute(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    enrollment = enr_result.scalar_one_or_none()
    if not enrollment:
        raise ValueError("Not enrolled in this course")
    if enrollment.status != "completed":
        raise ValueError("Course is not completed yet")

    # Resolve display names if not provided
    if not user_name or not course_title:
        from app.models.users import User
        from app.models.courses import Course
        if not user_name:
            u = await db.get(User, user_id)
            if u:
                user_name = f"{u.first_name} {u.last_name}".strip() or u.email
        if not course_title:
            c = await db.get(Course, course_id)
            if c:
                course_title = c.title

    issued_at = datetime.now(timezone.utc)
    settings = await get_certificate_settings(db, tenant_id)
    expires_at = _add_months(issued_at, settings.validity_months) if settings.validity_months else None

    cert = Certificate(
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        certificate_number=generate_certificate_number(),
        issued_at=issued_at,
        expires_at=expires_at,
        metadata_={
            "user_name": user_name or "",
            "course_title": course_title or "",
            "certificate_settings": settings.model_dump(),
        },
    )
    db.add(cert)
    await db.flush()
    await db.refresh(cert)

    # Render PDF (best-effort)
    await _generate_and_store_pdf(db, cert, user_name or "Student", course_title or "Course")

    return cert


async def get_user_certificates(
    db: AsyncSession, user_id: UUID, tenant_id: UUID
) -> list[Certificate]:
    """Get all certificates for a user."""
    result = await db.execute(
        select(Certificate)
        .where(Certificate.user_id == user_id, Certificate.tenant_id == tenant_id)
        .order_by(Certificate.issued_at.desc())
    )
    return result.scalars().all()


async def get_certificate(
    db: AsyncSession, cert_id: UUID, tenant_id: UUID
) -> Certificate | None:
    """Get a specific certificate."""
    cert = await db.get(Certificate, cert_id)
    if cert and cert.tenant_id == tenant_id:
        return cert
    return None


async def read_pdf_bytes(
    db: AsyncSession, cert_id: UUID, tenant_id: UUID
) -> bytes | None:
    """Read raw PDF bytes for a certificate. Regenerates if missing."""
    cert = await get_certificate(db, cert_id, tenant_id)
    if not cert:
        return None

    # Try storage first
    pdf_bytes = read_certificate_pdf(str(tenant_id), str(cert_id))
    if pdf_bytes:
        return pdf_bytes

    # Missing — regenerate (recovery path)
    user_name = (cert.metadata_ or {}).get("user_name", "Student")
    course_title = (cert.metadata_ or {}).get("course_title", "Course")
    try:
        settings = await get_certificate_settings(db, tenant_id)
        key = write_certificate_pdf(
            cert_id=str(cert.id),
            tenant_id=str(tenant_id),
            user_name=user_name,
            course_title=course_title,
            certificate_number=cert.certificate_number,
            issued_at=cert.issued_at or datetime.now(timezone.utc),
            organization=settings.organization_name,
            signer_name=settings.signer_name,
            signer_title=settings.signer_title,
            footer_note=settings.footer_note,
            verification_url=_verification_url(settings, cert.certificate_number),
        )
        cert.pdf_path = key
        await db.flush()
        return read_certificate_pdf(str(tenant_id), str(cert_id))
    except Exception as e:
        logger.exception(f"PDF regeneration failed for {cert_id}: {e}")
        return None


async def get_pdf_url(
    db: AsyncSession, cert_id: UUID, tenant_id: UUID, expires_in: int = 300
) -> str | None:
    """Return a URL the client can use to download the PDF.

    For Supabase: returns a time-limited signed URL.
    For local: returns None (caller should stream bytes instead).
    """
    from app.core.storage import get_storage
    from app.modules.certificates.pdf import certificate_storage_key

    cert = await get_certificate(db, cert_id, tenant_id)
    if not cert:
        return None
    # Ensure the current template exists before signing its storage URL.
    # Missing versioned files are regenerated by read_pdf_bytes().
    pdf_bytes = await read_pdf_bytes(db, cert_id, tenant_id)
    if not pdf_bytes:
        return None
    key = certificate_storage_key(str(tenant_id), str(cert_id))
    return get_storage().get_url(key, expires_in=expires_in)


async def verify_certificate(db: AsyncSession, certificate_number: str) -> dict | None:
    """Verify a certificate by number (public endpoint)."""
    result = await db.execute(
        select(Certificate).where(Certificate.certificate_number == certificate_number)
    )
    cert = result.scalar_one_or_none()
    if not cert:
        return None

    return {
        "valid": True,
        "certificate_number": cert.certificate_number,
        "issued_at": cert.issued_at.isoformat(),
        "expires_at": cert.expires_at.isoformat() if cert.expires_at else None,
        "user_name": (cert.metadata_ or {}).get("user_name", ""),
        "course_title": (cert.metadata_ or {}).get("course_title", ""),
    }
