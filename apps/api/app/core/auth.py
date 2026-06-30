import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.users import User

logger = logging.getLogger(__name__)

settings = get_settings()
security = HTTPBearer()

ROLES = ['superadmin', 'admin', 'org_admin', 'methodologist', 'teacher', 'student']


def _json_safe_jwt_payload(data: dict) -> dict:
    """Normalise a JWT payload so jwt.encode() never trips on UUID/datetime.

    `jwt.encode` uses stdlib `json.dumps` under the hood; both Python's
    stdlib json and PyJWT 2.x reject UUID/datetime values. We coerce:

      - UUID → str(uuid) (None stays None — that's intentional, see
        superadmin flow which uses tenant_id=None)
      - datetime → isoformat() (only datetime *objects*, not ints —
        `exp`/`iat`/`nbf` are intentionally emitted by callers as
        datetime, which we convert here so the payload is JSON-clean)

    Reasoning: callers throughout auth/service.py do `user.tenant_id`
    which is a UUID column. We used to require them to wrap every
    call site with `str(...)`. That's brittle — any new contributor who
    forgets gets a 500. A single guard here at the encode boundary
    enforces the contract once.
    """
    from uuid import UUID
    from datetime import datetime
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, UUID):
            out[k] = str(v) if v is not None else None
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _json_safe_jwt_payload(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [
                (str(x) if isinstance(x, UUID) else
                 x.isoformat() if isinstance(x, datetime) else x)
                for x in v
            ]
        else:
            out[k] = v
    return out


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = _json_safe_jwt_payload(data)
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire.isoformat()
    to_encode["iat"] = now.isoformat()
    to_encode["nbf"] = now.isoformat()
    to_encode["jti"] = str(uuid4())
    # aud/iss claims — required for validation on decode (see decode_token).
    # Callers may override them via the data dict, but defaults are always set.
    to_encode.setdefault("aud", settings.JWT_AUDIENCE)
    to_encode.setdefault("iss", settings.JWT_ISSUER)
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = _json_safe_jwt_payload(data)
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode["exp"] = expire.isoformat()
    to_encode["iat"] = now.isoformat()
    to_encode["nbf"] = now.isoformat()
    to_encode["jti"] = str(uuid4())
    to_encode["type"] = "refresh"
    to_encode.setdefault("aud", settings.JWT_AUDIENCE)
    to_encode.setdefault("iss", settings.JWT_ISSUER)
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT.

    Defense-in-depth (see audit §4.2):
      - algorithms list is explicit; never includes "none"
      - aud is validated against settings.JWT_AUDIENCE (rejects tokens
        minted by other services that happen to share the same secret)
      - iss is validated against settings.JWT_ISSUER
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={
                "require": ["exp", "iat", "aud", "iss", "sub"],
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "verify_signature": True,
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token issuer")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    # Set tenant context for RLS
    if tenant_id:
        try:
            from sqlalchemy import text
            await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
        except Exception as exc:
            # Fallback: rely on ORM filtering if RLS not available.
            # Logged as warning — silent failure previously (audit §2.4).
            logger.warning(
                "set_current_tenant failed for tenant_id=%s; falling back to ORM filter: %s",
                tenant_id,
                exc,
            )

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Role is always from DB, never from JWT (JWT role is just for fast checks)
    # UNLESS this is an impersonation token — in that case, the real sub is
    # the platform superadmin (tenant_id=NULL), but we want the wrapper to
    # behave like a tenant admin so all the require_tenant_user() checks
    # and ORM filters see the impersonated tenant context.
    if payload.get("impersonated_tenant"):
        return _ImpersonatedUser(
            real_user=user,
            tenant_id=UUID(payload["impersonated_tenant"]),
            role=payload.get("impersonated_role", "admin"),
        )
    return user


class _ImpersonatedUser:
    """Read-only view over a real User with overridden tenant_id and role.

    Used when a platform superadmin impersonates a tenant admin. The real
    sub in the JWT is still the superadmin (so audit log writes identify
    the actual operator), but `user.tenant_id` and `user.role` are
    overridden to the impersonation target so all tenant-scoped ORM
    filters and role checks behave naturally.

    Forwarded attributes: every attribute of the underlying User model is
    available via __getattr__, so endpoints that read `user.id`, `user.foo`
    keep working unchanged.
    """

    __slots__ = ("_user", "tenant_id", "role", "is_impersonating")

    def __init__(self, real_user: User, tenant_id: UUID, role: str):
        self._user = real_user
        self.tenant_id = tenant_id
        self.role = role
        self.is_impersonating = True

    def __getattr__(self, name):
        return getattr(self._user, name)

    def __repr__(self):
        return (
            f"<ImpersonatedUser id={self._user.id} "
            f"as={self.role} in tenant={self.tenant_id}>"
        )


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not active")
    return user


def require_role(*allowed_roles: str):
    for role in allowed_roles:
        if role not in ROLES:
            raise ValueError(f"Invalid role: {role}. Allowed: {ROLES}")

    async def role_checker(user: User = Depends(get_current_active_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {allowed_roles}"
            )
        return user

    return role_checker


def require_admin(user: User = Depends(require_role("admin", "org_admin", "superadmin"))) -> User:
    return user


async def get_superadmin(user: User = Depends(require_role("superadmin"))) -> User:
    return user


def require_tenant_user():
    """Reject platform superadmin (tenant_id IS NULL) from tenant-level endpoints.

    Most LMS features (courses, users, documents, AI generation) are
    scoped to a tenant. A superadmin who has tenant_id=NULL cannot
    operate on a NULL tenant -- they would either see empty results
    (misleading) or hit FK violations (500s). This dependency gives
    them an explicit 403 with a clear message.

    Superadmin should use the /admin/super/* endpoints instead, which
    explicitly take a tenant_id path param.
    """
    async def checker(user: User = Depends(get_current_active_user)) -> User:
        if user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This action requires a tenant context. "
                    "Superadmin should use /admin/super/* endpoints. "
                    "Switch to a tenant user via the Telegram login."
                ),
            )
        return user

    return checker
