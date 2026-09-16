"""Tenant-scoped API for append-only training evidence."""

# FastAPI dependency calls in defaults are the established project pattern.
# Ruff's B008 rule is not actionable for these route declarations.
# ruff: noqa: B008

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.core.storage import get_storage
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.training_evidence.form_settings import (
    TrainingEvidenceFormSettings,
    get_training_evidence_form_settings,
    render_training_evidence_form_preview,
    update_training_evidence_form_settings,
)
from app.modules.training_evidence.models import TrainingEvidenceSignedScan
from app.modules.training_evidence.schemas import (
    EvidenceCorrectionCreate,
    EvidenceEventCreate,
    EvidenceEventResponse,
    EvidenceRevocationCreate,
    LearnerEvidenceEventResponse,
    LegalHoldCreate,
    LegalHoldResponse,
    SignedScanLedgerResponse,
    SignedScanResponse,
    SignedScanReviewCreate,
    SignedScanReviewResponse,
    StepUpConfirmationResponse,
)
from app.modules.training_evidence.service import (
    add_legal_hold,
    get_event,
    get_learner_event,
    list_events,
    list_learner_events,
    list_legal_holds,
    list_step_up_confirmations,
    record_event,
)
from app.modules.training_evidence.signed_scan_service import (
    _eligible_event,
    append_signed_scan,
    derive_signed_copy_status,
    list_signed_scan_reviews,
    list_signed_scans,
    review_signed_scan,
)

router = APIRouter(
    prefix="/training-evidence",
    tags=["training-evidence"],
    dependencies=[Depends(require_tenant_user())],
)
_EVIDENCE_WRITERS = ("methodologist",)


@router.get("/form-settings", response_model=TrainingEvidenceFormSettings)
async def get_printable_form_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    return await get_training_evidence_form_settings(db, user.tenant_id)


@router.put("/form-settings", response_model=TrainingEvidenceFormSettings)
async def save_printable_form_settings(
    payload: TrainingEvidenceFormSettings,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    try:
        settings = await update_training_evidence_form_settings(db, user.tenant_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await log_action(
        db,
        user.tenant_id,
        "training_evidence.form_settings.updated",
        "training_evidence_form_settings",
        user_id=user.id,
        details={"template_version": settings.template_version},
    )
    return settings


@router.post("/form-settings/preview")
async def preview_printable_form_settings(
    payload: TrainingEvidenceFormSettings,
    _user: User = Depends(require_role("admin")),
):
    return Response(
        content=render_training_evidence_form_preview(payload),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="training-completion-form-preview.pdf"',
            "Cache-Control": "no-store",
        },
    )


def _signed_scan_response(scan, *, status_value: str, review=None) -> SignedScanResponse:
    return SignedScanResponse(
        id=scan.id,
        event_id=scan.event_id,
        enrollment_id=scan.enrollment_id,
        user_id=scan.user_id,
        status=status_value,
        original_filename=scan.original_filename,
        content_type=scan.content_type,
        size_bytes=scan.size_bytes,
        sha256=scan.sha256,
        uploaded_by_user_id=scan.uploaded_by_user_id,
        uploaded_at=scan.uploaded_at,
        created_at=scan.created_at,
        latest_review_action=review.action if review else None,
        latest_review_reason=review.reason if review else None,
        latest_reviewed_by_user_id=review.reviewed_by_user_id if review else None,
        latest_reviewed_at=review.reviewed_at if review else None,
    )


def _assignment_event_is_visible(user: User, event) -> None:
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    if assignment_enrollment_id is not None and event.enrollment_id != assignment_enrollment_id:
        raise HTTPException(status_code=404, detail="Evidence event not found")


@router.get("/events/mine", response_model=list[LearnerEvidenceEventResponse])
async def list_my_training_evidence(
    enrollment_id: UUID | None = Query(default=None),
    procedure_type: str | None = Query(default=None),
    confirmation_status: Literal["not_required", "pending", "confirmed"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    if assignment_enrollment_id is not None:
        if enrollment_id is not None and enrollment_id != assignment_enrollment_id:
            raise HTTPException(status_code=404, detail="Evidence event not found")
        enrollment_id = assignment_enrollment_id
    return await list_learner_events(
        db,
        user.tenant_id,
        user.id,
        enrollment_id=enrollment_id,
        procedure_type=procedure_type,
        confirmation_status=confirmation_status,
        limit=limit,
        offset=offset,
    )


@router.get("/events/mine/{event_id}", response_model=LearnerEvidenceEventResponse)
async def get_my_training_evidence(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    event = await get_learner_event(db, user.tenant_id, user.id, event_id)
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    if assignment_enrollment_id is not None and event.enrollment_id != assignment_enrollment_id:
        raise HTTPException(status_code=404, detail="Evidence event not found")
    return event


@router.get("/events", response_model=list[EvidenceEventResponse])
async def list_training_evidence(
    user_id: UUID | None = Query(default=None),
    procedure_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    return await list_events(
        db,
        user.tenant_id,
        user_id=user_id,
        procedure_type=procedure_type,
        limit=limit,
        offset=offset,
    )


@router.post("/events", response_model=EvidenceEventResponse, status_code=201)
async def create_training_evidence(
    payload: EvidenceEventCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    """Create one acknowledgement with server-controlled procedure binding."""

    if payload.procedure_type in {"training", "knowledge_check"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "system_evidence_workflow_required",
                "message": "Training and knowledge-check evidence is created by the trusted learning workflow",
            },
        )
    if payload.procedure_type in {"internal_attestation", "admission_decision"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "regulated_evidence_workflow_required",
                "message": "Attestation and admission evidence requires a dedicated regulated workflow",
            },
        )

    return await record_event(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        user_id=payload.user_id,
        enrollment_id=payload.enrollment_id,
        content_release_id=payload.content_release_id,
        training_procedure_id=payload.training_procedure_id,
        procedure_type=payload.procedure_type,
        source_event_key=payload.source_event_key,
        payload_snapshot=payload.payload_snapshot,
    )


@router.get("/events/{event_id}", response_model=EvidenceEventResponse)
async def get_training_evidence(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    return await get_event(db, user.tenant_id, event_id)


@router.post(
    "/events/{event_id}/signed-scans",
    response_model=SignedScanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_returned_signed_scan(
    event_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    """Append a returned hand-signed copy; it never mutates the result event."""

    if getattr(user, "is_impersonating", False):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "impersonation_cannot_append_evidence",
                "message": "Use a tenant methodologist account to append immutable evidence",
            },
        )

    scan = await append_signed_scan(
        db,
        tenant_id=user.tenant_id,
        uploader_user_id=user.id,
        event_id=event_id,
        file=file,
    )
    return _signed_scan_response(scan, status_value="uploaded_pending_review")


@router.post(
    "/events/mine/{event_id}/signed-scans",
    response_model=SignedScanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def learner_attach_returned_signed_scan(
    event_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    if getattr(user, "is_impersonating", False):
        raise HTTPException(status_code=403, detail="Impersonation cannot append returned evidence")
    event = await get_learner_event(db, user.tenant_id, user.id, event_id)
    _assignment_event_is_visible(user, event)
    scan = await append_signed_scan(
        db,
        tenant_id=user.tenant_id,
        uploader_user_id=user.id,
        event_id=event.id,
        file=file,
    )
    return _signed_scan_response(scan, status_value="uploaded_pending_review")


@router.get("/events/mine/{event_id}/signed-scans", response_model=SignedScanLedgerResponse)
async def learner_list_returned_signed_scans(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    event = await get_learner_event(db, user.tenant_id, user.id, event_id)
    _assignment_event_is_visible(user, event)
    _, scans = await list_signed_scans(db, tenant_id=user.tenant_id, event_id=event.id)
    reviews = await list_signed_scan_reviews(db, tenant_id=user.tenant_id, event_id=event.id)
    latest_reviews = {review.signed_scan_id: review for review in reviews}
    return SignedScanLedgerResponse(
        event_id=event.id,
        status=derive_signed_copy_status(scans, reviews),
        scans=[
            _signed_scan_response(
                scan,
                status_value=(
                    "accepted"
                    if latest_reviews.get(scan.id) and latest_reviews[scan.id].action == "accept"
                    else "replacement_requested"
                    if latest_reviews.get(scan.id)
                    else "uploaded_pending_review"
                ),
                review=latest_reviews.get(scan.id),
            )
            for scan in scans
        ],
    )


@router.get("/events/{event_id}/signed-scans", response_model=SignedScanLedgerResponse)
async def get_returned_signed_scans(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    event, scans = await list_signed_scans(db, tenant_id=user.tenant_id, event_id=event_id)
    reviews = await list_signed_scan_reviews(db, tenant_id=user.tenant_id, event_id=event.id)
    latest_reviews = {review.signed_scan_id: review for review in reviews}
    return SignedScanLedgerResponse(
        event_id=event.id,
        status=derive_signed_copy_status(scans, reviews),
        scans=[
            _signed_scan_response(
                scan,
                status_value=(
                    "accepted"
                    if latest_reviews.get(scan.id) and latest_reviews[scan.id].action == "accept"
                    else "replacement_requested"
                    if latest_reviews.get(scan.id)
                    else "uploaded_pending_review"
                ),
                review=latest_reviews.get(scan.id),
            )
            for scan in scans
        ],
    )


@router.get("/events/{event_id}/signed-scans/{scan_id}/download")
async def download_returned_signed_scan(
    event_id: UUID,
    scan_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    event = await _eligible_event(db, tenant_id=user.tenant_id, event_id=event_id)
    scan = await db.scalar(
        select(TrainingEvidenceSignedScan).where(
            TrainingEvidenceSignedScan.id == scan_id,
            TrainingEvidenceSignedScan.tenant_id == user.tenant_id,
            TrainingEvidenceSignedScan.event_id == event.id,
        )
    )
    if scan is None:
        raise HTTPException(status_code=404, detail="Signed copy not found")
    content = get_storage().get_bytes(scan.storage_key)
    if content is None:
        raise HTTPException(status_code=404, detail="Signed copy is unavailable")
    return StreamingResponse(
        iter((content,)),
        media_type=scan.content_type,
        headers={"Content-Disposition": f'inline; filename="{scan.original_filename}"'},
    )


@router.post(
    "/events/{event_id}/signed-scans/{scan_id}/review",
    response_model=SignedScanReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def review_returned_signed_scan(
    event_id: UUID,
    scan_id: UUID,
    payload: SignedScanReviewCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    if getattr(user, "is_impersonating", False):
        raise HTTPException(status_code=403, detail="Impersonation cannot review returned evidence")
    review = await review_signed_scan(
        db,
        tenant_id=user.tenant_id,
        reviewer_user_id=user.id,
        event_id=event_id,
        scan_id=scan_id,
        action=payload.action,
        reason=payload.reason,
    )
    return SignedScanReviewResponse.model_validate(
        {**review.__dict__, "status": "accepted" if payload.action == "accept" else "replacement_requested"}
    )


@router.post("/events/{event_id}/corrections", response_model=EvidenceEventResponse, status_code=201)
async def correct_training_evidence(
    event_id: UUID,
    payload: EvidenceCorrectionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    parent = await get_event(db, user.tenant_id, event_id)
    if parent.procedure_type in {"training", "knowledge_check"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "system_evidence_workflow_required",
                "message": "Training and knowledge-check evidence is corrected by the trusted learning workflow",
            },
        )
    if parent.procedure_type in {"internal_attestation", "admission_decision"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "regulated_evidence_workflow_required",
                "message": "Attestation and admission evidence requires a dedicated regulated workflow",
            },
        )
    return await record_event(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        user_id=payload.user_id,
        enrollment_id=payload.enrollment_id,
        content_release_id=payload.content_release_id,
        training_procedure_id=payload.training_procedure_id,
        procedure_type=payload.procedure_type,
        payload_snapshot=payload.payload_snapshot,
        record_type="correction",
        related_event_id=event_id,
        reason=payload.reason,
    )


@router.post("/events/{event_id}/revocations", response_model=EvidenceEventResponse, status_code=201)
async def revoke_training_evidence(
    event_id: UUID,
    payload: EvidenceRevocationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    parent = await get_event(db, user.tenant_id, event_id)
    return await record_event(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        user_id=parent.user_id,
        enrollment_id=parent.enrollment_id,
        content_release_id=parent.content_release_id,
        procedure_type=parent.procedure_type,
        payload_snapshot={"revoked_event_id": str(parent.id), "reason": payload.reason},
        record_type="revocation",
        related_event_id=event_id,
        reason=payload.reason,
    )


@router.get("/events/{event_id}/step-up-confirmations", response_model=list[StepUpConfirmationResponse])
async def get_step_up_confirmations(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    return await list_step_up_confirmations(db, user.tenant_id, event_id)


@router.post("/events/{event_id}/legal-hold", response_model=LegalHoldResponse, status_code=201)
async def create_legal_hold(
    event_id: UUID,
    payload: LegalHoldCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    return await add_legal_hold(
        db,
        tenant_id=user.tenant_id,
        event_id=event_id,
        actor_user_id=user.id,
        action=payload.action,
        reason=payload.reason,
    )


@router.get("/events/{event_id}/legal-hold", response_model=list[LegalHoldResponse])
async def get_legal_holds(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_EVIDENCE_WRITERS)),
):
    return await list_legal_holds(db, user.tenant_id, event_id)
