"""Business logic for provider_keys — encryption, CRUD, key probing."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_secret, encrypt_secret, mask_secret
from app.modules.admin.provider_keys import repository as repo
from app.modules.admin.provider_keys.models import ProviderKey
from app.modules.admin.provider_keys.schemas import (
    ProviderKeyCreate,
    ProviderKeyListResponse,
    ProviderKeyResponse,
    ProviderKeyTestResult,
    ProviderKeyUpdate,
)
from app.modules.ai.llm_client import _deepseek_llm_provider, _voyage_embed_provider

logger = logging.getLogger(__name__)


class ProviderKeyService:
    """CRUD + lifecycle for ProviderKey rows.

    Reads encrypted_key only when explicitly needed (e.g. testing a key
    or building an LLMProviderConfig). Other endpoints surface only the
    masked preview.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Read ─────────────────────────────────────────────────────────

    async def list_providers(self) -> ProviderKeyListResponse:
        """List global providers, with their source (db vs env).

        A provider may have:
          - 0 rows in DB and no env var   → not configured
          - 0 rows in DB, env var set      → source = 'env' (built from env)
          - N rows in DB                   → source = 'db', one is active
        """
        rows = await repo.list_global_keys(self.db)
        responses: list[ProviderKeyResponse] = []
        for row in rows:
            plaintext = decrypt_secret(row.encrypted_key)
            responses.append(
                ProviderKeyResponse(
                    id=row.id,
                    provider=row.provider,
                    label=row.label,
                    is_active=row.is_active,
                    key_preview=mask_secret(plaintext),
                    source="db",
                    created_by=row.created_by,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    last_used_at=row.last_used_at,
                    last_error=row.last_error,
                )
            )
        return ProviderKeyListResponse(providers=responses)

    # ── Create / Update / Delete ─────────────────────────────────────

    async def create_key(
        self, payload: ProviderKeyCreate, user_id: uuid.UUID | None
    ) -> ProviderKeyResponse:
        # Deactivate any existing active key for this provider.
        await repo.deactivate_existing(self.db, payload.provider, tenant_id=None)
        key = ProviderKey(
            tenant_id=None,  # global only in v1
            provider=payload.provider,
            encrypted_key=encrypt_secret(payload.api_key),
            label=payload.label,
            is_active=payload.is_active,
            created_by=user_id,
        )
        await repo.insert_key(self.db, key)
        await self.db.commit()
        await self.db.refresh(key)
        logger.info(
            "provider_key.created provider=%s id=%s by=%s",
            payload.provider, key.id, user_id,
        )
        plaintext = decrypt_secret(key.encrypted_key)
        return ProviderKeyResponse(
            id=key.id,
            provider=key.provider,
            label=key.label,
            is_active=key.is_active,
            key_preview=mask_secret(plaintext),
            source="db",
            created_by=key.created_by,
            created_at=key.created_at,
            updated_at=key.updated_at,
            last_used_at=key.last_used_at,
            last_error=key.last_error,
        )

    async def update_key(
        self, key_id: uuid.UUID, payload: ProviderKeyUpdate
    ) -> ProviderKeyResponse:
        key = await repo.get_key_by_id(self.db, key_id)
        if key is None:
            raise LookupError(f"ProviderKey {key_id} not found")
        if payload.api_key is not None:
            key.encrypted_key = encrypt_secret(payload.api_key)
            # Replacing the key clears last_error — let the user retest.
            key.last_error = None
        if payload.label is not None:
            key.label = payload.label
        if payload.is_active is not None:
            if payload.is_active:
                # Activating this one means deactivating the others.
                await repo.deactivate_existing(
                    self.db, key.provider, tenant_id=key.tenant_id
                )
            key.is_active = payload.is_active
        await self.db.commit()
        await self.db.refresh(key)
        logger.info("provider_key.updated id=%s by_endpoint", key.id)
        plaintext = decrypt_secret(key.encrypted_key)
        return ProviderKeyResponse(
            id=key.id,
            provider=key.provider,
            label=key.label,
            is_active=key.is_active,
            key_preview=mask_secret(plaintext),
            source="db",
            created_by=key.created_by,
            created_at=key.created_at,
            updated_at=key.updated_at,
            last_used_at=key.last_used_at,
            last_error=key.last_error,
        )

    async def delete_key(self, key_id: uuid.UUID) -> None:
        key = await repo.get_key_by_id(self.db, key_id)
        if key is None:
            raise LookupError(f"ProviderKey {key_id} not found")
        await repo.delete_key(self.db, key)
        await self.db.commit()
        logger.info("provider_key.deleted id=%s provider=%s", key.id, key.provider)

    # ── Test ─────────────────────────────────────────────────────────

    async def test_key(self, key_id: uuid.UUID) -> ProviderKeyTestResult:
        """Probe the provider API to confirm the key actually works."""
        key = await repo.get_key_by_id(self.db, key_id)
        if key is None:
            raise LookupError(f"ProviderKey {key_id} not found")
        plaintext = decrypt_secret(key.encrypted_key)
        result = await self._probe(key.provider, plaintext)
        # Record outcome for ops visibility.
        key.last_used_at = datetime.now(timezone.utc)
        key.last_error = result.error
        await self.db.commit()
        return result

    async def _probe(self, provider: str, api_key: str) -> ProviderKeyTestResult:
        """Send a minimal request to the provider to validate the key."""
        started = time.perf_counter()
        try:
            if provider == "deepseek":
                cfg = _deepseek_llm_provider()
                # If user has no env key, deepseek config is None — but we
                # have a plaintext key from the DB, so rebuild config with it.
                if cfg is None:
                    from app.core.config import get_settings
                    s = get_settings()
                    from app.modules.ai.llm_client import LLMProviderConfig
                    cfg = LLMProviderConfig(
                        name="deepseek",
                        base_url=s.DEEPSEEK_BASE_URL,
                        api_key=api_key,
                        model=s.DEEPSEEK_MODEL,
                        timeout=15.0,
                    )
                else:
                    # Override with DB key.
                    from dataclasses import replace
                    cfg = replace(cfg, api_key=api_key)
                async with httpx.AsyncClient(timeout=cfg.timeout) as client:
                    resp = await client.post(
                        f"{cfg.base_url}/chat/completions",
                        json={
                            "model": cfg.model,
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 1,
                        },
                        headers={"Authorization": f"Bearer {cfg.api_key}"},
                    )
                latency_ms = int((time.perf_counter() - started) * 1000)
                if resp.status_code == 200:
                    return ProviderKeyTestResult(
                        ok=True, latency_ms=latency_ms,
                        provider=provider, error=None,
                    )
                if resp.status_code in (401, 403):
                    return ProviderKeyTestResult(
                        ok=False, latency_ms=latency_ms,
                        provider=provider, error=f"auth failed ({resp.status_code})",
                    )
                return ProviderKeyTestResult(
                    ok=False, latency_ms=latency_ms,
                    provider=provider,
                    error=f"unexpected status {resp.status_code}",
                )
            if provider == "voyage":
                cfg = _voyage_embed_provider()
                from app.core.config import get_settings
                s = get_settings()
                if cfg is None:
                    from app.modules.ai.llm_client import LLMProviderConfig
                    cfg = LLMProviderConfig(
                        name="voyage",
                        base_url=s.VOYAGE_BASE_URL,
                        api_key=api_key,
                        model=s.VOYAGE_MODEL,
                        timeout=15.0,
                    )
                else:
                    from dataclasses import replace
                    cfg = replace(cfg, api_key=api_key)
                async with httpx.AsyncClient(timeout=cfg.timeout) as client:
                    resp = await client.post(
                        f"{cfg.base_url}/embeddings",
                        json={"model": cfg.model, "input": ["ping"]},
                        headers={"Authorization": f"Bearer {cfg.api_key}"},
                    )
                latency_ms = int((time.perf_counter() - started) * 1000)
                if resp.status_code == 200:
                    return ProviderKeyTestResult(
                        ok=True, latency_ms=latency_ms,
                        provider=provider, error=None,
                    )
                if resp.status_code in (401, 403):
                    return ProviderKeyTestResult(
                        ok=False, latency_ms=latency_ms,
                        provider=provider, error=f"auth failed ({resp.status_code})",
                    )
                return ProviderKeyTestResult(
                    ok=False, latency_ms=latency_ms,
                    provider=provider,
                    error=f"unexpected status {resp.status_code}",
                )
            return ProviderKeyTestResult(
                ok=False, provider=provider, error=f"unknown provider: {provider}"
            )
        except httpx.TimeoutException:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ProviderKeyTestResult(
                ok=False, latency_ms=latency_ms,
                provider=provider, error="timeout",
            )
        except httpx.HTTPError as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ProviderKeyTestResult(
                ok=False, latency_ms=latency_ms,
                provider=provider, error=f"network error: {type(e).__name__}",
            )

    # ── Resolve helpers used by llm_client ───────────────────────────

    async def get_active_key_value(self, provider: str) -> str | None:
        """Return the plaintext active global key for a provider, or None.

        Used by ResilientLLMClient / ResilientEmbeddingsClient to read
        keys from DB with env-var fallback (see llm_client.py).
        """
        key = await repo.get_active_global_key(self.db, provider)
        if key is None:
            return None
        return decrypt_secret(key.encrypted_key)