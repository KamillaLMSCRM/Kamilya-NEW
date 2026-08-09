from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.enrollments import access_service


def test_assignment_access_session_default_and_bounds() -> None:
    settings = Settings(JWT_SECRET="x" * 32)
    assert settings.ASSIGNMENT_ACCESS_SESSION_MINUTES == 240

    assert Settings(JWT_SECRET="x" * 32, ASSIGNMENT_ACCESS_SESSION_MINUTES=30).ASSIGNMENT_ACCESS_SESSION_MINUTES == 30
    assert Settings(JWT_SECRET="x" * 32, ASSIGNMENT_ACCESS_SESSION_MINUTES=480).ASSIGNMENT_ACCESS_SESSION_MINUTES == 480
    with pytest.raises(ValidationError):
        Settings(JWT_SECRET="x" * 32, ASSIGNMENT_ACCESS_SESSION_MINUTES=481)


def test_assignment_access_session_ttl_uses_bounded_setting(monkeypatch) -> None:
    monkeypatch.setattr(
        access_service,
        "get_settings",
        lambda: Settings(JWT_SECRET="x" * 32, ASSIGNMENT_ACCESS_SESSION_MINUTES=240),
    )
    assert access_service.assignment_access_session_ttl().total_seconds() == 4 * 60 * 60
