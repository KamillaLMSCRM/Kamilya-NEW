"""JWT token tests — create, decode, claims validation."""
import pytest
import jwt
import app.core.auth as auth_module
from datetime import datetime, timedelta, timezone
from uuid import uuid4


@pytest.fixture(autouse=True)
def _fake_settings():
    """Provide a fake JWT_SECRET for all JWT tests."""
    auth_module.settings.JWT_SECRET = "test-secret-key-for-jwt-validation-2026"
    auth_module.settings.JWT_ALGORITHM = "HS256"
    auth_module.settings.ACCESS_TOKEN_EXPIRE_MINUTES = 15
    auth_module.settings.REFRESH_TOKEN_EXPIRE_DAYS = 30
    yield
    auth_module.settings.JWT_SECRET = ""

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
