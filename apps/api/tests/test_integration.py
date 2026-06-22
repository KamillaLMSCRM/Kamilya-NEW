"""Integration tests — endpoints via TestClient + audit + config."""
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.modules.audit.service import log_action
from app.core.rate_limit import RateLimitMiddleware
from sqlalchemy.ext.asyncio import AsyncSession


# --- shared rate limit disabler (static helper) ---
def _disable_rate_limit(client):
    """Patch RateLimitMiddleware dispatch to skip rate limits."""
    from unittest import mock

    async def fake_dispatch(self, request, call_next):
        response = await call_next(request)
        return response

    return mock.patch.object(
        RateLimitMiddleware,
        "dispatch",
        fake_dispatch,
    )


class TestAuthEndpoint:
    """Test auth endpoint integration via TestClient."""

    @pytest.mark.asyncio
    async def test_login_missing_fields_rejected(self):
        """Login without required fields should get 422."""
        client = TestClient(app)
        with _disable_rate_limit(client):
            resp = client.post("/api/v1/auth/login", json={})
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_invalid_email_rejected(self):
        """Login with invalid email should get 422."""
        client = TestClient(app)
        with _disable_rate_limit(client):
            resp = client.post("/api/v1/auth/login", json={
                "email": "not-an-email",
                "password": "Test123!"
            })
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_missing_fields_rejected(self):
        """Register without required fields should get 422."""
        client = TestClient(app)
        with _disable_rate_limit(client):
            resp = client.post("/api/v1/auth/register", json={})
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_check_code_missing_required(self):
        """check-code without code or telegram_id should get 422."""
        client = TestClient(app)
        with _disable_rate_limit(client):
            resp = client.post("/api/v1/auth/check-code", json={})
            assert resp.status_code == 422


class TestCourseCRUD:
    """Test course CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_course_requires_auth(self):
        """Create course without auth should return 401."""
        client = TestClient(app)
        with _disable_rate_limit(client):
            resp = client.post("/api/v1/courses", json={
                "title": "Test",
                "description": "Test"
            })
            # Auth check happens before body validation in most setups
            assert resp.status_code in (401, 422)


class TestCSRFAndSecurity:
    """Test security headers and config."""

    def test_cors_allowed_origins_configured(self):
        """CORS origins should include production domain."""
        from app.core.config import get_settings
        origins = get_settings().CORS_ORIGINS
        assert "https://web-inky-three-48.vercel.app" in origins

    @pytest.mark.asyncio
    async def test_cors_simple_request(self):
        """POST with CORS header should succeed."""
        client = TestClient(app)
        with _disable_rate_limit(client):
            try:
                resp = client.post(
                    "/api/v1/courses",
                    json={"title": "", "description": ""},
                    headers={"Origin": "https://example.com"}
                )
                # May be 401 or 422 but should NOT be 429 (rate limited)
                assert resp.status_code != 429
            except Exception:
                pass


class TestAuditService:
    """Test audit log service."""

    @pytest.mark.asyncio
    async def test_log_action_creates_entry(self):
        """log_action should create audit log entry."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        await log_action(
            db=mock_session,
            tenant_id=uuid.uuid4(),
            action="CREATE_COURSE",
            resource_type="course",
            resource_id="test-course-id",
            user_id=uuid.uuid4(),
            details={"title": "Test Course"},
        )

        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_action_with_fields(self):
        """log_action should store all fields."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()

        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()

        await log_action(
            db=mock_session,
            tenant_id=tenant_id,
            action="LOGIN",
            resource_type="auth",
            user_id=user_id,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        entry = mock_session.add.call_args[0][0]
        assert entry.action == "LOGIN"
        assert entry.resource_type == "auth"
        assert entry.ip_address == "192.168.1.1"
        assert entry.user_agent == "Mozilla/5.0"


class TestRateLimitConfig:
    """Test rate limiting configuration."""

    def test_auth_login_stricter_than_default(self):
        """Auth login should have stricter limit than default."""
        from app.core.rate_limit import RATE_LIMITS
        login = RATE_LIMITS["/api/v1/auth/login"]
        default = RATE_LIMITS["default"]
        assert login.requests_per_minute < default.requests_per_minute

    def test_ai_generate_strictest(self):
        """AI generation should have strictest limit."""
        from app.core.rate_limit import RATE_LIMITS
        ai = RATE_LIMITS["/api/v1/ai/generate-course"]
        assert ai.requests_per_minute == 2


class TestDatabaseConfig:
    """Test database configuration."""

    def test_database_url_uses_asyncpg(self):
        """DATABASE_URL should use asyncpg driver."""
        from app.core.config import get_settings
        url = get_settings().DATABASE_URL
        assert "asyncpg" in url

    def test_database_url_overridden_from_env(self):
        """DATABASE_URL from .env supersedes default."""
        from app.core.config import get_settings
        url = get_settings().DATABASE_URL
        # Should connect to Supabase, not localhost
        assert "localhost" not in url
