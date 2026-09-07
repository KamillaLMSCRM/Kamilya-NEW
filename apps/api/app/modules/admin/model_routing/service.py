"""Atomic management of the approved generation-model route."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.admin.model_routing import repository as repo
from app.modules.admin.model_routing.catalog import (
    DEEPSEEK_ROUTE_ID,
    GENERATION_MODEL_CATALOG,
    GLM53_ROUTE_ID,
    QWEN38_ROUTE_ID,
    validate_generation_model_order,
)
from app.modules.admin.model_routing.models import GenerationModelRouting
from app.modules.admin.model_routing.schemas import (
    GenerationModelRouteItem,
    GenerationModelRoutingResponse,
    GenerationModelRoutingUpdate,
)
from app.modules.admin.provider_keys.repository import get_active_global_key

logger = logging.getLogger(__name__)


class RoutingRevisionConflictError(Exception):
    """The caller edited an obsolete revision."""


class RoutingConfigurationMissingError(Exception):
    """The singleton migration row is missing."""


class RoutingPrimaryNotConfiguredError(Exception):
    """The mandatory DeepSeek primary has no active key."""


class GenerationModelRoutingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self) -> GenerationModelRoutingResponse:
        row = await repo.get_routing(self.db)
        if row is None:
            raise RoutingConfigurationMissingError("generation_model_routing_missing")
        return await self._response(row)

    async def update(
        self,
        payload: GenerationModelRoutingUpdate,
        *,
        user_id: uuid.UUID,
    ) -> GenerationModelRoutingResponse:
        order = validate_generation_model_order(payload.ordered_model_ids)
        if not await self._deepseek_is_configured():
            raise RoutingPrimaryNotConfiguredError(
                "generation_model_routing_deepseek_not_configured"
            )
        row = await repo.get_routing(self.db, for_update=True)
        if row is None:
            raise RoutingConfigurationMissingError("generation_model_routing_missing")
        if row.revision != payload.revision:
            raise RoutingRevisionConflictError("generation_model_routing_revision_conflict")

        row.ordered_model_ids = list(order)
        row.revision += 1
        row.updated_by = user_id
        row.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(
            "generation_model_routing.updated revision=%s order=%s by=%s",
            row.revision,
            ",".join(order),
            user_id,
        )
        return await self._response(row)

    async def _response(
        self,
        row: GenerationModelRouting,
    ) -> GenerationModelRoutingResponse:
        settings = get_settings()
        order = validate_generation_model_order(row.ordered_model_ids)
        positions = {route_id: index + 1 for index, route_id in enumerate(order)}
        configured = {
            DEEPSEEK_ROUTE_ID: await self._deepseek_is_configured(),
            QWEN38_ROUTE_ID: bool(settings.QWEN38_FLASH_URL and settings.QWEN38_FLASH_MODEL),
            GLM53_ROUTE_ID: bool(settings.GLM53_FLASH_URL and settings.GLM53_FLASH_MODEL),
        }
        model_names = {
            DEEPSEEK_ROUTE_ID: settings.DEEPSEEK_MODEL,
            QWEN38_ROUTE_ID: settings.QWEN38_FLASH_MODEL,
            GLM53_ROUTE_ID: settings.GLM53_FLASH_MODEL,
        }
        models = [
            GenerationModelRouteItem(
                id=entry.id,
                provider=entry.provider,
                display_name=entry.display_name,
                model=model_names[entry.id],
                is_enabled=entry.id in positions,
                position=positions.get(entry.id),
                is_required=entry.is_required,
                is_configured=configured[entry.id],
            )
            for entry in GENERATION_MODEL_CATALOG.values()
        ]
        models.sort(key=lambda item: item.position or 999)
        return GenerationModelRoutingResponse(
            revision=row.revision,
            models=models,
            updated_at=row.updated_at,
        )

    async def _deepseek_is_configured(self) -> bool:
        settings = get_settings()
        if settings.DEEPSEEK_API_KEY:
            return True
        return await get_active_global_key(self.db, "deepseek") is not None
