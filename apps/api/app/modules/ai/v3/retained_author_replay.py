"""Read-only eligibility for explicitly supported completed-response protocols."""
from __future__ import annotations

import base64
import hashlib
import re
from typing import Any
from uuid import UUID

from app.modules.ai.v3.managed_rejection_quarantine import KEY, POLICY, private_key, private_plan
from app.modules.ai.v3.managed_rejection_quarantine import _valid_reference as _valid_quarantine_reference
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import checked_entries
from app.modules.ai.v3.stage_checkpoint import _digest

AUTHORIZATION_KEY = "v3_retained_author_replay"
AUTHORIZATION_POLICY = "v3-retained-author-replay-v1"


def is_retained_author_group(value: object) -> bool:
    """Match only practical V31 author IDs with a supported serialized output cap."""
    from app.modules.ai.v3.revision_policy import PRACTICAL_MAX_OUTPUT_TOKENS

    return isinstance(value, str) and value in {
        f"practical:author:editorial:v31:output={cap}" for cap in (8192, PRACTICAL_MAX_OUTPUT_TOKENS)
    }


def is_retained_stage_plan(plan: dict[str, Any]) -> bool:
    if is_semantic_plan_stage(plan):
        return True
    if plan.get('stage') == 'lesson':
        return is_retained_author_group(plan.get('group_id')) or is_focused_author_plan(plan)
    group = plan.get('group_id')
    return bool(
        plan.get('stage') == 'review' and isinstance(group, str) and re.fullmatch(
            r'practical:editorial:verify:v34:joint:[a-f0-9]{64}:output=(8192|16384|32768)', group)
        or is_simple_evidence_stage(plan)
    )


def is_simple_evidence_stage(plan: Any) -> bool:
    """Identify only the V11 evidence-repair metadata frontier.

    This is deliberately narrower than the V11 policy: V11 plans/authors and
    other repairs are not eligible for retained-author replay.
    """
    return bool(isinstance(plan, dict) and plan.get('stage') == 'repair'
        and isinstance(plan.get('group_id'), str)
        and re.fullmatch(
            r'practical:simple:repair-evidence:v11:[a-f0-9]{64}:unit=[a-f0-9]{64}:'
            r'proposal=[a-f0-9]{64}:output=(8192|16384|32768)', plan['group_id']))


def is_focused_author_plan(plan: Any) -> bool:
    return bool(isinstance(plan, dict) and plan.get('stage') == 'lesson'
        and isinstance(plan.get('group_id'), str) and re.fullmatch(
            r'practical:focused:author:v36:[a-f0-9]{64}:output=(8192|16384|32768)', plan['group_id']))


def is_semantic_plan_stage(plan: Any) -> bool:
    return semantic_plan_review_policy(plan) is not None


def semantic_plan_review_policy(plan: Any) -> str | None:
    from app.modules.ai.v3.revision_policy import (
        SIMPLE_COURSE_REVIEW_V6_POLICY,
        SIMPLE_COURSE_REVIEW_V9_POLICY,
        SIMPLE_COURSE_REVIEW_V11_POLICY,
    )

    if not (isinstance(plan, dict) and plan.get('stage') == 'review' and isinstance(plan.get('group_id'), str)):
        return None
    match = re.fullmatch(r'practical:simple:plan:v(6|9|11):[a-f0-9]{64}:output=(8192|16384|32768)', plan['group_id'])
    if not match:
        return None
    return {'6': SIMPLE_COURSE_REVIEW_V6_POLICY, '9': SIMPLE_COURSE_REVIEW_V9_POLICY,
            '11': SIMPLE_COURSE_REVIEW_V11_POLICY}[match[1]]


def retained_phase_allowed(plan: dict[str, Any], phase: Any) -> bool:
    if is_simple_evidence_stage(plan):
        return bool(phase == 'stage_finalize')
    return bool(phase == 'structured_shape' and not is_focused_author_plan(plan) and is_retained_stage_plan(plan)
                or phase == 'stage_finalize' and is_focused_author_plan(plan))


async def owned_candidate(db: Any, job: Any) -> dict[str, Any] | None:
    """Read private checkpoints; caller holds the job lock when authorizing a delivery."""
    try:
        if (not isinstance(job.result, dict) or not isinstance(job.user_id, UUID)
                or job.course_id is not None):
            return None
        entries = checked_entries(job.result)
        if len(entries) != 1:
            return None
        digest, entry = next(iter(entries.items()))
        if entry["claim_key"] != "v3-stage-claim:" + digest or entry["result_key"] != "v3-stage-result:" + digest:
            return None
        quarantine = job.result.get(KEY)
        if (not isinstance(quarantine, dict) or quarantine.get("policy") != POLICY
                or set(quarantine) != {"policy", "entries"} or not isinstance(quarantine.get("entries"), dict)
                or not quarantine["entries"]
                or any(not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key)
                       or not _valid_quarantine_reference(key, value)
                       for key, value in quarantine["entries"].items())
                or digest not in quarantine["entries"]):
            return None
        reference = quarantine["entries"][digest]
        if (reference.get('complete_http_response') is not True
                or type(reference.get('status')) is not int or reference.get('status') != 200
                or reference.get('phase') not in {'structured_shape', 'stage_finalize'}):
            return None
        journal = PendingStageJournal(str(job.tenant_id), job.user_id, str(job.id), None)
        saved_plan = await journal.repository.load_plan(db, tenant_id=journal.tenant_id,
                                                        generation_key=journal._owned_key(entry["claim_key"]))
        plan = dict(saved_plan.plan_payload)
        if (_digest(plan) != digest or plan.get("schema") != "v3-stage-checkpoint-v1"
                or not is_retained_stage_plan(plan)
                or not retained_phase_allowed(plan, reference.get('phase'))
                or plan.get("tenant_id") != journal.tenant_id or plan.get("job_id") != journal.job_id
                or plan.get("route_fingerprint") != reference.get("route_fingerprint")):
            return None
        if is_focused_author_plan(plan):
            from app.modules.ai.v3.revision_policy import FOCUSED_EDITORIAL_REVIEW_POLICY, REVIEW_KEY
            params = job.params if isinstance(getattr(job, 'params', None), dict) else {}
            analysis = params.get('source_analysis')
            if not isinstance(analysis, dict) or analysis.get(REVIEW_KEY) != FOCUSED_EDITORIAL_REVIEW_POLICY:
                return None
        if is_semantic_plan_stage(plan):
            from app.modules.ai.v3.revision_policy import REVIEW_KEY
            params = job.params if isinstance(getattr(job, 'params', None), dict) else {}
            analysis = params.get('source_analysis')
            if not isinstance(analysis, dict) or analysis.get(REVIEW_KEY) != semantic_plan_review_policy(plan):
                return None
        if is_simple_evidence_stage(plan):
            from app.modules.ai.v3.revision_policy import REVIEW_KEY, SIMPLE_COURSE_REVIEW_V11_POLICY
            params = job.params if isinstance(getattr(job, 'params', None), dict) else {}
            analysis = params.get('source_analysis')
            if not isinstance(analysis, dict) or analysis.get(REVIEW_KEY) != SIMPLE_COURSE_REVIEW_V11_POLICY:
                return None
        marker = await journal.read_owned_value_in_session(db, entry["claim_key"], plan)
        if marker != {"identity": digest, "claim_token": entry["token"]}:
            return None
        result_plan = await journal.repository.load_plan(db, tenant_id=journal.tenant_id,
                                                        generation_key=journal._owned_key(entry["result_key"]))
        if (result_plan.source_job_id != saved_plan.source_job_id
                or result_plan.plan_revision != saved_plan.plan_revision or result_plan.lessons != saved_plan.lessons
                or dict(result_plan.plan_payload) != plan
                or await journal.read_owned_value_in_session(db, entry["result_key"], plan) is not None):
            return None
        receipt = await journal.read_owned_value_in_session(db, private_key(digest), private_plan(plan))
        if not isinstance(receipt, dict) or {k: v for k, v in receipt.items() if k != "raw_base64"} != {
                k: v for k, v in reference.items() if k != "checkpoint_key"}:
            return None
        raw = base64.b64decode(receipt["raw_base64"], validate=True)
        if (type(receipt.get("byte_count")) is not int or len(raw) != receipt["byte_count"]
                or len(raw) > 2097152 or hashlib.sha256(raw).hexdigest() != receipt.get("body_sha256")
                or not isinstance(receipt.get("wire_request_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", receipt["wire_request_sha256"]) is None):
            return None
        return {"stage": digest, "body_sha256": receipt["body_sha256"],
                "pending_sha256": _digest(job.result["v3_pending_stages"]), "plan": plan,
                "marker": marker, "receipt": receipt}
    except Exception:
        return None
