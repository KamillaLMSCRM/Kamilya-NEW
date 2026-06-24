"""Certificate service — generation, PDF rendering, and management."""
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.certificates.models import Certificate
from app.modules.certificates.pdf import write_certificate_pdf, read_certificate_pdf

logger = logging.getLogger(__name__)


def generate_certificate_number() -> str:
    """Generate unique certificate number like KML-2026-XXXXXX."""
    year = datetime.now().year
    short_id = uuid.uuid4().hex[:6].upper()
    return f"KML-{year}-{short_id}"


def _storage_root() -> Path:
    s = get_settings()
    p = Path(s.CERTIFICATE_STORAGE_DIR)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


async def _generate_and_store_pdf(
    db: AsyncSession,
    cert: Certificate,
    user_name: str,
    course_title: str,
) -> None:
    """Render PDF and update cert.pdf_path. Best-effort — logs but does not raise."""
    try:
        rel_path = write_certificate_pdf(
            cert_id=str(cert.id),
            tenant_id=str(cert.tenant_id),
            user_name=user_name,
            course_title=course_title,
            certificate_number=cert.certificate_number,
            issued_at=cert.issued_at or datetime.now(timezone.utc),
            storage_root=_storage_root(),
        )
        cert.pdf_path = rel_path
        await db.flush()
    except Exception as e:
        logger.exception(f"Failed to render PDF for cert {cert.id}: {e}")


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

    cert = Certificate(
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        certificate_number=generate_certificate_number(),
        issued_at=datetime.now(timezone.utc),
        metadata_={
            "user_name": user_name or "",
            "course_title": course_title or "",
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
    """Read raw PDF bytes for a certificate. Regenerates if missing on disk."""
    cert = await get_certificate(db, cert_id, tenant_id)
    if not cert:
        return None

    # Try disk first
    pdf_bytes = read_certificate_pdf(str(tenant_id), str(cert_id), _storage_root())
    if pdf_bytes:
        return pdf_bytes

    # Missing on disk — regenerate (recovery path)
    user_name = (cert.metadata_ or {}).get("user_name", "Student")
    course_title = (cert.metadata_ or {}).get("course_title", "Course")
    try:
        rel_path = write_certificate_pdf(
            cert_id=str(cert.id),
            tenant_id=str(tenant_id),
            user_name=user_name,
            course_title=course_title,
            certificate_number=cert.certificate_number,
            issued_at=cert.issued_at or datetime.now(timezone.utc),
            storage_root=_storage_root(),
        )
        cert.pdf_path = rel_path
        await db.flush()
        return read_certificate_pdf(str(tenant_id), str(cert_id), _storage_root())
    except Exception as e:
        logger.exception(f"PDF regeneration failed for {cert_id}: {e}")
        return None


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
