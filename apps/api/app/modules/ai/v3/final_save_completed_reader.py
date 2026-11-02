"""Unwired completed-job custody contract; caller authenticates tenant and actor."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from app.models.ai_generation_checkpoint import AIGenerationLessonCheckpoint, AIGenerationRun
from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.assessment_schema import CourseAssessment
from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.ai.pipeline import GenerationState
from app.modules.ai.v3.final_save_contract import RECEIPT_KEY, _digest
from app.modules.ai.v3.final_save_readback import verify_snapshot
from app.modules.ai.v3.final_save_snapshot import validate_snapshot
from app.modules.ai.writer_schema import CourseContent
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice

POLICY = "v3-final-save-receipt-v2"
READBACK_PHASE: ContextVar[str] = ContextVar("v3_final_readback_phase", default="not_started")


def completed_receipt(intent: dict[str, Any], snapshot: dict[str, Any], course_id: str) -> dict[str, Any]:
    """Build prospective receipt; caller must atomically persist it with saved rows."""
    if (not validate_snapshot(snapshot, expected_intent_digest=intent.get("intent_digest", ""))
            or snapshot["intent"] != intent or str(UUID(course_id)) != course_id):
        raise ValueError("v3_completed_receipt_invalid")
    return {"policy": POLICY, "intent_digest": intent["intent_digest"], "attempt_id": intent["attempt_id"],
            "course_id": course_id, "output_digest": intent["output_digest"],
            "checkpoint_key": "v3-final-snapshot:" + intent["intent_digest"], "snapshot_digest": _digest(snapshot)}


async def read_completed_snapshot(session: Any, *, tenant_id: UUID, actor_id: UUID, job_id: UUID) -> bool:
    """Read under one transaction; caller must independently authenticate actor and tenant.

    This verifies a completed owner's exact saved artifact; it does not mutate or commit.
    Caller controls transaction lifetime and must release locks. Any uncertainty returns False.
    """
    try:
        from app.modules.ai.lesson_cycle import POLICY_VERSION
        from app.modules.ai.qa_luna_dev_route import QA_TENANT
        from app.modules.ai.source_assessment_plan import PLAN_POLICY

        READBACK_PHASE.set("scope")
        if tenant_id != QA_TENANT or not all(isinstance(x, UUID) for x in (tenant_id, actor_id, job_id)):
            return False
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        READBACK_PHASE.set("job")
        job = await session.scalar(select(AIJob).where(AIJob.id == str(job_id), AIJob.tenant_id == tenant_id,
            AIJob.user_id == actor_id).with_for_update().execution_options(populate_existing=True))
        if job is None or job.status != "completed" or not isinstance(job.result, dict):
            return False
        READBACK_PHASE.set("receipt")
        receipt = job.result.get(RECEIPT_KEY)
        if not isinstance(receipt, dict) or set(receipt) != {"policy", "intent_digest", "attempt_id", "course_id",
                "output_digest", "checkpoint_key", "snapshot_digest"} or receipt["policy"] != POLICY:
            return False
        digest = receipt["intent_digest"]
        if not isinstance(digest, str) or receipt["checkpoint_key"] != "v3-final-snapshot:" + digest:
            return False
        # WorkerCycleJournal prefixes every key with its tenant/job ownership digest.
        from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal
        journal = WorkerCycleJournal(str(tenant_id), str(job_id), None)
        READBACK_PHASE.set("checkpoint")
        run = await session.scalar(select(AIGenerationRun).where(AIGenerationRun.tenant_id == tenant_id,
            AIGenerationRun.source_job_id == str(job_id),
            AIGenerationRun.generation_key == journal._owned_key(receipt["checkpoint_key"])).with_for_update())
        if (run is None or run.plan_revision != f"{PLAN_POLICY}/{POLICY_VERSION}"
                or run.plan_payload != {"schema": "v3-final-snapshot-v1", "intent_digest": digest}):
            return False
        checkpoints = list((await session.scalars(select(AIGenerationLessonCheckpoint).where(
            AIGenerationLessonCheckpoint.tenant_id == tenant_id,
            AIGenerationLessonCheckpoint.generation_run_id == run.id).with_for_update())).all())
        if len(checkpoints) != 1:
            return False
        cp = checkpoints[0]
        snapshot = cp.assessment_payload
        if (cp.module_key != "cycle" or cp.lesson_key != "lesson" or cp.assessment_status != "completed"
                or not validate_snapshot(snapshot, expected_intent_digest=digest)
                or _digest(snapshot) != receipt["snapshot_digest"]
                or completed_receipt(snapshot["intent"], snapshot, receipt["course_id"]) != receipt):
            return False
        intent, output = snapshot["intent"], snapshot["output"]
        if (intent["tenant_id"] != str(tenant_id) or intent["user_id"] != str(actor_id)
                or intent["job_id"] != str(job_id) or str(job.course_id) != receipt["course_id"]):
            return False
        READBACK_PHASE.set("reconstruction")
        structure = CourseStructure._from_dict(output["structure"])
        content = CourseContent.from_dict(output["content"])
        assessment = CourseAssessment.from_dict(output["assessment"])  # type: ignore[no-untyped-call]
        if (asdict(structure) != output["structure"] or asdict(content) != output["content"]
                or asdict(assessment) != output["assessment"]):
            return False
        state = GenerationState(job_id=str(job_id), structure=structure, content=content, assessment=assessment,
            source_document_ids=output["source_document_ids"], source_strategy=output["source_strategy"],
            source_combination_goal=output["source_combination_goal"], source_analysis=output["source_analysis"],
            server_source_review_required=output["source_review_required"], reuse_reason=output["reuse_reason"])
        READBACK_PHASE.set("course")
        course = await session.scalar(select(Course).where(Course.id == job.course_id,
            Course.tenant_id == tenant_id).with_for_update().execution_options(populate_existing=True))
        if course is None:
            return False
        READBACK_PHASE.set("source")
        ids = [UUID(doc["doc_id"]) for doc in intent["documents"]]
        documents = list((await session.scalars(select(Document).where(Document.tenant_id == tenant_id,
            Document.id.in_(ids)).order_by(Document.id).with_for_update().execution_options(populate_existing=True))).all())
        if len(documents) != len(ids):
            return False
        ordered = {d.id: d for d in documents}
        corpus = await build_direct_source_corpus([ordered[i] for i in ids], tenant_id=tenant_id)
        READBACK_PHASE.set("rows")
        modules = list((await session.scalars(select(Module).where(Module.tenant_id == tenant_id,
            Module.course_id == course.id).with_for_update())).all())
        lessons = list((await session.scalars(select(Lesson).where(Lesson.tenant_id == tenant_id,
            Lesson.module_id.in_([m.id for m in modules])).with_for_update())).all())
        quizzes = list((await session.scalars(select(Quiz).where(Quiz.tenant_id == tenant_id,
            Quiz.lesson_id.in_([lesson.id for lesson in lessons])).with_for_update())).all())
        questions = list((await session.scalars(select(Question).where(
            Question.quiz_id.in_([q.id for q in quizzes])).with_for_update())).all())
        choices = list((await session.scalars(select(QuizChoice).where(
            QuizChoice.question_id.in_([q.id for q in questions])).with_for_update())).all())
        legacy_receipt = {k: receipt[k] for k in ("intent_digest", "attempt_id", "course_id", "output_digest")}
        legacy_receipt["policy"] = "v3-final-save-receipt-v1"
        job_view = SimpleNamespace(**{key: getattr(job, key) for key in (
            "id", "tenant_id", "user_id", "status", "stage", "progress", "message", "completed_at", "updated_at",
            "errors", "course_id", "params")}, result={**job.result, RECEIPT_KEY: legacy_receipt})
        READBACK_PHASE.set("verification")
        return verify_snapshot(state=state, intent=intent, job=job_view, course=course, source_corpus=corpus,
            documents=documents, modules=modules, lessons=lessons, quizzes=quizzes, questions=questions, choices=choices)
    except Exception:
        return False
