"""Certificate API router"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.core.storage import get_storage
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.certificates.schemas import (
    CertificatePreviewRequest,
    CertificateResponse,
    CertificateRevocationRequest,
    CertificateSettings,
    CertificateVerificationResponse,
)
from app.modules.certificates.service import (
    get_certificate,
    get_certificate_settings,
    get_pdf_url,
    get_user_certificates,
    issue_certificate,
    read_pdf_bytes,
    render_certificate_preview,
    revoke_certificate,
    update_certificate_settings,
    verify_certificate,
)

router = APIRouter(prefix="/certificates", tags=["certificates"])
Database = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_role("admin"))]
MethodologistUser = Annotated[User, Depends(require_role("methodologist"))]


@router.get("/settings", response_model=CertificateSettings)
async def get_settings(
    db: Database,
    user: AdminUser,
):
    """Get tenant certificate template/settings."""
    return await get_certificate_settings(db, user.tenant_id)


@router.put("/settings", response_model=CertificateSettings)
async def save_settings(
    payload: CertificateSettings,
    db: Database,
    user: AdminUser,
):
    """Save tenant certificate template/settings."""
    try:
        settings = await update_certificate_settings(db, user.tenant_id, payload)
        await log_action(
            db,
            user.tenant_id,
            "certificate.settings.updated",
            "certificate_settings",
            user_id=user.id,
            details={
                "validity_months": settings.validity_months,
                "show_verification_url": settings.show_verification_url,
            },
        )
        return settings
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/settings/preview")
async def preview_settings(
    payload: CertificatePreviewRequest,
    _user: AdminUser,
):
    """Render unsaved certificate settings with the production PDF renderer."""
    pdf_bytes = render_certificate_preview(payload)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="certificate-preview.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.get("", response_model=list[CertificateResponse])
async def list_certificates(
    db: Database,
    user: CurrentUser,
):
    """Get current user's certificates."""
    return await get_user_certificates(
        db,
        user.id,
        user.tenant_id,
        enrollment_id=getattr(user, "assignment_access_enrollment_id", None),
    )


@router.post("/{course_id}/issue", response_model=CertificateResponse, status_code=201)
async def issue_course_certificate(
    course_id: UUID,
    db: Database,
    user: CurrentUser,
):
    """Issue certificate for completing a course (enforces completion)."""
    if getattr(user, "assignment_access_enrollment_id", None) is not None:
        # Personal-link completion already issues the exact-enrollment
        # certificate atomically.  This legacy/manual endpoint must not let a
        # scoped bearer mint a certificate for another own course.
        raise HTTPException(status_code=403, detail="Certificate is issued by course completion")
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/verify/{certificate_number}",
    response_model=CertificateVerificationResponse,
)
async def verify_cert(
    certificate_number: str,
    db: Database,
):
    """Verify a certificate (public endpoint)."""
    # Certificate verification is intentionally public, including for users
    # without a tenant session. FORCE RLS otherwise hides valid certificates
    # from this exact-number lookup.
    await db.execute(text("SELECT set_config('app.public_certificate_lookup', 'true', true)"))
    result = await verify_certificate(db, certificate_number)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return result


@router.post(
    "/{cert_id}/revoke",
    response_model=CertificateVerificationResponse,
)
async def revoke_cert(
    cert_id: UUID,
    payload: CertificateRevocationRequest,
    db: Database,
    user: MethodologistUser,
):
    """Irreversibly revoke a tenant certificate and retain the audit reason."""
    try:
        cert = await revoke_certificate(
            db,
            cert_id,
            user.tenant_id,
            payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await log_action(
        db,
        user.tenant_id,
        "certificate.revoked",
        "certificate",
        resource_id=cert.id,
        user_id=user.id,
        details={"reason": cert.revoked_reason},
    )
    result = await verify_certificate(db, cert.certificate_number)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return result


def _can_access_certificate(user, cert) -> bool:
    if user.role == "methodologist":
        return True
    if cert.user_id != user.id:
        return False
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    return assignment_enrollment_id is None or cert.enrollment_id == assignment_enrollment_id


@router.get("/{cert_id}", response_model=CertificateResponse)
async def get_cert(
    cert_id: UUID,
    db: Database,
    user: CurrentUser,
):
    """Get a specific certificate."""
    cert = await get_certificate(db, cert_id, user.tenant_id)
    if not cert or not _can_access_certificate(user, cert):
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert


@router.get("/{cert_id}/download")
async def download_certificate_pdf(
    cert_id: UUID,
    db: Database,
    user: CurrentUser,
):
    """Download certificate as PDF.

    Storage routing:
    - Supabase backend: 302 redirect to a time-limited signed URL (offloads bandwidth).
    - Local backend: stream the PDF bytes directly.
    """
    cert = await get_certificate(db, cert_id, user.tenant_id)
    if not cert or not _can_access_certificate(user, cert):
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
