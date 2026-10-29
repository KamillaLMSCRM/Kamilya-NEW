"""Narrow, default-off Luna route for the permanent synthetic DEV QA tenant."""

from __future__ import annotations

from typing import Any
from uuid import UUID

QA_TENANT = UUID("a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0")


async def qa_luna_dev_client(*, settings: Any, tenant_id: UUID, temperature: float) -> Any:
    """Construct a single-provider client only after local worker readiness.

    No client-controlled model selection or global routing change is involved.
    Unavailable proof fails closed for this explicitly enabled QA route.
    """
    if getattr(settings, "AI_QA_LUNA_DEV_ENABLED", False) is not True or tenant_id != QA_TENANT:
        return None
    if not (
        getattr(settings, "DEPLOYMENT_ENVIRONMENT", None) == "render-development-worker"
        and getattr(settings, "AI_LESSON_CYCLE_DEV_ENABLED", False) is True
        and str(QA_TENANT) in getattr(settings, "AI_LESSON_CYCLE_DEV_TENANTS", ())
    ):
        raise RuntimeError("dev_qa_luna_route_misconfigured")

    from app.modules.admin.model_routing.catalog import CHATGPT_RESERVE_ROUTE_ID
    from app.modules.admin.model_routing.chatgpt_reserve import check_readiness
    from app.modules.ai.llm_client import ResilientLLMClient, _generation_fallback_providers

    readiness = await check_readiness()
    if readiness.ready is not True:
        raise RuntimeError("dev_qa_luna_connector_not_ready")
    providers = _generation_fallback_providers((CHATGPT_RESERVE_ROUTE_ID,))
    if len(providers) != 1 or providers[0].model != "gpt-5.6-luna":
        raise RuntimeError("dev_qa_luna_provider_not_configured")
    return ResilientLLMClient(providers, temperature=temperature, max_retries_per_provider=0)
