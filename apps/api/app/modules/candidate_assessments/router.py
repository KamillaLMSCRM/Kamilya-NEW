# ruff: noqa: B008
from __future__ import annotations

# FastAPI dependencies are intentionally declared in signatures.
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.models.users import User
from app.modules.candidate_assessments import service
from app.modules.candidate_assessments.models import (
    AssessmentCandidate,
    CandidateAccessCredential,
    CandidateAssessmentAttempt,
    CandidateAssessmentCampaign,
)
from app.modules.candidate_assessments.schemas import (
    CampaignCreate,
    CampaignUpdate,
    CandidateCreate,
    CandidateStatusUpdate,
    PinRequest,
    Submission,
)

router = APIRouter(prefix="/candidate-assessments", tags=["candidate-assessments"])
public_router = APIRouter(prefix="/candidate-assessment", tags=["candidate-assessment-public"])
candidate_bearer = HTTPBearer(auto_error=False)


def _campaign_payload(item: CandidateAssessmentCampaign) -> dict:
    return {
        "id": item.id,
        "content_release_id": item.content_release_id,
        "title": item.title,
        "instructions": item.instructions,
        "status": item.status,
        "expires_at": item.expires_at,
        "attempt_limit": item.attempt_limit,
        "retention_days": item.retention_days,
        "created_at": item.created_at,
    }


@router.get("")
async def list_campaigns(db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))):  # noqa: B008
    rows = (
        await db.scalars(
            select(CandidateAssessmentCampaign)
            .where(CandidateAssessmentCampaign.tenant_id == user.tenant_id)
            .order_by(CandidateAssessmentCampaign.created_at.desc())
        )
    ).all()
    return [_campaign_payload(row) for row in rows]


@router.post("", status_code=201)
async def create_campaign(
    payload: CampaignCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):  # noqa: B008
    try:
        return _campaign_payload(await service.create_campaign(db, user.tenant_id, user.id, payload))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):  # noqa: B008
    campaign = await db.scalar(
        select(CandidateAssessmentCampaign)
        .where(CandidateAssessmentCampaign.id == campaign_id, CandidateAssessmentCampaign.tenant_id == user.tenant_id)
        .with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, key, value)
    await db.flush()
    return _campaign_payload(campaign)


@router.post("/{campaign_id}/candidates", status_code=201)
async def invite_candidate(
    campaign_id: UUID,
    payload: CandidateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):  # noqa: B008
    try:
        return await service.add_candidate(db, campaign_id, user.tenant_id, payload, get_settings().PUBLIC_URL)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{campaign_id}/candidates")
async def list_candidates(
    campaign_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):  # noqa: B008
    campaign = await db.scalar(
        select(CandidateAssessmentCampaign.id).where(
            CandidateAssessmentCampaign.id == campaign_id, CandidateAssessmentCampaign.tenant_id == user.tenant_id
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    rows = (
        await db.scalars(
            select(AssessmentCandidate)
            .where(AssessmentCandidate.campaign_id == campaign_id, AssessmentCandidate.tenant_id == user.tenant_id)
            .order_by(AssessmentCandidate.created_at)
        )
    ).all()
    return [
        {
            "id": row.id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
            "phone": row.phone,
            "status": row.status,
            "retention_until": row.retention_until,
        }
        for row in rows
    ]


@router.patch("/candidates/{candidate_id}/status")
async def update_candidate_status(
    candidate_id: UUID,
    payload: CandidateStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):  # noqa: B008
    candidate = await db.scalar(
        select(AssessmentCandidate)
        .where(AssessmentCandidate.id == candidate_id, AssessmentCandidate.tenant_id == user.tenant_id)
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    candidate.status = payload.status
    if payload.status == "withdrawn":
        await db.execute(
            CandidateAccessCredential.__table__.update()
            .where(
                CandidateAccessCredential.candidate_id == candidate.id,
                CandidateAccessCredential.tenant_id == user.tenant_id,
                CandidateAccessCredential.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    await db.flush()
    return {"id": candidate.id, "status": candidate.status}


@router.delete("/candidates/{candidate_id}")
async def redact_candidate(
    candidate_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):  # noqa: B008
    candidate = await db.scalar(
        select(AssessmentCandidate)
        .where(AssessmentCandidate.id == candidate_id, AssessmentCandidate.tenant_id == user.tenant_id)
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    candidate.first_name, candidate.last_name, candidate.email, candidate.phone, candidate.status = (
        "Deleted",
        "",
        None,
        None,
        "deleted",
    )
    await db.execute(
        CandidateAccessCredential.__table__.update()
        .where(
            CandidateAccessCredential.candidate_id == candidate.id,
            CandidateAccessCredential.tenant_id == user.tenant_id,
            CandidateAccessCredential.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.flush()
    return {"id": candidate.id, "status": "deleted"}


@router.get("/{campaign_id}/results.csv")
async def export_results(
    campaign_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):  # noqa: B008
    rows = (
        await db.execute(
            select(CandidateAssessmentCampaign, AssessmentCandidate, CandidateAssessmentAttempt)
            .join(AssessmentCandidate, AssessmentCandidate.campaign_id == CandidateAssessmentCampaign.id)
            .join(CandidateAssessmentAttempt, CandidateAssessmentAttempt.candidate_id == AssessmentCandidate.id)
            .where(
                CandidateAssessmentCampaign.id == campaign_id,
                CandidateAssessmentCampaign.tenant_id == user.tenant_id,
                CandidateAssessmentAttempt.status == "submitted",
            )
            .order_by(AssessmentCandidate.last_name, CandidateAssessmentAttempt.attempt_number)
        )
    ).all()
    if (
        not rows
        and await db.scalar(
            select(CandidateAssessmentCampaign.id).where(
                CandidateAssessmentCampaign.id == campaign_id, CandidateAssessmentCampaign.tenant_id == user.tenant_id
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return Response(
        service.results_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="candidate-results.csv"'},
    )


@public_router.post("/{token}/exchange")
async def exchange(token: str, payload: PinRequest, db: AsyncSession = Depends(get_db)):  # noqa: B008
    tenant_id = await service.establish_context(db, token)
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="Assessment link not found")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
    try:
        result = await service.exchange(db, token, payload.pin, payload.consent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=401, detail="Assessment link or PIN is invalid")
    return result


@public_router.post("/submit")
async def submit(
    payload: Submission,
    credentials: HTTPAuthorizationCredentials | None = Depends(candidate_bearer),
    db: AsyncSession = Depends(get_db),
):  # noqa: B008
    if credentials is None:
        raise HTTPException(status_code=401, detail="Candidate assessment access required")
    try:
        claims = service.candidate_claims(credentials.credentials)
        await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": claims["tenant_id"]})
        return await service.submit(
            db, claims, payload.attempt_id, [answer.model_dump(mode="json") for answer in payload.answers]
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Active assessment not found") from exc
