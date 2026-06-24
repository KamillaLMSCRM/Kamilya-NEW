"""Certificate API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.storage import get_storage
from app.modules.certificates.schemas import CertificateResponse
from app.modules.certificates.service import (
    issue_certificate,
    get_user_certificates,
    get_certificate,
    verify_certificate,
    read_pdf_bytes,
    get_pdf_url,
)

router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.get("", response_model=list[CertificateResponse])
async def list_certificates(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get current user's certificates."""
    return await get_user_certificates(db, user.id, user.tenant_id)


@router.post("/{course_id}/issue", response_model=CertificateResponse, status_code=201)
async def issue_course_certificate(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Issue certificate for completing a course (enforces completion)."""
    try:
        cert = await issue_certificate(
            db=db,
            user_id=user.id,
            course_id=course_id,
            tenant_id=user.tenant_id,
            user_name=f"{user.first_name} {user.last_name}" if hasattr(user, "first_name") else "",
            course_title="",
        )
        return cert
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{cert_id}", response_model=CertificateResponse)
async def get_cert(
    cert_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get a specific certificate."""
    cert = await get_certificate(db, cert_id, user.tenant_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert


@router.get("/{cert_id}/download")
async def download_certificate_pdf(
    cert_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Download certificate as PDF.

    Storage routing:
    - Supabase backend: 302 redirect to a time-limited signed URL (offloads bandwidth).
    - Local backend: stream the PDF bytes directly.
    """
    cert = await get_certificate(db, cert_id, user.tenant_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    storage = get_storage()
    backend_name = storage.name

    if backend_name.startswith("supabase"):
        # Redirect to signed URL
        signed_url = await get_pdf_url(db, cert_id, user.tenant_id, expires_in=300)
        if not signed_url:
            raise HTTPException(status_code=500, detail="Could not generate download URL")
        return RedirectResponse(url=signed_url, status_code=302)

    # Local: stream bytes
    pdf_bytes = await read_pdf_bytes(db, cert_id, user.tenant_id)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="PDF generation failed")

    filename = f"certificate-{cert.certificate_number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/verify/{certificate_number}")
async def verify_cert(
    certificate_number: str,
    db: AsyncSession = Depends(get_db),
):
    """Verify a certificate (public endpoint)."""
    result = await verify_certificate(db, certificate_number)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return result
