"""Public invitation endpoints (no auth).

Used by /accept-invite page to:
- View invitation details (GET /invitations/{token})
- Accept invitation and create password (POST /invitations/{token}/accept)

Public — anyone with the token can call. Token is 32-char URL-safe (~190 bits entropy).
Rate-limited by token uniqueness; brute force infeasible.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.users.schemas import (
    InvitationPublicView,
    InvitationAcceptRequest,
    InvitationAcceptResponse,
)
from app.modules.users.invitations_service import (
    get_public_invitation,
    accept_invitation,
)

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.get("/{token}", response_model=InvitationPublicView)
async def view_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public view of an invitation by token. No auth required."""
    result = await get_public_invitation(db, token)
    # The service returns dict; shape matches InvitationPublicView
    return result


@router.post("/{token}/accept", response_model=InvitationAcceptResponse)
async def accept_invitation_endpoint(
    token: str,
    payload: InvitationAcceptRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Accept invitation: set password, activate user, issue JWT.

    No auth required — token is the credential. After success, frontend
    stores the access_token and redirects to /dashboard.
    """
    try:
        result = await accept_invitation(
            db,
            token=token,
            first_name=payload.first_name,
            last_name=payload.last_name,
            password=payload.password,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Accept failed: {e}")
