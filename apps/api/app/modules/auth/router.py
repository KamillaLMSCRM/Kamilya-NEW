import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, text
from starlette.responses import JSONResponse

from app.core.auth import create_access_token, create_refresh_token, decode_token, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.email import EmailService
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.auth.auth_sessions import (
    AuthSessionStoreUnavailableError,
    check_code,
    generate_auth_code,
)
from app.modules.auth.browser_session import BrowserSessionPolicy, get_browser_session_policy
from app.modules.auth.email_otp import consume_email_code, create_email_code
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RoleSwitchRequest,
    TokenResponse,
)
from app.modules.auth.service import (
    authenticate_user,
    blacklist_refresh_token,
    build_user_payload,
    get_user_roles,
    issue_refresh_session,
    refresh_access_token,
)
from app.modules.auth.telegram import is_telegram_login_enabled
from app.modules.demo.service import ensure_demo_student_course

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _enforce_browser_session_request(request: Request) -> BrowserSessionPolicy:
    """Resolve and enforce the browser boundary before auth/DB dependencies."""
    browser_session = get_browser_session_policy()
    browser_session.enforce_request(request)
    return browser_session


async def _get_browser_session_current_user(
    _browser_session: Annotated[BrowserSessionPolicy, Depends(_enforce_browser_session_request)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Order the browser boundary ahead of access-token user resolution."""
    return current_user


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, response: Response, db=Depends(get_db)):
    browser_session = get_browser_session_policy()
    browser_session.enforce_request(request)
    try:
        user, access_token, refresh_token = await authenticate_user(db, req.email, req.password)
    except HTTPException:
        raise
    except Exception:
        logger.error("authenticate_user_failed")
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
    except Exception:
        logger.error("login_audit_failed")
        raise
    await issue_refresh_session(db, user, refresh_token, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None)
    await db.commit()
    # Set refresh token as httpOnly cookie only after its allowlist row is durable.
    browser_session.set_refresh_cookie(response, refresh_token)
    user_payload = await build_user_payload(db, user)
    return TokenResponse(
        access_token=access_token,
        expires_in=900,
        user=user_payload,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, request: Request, response: Response, db=Depends(get_db)):
    browser_session = get_browser_session_policy()
    refresh_token = browser_session.read_refresh_token(request, req.refresh_token)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        new_access, new_refresh, user_payload = await refresh_access_token(db, refresh_token)
    except Exception:
        # Keep the response identical to a real auth failure so we don't
        # leak which JWT claim failed (e.g. aud vs exp). Lesson 17.
        import logging
        logging.getLogger(__name__).exception("/refresh failed")
        error_response = JSONResponse(status_code=401, content={"detail": "Invalid refresh token"})
        browser_session.clear_refresh_cookie(error_response)
        return error_response
    await db.commit()
    browser_session.set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=new_access,
        expires_in=900,
        user=user_payload,
    )


@router.post("/switch-role", response_model=TokenResponse)
async def switch_role(
    req: RoleSwitchRequest,
    request: Request,
    response: Response,
    browser_session: Annotated[BrowserSessionPolicy, Depends(_enforce_browser_session_request)],
    current_user: Annotated[User, Depends(_get_browser_session_current_user)],
    db=Depends(get_db),
):
    """Select one of the roles assigned to the current tenant account."""
    prior_refresh = browser_session.read_refresh_token(request)
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
    if prior_refresh:
        try:
            await blacklist_refresh_token(db, prior_refresh)
        except HTTPException:
            # A stale/invalid cookie must not prevent an authenticated user
            # from selecting another role. The replacement session below is
            # still allowlisted before it is returned.
            pass
    user_payload = await build_user_payload(db, user, active_role=req.role)
    await issue_refresh_session(db, user, refresh_token)
    await db.commit()
    browser_session.set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
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
    browser_session = get_browser_session_policy()
    refresh_token = browser_session.read_refresh_token(request, req.refresh_token)
    user = None
    if refresh_token:
        # Best-effort revocation — malformed or expired credentials must not
        # prevent the browser cookie from being cleared.
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") == "refresh":
                await blacklist_refresh_token(db, refresh_token)
                user_id = UUID(payload["sub"])
                user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        except Exception:
            user = None
    if user is not None:
        # AuditLog.tenant_id is NOT NULL, while a platform superadmin has no
        # tenant. Keep platform events in the established sentinel scope so
        # the audit insert cannot roll back refresh-session revocation.
        audit_tenant_id = user.tenant_id or UUID(int=0)
        await log_action(
            db, audit_tenant_id, "logout", "user",
            resource_id=str(user.id), user_id=user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    await db.commit()
    browser_session.clear_refresh_cookie(response)
    return {"status": "ok"}


@router.post("/register", include_in_schema=False)
async def register() -> None:
    """Retired: tenant membership is invitation-bound, trials use /tenants/register."""
    raise HTTPException(status_code=410, detail="Use the tenant trial or invitation flow")


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


class AuthCapabilitiesResponse(BaseModel):
    telegram_login_enabled: bool


@router.get("/capabilities", response_model=AuthCapabilitiesResponse)
async def auth_capabilities() -> AuthCapabilitiesResponse:
    """Return safe, public capability flags for the login screen."""
    return AuthCapabilitiesResponse(
        telegram_login_enabled=is_telegram_login_enabled(),
    )


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
async def verify_email_code(req: EmailCodeVerifyRequest, request: Request, response: Response, db=Depends(get_db)):
    browser_session = get_browser_session_policy()
    browser_session.enforce_request(request)
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

    verified_at = datetime.now(timezone.utc)
    user.last_login = verified_at
    user.email_verified_at = verified_at
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
    await issue_refresh_session(db, user, refresh_token)
    await log_action(
        db,
        user.tenant_id,
        "login.email_otp",
        "user",
        resource_id=str(user.id),
        user_id=user.id,
    )
    await db.commit()
    browser_session.set_refresh_cookie(response, refresh_token)
    return {
        "verified": True,
        "access_token": access_token,
        "expires_in": 900,
        "user": user_payload,
    }


@router.post("/generate-code", response_model=GenerateCodeResponse)
async def generate_code():
    """Generate a 6-digit code for Telegram bot authentication."""
    if not is_telegram_login_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "telegram_unavailable",
                "message": "Telegram login is temporarily unavailable.",
            },
        )

    try:
        code, expires_in = await generate_auth_code()
        return GenerateCodeResponse(code=code, expires_in=expires_in)
    except AuthSessionStoreUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from None
    except Exception:
        # Never include a one-time code or provider details in application logs.
        logger.error("telegram_auth_code_generation_failed")
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable") from None


@router.post("/check-code")
async def check_auth_code(req: CheckCodeRequest, request: Request, response: Response, db=Depends(get_db)):
    """Poll for code verification status. Returns JWT when verified.

    On a successful verification we also mint a refresh token and set it
    as an httpOnly cookie — otherwise the in-memory access token is the
    only thing carrying the session, and any page reload (which clears
    the in-memory store) would log the user out. Mirrors what /auth/login
    does for the email/password flow.
    """

    browser_session = get_browser_session_policy()
    browser_session.enforce_request(request)
    try:
        result = await check_code(req.code)
    except Exception:
        return JSONResponse(content={"verified": False, "error": "check_error"})

    error = result.get("error")
    if error == "unavailable":
        return JSONResponse(
            status_code=503,
            content={
                "verified": False,
                "error": "Authentication service temporarily unavailable",
            },
        )
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
    from types import SimpleNamespace
    user = SimpleNamespace(
        id=UUID(user_data["user_id"]),
        tenant_id=UUID(user_data["tenant_id"]) if user_data["tenant_id"] else None,
        role=user_data["role"],
    )
    await issue_refresh_session(db, user, refresh_token)
    await db.commit()
    browser_session.set_refresh_cookie(response, refresh_token)

    return {
        "verified": True,
        "access_token": access_token,
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
async def demo_login(req: DemoLoginRequest, request: Request, response: Response, db=Depends(get_db)):
    """Login as a demo user for the given role. Creates user/tenant if needed.

    Production gate (audit §4.8):
    - methodologist/student: always allowed (safe — no privilege escalation).
    - admin/superadmin: REJECTED in production. Was previously gated by
      ALLOW_ADMIN_DEMO / ALLOW_SUPERADMIN_DEMO env vars, but those were
      temporary opt-ins for E2E testing. E2E tests now exist (see
      apps/web/tests/e2e/) so the opt-in escape hatch is removed.
    """
    browser_session = get_browser_session_policy()
    browser_session.enforce_request(request)
    import logging
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
                tenant = Tenant(
                    name="Демо-организация",
                    slug=DEMO_TENANT_SLUG,
                    status="active",
                    is_demo=True,
                )
                db.add(tenant)
                await db.flush()

        # The reserved demo slug is always a sandbox. Repair legacy rows that
        # predate the explicit flag so demo limits and cleanup remain active.
        if target_tenant_slug == DEMO_TENANT_SLUG and not tenant.is_demo:
            tenant.is_demo = True
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

        if req.role == "student":
            course_id = await ensure_demo_student_course(
                db,
                tenant_id=tenant.id,
                student_id=user.id,
            )
            if course_id is None:
                raise HTTPException(
                    status_code=503,
                    detail="Demo course is temporarily unavailable",
                )

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
        await issue_refresh_session(db, user, refresh_token)
        await db.commit()
        browser_session.set_refresh_cookie(response, refresh_token)

        return {
            "access_token": access_token,
            "user": user_data,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("demo_login_failed")
        raise HTTPException(status_code=500, detail="Demo login failed") from None
