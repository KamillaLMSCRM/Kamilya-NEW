from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _production_settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "production",
        "JWT_SECRET": "x" * 32,
        "PUBLIC_URL": "https://app.kml.kz",
        "SCORM_CONTENT_ORIGIN": "https://scorm.kml.kz",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_validates_configured_scorm_origin():
    # Empty is allowed at process startup so the rest of LMS stays available;
    # the launch endpoint itself fails closed with 503 until configured.
    assert _production_settings(SCORM_CONTENT_ORIGIN="").SCORM_CONTENT_ORIGIN == ""
    with pytest.raises(ValidationError, match="HTTPS"):
        _production_settings(SCORM_CONTENT_ORIGIN="http://scorm.kml.kz")
    with pytest.raises(ValidationError, match="separate origin"):
        _production_settings(SCORM_CONTENT_ORIGIN="https://app.kml.kz/")


def test_scorm_origin_is_normalized_and_allowed_outside_production():
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        JWT_SECRET="x" * 32,
        SCORM_CONTENT_ORIGIN="https://scorm.kml.kz/",
    )

    assert settings.SCORM_CONTENT_ORIGIN == "https://scorm.kml.kz"
