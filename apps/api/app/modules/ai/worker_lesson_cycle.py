"""DEV-only adapter: automatic source plan -> serial reviewed durable lessons.

No model selection, publication or direct course/quiz writes. Existing generation
repository owns tenant-bound storage; the course pipeline owns draft persistence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import BlockAssessmentResult
from app.modules.ai.generation_checkpoint import AIGenerationCheckpointRepository, PlannedLesson
from app.modules.ai.lesson_cycle import (
    POLICY_VERSION,
    LessonCycleResult,
    LessonPacket,
    ReviewedQuestion,
    SourceExcerpt,
    run_lesson_cycles,
)
from app.modules.ai.llm_client import AllProvidersFailedError
from app.modules.ai.source_assessment_plan import PLAN_POLICY, SourcePlanError, build_source_assessment_plan


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def create_dev_lesson_assessor(*, settings: Any, tenant_id: str, job_id: str,
                               client: Any, session_factory: Any, checkpoint: Any) -> WorkerLessonAssessor | None:
    """Exact existing DEV identities, never APP_ENV (DEV also uses production)."""
    if (settings.DEPLOYMENT_ENVIRONMENT not in {"render-development", "render-development-worker"}
            or not settings.AI_LESSON_CYCLE_DEV_ENABLED
            or tenant_id not in settings.AI_LESSON_CYCLE_DEV_TENANTS):
        return None
    return WorkerLessonAssessor(tenant_id=tenant_id, client=client,
        journal=WorkerCycleJournal(tenant_id, job_id, session_factory), checkpoint=checkpoint)


class _MeasuredClient:
    def __init__(self, client: Any, checkpoint: Any):
        self.client, self.checkpoint = client, checkpoint
        self.calls = self.attempts = 0

    async def ainvoke_validated(self, *args: Any, **kwargs: Any) -> Any:
        await self.checkpoint()
        self.calls += 1
        try:
            response = await self.client.ainvoke_validated(*args, **kwargs)
        except AllProvidersFailedError as exc:
            self.attempts += len(exc.reasons) or 1
            raise
        self.attempts += response.attempt_count
        return response


class WorkerCycleJournal:
    """Small transactions, no database session held during provider calls."""

    def __init__(self, tenant_id: str, job_id: str, session_factory: Any):
        self.tenant_id, self.job_id, self.sessions = tenant_id, job_id, session_factory
        self.repository = AIGenerationCheckpointRepository()

    async def prepare(self, key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        key = self._owned_key(key)
        async with self.sessions() as session:
            await self.repository.create_plan(session, tenant_id=self.tenant_id,
                generation_key=key, plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                source_job_id=self.job_id, plan_payload=payload,
                lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
            rows = await self.repository.load_checkpoints(session, tenant_id=self.tenant_id, generation_key=key)
            await session.commit()
            return dict(rows[0].assessment_payload) if rows[0].assessment_payload is not None else None

    async def save_value(self, key: str, value: dict[str, Any]) -> None:
        key = self._owned_key(key)
        async with self.sessions() as session:
            args = dict(tenant_id=self.tenant_id, generation_key=key, module_key="cycle", lesson_key="lesson")
            await self.repository.checkpoint_content(session, **args, content_payload={"owned": True})
            await self.repository.checkpoint_review(session, **args, review_payload={"policy": PLAN_POLICY})
            await self.repository.checkpoint_assessment(session, **args, assessment_payload=value)
            await session.commit()

    def _owned_key(self, key: str) -> str:
        # Source job ownership is immutable in the repository. A fresh generation
        # must not collide with another job's identical source/lesson checkpoint.
        return "worker-cycle:" + _digest([self.job_id, key])


class _CycleStore:
    def __init__(self, journal: Any, packet: LessonPacket, saved: dict[str, Any] | None, key: str):
        self.journal, self.packet, self.saved, self.key = journal, packet, saved, key

    async def load(self, tenant_id: str, identity: str) -> LessonCycleResult | None:
        if tenant_id != self.packet.tenant_id or identity != self.packet.identity():
            raise ValueError("worker_cycle_store_identity")
        if self.saved is None:
            return None
        value = dict(self.saved)
        value["questions"] = tuple(ReviewedQuestion(**(row | {
            "target_ids": tuple(row["target_ids"]), "options": tuple(row["options"]),
            "option_evidence": tuple(row["option_evidence"]),
        })) for row in value["questions"])
        value["missing_target_ids"] = tuple(value["missing_target_ids"])
        value["issues"] = tuple(value["issues"])
        return LessonCycleResult(**value)

    async def save(self, tenant_id: str, identity: str, result: LessonCycleResult) -> None:
        if tenant_id != self.packet.tenant_id or identity != self.packet.identity() or result.identity != identity:
            raise ValueError("worker_cycle_store_identity")
        await self.journal.save_value(self.key, asdict(result))


class WorkerLessonAssessor:
    def __init__(self, *, tenant_id: str, client: Any, journal: Any, checkpoint: Any):
        self.tenant_id, self.client, self.journal, self.checkpoint = tenant_id, client, journal, checkpoint

    async def __call__(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> BlockAssessmentResult:
        await self.checkpoint()
        client = _MeasuredClient(self.client, self.checkpoint)
        primary = [facts_by_id[fid] for fid in lesson.fact_ids]
        # Preserve governing/sibling rules; no silent top-k truncation. Oversize
        # source context is an explicit review state, not fabricated completeness.
        context = list(facts_by_id.values())
        identity = {"tenant": self.tenant_id, "lesson": asdict(lesson),
                    "facts": [asdict(f) for f in context], "policy": f"{PLAN_POLICY}/{POLICY_VERSION}"}
        plan_key = "source-plan:" + _digest(identity)
        saved = await self.journal.prepare(plan_key, {"input_sha256": _digest(identity), "input": identity})
        def rejected(evidence: Any) -> BlockAssessmentResult:
            return BlockAssessmentResult((), {
                "engine": "lesson_cycle", "terminal_status": "review_required",
                "coverage": {"requires_review": True, "source_plan_rejected": True},
                "lesson_id": lesson.lesson_id, "source_plan_rejection": evidence,
                "logical_model_calls": client.calls, "provider_attempt_count": client.attempts,
            }, client.attempts)

        if saved is not None and saved.get("rejected") is True:
            return rejected(saved.get("evidence"))
        try:
            plan = await build_source_assessment_plan(lesson, primary, context, client=client, saved_evidence=saved)
        except SourcePlanError as exc:
            await self.journal.save_value(plan_key, {"rejected": True, "policy": PLAN_POLICY, "evidence": exc.evidence})
            return rejected(exc.evidence)
        if saved is None:
            await self.journal.save_value(plan_key, plan.evidence)
        await self.checkpoint()
        source_text = "\n".join("\n".join(dict.fromkeys((f.subject, f.attribute, f.value))) for f in context)
        sources = (SourceExcerpt(_digest([asdict(f) for f in context]), source_text),)
        questions = []
        results = []
        # Bounds are per model response, not a license to omit targets.
        admitted = tuple(t for t in plan.targets if t.target_id in plan.admitted_target_ids)
        for start in range(0, len(admitted), 24):
            await self.checkpoint()
            packet = LessonPacket(self.tenant_id, lesson.lesson_id, lesson.title, lesson.content,
                                  sources, admitted[start:start + 24], PLAN_POLICY)
            key = "lesson-cycle:" + packet.identity()
            value = await self.journal.prepare(key, {"packet": asdict(packet)})
            store = _CycleStore(self.journal, packet, value, key)
            result = (await run_lesson_cycles([packet], client=client, store=store))[0]
            results.append(result)
            for q in result.questions:
                fids = tuple(fid for fid, tids in plan.source_target_ids.items() if set(tids) & set(q.target_ids))
                if not fids:
                    raise ValueError("worker_cycle_unowned_question")
                options = tuple(sorted(q.options, key=lambda option: _digest([packet.identity(), q.question_id, option])))
                questions.append(QuestionDraft(
                    question_id=f"{packet.identity()[:16]}:{q.question_id}", lesson_id=lesson.lesson_id,
                    kind="single_choice", prompt=q.text, options=options,
                    correct_answer=q.options[q.correct_index], explanation=q.explanation,
                    fact_id=fids[0], evidence_fact_ids=fids,
                    source_quote="\n".join(str(e["quote"]) for e in q.option_evidence if e["index"] == q.correct_index),
                    semantic_reviewed=True,
                ))
        missing = [t.target_id for t in plan.targets if t.target_id not in plan.admitted_target_ids]
        missing.extend(tid for result in results for tid in result.missing_target_ids)
        requires_review = bool(missing) or plan.requires_review
        return BlockAssessmentResult(tuple(questions), {
            "engine": "lesson_cycle", "policy": f"{PLAN_POLICY}/{POLICY_VERSION}",
            "terminal_status": "review_required" if requires_review else "ready_for_methodologist",
            "coverage": {"requires_review": requires_review, "required_target_count": len(plan.targets),
                         "retained_target_count": len(plan.targets) - len(missing), "missing_target_ids": missing,
                         "unresolved_source_refs": list(plan.unresolved_source_refs)},
            "source_plan": plan.evidence, "lesson_id": lesson.lesson_id,
            "logical_model_calls": client.calls, "provider_attempt_count": client.attempts,
            "results": [asdict(result) for result in results],
        }, client.attempts)
