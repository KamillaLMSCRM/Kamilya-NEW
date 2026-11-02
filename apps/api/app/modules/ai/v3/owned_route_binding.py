"""Fresh QA-v3 worker route binding; never accepts route identity from a request."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.models.ai_generation_checkpoint import AIGenerationRun
from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import _locked_job, has_pending
from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, MANAGED_POLICY
from app.modules.ai.v3.qa_luna_pending_policy import KEY as POLICY_KEY

KEY = "v3_owned_route_binding"
POLICY = "v3-owned-route-binding-v1"


async def bind_owned_route(*, journal: Any, user_id: Any, client: DirectLunaResponsesClient | ManagedLunaClient) -> str:
    """Install once under the delivery lock; old unbound stage histories hold."""
    try:
        if (type(client) not in (DirectLunaResponsesClient, ManagedLunaClient) or journal.tenant_id != str(QA_TENANT)
                or client._scope != (QA_TENANT, user_id, journal.job_id) or client._closed):
            raise ValueError("v3_route_binding_scope_invalid")
        expected_policy = MANAGED_POLICY if type(client) is ManagedLunaClient else DIRECT_POLICY
        fingerprint = client.cache_fingerprint()
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("v3_route_binding_invalid")
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            params = job.params if isinstance(job.params, dict) else {}
            analysis = params.get("source_analysis")
            if (job.course_id is not None or not isinstance(analysis, dict)
                    or analysis.get(POLICY_KEY) != expected_policy or analysis.get("generation_engine") != "evidence_v3"
                    or job.result is not None and not isinstance(job.result, dict)):
                raise ValueError("v3_route_binding_owner_invalid")
            result = dict(job.result or {})
            expected = {"policy": POLICY, "fingerprint": fingerprint}
            if KEY in result:
                if result[KEY] != expected:
                    raise ValueError("v3_route_binding_changed")
            else:
                if has_pending(job.result):
                    raise ValueError("v3_route_binding_legacy_pending")
                prior = await session.scalar(select(AIGenerationRun.id).where(
                    AIGenerationRun.tenant_id == journal.tenant_id,
                    AIGenerationRun.source_job_id == journal.job_id).limit(1))
                if prior is not None:
                    raise ValueError("v3_route_binding_legacy_history")
                result[KEY] = expected
                job.result = result
            await session.commit()
            return fingerprint
    except BaseException as exc:
        raise ExtractionOutcomeUnknownError("v3_route_binding_unverified") from exc
