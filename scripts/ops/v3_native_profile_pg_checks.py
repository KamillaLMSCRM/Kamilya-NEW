"""Disposable-schema native V2 custody exercise. No external provider calls."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from uuid import uuid4


async def exercise(owner: Any, runtime: Any, schema: str, tenant: Any, *, enabled: bool) -> None:
    if not enabled:
        raise RuntimeError("native_gate_disabled")
    import ai_generation_checkpoint_dev_check as canonical
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.modules.ai import delivery_ownership
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.managed_rejection_quarantine import KEY, private_key
    from app.modules.ai.v3.native_profile_binding import KEY as PROFILE_KEY
    from app.modules.ai.v3.native_profile_binding import bind_native_profile
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.provider_profile import V3ProfiledClient
    from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
    from app.modules.ai.v3.revision_policy import POLICY, stamp_policy
    from app.modules.ai.v3.stage_checkpoint import _digest

    canonical.validate_schema(schema)
    job, actor = str(uuid4()), uuid4()
    params = {'source_analysis': stamp_policy({'generation_engine': 'evidence_v3'})}
    async with owner.begin() as conn:
        await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs (id,tenant_id,user_id,status,params,result)
            VALUES(:j,:t,:u,'running',CAST(:p AS json),CAST(:r AS json))'''),
            {'j': job, 't': tenant, 'u': actor, 'p': json.dumps(params), 'r': '{}'})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    async def source(_session: Any, _job: Any, _plan: Any) -> bool:
        return True  # Synthetic fixture only; real source drift is exercised separately.
    journal = PendingStageJournal(str(tenant), actor, job, sessions, verify_source=source)
    journal.expected_revision_policy = POLICY
    journal.expected_revision_actor = actor
    class SyntheticSource:
        async def verify_locked(self, _session: Any, locked: Any, _plan: Any) -> bool:
            return locked.user_id == actor and str(locked.tenant_id) == str(tenant)
    journal.expected_revision_source = SyntheticSource()
    journal.expected_revision_plan = {'synthetic': True}
    client = object.__new__(V3ProfiledClient)
    client._fingerprint = 'a' * 64
    token = delivery_ownership.delivery_id.set(job)
    try:
        await bind_native_profile(journal=journal, user_id=actor, client=client)
        plan = {'tenant_id': str(tenant), 'job_id': job, 'route_fingerprint': 'a' * 64,
                'request_sha256': 'b' * 64, 'stage': 'synthetic-native'}
        calls = []
        entered, release = asyncio.Event(), asyncio.Event()
        async def invoke() -> dict[str, Any]:
            calls.append(1)
            entered.set()
            await release.wait()
            raise ModelArtifactRejectedError('synthetic-native-content').bound(job_id=job, route='a' * 64, request='b' * 64)
        def validate(value: dict[str, Any]) -> dict[str, Any]:
            return value
        args = dict(plan=plan, result_key='native-result', claim_key='native-claim', validate_value=validate,
                    validate_response=validate, invoke=invoke)
        first = asyncio.create_task(journal.run_pending(**args))
        try:
            await asyncio.wait_for(entered.wait(), timeout=20)
            other = {**plan, 'request_sha256': 'd' * 64}
            try:
                await journal.run_pending(**(args | {'plan': other, 'result_key': 'other-result', 'claim_key': 'other-claim'}))
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError('native_distinct_claim_allowed')
        finally:
            release.set()
        try:
            await first
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError('native_rejection_not_held')
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            result = await session.scalar(text(f'SELECT result FROM "{schema}".ai_jobs WHERE id=:j'), {'j': job})
            if not isinstance(result, dict) or result.get(PROFILE_KEY) != journal.expected_native_profile:
                raise AssertionError('native_profile_not_saved')
            if 'synthetic-native-content' in json.dumps(result):
                raise AssertionError('native_artifact_in_job')
        receipt = await journal.read_owned_value(private_key(_digest(plan)), {'policy': 'managed-response-quarantine-v1',
            'accepted': False, 'stage_plan': plan})
        if (not receipt or receipt.get('capture_kind') != 'model_content_text' or receipt.get('status') is not None
                or receipt.get('complete_http_response') is not False
                or base64.b64decode(receipt['raw_base64']) != b'synthetic-native-content'):
            raise AssertionError('native_artifact_custody_invalid')
        if KEY not in result:
            raise AssertionError('native_artifact_reference_missing')
        try:
            await journal.run_pending(**args)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError('native_cold_pending_not_held')
        if len(calls) != 1:
            raise AssertionError('native_pending_retried')
        async with owner.begin() as conn:
            altered = dict(result)
            altered[PROFILE_KEY] = {'policy': 'v3-native-profile-binding-v1', 'fingerprint': 'c' * 64}
            await conn.execute(text(f'UPDATE "{schema}".ai_jobs SET result=CAST(:r AS json) WHERE id=:j'),
                               {'r': json.dumps(altered), 'j': job})
        try:
            await journal.run_pending(**args)
        except Exception:
            pass
        else:
            raise AssertionError('native_profile_drift_allowed')
        if len(calls) != 1:
            raise AssertionError('native_profile_drift_invoked')
    finally:
        delivery_ownership.delivery_id.reset(token)
