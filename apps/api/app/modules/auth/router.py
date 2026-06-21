from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserResponse
from app.modules.auth.service import authenticate_user, create_user_and_tokens, refresh_access_token, blacklist_refresh_token
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
