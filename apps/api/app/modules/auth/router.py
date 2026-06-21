from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from app.core.auth import create_access_token, get_current_user
from app.core.db import get_db
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserResponse
from app.modules.auth.service import authenticate_user, create_user_and_tokens, refresh_access_token, blacklist_refresh_token
from app.modules.auth.auth_sessions import generate_auth_code, check_code
from app.models.tenants import Tenant

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db=Depends(get_db)):
    user, access_token, refresh_token = await authenticate_user(db, req.email, req.password)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db=Depends(get_db)):
    try:
        new_token = await refresh_access_token(db, req.refresh_token)
        return TokenResponse(access_token=new_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.post("/logout")
async def logout(req: RefreshRequest, db=Depends(get_db), _=Depends(get_current_user)):
    await blacklist_refresh_token(db, req.refresh_token)
    return {"status": "ok"}


@router.post("/register", response_model=TokenResponse)
async def register(req: UserCreate, db=Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.slug == req.email.split("@")[-1]))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(id=req.tenant_id, name=req.email.split("@")[-1], slug=req.email.split("@")[-1], status="trial")
        db.add(tenant)
        await db.flush()

    user, access_token, refresh_token = await create_user_and_tokens(
        db, tenant.id, req.email, req.first_name, req.last_name, password=req.password
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=900)


# ── Telegram Bot Auth ──────────────────────────────────────────────────

class GenerateCodeResponse(BaseModel):
    code: str
    expires_in: int


class CheckCodeRequest(BaseModel):
    code: str


class CheckCodeResponse(BaseModel):
    verified: bool
    access_token: str | None = None
    user: dict | None = None
    error: str | None = None


@router.post("/generate-code", response_model=GenerateCodeResponse)
async def generate_code():
    """Generate a 6-digit code for Telegram bot authentication."""
    code, expires_in = generate_auth_code()
    return GenerateCodeResponse(code=code, expires_in=expires_in)


@router.post("/check-code", response_model=CheckCodeResponse)
async def check_auth_code(req: CheckCodeRequest):
    """Poll for code verification status. Returns JWT when verified."""
    result = check_code(req.code)

    error = result.get("error")
    if error == "not_found":
        return CheckCodeResponse(verified=False, error="Code not found")
    if error == "expired":
        return CheckCodeResponse(verified=False, error="Code expired")

    if not result["verified"]:
        return CheckCodeResponse(verified=False)

    # Generate JWT token
    user_data = result["user"]
    access_token = create_access_token({
        "sub": user_data["user_id"],
        "tenant_id": user_data["tenant_id"],
        "roles": [user_data["role"]],
    })

    return CheckCodeResponse(
        verified=True,
        access_token=access_token,
        user=user_data,
    )
