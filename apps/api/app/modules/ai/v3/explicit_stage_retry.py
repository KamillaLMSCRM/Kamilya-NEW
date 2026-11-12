"""One acknowledged DEV QA retry; original unknown claim and completed work survive."""
from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator
from sqlalchemy import select

from app.models.ai_generation_checkpoint import AIGenerationRun
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
from app.modules.ai.v3.pending_stage_transactions import checked_entries
from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_KEY
from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.stage_checkpoint import _digest, _validate_direct_metadata

KEY = 'v3_explicit_stage_retries'
POLICY = 'v3-explicit-unknown-stage-retry-v1'
_HEX = re.compile(r'[a-f0-9]{64}')
_PLAN_KEYS = {'schema', 'tenant_id', 'job_id', 'stage', 'group_id', 'source_sha256',
              'route_fingerprint', 'request_sha256'}


class UnknownStageRetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage_sha256: str
    recovery_id: UUID
    acknowledge_unknown_outcome: StrictBool

    @field_validator('stage_sha256')
    @classmethod
    def stage_valid(cls, value: str) -> str:
        if not _HEX.fullmatch(value):
            raise ValueError('explicit_stage_retry_invalid')
        return value

    @field_validator('acknowledge_unknown_outcome')
    @classmethod
    def acknowledged(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError('explicit_stage_retry_acknowledgement_required')
        return value


class ResumeGenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    retry_unfinished: UnknownStageRetryRequest | None = None


def _plan_valid(plan: Any) -> bool:
    if (not isinstance(plan, dict) or set(plan) != _PLAN_KEYS
            or plan.get('schema') != 'v3-stage-checkpoint-v1'
            or any(not isinstance(plan.get(k), str) or not _HEX.fullmatch(plan[k])
                   for k in ('source_sha256', 'route_fingerprint', 'request_sha256'))):
        return False
    match = re.fullmatch(
        r'practical:simple:(plan|author-unit|review-unit|review-content|editor-joint|repair-address):v9:'
        r'[a-f0-9]{64}(?::plan=[a-f0-9]{64})?(?::unit=[a-f0-9]{64})?'
        r'(?::proposal=[a-f0-9]{64})?:output=(8192|16384|32768)', plan.get('group_id', ''))
    expected = {'plan': 'review', 'author-unit': 'lesson', 'review-unit': 'review',
                'review-content': 'review', 'editor-joint': 'repair', 'repair-address': 'repair'}
    return bool(match and plan.get('stage') == expected[match[1]])


def checked_ledger(params: Any) -> dict[str, Any] | None:
    if isinstance(params, dict) and KEY not in params:
        return None
    ledger = params.get(KEY) if isinstance(params, dict) else None
    if (not isinstance(ledger, dict) or set(ledger) != {'policy', 'entries'}
            or ledger['policy'] != POLICY or not isinstance(ledger['entries'], dict) or len(ledger['entries']) != 1):
        raise ValueError('explicit_stage_retry_ledger_invalid')
    for digest, entry in ledger['entries'].items():
        if (not isinstance(digest, str) or not _HEX.fullmatch(digest) or not isinstance(entry, dict)
                or entry.get('original_stage_sha256') != digest or not _plan_valid(entry.get('original_plan'))
                or _digest(entry['original_plan']) != digest or entry.get('prior_outcome') != 'UNKNOWN'
                or entry.get('prior_usage') != 'UNKNOWN' or entry.get('prior_cost') != 'UNKNOWN'
                or not isinstance(entry.get('pending_sha256'), str) or not _HEX.fullmatch(entry['pending_sha256'])):
            raise ValueError('explicit_stage_retry_ledger_invalid')
        for key in ('recovery_id', 'actor_id'):
            if str(UUID(entry[key])) != entry[key]:
                raise ValueError('explicit_stage_retry_ledger_invalid')
        inventory = entry.get('completed_stages')
        if not isinstance(inventory, dict):
            raise ValueError('explicit_stage_retry_inventory_invalid')
        groups = set()
        for sid, row in inventory.items():
            if (not isinstance(row, dict) or set(row) != {'plan', 'response_sha256', 'direct_metadata_sha256'}
                    or not _plan_valid(row['plan']) or _digest(row['plan']) != sid or sid == digest
                    or any(row['plan'][k] != entry['original_plan'][k]
                           for k in ('tenant_id', 'job_id', 'source_sha256', 'route_fingerprint'))
                    or row['plan']['group_id'] in groups
                    or any(not isinstance(row[k], str) or not _HEX.fullmatch(row[k])
                           for k in ('response_sha256', 'direct_metadata_sha256'))):
                raise ValueError('explicit_stage_retry_inventory_invalid')
            groups.add(row['plan']['group_id'])
    return copy.deepcopy(ledger)


def retry_plan(original_plan: dict[str, Any], ledger: dict[str, Any] | None) -> dict[str, Any]:
    if ledger is None:
        return original_plan
    checked = checked_ledger({KEY: ledger})
    assert checked is not None
    digest = _digest(original_plan)
    entry = checked['entries'].get(digest)
    if entry is None:
        return original_plan
    if entry['original_plan'] != original_plan:
        raise ValueError('explicit_stage_retry_plan_changed')
    return {**original_plan, 'explicit_recovery': {'policy': POLICY,
        'original_stage_sha256': digest, 'recovery_id': entry['recovery_id']}}


async def retry_candidate(db: Any, job: Any, actor_id: Any, settings: Any) -> dict[str, Any] | None:
    """Read-only proof; admission calls again while holding tenant and job locks."""
    try:
        if (str(job.tenant_id) != str(QA_TENANT) or not isinstance(actor_id, UUID) or job.user_id != actor_id
                or job.status != 'interrupted' or job.course_id is not None
                or getattr(settings, 'DEPLOYMENT_ENVIRONMENT', None) != 'render-development'
                or getattr(settings, 'AI_MANAGED_LUNA_QA_DEV_ENABLED', False) is not True
                or getattr(settings, 'AI_DIRECT_LUNA_QA_DEV_ENABLED', False) is not False
                or getattr(settings, 'AI_QA_LUNA_DEV_ENABLED', False) is not True):
            return None
        params = job.params if isinstance(job.params, dict) else {}
        analysis = params.get('source_analysis')
        if (not isinstance(analysis, dict) or analysis.get('generation_engine') != 'evidence_v3'
                or analysis.get('v3_review_policy') != SIMPLE_COURSE_REVIEW_V9_POLICY
                or analysis.get(QA_KEY) != MANAGED_POLICY
                or 'source_reference_review_required' in (job.errors or [])):
            return None
        entries = checked_entries(job.result)
        if (len(entries) != 1 or any(k in job.result for k in
                ('source_first_commit_intent', 'source_first_partitioned_commit_intent'))):
            return None
        digest, entry = next(iter(entries.items()))
        if entry['claim_key'] != 'v3-stage-claim:' + digest or entry['result_key'] != 'v3-stage-result:' + digest:
            return None
        ledger = checked_ledger(params)
        if ledger is not None:
            return None
        journal = PendingStageJournal(str(job.tenant_id), actor_id, str(job.id), None)
        saved = await journal.repository.load_plan(db, tenant_id=journal.tenant_id,
                                                  generation_key=journal._owned_key(entry['claim_key']))
        plan = dict(saved.plan_payload)
        if (not _plan_valid(plan) or _digest(plan) != digest or plan['job_id'] != str(job.id)
                or plan['tenant_id'] != str(job.tenant_id)
                or job.result.get('v3_owned_route_binding') != {
                    'policy': 'v3-owned-route-binding-v1', 'fingerprint': plan['route_fingerprint']}):
            return None
        other = await journal.repository.load_plan(db, tenant_id=journal.tenant_id,
                                                   generation_key=journal._owned_key(entry['result_key']))
        if (dict(other.plan_payload) != plan or other.source_job_id != saved.source_job_id
                or other.plan_revision != saved.plan_revision or other.lessons != saved.lessons
                or saved.source_job_id != str(job.id)):
            return None
        if await journal.read_owned_value_in_session(db, entry['claim_key'], plan) != {
                'identity': digest, 'claim_token': entry['token']}:
            return None
        if await journal.read_owned_value_in_session(db, entry['result_key'], plan) is not None:
            return None
        return {'stage': digest, 'original_plan': plan, 'pending_sha256': _digest(job.result[PENDING_KEY])}
    except Exception:
        return None


async def authorize_retry(db: Any, job: Any, actor_id: Any, settings: Any,
                          request: UnknownStageRetryRequest) -> dict[str, Any]:
    candidate = await retry_candidate(db, job, actor_id, settings)
    if (type(request) is not UnknownStageRetryRequest or request.acknowledge_unknown_outcome is not True
            or candidate is None or request.stage_sha256 != candidate['stage']):
        raise ValueError('explicit_stage_retry_unverified')
    from app.modules.source_editorial_review.service import SOURCE_PINS, resolve_pins
    analysis = job.params['source_analysis']
    selected = job.params.get('documents')
    if (not isinstance(selected, list) or not selected or len(selected) != len(set(selected))
            or SOURCE_PINS not in analysis):
        raise ValueError('explicit_stage_retry_source_unverified')
    try:
        await resolve_pins(db, UUID(str(job.tenant_id)), tuple(selected), analysis[SOURCE_PINS])
    except Exception:
        raise ValueError('explicit_stage_retry_source_unverified') from None
    completed = await completed_inventory(db, job, actor_id)
    ledger = checked_ledger(job.params) or {'policy': POLICY, 'entries': {}}
    if any(e['recovery_id'] == str(request.recovery_id) for e in ledger['entries'].values()):
        raise ValueError('explicit_stage_retry_already_used')
    entry = {**candidate, 'original_stage_sha256': candidate['stage'], 'recovery_id': str(request.recovery_id),
             'actor_id': str(actor_id), 'authorized_at': datetime.now(UTC).isoformat(),
             'prior_outcome': 'UNKNOWN', 'prior_usage': 'UNKNOWN', 'prior_cost': 'UNKNOWN',
             'previous_status': job.status, 'previous_errors': copy.deepcopy(job.errors),
             'previous_delivery_id': job.result.get('delivery_task_id'), 'completed_stages': completed}
    entry.pop('stage')
    ledger['entries'][candidate['stage']] = entry
    params = {**job.params, KEY: ledger}
    checked_ledger(params)
    result = dict(job.result)
    del result[PENDING_KEY]
    # The immutable original checkpoint claim/result records are deliberately untouched.
    job.params, job.result = params, result
    return copy.deepcopy(entry)


async def completed_inventory(db: Any, job: Any, actor_id: UUID) -> dict[str, Any]:
    journal = PendingStageJournal(str(job.tenant_id), actor_id, str(job.id), None)
    rows = (await db.scalars(select(AIGenerationRun).where(
        AIGenerationRun.tenant_id == job.tenant_id, AIGenerationRun.source_job_id == str(job.id)))).all()
    result = {}
    for saved in rows:
        plan = dict(saved.plan_payload)
        if not _plan_valid(plan):
            continue
        digest = _digest(plan)
        key = 'v3-stage-result:' + digest
        if saved.generation_key != journal._owned_key(key):
            continue
        value = await journal.read_owned_value_in_session(db, key, plan)
        if value is None:
            continue
        if (not isinstance(value, dict) or value.get('identity') != digest
                or not isinstance(value.get('response'), dict)
                or value.get('response_sha256') != _digest(value['response'])):
            raise ValueError('explicit_stage_retry_inventory_invalid')
        _validate_direct_metadata(value)
        if 'direct_metadata_sha256' not in value:
            raise ValueError('explicit_stage_retry_inventory_invalid')
        result[digest] = {'plan': plan, 'response_sha256': value['response_sha256'],
                          'direct_metadata_sha256': value['direct_metadata_sha256']}
    return result


async def guard_recovery_stage(journal: Any, original: dict[str, Any]) -> None:
    """Every saved prefix is exact cache replay before the single retry frontier."""
    ledger = journal.explicit_stage_retries
    if ledger is None:
        return
    checked = checked_ledger({KEY: ledger})
    assert checked is not None
    entry = next(iter(checked['entries'].values()))
    inventory = entry['completed_stages']
    if original['group_id'].startswith('practical:simple:plan:v9:'):
        journal.explicit_retry_seen = set()
        journal.explicit_retry_reached = False
    seen = getattr(journal, 'explicit_retry_seen', None)
    if not isinstance(seen, set):
        raise ValueError('explicit_stage_retry_prefix_unverified')
    digest = _digest(original)
    if digest in inventory:
        row = inventory[digest]
        value = await journal.read_owned_value('v3-stage-result:' + digest, original)
        if (row['plan'] != original or not isinstance(value, dict) or value.get('identity') != digest
                or value.get('response_sha256') != row['response_sha256']
                or value.get('direct_metadata_sha256') != row['direct_metadata_sha256']
                or _digest(value.get('response')) != row['response_sha256']):
            raise ValueError('explicit_stage_retry_cached_result_changed')
        _validate_direct_metadata(value)
        seen.add(digest)
        return
    if digest == entry['original_stage_sha256']:
        if seen != set(inventory):
            raise ValueError('explicit_stage_retry_prefix_incomplete')
        journal.explicit_retry_reached = True
        return
    if (any(row['plan']['group_id'] == original['group_id'] for row in inventory.values())
            or entry['original_plan']['group_id'] == original['group_id']
            or not getattr(journal, 'explicit_retry_reached', False)):
        raise ValueError('explicit_stage_retry_request_changed')
