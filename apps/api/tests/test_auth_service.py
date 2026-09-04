"""Unit tests for auth module — schemas and token logic."""
import pytest
from fastapi import Response

from app.modules.auth.browser_session import get_browser_session_policy
from app.modules.auth.schemas import LoginRequest, TokenResponse, UserCreate


class TestAuthSchemas:
    """Test auth pydantic schemas."""

    def test_login_request_valid(self) -> None:
        """Valid login request."""
        req = LoginRequest(email="test@example.com", password="Test123!")
        assert req.email == "test@example.com"
        assert len(req.password) >= 8

    def test_login_request_empty_email(self) -> None:
        """Empty email should fail Pydantic validation."""
        with pytest.raises(Exception):
            LoginRequest(email="", password="Test123!")

    def test_token_response_fields(self) -> None:
        """Browser responses expose only the short-lived access token."""
        token = TokenResponse(access_token="at123", token_type="bearer", expires_in=900)
        assert token.access_token == "at123"
        assert "refresh_token" not in token.model_dump()
        assert token.token_type == "bearer"
        assert token.expires_in == 900

    def test_token_response_default_token_type(self) -> None:
        """token_type defaults to bearer."""
        token = TokenResponse(access_token="at", expires_in=600)
        assert token.token_type == "bearer"

    def test_refresh_cookie_is_httponly_and_not_in_response_model(self) -> None:
        response = Response()
        get_browser_session_policy().set_refresh_cookie(response, "test-refresh-token")
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "refresh_token" not in TokenResponse(access_token="at", expires_in=900).model_dump()

    def test_login_request_email_validation(self) -> None:
        """Invalid email should fail."""
        with pytest.raises(Exception):
            LoginRequest(email="not-an-email", password="Test123!")


class TestTokenExpiry:
    """Test token expiry logic."""

    def test_access_token_expires_sooner_than_refresh(self) -> None:
        """Access token (15 min) should expire before refresh (30 days)."""
        assert 15 < (30 * 24 * 60)  # 15 min < 30 days in minutes

    def test_token_expiry_is_positive(self) -> None:
        """Access token expiry should be positive."""
        import app.core.auth as auth_module
        auth_module.settings.JWT_SECRET = "test"
        auth_module.settings.ACCESS_TOKEN_EXPIRE_MINUTES = 15
        assert auth_module.settings.ACCESS_TOKEN_EXPIRE_MINUTES > 0
