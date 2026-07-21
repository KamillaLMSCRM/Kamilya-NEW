from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, text
from starlette.responses import JSONResponse
from datetime import datetime, timezone
from uuid import UUID
from app.core.auth import create_access_token, create_refresh_token, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.email import EmailService
from app.modules.auth.schemas import LoginRequest, RefreshRequest, RoleSwitchRequest, TokenResponse, UserCreate, UserResponse
from app.modules.auth.service import (
    authenticate_user,
    create_user_and_tokens,
    refresh_access_token,
    blacklist_refresh_token,
    build_user_payload,
    get_user_roles,
)
from app.modules.auth.auth_sessions import generate_auth_code, check_code
from app.modules.auth.email_otp import create_email_code, consume_email_code
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
# on plain HTTP.
#
# SameSite=None is required because the frontend at app.kml.kz makes
# cross-origin XHR/fetch requests directly to the API at
# kamilya-lms-api.onrender.com. Browsers (Chrome/Firefox/Safari) refuse to
# set a cookie with SameSite=Strict or SameSite=Lax in a cross-origin
# response, which made the refresh cookie silently disappear — breaking
# session persistence on every page reload (see session-repair 2026-06-29).
#
# IMPORTANT: per RFC 6265bis and the Chrome/Firefox/Safari implementations,
# a cookie with SameSite=None MUST also have Secure=true or the browser
# drops it on the floor. We therefore always set Secure=True (the API is
# always reached via HTTPS — on Render via the *.onrender.com TLS endpoint,
# and locally via the Vercel preview proxy or a developer-managed reverse
# proxy that terminates TLS).
#
# For local plain-HTTP dev (e.g. uvicorn on http://localhost:8000), the
# cookie will be ignored by the browser. Workaround: use the Vercel
# preview URL (https://web-*.vercel.app) which proxies /api/v1/* to
# localhost via ssh-tunnel or similar — the dev cookie path.
#
# CSRF defense instead relies on:
#   1. The cookie path being /api/v1/auth only — it is never sent on
#      state-changing endpoints outside auth.
#   2. The frontend never sending the refresh token in a body or custom
#      header that an attacker page could forge.
#   3. rotate-on-use: every /refresh consumes the old refresh and issues a
#      new one (see service.refresh_access_token), so a stolen refresh
#      token is single-use.
# ---------------------------------------------------------------------------
REFRESH_COOKIE_NAME = "kamilya_refresh"
REFRESH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days, matches REFRESH_TOKEN_EXPIRE_DAYS


def _append_partitioned_cookie_attribute(response: Response, cookie_name: str) -> None:
    prefix = f"{cookie_name}=".lower().encode()
    for index in range(len(response.raw_headers) - 1, -1, -1):
        key, value = response.raw_headers[index]
        if key.lower() == b"set-cookie" and value.lower().startswith(prefix) and b"partitioned" not in value.lower():
            response.raw_headers[index] = (key, value + b"; Partitioned")
            return


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS,
        path="/api/v1/auth",  # Only sent to auth endpoints — minimizes XSRF surface
        httponly=True,
        secure=True,  # Required by SameSite=None (RFC 6265bis)
        samesite="none",
        # CHIPS (Cookies Having Independent Partitioned State) — lets Chrome
        # store the cookie even when the API is on a different eTLD+1
        # (kamilya-lms-api.onrender.com) than the top-level site
        # (app.kml.kz). Without Partitioned, Chrome's third-party cookie
        # handling silently drops the cookie on cross-site requests, which
        # broke login in 2026-06-29 because the Vercel Edge middleware
        # (apps/web/src/middleware.ts) couldn't see the refresh cookie on
        # the /dashboard navigation and 307'd the user back to /login.
    )
    _append_partitioned_cookie_attribute(response, REFRESH_COOKIE_NAME)


def _clear_refresh_cookie(response: Response) -> None:
    # Note: starlette's Response.delete_cookie() in 0.41.x does NOT accept
    # the `partitioned` kwarg (only set_cookie does). We work around by
    # setting a same-attribute Set-Cookie with max-age=0. See
    # https://github.com/encode/starlette/issues/2529
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value="",
        max_age=0,
        path="/api/v1/auth",
        secure=True,
        samesite="none",
    )
    _append_partitioned_cookie_attribute(response, REFRESH_COOKIE_NAME)


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
        # The regular email login intentionally supports the legacy/platform
        # superadmin account. Its tenant_id is NULL, so the audit insert must
        # use the same explicit RLS context as the dedicated superadmin login
        # endpoint; otherwise FORCE RLS turns a valid login into a 500.
        if user.tenant_id is None and user.role == "superadmin":
            await db.execute(text("SELECT set_config('app.is_superadmin', 'true', true)"))
        audit_tenant_id = user.tenant_id
        if user.tenant_id is None and user.role == "superadmin":
            # audit_logs predates platform-level accounts and keeps tenant_id
            # NOT NULL. Keep platform events on the same sentinel used by the
            # dedicated superadmin login endpoint.
            audit_tenant_id = UUID("00000000-0000-0000-0000-000000000000")
        await log_action(
            db, audit_tenant_id, "login", "user",
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
        new_access, new_refresh, user_payload = await refresh_access_token(db, refresh_token)
    except Exception:
        # Keep the response identical to a real auth failure so we don't
        # leak which JWT claim failed (e.g. aud vs exp). Lesson 17.
        import logging
        logging.getLogger(__name__).exception("/refresh failed")
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=900,
        user=user_payload,
    )


@router.post("/switch-role", response_model=TokenResponse)
async def switch_role(
    req: RoleSwitchRequest,
    response: Response,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Select one of the roles assigned to the current tenant account."""
    if getattr(current_user, "is_impersonating", False):
        raise HTTPException(status_code=403, detail="Role switching is unavailable while impersonating")

    user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    roles = await get_user_roles(db, user)
    if req.role not in roles:
        raise HTTPException(status_code=403, detail="Role is not assigned to this account")

    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "roles": roles,
        "active_role": req.role,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "active_role": req.role,
    })
    user_payload = await build_user_payload(db, user, active_role=req.role)
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=900,
        user=user_payload,
    )


@router.post("/logout")
async def logout(req: RefreshRequest, request: Request, response: Response, db=Depends(get_db)):
    # Logout used to depend on `get_current_user` (Bearer access-token),
    # which 401'd when the access-token expired (1h TTL) before logout
    # had a chance to blacklist the refresh-token. The user saw a 401 in
    # Network and thought logout was broken, even though the cookie was
    # already cleared client-side.
    #
    # The refresh-token itself is the source of truth for "is this user
    # still in a session we own" — its TTL is 30 days. We decode it,
    # look up the user, blacklist the token, log the action, clear the
    # cookie. No access-token required.
    refresh_token = _read_refresh_cookie_or_body(request, req.refresh_token)
    user = None
    if refresh_token:
        # Best-effort decode — if the token is malformed/expired/revoked
        # we still want to clear the cookie. Don't raise.
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") == "refresh":
                user_id = UUID(payload["sub"])
                user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        except Exception:
            user = None
        await blacklist_refresh_token(db, refresh_token)
    if user is not None:
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
        # Auto-create a new tenant from the email domain. The id is
        # server-generated (uuid4); we never trust the client to
        # provide a tenant_id. Lesson 17 cross-cutting rule: trust
        # the JWT for tenant_id, derive from email domain for new
        # tenants, never from request body.
        from uuid import uuid4
        domain = req.email.split("@")[-1]
        tenant = Tenant(
            id=uuid4(),
            name=domain,
            slug=domain,
            status="trial",
        )
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


class EmailCodeRequest(BaseModel):
    email: str


class EmailCodeVerifyRequest(BaseModel):
    email: str
    code: str


class EmailCodeResponse(BaseModel):
    ok: bool
    expires_in: int = 300


async def _lookup_login_user_by_email(db, email: str) -> dict | None:
    result = await db.execute(
        text(
            """
            SELECT user_id, tenant_id, role, is_active
            FROM lookup_login_user_by_email(:email)
            """
        ),
        {"email": email.lower().strip()},
    )
    row = result.mappings().first()
    return dict(row) if row else None


@router.post("/email/request-code", response_model=EmailCodeResponse)
async def request_email_code(req: EmailCodeRequest, db=Depends(get_db)):
    """Send an email OTP when the user exists.

    Response is intentionally neutral to avoid disclosing which emails are
    registered in the system.
    """
    normalized_email = req.email.lower().strip()
    if "@" not in normalized_email:
        return EmailCodeResponse(ok=True)

    user_row = await _lookup_login_user_by_email(db, normalized_email)
    if not user_row or not user_row.get("is_active"):
        return EmailCodeResponse(ok=True)

    code, expires_in = await create_email_code(
        email=normalized_email,
        user_id=str(user_row["user_id"]),
        tenant_id=str(user_row["tenant_id"]) if user_row["tenant_id"] else None,
        role=user_row["role"] or "student",
    )
    await EmailService().send_login_code(to_email=normalized_email, code=code)
    return EmailCodeResponse(ok=True, expires_in=expires_in)


@router.post("/email/verify-code")
async def verify_email_code(req: EmailCodeVerifyRequest, response: Response, db=Depends(get_db)):
    normalized_email = req.email.lower().strip()
    normalized_code = req.code.strip()
    payload = await consume_email_code(email=normalized_email, code=normalized_code)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code")

    tenant_id = payload.get("tenant_id")
    if tenant_id:
        await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})

    user = (
        await db.execute(select(User).where(User.id == UUID(payload["user_id"])))
    ).scalar_one_or_none()
    if not user or not user.is_active or (user.email or "").lower() != normalized_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code")

    user.last_login = datetime.now(timezone.utc)
    await db.flush()
    user_payload = await build_user_payload(db, user)

    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "roles": user_payload["roles"],
        "active_role": user_payload["role"],
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "active_role": user_payload["role"],
    })
    _set_refresh_cookie(response, refresh_token)
    await log_action(
        db,
        user.tenant_id,
        "login.email_otp",
        "user",
        resource_id=str(user.id),
        user_id=user.id,
    )
    await db.commit()
    return {
        "verified": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": 900,
        "user": user_payload,
    }


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
    # FastAPI's default JSON encoder doesn't know how to serialise UUID.
    # auth_sessions stores user_data verbatim (it survives via UUID-aware
    # `_SessionEncoder`) but the response body we return here goes through
    # starlette's JSONResponse which uses stdlib json.dumps — crash.
    # Str-ify at the boundary so the frontend gets a normal JSON shape.
    from uuid import UUID
    if isinstance(user_data.get("tenant_id"), UUID):
        user_data["tenant_id"] = str(user_data["tenant_id"])
    if isinstance(user_data.get("user_id"), UUID):
        user_data["user_id"] = str(user_data["user_id"])
    if isinstance(user_data.get("telegram_id"), UUID):
        user_data["telegram_id"] = str(user_data["telegram_id"])
    tenant_obj = user_data.get("tenant")
    if isinstance(tenant_obj, dict) and isinstance(tenant_obj.get("id"), UUID):
        tenant_obj["id"] = str(tenant_obj["id"])

    access_token = create_access_token({
        "sub": user_data["user_id"],
        "tenant_id": user_data["tenant_id"],
        "roles": [user_data["role"]],
        "active_role": user_data["role"],
    })
    refresh_token = create_refresh_token({
        "sub": user_data["user_id"],
        "tenant_id": user_data["tenant_id"],
        "active_role": user_data["role"],
    })
    _set_refresh_cookie(response, refresh_token)

    return {
        "verified": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user_data,
    }


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
    "methodologist": {
        "telegram_id": 900000004,
        "email": "methodologist@demo.kml",
        "first_name": "Методист",
        "last_name": "Демо",
        "role": "methodologist",
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
    - methodologist/student: always allowed (safe — no privilege escalation).
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

        # The demo tenant may be created or resolved without an authenticated
        # request context. Establish the tenant scope before reading or
        # inserting the demo user under FORCE RLS.
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant.id)},
        )

        # Find or create demo user (search by telegram_id within the
        # target tenant — handles the case where a superadmin demo user
        # was previously created under the generic demo tenant and now
        # needs to migrate).
        result = await db.execute(
            select(User)
            .where(User.telegram_id == demo["telegram_id"], User.tenant_id == tenant.id)
            .order_by(User.created_at.desc())
            .limit(1)
        )
        # Historical demo runs can leave duplicate rows for the same
        # telegram_id in one tenant. The login path must remain available;
        # choose the newest deterministic row instead of raising
        # MultipleResultsFound from scalar_one_or_none().
        user = result.scalars().first()
        if user is None:
            # RLS bypass: same pattern as create_user_and_tokens — set
            # app.tenant_id before INSERT so the `tenant_isolation` policy
            # on `users` allows the row. demo_login creates the user inline
            # (does not go through create_user_and_tokens) so the policy
            # was failing here as well. See P1 QA 2026-07-10 bug #2.
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant.id)},
            )
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
            "active_role": user.role,
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
            "active_role": user.role,
        })
        _set_refresh_cookie(response, refresh_token)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"demo_login failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
