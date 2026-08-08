"""Public invitation endpoints (no auth).

Used by /accept-invite page to:
- View invitation details (GET /invitations/{token})
- Send a scoped email OTP (POST /invitations/{token}/request-code)
- Accept invitation after OTP verification (POST /invitations/{token}/accept)

Public — anyone with the token can call. Token is 32-char URL-safe (~190 bits entropy).
Rate-limited by network identity and a hashed token bucket.
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.router import _set_refresh_cookie
from app.modules.users.invitations_service import (
    accept_invitation,
    get_public_invitation,
    request_invitation_code,
)
from app.modules.users.schemas import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCodeResponse,
    InvitationPublicView,
)

router = APIRouter(prefix="/invitations", tags=["invitations"])
logger = logging.getLogger(__name__)


@router.get("/{token}", response_model=InvitationPublicView)
async def view_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public view of an invitation by token. No auth required."""
    result = await get_public_invitation(db, token)
    # The service returns dict; shape matches InvitationPublicView
    return result


@router.post("/{token}/request-code", response_model=InvitationCodeResponse)
async def request_invitation_email_code(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Send a one-time code to the HR-managed invitation email."""
    return await request_invitation_code(db, token)


@router.post("/{token}/accept", response_model=InvitationAcceptResponse)
async def accept_invitation_endpoint(
    token: str,
    request: Request,
    response: Response,
    payload: InvitationAcceptRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Accept invitation after email OTP verification and issue JWTs.

    The invitation token identifies the HR-managed learner record. The scoped
    email code proves control of the stored address before activation.

    Captures client IP and User-Agent for audit. HR can review
    accepted_ip / accepted_user_agent in /users/invitations to spot
    suspicious accepts (different IP/UA than expected).
    """
    # Extract client IP — handle X-Forwarded-For (Render proxy)
    ip = request.client.host if request.client and request.client.host else None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
    ua = request.headers.get("user-agent", "")

    try:
        result = await accept_invitation(
            db,
            token=token,
            code=payload.code,
            accepted_ip=ip,
            accepted_user_agent=ua,
        )
        if result.get("refresh_token"):
            _set_refresh_cookie(response, result["refresh_token"])
        result.pop("refresh_token", None)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Invitation acceptance failed")
        raise HTTPException(
            status_code=500,
            detail="Не удалось принять приглашение",
        ) from exc
