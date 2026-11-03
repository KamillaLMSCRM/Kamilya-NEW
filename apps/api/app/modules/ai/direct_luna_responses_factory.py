"""Exact-tenant server configuration for the unselected DEV direct Responses route."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from pydantic import SecretStr

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.qa_luna_dev_route import QA_TENANT


def create_direct_qa_responses_client(*, settings: Any, tenant_id: UUID, user_id: UUID,
                                      job_id: str) -> DirectLunaResponsesClient:
    key = getattr(settings, 'AI_DIRECT_LUNA_QA_API_KEY', None)
    revision = getattr(settings, 'AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION', None)
    if (tenant_id != QA_TENANT or not isinstance(user_id, UUID) or not job_id
            or getattr(settings, 'AI_DIRECT_LUNA_QA_DEV_ENABLED', False) is not True
            or getattr(settings, 'AI_MANAGED_LUNA_QA_DEV_ENABLED', False) is not False
            or getattr(settings, 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED', False) is not True
            or getattr(settings, 'DEPLOYMENT_ENVIRONMENT', None) not in {'render-development-worker', 'vm-development-worker'}
            or not isinstance(key, SecretStr) or not key.get_secret_value().strip()
            or not isinstance(revision, str) or not revision.strip()):
        raise ValueError('direct_qa_responses_unavailable')
    return DirectLunaResponsesClient(api_key=key.get_secret_value(), tenant_id=tenant_id,
        user_id=user_id, job_id=job_id, credential_revision=revision)


async def create_managed_qa_client(*, settings: Any, tenant_id: UUID, user_id: UUID,
                                   job_id: str, reasoning_effort: str = "low", deadline_seconds: float = 60.0,
                                   profile: str = "legacy-luna56") -> Any:
    """Fresh managed-auth QA only; never activate the global reserve route."""
    from app.modules.admin.model_routing.chatgpt_reserve import check_readiness, configuration_blocker
    from app.modules.ai.managed_luna_client import LUNA6_MODEL, MODEL, ManagedLunaClient

    revision = getattr(settings, "AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION", None)
    if type(profile) is not str or profile not in {"legacy-luna56", "luna6"}:
        raise ValueError("managed_qa_luna_unavailable")
    if profile == "luna6":
        if reasoning_effort != "low" or deadline_seconds != 60.0:
            raise ValueError("managed_qa_luna_unavailable")
        model, reasoning_effort, deadline_seconds = LUNA6_MODEL, "high", 300.0
        readiness_settings = SimpleNamespace(
            CHATGPT_RESERVE_URL=getattr(settings, "CHATGPT_RESERVE_URL", None),
            CHATGPT_RESERVE_TOKEN=getattr(settings, "CHATGPT_RESERVE_TOKEN", None),
            CHATGPT_RESERVE_MODEL=model,
            CHATGPT_RESERVE_AUTH_MODE=getattr(settings, "CHATGPT_RESERVE_AUTH_MODE", None))
    else:
        model, readiness_settings = MODEL, settings
    if (tenant_id != QA_TENANT or not isinstance(user_id, UUID) or not job_id
            or type(reasoning_effort) is not str or reasoning_effort not in ({"high"} if profile == "luna6" else {"low", "medium"})
            or isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int | float)
            or not 0 < deadline_seconds <= (300 if profile == "luna6" else 120)
            or getattr(readiness_settings, "CHATGPT_RESERVE_MODEL", None) != model
            or getattr(settings, "AI_MANAGED_LUNA_QA_DEV_ENABLED", False) is not True
            or getattr(settings, "AI_DIRECT_LUNA_QA_DEV_ENABLED", False) is not False
            or getattr(settings, "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED", False) is not True
            or getattr(settings, "DEPLOYMENT_ENVIRONMENT", None) not in {"render-development-worker", "vm-development-worker"}
            or not isinstance(revision, str) or not revision.strip()
            # Both readiness functions consume only the four reserve fields in this view.
            or configuration_blocker(cast(Any, readiness_settings)) is not None):
        raise ValueError("managed_qa_luna_unavailable")
    readiness = await check_readiness(cast(Any, readiness_settings))
    if readiness.ready is not True:
        raise ValueError("managed_qa_luna_unavailable")
    return ManagedLunaClient(base_url=readiness_settings.CHATGPT_RESERVE_URL,
        api_key=readiness_settings.CHATGPT_RESERVE_TOKEN, tenant_id=tenant_id, user_id=user_id,
        job_id=job_id, credential_revision=revision, reasoning_effort=reasoning_effort,
        deadline_seconds=deadline_seconds, model=model)
