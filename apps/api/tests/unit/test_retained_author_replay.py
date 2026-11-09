import base64
import hashlib
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.ai.v3 import retained_author_replay as replay
from app.modules.ai.v3.stage_checkpoint import _digest


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "other_stage", "claim", "body", "reference", "multiple"])
@pytest.mark.parametrize(("group", "stage", "allowed"), [
    ("practical:author:editorial:v31:output=16384", "lesson", True),
    ("practical:author:editorial:v31:output=8192", "lesson", True),
    ("practical:author:editorial:v31", "lesson", False),
    ("practical:review:editorial:v31:output=16384", "review", False),
    ("practical:author:editorial:v31:output=016384", "lesson", False),
    ("practical:author:editorial:v31:output=32768", "lesson", False),
    ("practical:author:editorial:v31:output=16384:other", "lesson", False),
    ("practical:editorial:verify:v34:joint:" + "f" * 64 + ":output=32768", "review", True),
    ("practical:editorial:verify:v34:joint:" + "f" * 64 + ":output=16384", "review", True),
    ("practical:editorial:verify:v34:joint:" + "f" * 64 + ":output=32768", "lesson", False),
    ("practical:editorial:verify:v33:joint:" + "f" * 64 + ":output=32768", "review", False),
    ("practical:editorial:verify:v34:proof:" + "f" * 64 + ":output=32768", "review", False),
    ("practical:editorial:verify:v34:complete-resolutions:" + "f" * 64 + ":output=32768", "review", False),
])
async def test_private_candidate_is_exact_and_fail_closed(monkeypatch, mutation, group, stage, allowed):
    tenant, actor, job_id = str(uuid4()), uuid4(), str(uuid4())
    plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": tenant, "job_id": job_id,
            "stage": stage, "group_id": group, "route_fingerprint": "a" * 64}
    digest = _digest(plan)
    entry = {"claim_key": "v3-stage-claim:" + digest, "result_key": "v3-stage-result:" + digest, "token": "b" * 32}
    raw = b"synthetic"
    receipt = {"policy": replay.POLICY, "accepted": False, "complete_http_response": True, "status": 200,
               "phase": "structured_shape", "stage_sha256": digest, "route_fingerprint": "a" * 64,
               "wire_request_sha256": "c" * 64, "raw_base64": base64.b64encode(raw).decode(),
               "body_sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw)}
    reference = {k: v for k, v in receipt.items() if k != "raw_base64"} | {"checkpoint_key": replay.private_key(digest)}
    job = SimpleNamespace(id=job_id, tenant_id=tenant, user_id=actor, course_id=None, result={
        "v3_pending_stages": {"policy": "v3-pending-stages-v1", "entries": {digest: entry}},
        replay.KEY: {"policy": replay.POLICY, "entries": {digest: reference}}})
    marker = {"identity": digest, "claim_token": entry["token"]}
    class Journal:
        def __init__(self, tenant_id, user_id, job_id, sessions):
            self.tenant_id, self.job_id = tenant_id, job_id
            self.repository = self
        def _owned_key(self, key): return key
        async def load_plan(self, *_args, **_kwargs):
            return SimpleNamespace(plan_payload=plan, source_job_id=job_id, plan_revision='v1', lessons=('lesson',))
        async def read_owned_value_in_session(self, _db, key, _plan):
            return marker if key == entry["claim_key"] else None if key == entry["result_key"] else receipt
    monkeypatch.setattr(replay, "PendingStageJournal", Journal)
    if mutation == "other_stage":
        plan["group_id"] = "practical:review:editorial:v31"
    if mutation == "claim":
        marker["claim_token"] = "d" * 32
    if mutation == "body":
        receipt["raw_base64"] = base64.b64encode(b"tampered").decode()
    if mutation == "reference":
        reference["phase"] = "usage"
    if mutation == "multiple":
        job.result["v3_pending_stages"]["entries"]["e" * 64] = deepcopy(entry)
    candidate = await replay.owned_candidate(object(), job)
    assert (candidate is not None) is (mutation is None and allowed)
