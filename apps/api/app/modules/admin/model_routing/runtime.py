"""Runtime read path for the non-secret global generation route."""

from __future__ import annotations

import logging

from app.modules.admin.model_routing.catalog import (
    validate_generation_model_order,
)

logger = logging.getLogger(__name__)


class RuntimeGenerationModelRoutingUnavailableError(RuntimeError):
    """The saved operator route cannot be read safely."""


async def resolve_runtime_generation_model_order() -> tuple[str, ...]:
    """Load the current route for a newly constructed AI client.

    A database/read-policy failure must not silently reactivate a provider that
    the operator disabled. Only the exception class is logged, then client
    construction fails closed.
    """
    from app.core.db import async_session_factory
    from app.modules.admin.model_routing.repository import get_routing

    try:
        async with async_session_factory() as db:
            row = await get_routing(db)
            if row is None:
                raise LookupError("generation_model_routing_missing")
            return validate_generation_model_order(row.ordered_model_ids)
    except Exception as exc:
        logger.error(
            "generation_model_routing.read_failed error_type=%s fail_closed=true",
            type(exc).__name__,
        )
        raise RuntimeGenerationModelRoutingUnavailableError(
            "generation_model_routing_unavailable"
        ) from None
