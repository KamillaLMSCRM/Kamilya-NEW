"""JWT token tests — create, decode, claims validation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.core.auth as auth_module


@pytest.fixture(autouse=True)
def _fake_settings():
    """Provide a fake JWT_SECRET for all JWT tests."""
    original_secret = auth_module.settings.JWT_SECRET
    auth_module.settings.JWT_SECRET = "test-secret-key-for-jwt-validation-2026"
    auth_module.settings.JWT_ALGORITHM = "HS256"
    auth_module.settings.ACCESS_TOKEN_EXPIRE_MINUTES = 15
    auth_module.settings.REFRESH_TOKEN_EXPIRE_DAYS = 30
    yield
    auth_module.settings.JWT_SECRET = original_secret

def test_create_access_token_has_required_claims():
    data = {"sub": str(uuid4()), "tenant_id": str(uuid4()), "roles": ["student"]}
    token = auth_module.create_access_token(data)
    payload = jwt.decode(
        token,
        "test-secret-key-for-jwt-validation-2026",
        algorithms=["HS256"],
        audience="kamilya-lms",
        issuer="kamilya-lms",
    )
    assert "exp" in payload
    assert "iat" in payload
    assert "nbf" in payload
    assert "jti" in payload
    assert payload["sub"] == data["sub"]
    assert payload["roles"] == data["roles"]
    assert payload["type"] == "access"


def test_create_refresh_token_has_type_claim():
    data = {"sub": str(uuid4()), "tenant_id": str(uuid4())}
    token = auth_module.create_refresh_token(data)
    payload = auth_module.decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_expired_token_raises():
    secret = "test-secret-key-for-jwt-validation-2026"
    data = {"sub": str(uuid4()), "tenant_id": str(uuid4())}
    expired = datetime.now(timezone.utc) - timedelta(minutes=20)
    to_encode = {**data, "exp": expired, "iat": expired, "nbf": expired, "jti": str(uuid4())}
    token = jwt.encode(to_encode, secret, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, secret, algorithms=["HS256"])


def test_decode_invalid_token_raises():
    """Invalid token raises HTTPException with 401 detail."""
    with pytest.raises(Exception) as exc_info:
        auth_module.decode_token("invalid.token.here")
    assert "Invalid token" in str(exc_info.value)


def test_create_access_token_custom_expiry():
    secret = "test-secret-key-for-jwt-validation-2026"
    data = {"sub": str(uuid4()), "tenant_id": str(uuid4())}
    token = auth_module.create_access_token(data, expires_delta=timedelta(hours=2))
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="kamilya-lms",
        issuer="kamilya-lms",
    )
    # JWT exp is a Unix timestamp (int)
    expire_ts = payload["exp"]
    now_ts = datetime.now(timezone.utc).timestamp()
    assert expire_ts > now_ts + 3600  # 1 hour = 3600 seconds


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token_factory",
    [
        lambda data: auth_module.create_refresh_token(data),
        lambda data: auth_module.create_scoped_token(
            data, token_type="scorm_launch", expires_delta=timedelta(minutes=5)
        ),
    ],
)
async def test_non_access_tokens_are_rejected_before_user_lookup(token_factory):
    token = token_factory({"sub": str(uuid4()), "tenant_id": str(uuid4())})
    db = SimpleNamespace(execute=AsyncMock(), rollback=AsyncMock())
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException, match="Invalid access token") as exc_info:
        await auth_module.get_current_user(credentials=credentials, db=db)

    assert exc_info.value.status_code == 401
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_token_is_accepted_by_protected_dependency():
    user_id, tenant_id = uuid4(), uuid4()
    token = auth_module.create_access_token({"sub": str(user_id), "tenant_id": str(tenant_id)})
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="student", is_active=True)

    class Result:
        def scalar_one_or_none(self):
            return user

    db = SimpleNamespace(execute=AsyncMock(side_effect=[object(), Result()]), rollback=AsyncMock())
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    assert await auth_module.get_current_user(credentials=credentials, db=db) is user


@pytest.mark.asyncio
async def test_kiosk_access_token_requires_active_credential_and_link():
    user_id, tenant_id, kiosk_id, credential_id = uuid4(), uuid4(), uuid4(), uuid4()
    token = auth_module.create_scoped_token(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "auth_method": "kiosk",
            "kiosk_id": str(kiosk_id),
            "kiosk_credential_id": str(credential_id),
        },
        token_type="kiosk_access",
        expires_delta=timedelta(minutes=20),
    )
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        role="student",
        is_active=True,
        status="active",
        position_id=None,
    )

    class Result:
        def scalar_one_or_none(self):
            return user

    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[object(), Result()]),
        scalar=AsyncMock(return_value=credential_id),
        rollback=AsyncMock(),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    principal = await auth_module.get_current_user(credentials=credentials, db=db)

    assert principal.id == user_id
    assert principal.kiosk_access_kiosk_id == kiosk_id
    assert principal.role == "student"
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_kiosk_access_token_is_rejected_when_server_credential_is_inactive():
    user_id, tenant_id, kiosk_id, credential_id = uuid4(), uuid4(), uuid4(), uuid4()
    token = auth_module.create_scoped_token(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "auth_method": "kiosk",
            "kiosk_id": str(kiosk_id),
            "kiosk_credential_id": str(credential_id),
        },
        token_type="kiosk_access",
        expires_delta=timedelta(minutes=20),
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=object()),
        scalar=AsyncMock(return_value=None),
        rollback=AsyncMock(),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException, match="Kiosk access revoked") as exc_info:
        await auth_module.get_current_user(credentials=credentials, db=db)

    assert exc_info.value.status_code == 401
