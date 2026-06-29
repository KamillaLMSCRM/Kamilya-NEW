from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from starlette.responses import JSONResponse
from app.core.auth import create_access_token, create_refresh_token, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserResponse
from app.modules.auth.service import authenticate_user, create_user_and_tokens, refresh_access_token, blacklist_refresh_token
from app.modules.auth.auth_sessions import generate_auth_code, check_code
from app.modules.audit.service import log_action
from app.models.tenants import Tenant
from app.models.users import User

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Refresh-token cookie helpers
# ---------------------------------------------------------------------------
# We store the refresh token in an httpOnly cookie so JavaScript cannot read
# it (XSS-stealing-resistant). The access token is returned in the JSON
# body and held in-memory by the frontend. On 401 the frontend calls
# /auth/refresh which reads the refresh-token cookie, mints a new access
# token, and (optionally) rotates the refresh cookie.
#
# Per audit §4.1: in production the cookie MUST be Secure (HTTPS only). In
# local dev Secure is omitted because browsers refuse to set Secure cookies
# on plain HTTP. SameSite=Strict prevents the cookie from being sent on
# cross-origin requests (defense against CSRF).
# ---------------------------------------------------------------------------
REFRESH_COOKIE_NAME = "kamilya_refresh"
REFRESH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days, matches REFRESH_TOKEN_EXPIRE_DAYS


def _is_production() -> bool:
    return get_settings().APP_ENV == "production"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS,
        path="/api/v1/auth",  # Only sent to auth endpoints — minimizes XSRF surface
        httponly=True,
        secure=_is_production(),
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
        secure=_is_production(),
        samesite="strict",
    )


def _read_refresh_cookie_or_body(request: Request, body_token: str | None) -> str | None:
    """Return refresh token from httpOnly cookie if present, else from body.

    Cookie is preferred because it survives across tabs and is rotated by
    the server on every successful refresh. Body is kept for backward
    compatibility with clients that haven't migrated yet.
    """
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    return cookie_token or body_token


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, response: Response, db=Depends(get_db)):
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
    # Set refresh token as httpOnly cookie; access token still returned in body.
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=900)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, request: Request, response: Response, db=Depends(get_db)):
    # Prefer refresh token from cookie; fall back to request body for legacy clients.
    refresh_token = _read_refresh_cookie_or_body(request, req.refresh_token)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        # refresh_access_token rotates the refresh token and returns the new one.
        new_access, new_refresh = await refresh_access_token(db, refresh_token)
    except Exception:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    # Re-issue the cookie with the rotated refresh token.
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh, expires_in=900)


@router.post("/logout")
async def logout(req: RefreshRequest, request: Request, response: Response, db=Depends(get_db), user=Depends(get_current_user)):
    refresh_token = _read_refresh_cookie_or_body(request, req.refresh_token)
    if refresh_token:
        await blacklist_refresh_token(db, refresh_token)
    await log_action(
        db, user.tenant_id, "logout", "user",
        resource_id=str(user.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    _clear_refresh_cookie(response)
    return {"status": "ok"}


@router.post("/register", response_model=TokenResponse)
async def register(req: UserCreate, request: Request, response: Response, db=Depends(get_db)):
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
    _set_refresh_cookie(response, refresh_token)
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
async def check_auth_code(req: CheckCodeRequest, response: Response):
    """Poll for code verification status. Returns JWT when verified.

    On a successful verification we also mint a refresh token and set it
    as an httpOnly cookie — otherwise the in-memory access token is the
    only thing carrying the session, and any page reload (which clears
    the in-memory store) would log the user out. Mirrors what /auth/login
    does for the email/password flow.
    """
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
    refresh_token = create_refresh_token({
        "sub": user_data["user_id"],
        "tenant_id": user_data["tenant_id"],
    })
    _set_refresh_cookie(response, refresh_token)

    return JSONResponse(content={
        "verified": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
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
    # Superadmin demo — only enabled in production when ALLOW_ADMIN_DEMO is set.
    # Used by the platform operator (Askar) to log in as superadmin via the
    # /login/demo UI without needing Telegram. The demo user is auto-created
    # on first login and bound to the existing `kamilya-demo` tenant so the
    # operator lands in the right organization context.
    "superadmin": {
        "telegram_id": 900000000,
        "email": "superadmin@demo.kml",
        "first_name": "Super",
        "last_name": "Admin",
        "role": "superadmin",
        "_tenant_slug": "kamilya-demo",  # always join this tenant
    },
}


class DemoLoginRequest(BaseModel):
    role: str


@router.post("/demo-login")
async def demo_login(req: DemoLoginRequest, response: Response, db=Depends(get_db)):
    """Login as a demo user for the given role. Creates user/tenant if needed.

    Production gate (audit §4.8):
    - teacher/student: always allowed (safe — no privilege escalation).
    - admin/superadmin: REJECTED in production. Was previously gated by
      ALLOW_ADMIN_DEMO / ALLOW_SUPERADMIN_DEMO env vars, but those were
      temporary opt-ins for E2E testing. E2E tests now exist (see
      apps/web/tests/e2e/) so the opt-in escape hatch is removed.
    """
    import logging
    from app.core.config import get_settings
    settings = get_settings()
    logger = logging.getLogger(__name__)

    # Block admin/superadmin demo-login in production unconditionally.
    if settings.APP_ENV == "production" and req.role in ("admin", "superadmin"):
        raise HTTPException(
            status_code=404,
            detail=f"{req.role.capitalize()} demo login is not available in production",
        )

    if req.role not in DEMO_USERS:
        raise HTTPException(status_code=400, detail=f"Unknown demo role: {req.role}")

    demo = DEMO_USERS[req.role]

    try:
        # Resolve tenant — superadmin demo binds to an existing operator
        # tenant so the JWT lands in the right org context.
        target_tenant_slug = demo.get("_tenant_slug") or DEMO_TENANT_SLUG
        result = await db.execute(select(Tenant).where(Tenant.slug == target_tenant_slug))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            # Fallback to the generic demo tenant if the operator-specified
            # one doesn't exist yet.
            result = await db.execute(select(Tenant).where(Tenant.slug == DEMO_TENANT_SLUG))
            tenant = result.scalar_one_or_none()
            if tenant is None:
                tenant = Tenant(name="Демо-организация", slug=DEMO_TENANT_SLUG, status="active")
                db.add(tenant)
                await db.flush()

        # Find or create demo user (search by telegram_id within the
        # target tenant — handles the case where a superadmin demo user
        # was previously created under the generic demo tenant and now
        # needs to migrate).
        result = await db.execute(
            select(User).where(User.telegram_id == demo["telegram_id"], User.tenant_id == tenant.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
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
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "is_demo": tenant.is_demo,
                "plan": tenant.plan,
            },
        }

        # Same httpOnly refresh-cookie contract as /login and /register.
        # Without this the in-memory access token is the only session
        # anchor and any page reload would log the user out.
        refresh_token = create_refresh_token({
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
        })
        _set_refresh_cookie(response, refresh_token)

        return JSONResponse(content={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_data,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"demo_login failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
