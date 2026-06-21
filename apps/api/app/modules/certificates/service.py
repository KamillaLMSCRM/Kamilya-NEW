"""Certificate service — generation and management"""
import uuid
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.modules.certificates.models import Certificate


def generate_certificate_number() -> str:
    """Generate unique certificate number like KML-2026-XXXXXX."""
    year = datetime.now().year
    short_id = uuid.uuid4().hex[:6].upper()
    return f"KML-{year}-{short_id}"


async def issue_certificate(
    db: AsyncSession,
    user_id: UUID,
    course_id: UUID,
    tenant_id: UUID,
    user_name: str = "",
    course_title: str = "",
) -> Certificate:
    """Issue a certificate for completing a course."""
    # Check if already issued
    existing = await db.execute(
        select(Certificate).where(
            Certificate.user_id == user_id,
            Certificate.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Certificate already issued for this course")

    cert = Certificate(
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        certificate_number=generate_certificate_number(),
        metadata_={
            "user_name": user_name,
            "course_title": course_title,
        },
    )
    db.add(cert)
    await db.flush()
    await db.refresh(cert)
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
