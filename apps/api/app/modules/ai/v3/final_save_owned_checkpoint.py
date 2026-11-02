"""Unwired owned final-output checkpoint, atomically fenced before any save."""
from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError, PlannedLesson
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.final_save_contract import FENCE_POLICY, INTENT_KEY, install_intent
from app.modules.ai.v3.final_save_snapshot import make_snapshot, validate_snapshot
from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY
from app.modules.ai.v3.owned_route_binding import POLICY as ROUTE_POLICY
from app.modules.ai.v3.owned_source_context import OwnedSourceContext
from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
from app.modules.ai.v3.pending_stage_transactions import _locked_job
from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, KEY
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal


async def checkpoint_final_output(*, journal: WorkerCycleJournal, context: OwnedSourceContext,
                                  state: Any, intent: dict[str, Any]) -> None:
    """Persist snapshot and lifecycle fence in one owned transaction; never save a course."""
    from app.modules.ai.lesson_cycle import POLICY_VERSION
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.source_assessment_plan import PLAN_POLICY

    try:
        if (type(context) is not OwnedSourceContext or context.journal is not journal
                or context.tenant_id != QA_TENANT or not isinstance(context.user_id, UUID)
                or str(context.tenant_id) != journal.tenant_id or context.job_id != journal.job_id
                or state.course_id is not None):
            raise ValueError("v3_final_checkpoint_scope_invalid")
        snapshot = make_snapshot(state, intent)
        if (intent["tenant_id"] != journal.tenant_id or intent["job_id"] != journal.job_id
                or intent["user_id"] != str(context.user_id)):
            raise ValueError("v3_final_checkpoint_scope_invalid")
        corpus = context.corpus
        if tuple(context.selection) != tuple(d["doc_id"] for d in intent["documents"]):
            raise ValueError("v3_final_checkpoint_source_invalid")
        for doc, expected in zip(corpus.documents, intent["documents"], strict=True):
            if (doc.doc_id != expected["doc_id"] or doc.source_revision != expected["revision"]
                    or not isinstance(doc.source_text, str)
                    or hashlib.sha256(doc.source_text.encode()).hexdigest() != expected["text_sha256"]):
                raise ValueError("v3_final_checkpoint_source_invalid")
        plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": journal.tenant_id,
                "job_id": journal.job_id, "source_sha256": hashlib.sha256(
                    "\n\n".join(d.source_text for d in corpus.documents if d.source_text).encode()).hexdigest()}
        checkpoint_plan = {"schema": "v3-final-snapshot-v1", "intent_digest": intent["intent_digest"]}
        key = "v3-final-snapshot:" + intent["intent_digest"]
        async with journal.sessions() as session:
            job: Any = await _locked_job(session, journal, context.user_id)
            params = job.params if isinstance(job.params, dict) else {}
            analysis = params.get("source_analysis")
            if (job.course_id is not None or not isinstance(analysis, dict)
                    or analysis.get(KEY) != DIRECT_POLICY or analysis.get("generation_engine") != "evidence_v3"
                    or job.result is None or not isinstance(job.result, dict)
                    or job.result.get("delivery_task_id") != intent["delivery_id"]
                    or job.result.get(ROUTE_KEY) != {"policy": ROUTE_POLICY, "fingerprint": intent["route_fingerprint"]}
                    or await context.verify_locked(session, job, plan) is not True):
                raise ValueError("v3_final_checkpoint_owner_invalid")
            if INTENT_KEY in job.result:
                fence = {"policy": FENCE_POLICY, "intent_digest": intent["intent_digest"],
                         "attempt_id": intent["attempt_id"]}
                if job.result[INTENT_KEY] != intent or job.result.get(PENDING_KEY) != fence:
                    raise ValueError("v3_final_checkpoint_intent_mismatch")
                saved = await journal.read_owned_value_in_session(session, key, checkpoint_plan)
                if saved != snapshot or not validate_snapshot(saved, expected_intent_digest=intent["intent_digest"]):
                    raise ValueError("v3_final_checkpoint_replay_invalid")
                await session.commit()
                return
            try:
                await journal.repository.load_plan(session, tenant_id=journal.tenant_id, generation_key=journal._owned_key(key))
            except AIGenerationCheckpointError as exc:
                if str(exc) != "generation_plan_not_found":
                    raise
            else:
                raise ValueError("v3_final_checkpoint_orphan")
            await journal.repository.create_plan(session, tenant_id=journal.tenant_id,
                generation_key=journal._owned_key(key), plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                source_job_id=journal.job_id, plan_payload=checkpoint_plan,
                lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
            fields = dict(tenant_id=journal.tenant_id, generation_key=journal._owned_key(key),
                          module_key="cycle", lesson_key="lesson")
            await journal.repository.checkpoint_content(session, **fields, content_payload={"owned": True})
            await journal.repository.checkpoint_review(session, **fields, review_payload={"policy": PLAN_POLICY})
            await journal.repository.checkpoint_assessment(session, **fields, assessment_payload=snapshot)
            job.result = install_intent(job.result, intent)
            await session.commit()
    except BaseException as exc:
        raise ExtractionOutcomeUnknownError("v3_final_checkpoint_unverified") from exc
