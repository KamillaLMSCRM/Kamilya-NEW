"""Exact-tenant server configuration for the unselected DEV direct Responses route."""
from __future__ import annotations

from typing import Any
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
                                   job_id: str) -> Any:
    """Fresh managed-auth QA only; never activate the global reserve route."""
    from app.modules.admin.model_routing.chatgpt_reserve import check_readiness, configuration_blocker
    from app.modules.ai.managed_luna_client import ManagedLunaClient

    revision = getattr(settings, "AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION", None)
    if (tenant_id != QA_TENANT or not isinstance(user_id, UUID) or not job_id
            or getattr(settings, "AI_MANAGED_LUNA_QA_DEV_ENABLED", False) is not True
            or getattr(settings, "AI_DIRECT_LUNA_QA_DEV_ENABLED", False) is not False
            or getattr(settings, "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED", False) is not True
            or getattr(settings, "DEPLOYMENT_ENVIRONMENT", None) not in {"render-development-worker", "vm-development-worker"}
            or not isinstance(revision, str) or not revision.strip()
            or configuration_blocker(settings) is not None):
        raise ValueError("managed_qa_luna_unavailable")
    readiness = await check_readiness(settings)
    if readiness.ready is not True:
        raise ValueError("managed_qa_luna_unavailable")
    return ManagedLunaClient(base_url=settings.CHATGPT_RESERVE_URL,
        api_key=settings.CHATGPT_RESERVE_TOKEN, tenant_id=tenant_id, user_id=user_id,
        job_id=job_id, credential_revision=revision)
