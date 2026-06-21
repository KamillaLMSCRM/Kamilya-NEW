"""Unit tests for auth module"""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.service import authenticate_user, refresh_access_token, blacklist_refresh_token
from app.models.users import User
from app.models.user_sessions import UserSession


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


class TestAuthentication:
    """Test auth service functions."""

    @pytest.mark.asyncio
    async def test_authenticate_user_success(self, mock_db: AsyncMock) -> None:
        """Test successful authentication."""
        user: User = User(
            id="123e4567-e89b-12d3-a456-426614174000",
            tenant_id="123e4567-e89b-12d3-a456-426614174001",
            email="test@example.com",
            password_hash="$argon2id$v=19$m=65536,t=3,p=1$abc...",
            first_name="Test",
            last_name="User",
            status="active",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        with patch(
            "app.modules.auth.service.ph",
            new_callable=lambda: type("PH", (), {"verify": lambda self, a, b: None}),
        ):
            with patch(
                "app.modules.auth.service.create_access_token", return_value="at123"
            ):
                with patch(
                    "app.modules.auth.service.create_refresh_token", return_value="rt123"
                ):
                    result = await authenticate_user(mock_db, "test@example.com", "pass")
                    assert len(result) == 3
                    assert result[0].email == "test@example.com"
                    assert result[1] == "at123"
                    assert result[2] == "rt123"

    @pytest.mark.asyncio
    async def test_authenticate_user_not_found(self, mock_db: AsyncMock) -> None:
        """Test authentication with non-existent email."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(Exception) as exc_info:
            await authenticate_user(mock_db, "nobody@example.com", "pass")
        assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authenticate_user_inactive(self, mock_db: AsyncMock) -> None:
        """Test authentication with inactive user."""
        user = User(
            id="123e4567-e89b-12d3-a456-426614174000",
            tenant_id="123e4567-e89b-12d3-a456-426614174001",
            email="test@example.com",
            password_hash="hash",
            first_name="Test",
            last_name="User",
            status="banned",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = user

        with patch(
            "app.modules.auth.service.ph",
            new_callable=lambda: type("PH", (), {"verify": lambda self, a, b: None}),
        ):
            with pytest.raises(Exception) as exc_info:
                await authenticate_user(mock_db, "test@example.com", "pass")
            assert "not active" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_blacklist_token(self, mock_db: AsyncMock) -> None:
        """Test refresh token blacklisting."""
        await blacklist_refresh_token(mock_db, "old_refresh_token")
        mock_db.execute.assert_called_once()
