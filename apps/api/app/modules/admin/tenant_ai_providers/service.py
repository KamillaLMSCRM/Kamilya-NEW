"""BYOK policy, secret handling, and lazy tenant runtime resolution."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret
from app.modules.admin.tenant_ai_providers import repository
from app.modules.admin.tenant_ai_providers.models import TenantAIProvider
from app.modules.admin.tenant_ai_providers.schemas import (
    TenantAIProviderListResponse,
    TenantAIProviderResponse,
    TenantAIProviderUpdate,
)

if TYPE_CHECKING:
    from app.modules.ai.llm_client import LLMProviderConfig

_ALLOWED = {
    "generation": {"deepseek", "openrouter"},
    "embedding": {"voyage", "cohere", "openrouter"},
}


class TenantProviderConfigurationError(RuntimeError):
    """Safe fail-closed error for an explicit tenant provider override."""


def _sanitized(row: TenantAIProvider) -> TenantAIProviderResponse:
    return TenantAIProviderResponse(purpose=row.purpose, provider=row.provider, model=row.model, enabled=row.enabled, free_only=row.free_only, output_dimensions=row.output_dimensions, has_key=bool(row.encrypted_key))


def _validate(purpose: str, payload: TenantAIProviderUpdate) -> None:
    if purpose not in _ALLOWED or payload.provider not in _ALLOWED[purpose]:
        raise ValueError("provider_not_allowed_for_purpose")
    if payload.output_dimensions is not None:
        raise ValueError("output_dimensions_unsupported")
    if payload.provider == "openrouter" and payload.free_only:
        if purpose == "generation" and (
            payload.model == "openrouter/free" or payload.model.endswith(":free")
        ):
            return
        if purpose == "embedding" and payload.model.endswith(":free"):
            return
        raise ValueError("openrouter_free_model_required")


class TenantAIProviderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, tenant_id: uuid.UUID) -> TenantAIProviderListResponse:
        return TenantAIProviderListResponse(providers=[_sanitized(row) for row in await repository.list_for_tenant(self.db, tenant_id)])

    async def put(self, tenant_id: uuid.UUID, purpose: str, payload: TenantAIProviderUpdate) -> TenantAIProviderResponse:
        _validate(purpose, payload)
        current = await repository.get_for_tenant(self.db, tenant_id, purpose)
        if payload.api_key is None:
            if current is None:
                raise ValueError("api_key_required_for_new_provider")
            if current.provider != payload.provider:
                raise ValueError("api_key_required_for_provider_change")
            encrypted_key = current.encrypted_key
        else:
            encrypted_key = encrypt_secret(payload.api_key)
        row = await repository.upsert_for_tenant(self.db, tenant_id=tenant_id, purpose=purpose, values={"provider": payload.provider, "model": payload.model, "encrypted_key": encrypted_key, "enabled": payload.enabled, "free_only": payload.free_only, "output_dimensions": payload.output_dimensions})
        await self.db.commit()
        return _sanitized(row)

    async def delete(self, tenant_id: uuid.UUID, purpose: str) -> None:
        if purpose not in _ALLOWED or not await repository.delete_for_tenant(self.db, tenant_id, purpose):
            raise LookupError("tenant_ai_provider_not_found")
        await self.db.commit()


async def resolve_tenant_provider(
    tenant_id: uuid.UUID,
    purpose: str,
) -> LLMProviderConfig | None:
    """Return an enabled override config, ``None`` for absent/disabled, or fail closed."""
    from app.core.db import async_session_factory
    from app.modules.ai.llm_client import LLMProviderConfig, _openai_base_url

    try:
        async with async_session_factory() as session:
            await session.execute(
                text("SELECT set_current_tenant(:tenant_id)"),
                {"tenant_id": str(tenant_id)},
            )
            row = await repository.get_for_tenant(session, tenant_id, purpose)
    except Exception as exc:
        raise TenantProviderConfigurationError("tenant_provider_resolution_unavailable") from exc
    if row is None or not row.enabled:
        return None
    try:
        key = decrypt_secret(row.encrypted_key)
    except Exception as exc:
        raise TenantProviderConfigurationError("tenant_provider_key_unavailable") from exc
    if not key:
        raise TenantProviderConfigurationError("tenant_provider_key_unavailable")
    if row.provider == "deepseek":
        from app.core.config import get_settings
        settings = get_settings()
        return LLMProviderConfig(name="deepseek", base_url=_openai_base_url(settings.DEEPSEEK_BASE_URL), api_key=key, model=row.model, timeout=120.0, extra_body={"thinking": {"type": "disabled"}})
    if row.provider == "voyage":
        return LLMProviderConfig(name="voyage", base_url="https://api.voyageai.com/v1", api_key=key, model=row.model, timeout=60.0)
    if row.provider == "cohere":
        return LLMProviderConfig(name="cohere", base_url="https://api.cohere.com/v2", api_key=key, model=row.model, timeout=30.0, endpoint="/embed")
    if row.provider == "openrouter":
        extra = {
            "provider": {
                "allow_fallbacks": False,
                "data_collection": "deny",
                "max_price": {"prompt": 0, "completion": 0, "image": 0, "request": 0},
            }
        } if row.free_only else {}
        return LLMProviderConfig(name="openrouter", base_url="https://openrouter.ai/api/v1", api_key=key, model=row.model, timeout=60.0, extra_body=extra)
    raise TenantProviderConfigurationError("tenant_provider_invalid")
