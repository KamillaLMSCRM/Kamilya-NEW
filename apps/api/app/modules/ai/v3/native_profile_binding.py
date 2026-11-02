"""Bind a new ordinary V3 job to its effective provider profile before inference."""
from __future__ import annotations

from typing import Any

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import _locked_job
from app.modules.ai.v3.provider_profile import V3ProfiledClient
from app.modules.ai.v3.revision_policy import POLICY, read_policy

KEY = "v3_native_profile_binding"
POLICY_ID = "v3-native-profile-binding-v1"


async def bind_native_profile(*, journal: Any, user_id: Any, client: V3ProfiledClient) -> None:
    if type(client) is not V3ProfiledClient or journal.expected_revision_policy != POLICY:
        raise ValueError("v3_native_profile_scope_invalid")
    expected = {"policy": POLICY_ID, "fingerprint": client.cache_fingerprint()}
    try:
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            if read_policy(job.params.get("source_analysis")) != POLICY:
                raise ValueError("v3_native_profile_policy_changed")
            previous = (job.result or {}).get(KEY)
            if KEY in (job.result or {}) and previous != expected:
                raise ValueError("v3_native_profile_route_changed")
            if previous is None:
                job.result = {**(job.result or {}), KEY: expected}
            await session.commit()
        journal.expected_native_profile = expected
    except Exception:
        raise ExtractionOutcomeUnknownError("v3_native_profile_binding_unverified") from None
