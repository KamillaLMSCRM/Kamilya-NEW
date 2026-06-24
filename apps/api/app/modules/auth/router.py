from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from starlette.responses import JSONResponse
from app.core.auth import create_access_token, get_current_user
from app.core.db import get_db
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserResponse
from app.modules.auth.service import authenticate_user, create_user_and_tokens, refresh_access_token, blacklist_refresh_token
from app.modules.auth.auth_sessions import generate_auth_code, check_code
from app.modules.audit.service import log_action
from app.models.tenants import Tenant
from app.models.users import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db=Depends(get_db)):
    import logging
    logger = logging.getLogger(__name__)
    try:
        user, access_token, refresh_token = await authenticate_user(db, req.email, req.password)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"authenticate_user failed: {e}")
        raise
    try:
        await log_action(
            db, user.tenant_id, "login", "user",
            resource_id=str(user.id), user_id=user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as e:
        logger.exception(f"log_action failed: {e}")
        raise
    await db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=900)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db=Depends(get_db)):
    try:
        new_token = await refresh_access_token(db, req.refresh_token)
        return TokenResponse(access_token=new_token, refresh_token=req.refresh_token, expires_in=900)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.post("/logout")
async def logout(req: RefreshRequest, request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    await blacklist_refresh_token(db, req.refresh_token)
    await log_action(
        db, user.tenant_id, "logout", "user",
        resource_id=str(user.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/register", response_model=TokenResponse)
async def register(req: UserCreate, request: Request, db=Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.slug == req.email.split("@")[-1]))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(id=req.tenant_id, name=req.email.split("@")[-1], slug=req.email.split("@")[-1], status="trial")
        db.add(tenant)
        await db.flush()

    user, access_token, refresh_token = await create_user_and_tokens(
        db, tenant.id, req.email, req.first_name, req.last_name, password=req.password, role="student"
    )
    await log_action(
        db, tenant.id, "register", "user",
        resource_id=str(user.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
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
    import logging
    logger = logging.getLogger(__name__)
    try:
        code, expires_in = await generate_auth_code()
        logger.info(f"Generated auth code: {code}")
        return GenerateCodeResponse(code=code, expires_in=expires_in)
    except Exception as e:
        logger.exception(f"Error generating auth code: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-code")
async def check_auth_code(req: CheckCodeRequest):
    """Poll for code verification status. Returns JWT when verified."""
    from starlette.responses import JSONResponse

    try:
        result = await check_code(req.code)
    except Exception:
        return JSONResponse(content={"verified": False, "error": "check_error"})

    error = result.get("error")
    if error == "not_found":
        return JSONResponse(content={"verified": False, "error": "Code not found"})
    if error == "expired":
        return JSONResponse(content={"verified": False, "error": "Code expired"})

    if not result["verified"]:
        return JSONResponse(content={"verified": False})

    user_data = result["user"]
    access_token = create_access_token({
        "sub": user_data["user_id"],
        "tenant_id": user_data["tenant_id"],
        "roles": [user_data["role"]],
    })

    return JSONResponse(content={
        "verified": True,
        "access_token": access_token,
        "user": user_data,
    })


# ── Demo Login ─────────────────────────────────────────────────────────

DEMO_TENANT_SLUG = "demo"
DEMO_USERS = {
    "admin": {
        "telegram_id": 900000001,
        "email": "admin@demo.kml",
        "first_name": "Админ",
        "last_name": "Демо",
        "role": "admin",
    },
    "teacher": {
        "telegram_id": 900000002,
        "email": "teacher@demo.kml",
        "first_name": "Айгуль",
        "last_name": "Методологова",
        "role": "teacher",
    },
    "student": {
        "telegram_id": 900000003,
        "email": "student@demo.kml",
        "first_name": "Арман",
        "last_name": "Обучаев",
        "role": "student",
    },
}


class DemoLoginRequest(BaseModel):
    role: str


@router.post("/demo-login")
async def demo_login(req: DemoLoginRequest, db=Depends(get_db)):
    """Login as a demo user for the given role. Creates user/tenant if needed.
    In production: rate-limited, creates only non-admin roles."""
    import logging
    from app.core.config import get_settings
    settings = get_settings()
    logger = logging.getLogger(__name__)

    if settings.APP_ENV == "production" and req.role == "admin":
        raise HTTPException(status_code=404, detail="Admin demo login not available in production")

    if req.role not in DEMO_USERS:
        raise HTTPException(status_code=400, detail=f"Unknown demo role: {req.role}")

    demo = DEMO_USERS[req.role]

    try:
        # Ensure demo tenant exists
        result = await db.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
        tenant = result.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(name="Демо-организация", slug=DEMO_TENANT_SLUG, status="active")
            db.add(tenant)
            await db.flush()

        # Find or create demo user (search by telegram_id within demo tenant)
        result = await db.execute(
            select(User).where(User.telegram_id == demo["telegram_id"], User.tenant_id == tenant.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                tenant_id=tenant.id,
                telegram_id=demo["telegram_id"],
                email=demo["email"],
                first_name=demo["first_name"],
                last_name=demo["last_name"],
                role=demo["role"],
                is_active=True,
                status="active",
            )
            db.add(user)
            await db.flush()

        access_token = create_access_token({
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "roles": [user.role],
        })

        user_data = {
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "telegram_id": str(user.telegram_id),
            "role": user.role,
            "full_name": f"{user.first_name} {user.last_name}",
        }

        return JSONResponse(content={
            "access_token": access_token,
            "user": user_data,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"demo_login failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
