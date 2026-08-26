from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.legal_versions import (
    CURRENT_PRIVACY_CONSENT_VERSION,
    CURRENT_PUBLIC_LEAD_CONSENT_VERSION,
    CURRENT_TERMS_VERSION,
)
from app.modules.auth import telegram_register
from app.modules.auth.telegram_register import TelegramRegisterRequest
from app.modules.tenants.schemas import PublicLeadRequest, TenantRegisterRequest


def test_public_registration_requires_versioned_privacy_and_terms_acceptance() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TenantRegisterRequest.model_validate(
            {
                "company_name": "QA Company",
                "contact_name": "QA Admin",
                "email": "qa@example.com",
                "password": "qa-password-2026",
                "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
                "privacy_consent_locale": "ru",
                "privacy_consent_surface": "tenant_registration",
            }
        )

    assert "terms_version" in str(exc_info.value)


def test_public_registration_normalizes_legal_evidence_versions() -> None:
    payload = TenantRegisterRequest.model_validate(
        {
            "company_name": "QA Company",
            "contact_name": "QA Admin",
            "email": "QA@EXAMPLE.COM ",
            "email_code": "123456",
            "password": "qa-password-2026",
            "privacy_consent_version": f" {CURRENT_PRIVACY_CONSENT_VERSION} ",
            "privacy_consent_locale": "ru",
            "privacy_consent_surface": " tenant_registration ",
            "terms_version": f" {CURRENT_TERMS_VERSION} ",
        }
    )

    assert payload.email == "qa@example.com"
    assert payload.privacy_consent_version == CURRENT_PRIVACY_CONSENT_VERSION
    assert payload.privacy_consent_surface == "tenant_registration"
    assert payload.terms_version == CURRENT_TERMS_VERSION


def test_public_registration_rejects_client_supplied_acceptance_timestamps() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TenantRegisterRequest.model_validate(
            {
                "company_name": "QA Company",
                "contact_name": "QA Admin",
                "email": "qa@example.com",
                "password": "qa-password-2026",
                "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
                "privacy_consent_locale": "ru",
                "privacy_consent_surface": "tenant_registration",
                "terms_version": CURRENT_TERMS_VERSION,
                "privacy_consent_at": "2000-01-01T00:00:00Z",
                "terms_accepted_at": "2000-01-01T00:00:00Z",
            }
        )

    assert "privacy_consent_at" in str(exc_info.value)
    assert "terms_accepted_at" in str(exc_info.value)


@pytest.mark.parametrize("field", ["privacy_consent_version", "terms_version"])
def test_public_registration_rejects_fictitious_legal_versions(field: str) -> None:
    payload = {
        "company_name": "QA Company",
        "contact_name": "QA Admin",
        "email": "qa@example.com",
        "password": "qa-password-2026",
        "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
        "privacy_consent_locale": "ru",
        "privacy_consent_surface": "tenant_registration",
        "terms_version": CURRENT_TERMS_VERSION,
    }
    payload[field] = "fictitious-version"

    with pytest.raises(ValidationError):
        TenantRegisterRequest.model_validate(payload)


def test_telegram_registration_requires_canonical_legal_acceptance() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TelegramRegisterRequest.model_validate(
            {
                "company": "QA Company",
                "telegram_id": 123456,
                "first_name": "QA",
                "last_name": "Admin",
                "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
                "privacy_consent_locale": "ru",
                "privacy_consent_surface": "client-value",
            }
        )

    assert "terms_version" in str(exc_info.value)


@pytest.mark.parametrize(
    "missing_field",
    ["privacy_consent_version", "privacy_consent_locale", "privacy_consent_surface", "terms_version"],
)
def test_telegram_registration_requires_each_legal_acceptance_field(missing_field: str) -> None:
    payload = {
        "company": "QA Company",
        "telegram_id": 123456,
        "first_name": "QA",
        "last_name": "Admin",
        "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
        "privacy_consent_locale": "ru",
        "privacy_consent_surface": "telegram_registration",
        "terms_version": CURRENT_TERMS_VERSION,
    }
    payload.pop(missing_field)

    with pytest.raises(ValidationError, match=missing_field):
        TelegramRegisterRequest.model_validate(payload)


def test_telegram_registration_stores_a_server_owned_canonical_surface() -> None:
    source = open(telegram_register.__file__, encoding="utf-8").read()

    assert 'privacy_consent_surface="telegram_registration"' in source


@pytest.mark.parametrize("schema", [TenantRegisterRequest, TelegramRegisterRequest])
@pytest.mark.parametrize("locale", ["kk", "en"])
def test_public_registration_rejects_locales_without_a_shown_legal_document(schema, locale: str) -> None:
    payload = {
        "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
        "privacy_consent_locale": locale,
        "privacy_consent_surface": "public-registration",
        "terms_version": CURRENT_TERMS_VERSION,
    }
    if schema is TenantRegisterRequest:
        payload.update(
            company_name="QA Company",
            contact_name="QA Admin",
            email="qa@example.com",
            password="qa-password-2026",
        )
    else:
        payload.update(company="QA Company", telegram_id=123456, first_name="QA", last_name="Admin")

    with pytest.raises(ValidationError, match="privacy_consent_locale"):
        schema.model_validate(payload)


def test_public_lead_requires_canonical_consent_and_rejects_client_timestamp() -> None:
    payload = {
        "name": "QA Lead",
        "company": "QA Company",
        "email": "qa@example.com",
        "interest": "demo",
        "consent_version": CURRENT_PUBLIC_LEAD_CONSENT_VERSION,
        "consented_at": "2000-01-01T00:00:00Z",
    }

    with pytest.raises(ValidationError, match="consented_at"):
        PublicLeadRequest.model_validate(payload)

    payload.pop("consented_at")
    payload["consent_version"] = "fictitious-version"
    with pytest.raises(ValidationError, match="consent_version"):
        PublicLeadRequest.model_validate(payload)
