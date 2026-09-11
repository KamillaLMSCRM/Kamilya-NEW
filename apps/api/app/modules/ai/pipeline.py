"""AI Generation Pipeline вЂ” orchestrates architect, writer, and assessment agents."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import TypedDict, cast
from uuid import UUID, uuid4

from billiard.exceptions import SoftTimeLimitExceeded

from app.core.db import async_session_factory
from app.modules.ai.architect import create_architect_tools, run_architect
from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.assessment import generate_course_assessment
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.direct_source import (
    DirectSourceCorpus,
    DirectSourceError,
    load_direct_source_corpus,
    run_direct_architect,
    write_direct_course,
)
from app.modules.ai.generation_checkpoint import (
    AIGenerationCheckpointError,
    AIGenerationCheckpointRepository,
    GenerationPlan,
    PlannedLesson,
)
from app.modules.ai.ingestion import EmbeddingsProvider, VectorStore
from app.modules.ai.llm_client import ResilientLLMClient
from app.modules.ai.reviewer import ReviewerAgent
from app.modules.ai.source_map_checkpoint import SourceMapCheckpointStore
from app.modules.ai.writer import UnsupportedLessonSourceError, write_course
from app.modules.ai.writer_schema import CourseContent, LessonContent

logger = logging.getLogger(__name__)

GENERATION_FAILURE_CODE = "generation_failed"
GENERATION_FAILURE_MESSAGE = (
    "Не удалось сгенерировать курс. Повторите попытку или обратитесь к администратору."
)


class _DocumentProfile(TypedDict):
    all_job_instructions: bool
    total_chunks: int


def _source_map_checkpoint_store(
    llm: object, tenant_id: UUID | None, job_id: str, options: dict[str, object],
) -> SourceMapCheckpointStore | None:
    """Only identified jobs using a resolved route may reuse internal checkpoints."""
    fingerprint = getattr(llm, "cache_fingerprint", None)
    if tenant_id is None or not callable(fingerprint):
        return None
    route_digest = fingerprint()
    if not isinstance(route_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", route_digest):
        return None
    digest = hashlib.sha256(json.dumps(
        [route_digest, options], sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    try:
        return SourceMapCheckpointStore(str(tenant_id), job_id, digest)
    except ValueError:
        # Legacy/internal non-UUID job identifiers cannot enter the shared cache.
        return None


def _estimate_lesson_duration_seconds(content: str | None) -> int:
    """Estimate focused reading time at 150 words/minute, with a 2-minute floor."""
    word_count = len(re.findall(r"\b[\w-]+\b", content or "", flags=re.UNICODE))
    return max(2, math.ceil(word_count / 150)) * 60


def _generation_plan_payload(
    structure: CourseStructure,
    *,
    documents: list[str],
    options: dict[str, object],
) -> dict[str, object]:
    return {
        "structure": json.loads(structure.to_json()),
        "source_document_ids": list(documents),
        "options": options,
    }


def _generation_plan_revision(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _planned_generation_lessons(structure: CourseStructure) -> tuple[PlannedLesson, ...]:
    return tuple(
        PlannedLesson(
            module_key=f"module-{module_index:03d}",
            lesson_key=f"lesson-{module_index:03d}-{lesson_index:03d}",
            module_order=module_index,
            lesson_order=lesson_index,
        )
        for module_index, module in enumerate(structure.modules)
        for lesson_index, _lesson in enumerate(module.lessons)
    )


def _structure_from_generation_plan(
    plan: GenerationPlan,
    *,
    documents: list[str],
) -> CourseStructure:
    payload = dict(plan.plan_payload)
    if payload.get("source_document_ids") != documents:
        raise AIGenerationCheckpointError("generation_source_identity_conflict")
    if _generation_plan_revision(payload) != plan.plan_revision:
        raise AIGenerationCheckpointError("generation_plan_revision_conflict")
    structure_payload = payload.get("structure")
    if not isinstance(structure_payload, dict):
        raise AIGenerationCheckpointError("invalid_persisted_plan_payload")
    structure = CourseStructure.from_json(
        json.dumps(structure_payload, ensure_ascii=False)
    )
    if _planned_generation_lessons(structure) != plan.lessons:
        raise AIGenerationCheckpointError("generation_plan_lesson_identity_conflict")
    return structure


async def _selected_document_profile(
    document_ids: list[str],
    tenant_id: UUID | str | None,
) -> _DocumentProfile:
    if not document_ids or not tenant_id:
        return {"all_job_instructions": False, "total_chunks": 0}
    from sqlalchemy import select, text

    from app.models.document import Document

    parsed_ids = []
    for document_id in document_ids:
        try:
            parsed_ids.append(UUID(str(document_id)))
        except ValueError:
            continue
    if not parsed_ids:
        return {"all_job_instructions": False, "total_chunks": 0}
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_current_tenant(:tid)"),
            {"tid": str(tenant_id)},
        )
        documents = (
            await session.execute(
                select(Document).where(
                    Document.id.in_(parsed_ids),
                    Document.tenant_id == UUID(str(tenant_id)),
                )
            )
        ).scalars().all()
    return {
        "all_job_instructions": (
            len(documents) == len(parsed_ids)
            and all(
                cast(str, document.category) == "job_instruction"
                for document in documents
            )
        ),
        "total_chunks": sum(
            cast(int, document.index_chunks_total or 0) for document in documents
        ),
    }


@dataclass
class GenerationState:
    """Tracks progress of course generation."""
    job_id: str
    status: str = "pending"
    stage: str = "queued"
    progress: int = 0
    message: str = ""
    course_id: str | None = None
    structure: CourseStructure | None = None
    content: CourseContent | None = None
    assessment: CourseAssessment | None = None
    started_at: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)
    source_document_ids: list[str] = field(default_factory=list)
    source_strategy: str = "single_topic"
    source_combination_goal: str = ""
    source_analysis: dict = field(default_factory=dict)
    reuse_reason: str | None = None


async def _update_job_db(job_id: str, tenant_id: UUID | str | None = None, **kwargs):
    """Update job state in the database."""
    from sqlalchemy import text

    from app.modules.ai.job_service import update_ai_job
    async with async_session_factory() as session:
        tenant_value = str(tenant_id) if tenant_id else None
        if tenant_value:
            await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_value})
        await update_ai_job(session, job_id, tenant_id=tenant_value, **kwargs)
        await session.commit()


async def _save_generation_to_db(
    state: GenerationState,
    tenant_id: UUID,
    user_id: UUID,
):
    """Save generated course structure, content, and assessments to DB."""
    from sqlalchemy import delete, select, text

    from app.models.ai_job import AIJob
    from app.modules.courses.models import Course
    from app.modules.lessons.models import Lesson, Module
    from app.modules.quizzes.models import Question, Quiz, QuizChoice

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        job = await session.scalar(
            select(AIJob)
            .where(AIJob.id == state.job_id, AIJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if not job:
            raise RuntimeError("Generation job does not exist in this tenant")
        if job.status == "cancelled":
            raise asyncio.CancelledError(f"Job {state.job_id} cancelled")
        if job.status != "running":
            raise RuntimeError(f"Generation job is not active: {job.status}")
        if not state.course_id:
            course = Course(
                id=uuid4(),
                tenant_id=tenant_id,
                title=state.structure.title if state.structure else "AI Generated Course",
                description=state.structure.description if state.structure else "",
                status="draft",
                created_by=user_id,
                ai_generated=True,
                source_document_ids=state.source_document_ids,
                source_strategy=state.source_strategy,
                source_combination_goal=state.source_combination_goal or None,
                source_analysis=(
                    {**state.source_analysis, "reuse_reason": state.reuse_reason}
                    if state.reuse_reason
                    else state.source_analysis
                ),
            )
            session.add(course)
            await session.flush()
            state.course_id = str(course.id)
        else:
            course = await session.scalar(
                select(Course).where(
                    Course.id == UUID(state.course_id),
                    Course.tenant_id == tenant_id,
                )
            )
            if not course:
                raise ValueError("Target course does not exist in this tenant")
            course.title = state.structure.title if state.structure else course.title
            course.description = (
                state.structure.description if state.structure else course.description
            )
            course.status = "draft"
            course.ai_generated = True
            course.source_document_ids = state.source_document_ids
            course.source_strategy = state.source_strategy
            course.source_combination_goal = state.source_combination_goal or None
            course.source_analysis = (
                {**state.source_analysis, "reuse_reason": state.reuse_reason}
                if state.reuse_reason
                else state.source_analysis
            )
            # Regeneration replaces the draft's previous learning structure.
            # Database cascades remove lessons/quizzes below each module.
            await session.execute(
                delete(Module).where(
                    Module.course_id == course.id,
                    Module.tenant_id == tenant_id,
                )
            )
            await session.flush()

        assessment_by_position: dict[tuple[int, int], LessonAssessment] = {}
        if state.structure and state.assessment:
            planned_positions = [
                (module_index, lesson_index, lesson.title)
                for module_index, module in enumerate(state.structure.modules)
                for lesson_index, lesson in enumerate(module.lessons)
            ]
            if len(planned_positions) != len(state.assessment.assessments):
                raise AIGenerationCheckpointError("generation_assessment_count_conflict")
            for position, lesson_assessment in zip(
                planned_positions,
                state.assessment.assessments,
                strict=True,
            ):
                module_index, lesson_index, lesson_title = position
                if lesson_assessment.lesson_title != lesson_title:
                    raise AIGenerationCheckpointError(
                        "generation_assessment_identity_conflict"
                    )
                assessment_by_position[(module_index, lesson_index)] = lesson_assessment

        # Create modules and lessons
        if state.structure and state.content:
            for mod_idx, (struct_mod, content_mod) in enumerate(
                zip(state.structure.modules, state.content.modules, strict=False)
            ):
                module = Module(
                    tenant_id=tenant_id,
                    course_id=course.id,
                    title=struct_mod.title,
                    description=struct_mod.description or "",
                    order_index=mod_idx,
                    ai_generated=True,
                )
                session.add(module)
                await session.flush()

                for les_idx, (struct_les, content_les) in enumerate(
                    zip(struct_mod.lessons, content_mod.lessons, strict=False)
                ):
                    actual_source_ids = list(dict.fromkeys(
                        str(reference.get("doc_id"))
                        for reference in content_les.source_references
                        if reference.get("doc_id")
                    ))
                    lesson = Lesson(
                        tenant_id=tenant_id,
                        module_id=module.id,
                        title=struct_les.title,
                        content_type="text",
                        content=content_les.content if hasattr(content_les, 'content') else "",
                        duration_seconds=_estimate_lesson_duration_seconds(
                            content_les.content if hasattr(content_les, "content") else ""
                        ),
                        order_index=les_idx,
                        ai_generated=True,
                        source_document_ids=actual_source_ids,
                        source_references=list(content_les.source_references),
                        source_validation_status="verified",
                    )
                    session.add(lesson)
                    await session.flush()

                    # Create quiz from assessment
                    if state.assessment:
                        for lesson_assess in [assessment_by_position[(mod_idx, les_idx)]]:
                            if lesson_assess.lesson_title == struct_les.title:
                                question_count = (
                                    len(lesson_assess.mcq)
                                    + len(lesson_assess.true_false)
                                    + sum(len(mq.pairs) for mq in lesson_assess.matching)
                                )
                                if question_count == 0:
                                    logger.warning("Skipping empty quiz for lesson %s", struct_les.title)
                                    continue

                                quiz = Quiz(
                                    tenant_id=tenant_id,
                                    lesson_id=lesson.id,
                                    title=struct_les.title,
                                    pass_score=80,
                                    attempt_limit=3,
                                    review_status="needs_review",
                                    reviewed_by=None,
                                    reviewed_at=None,
                                )
                                session.add(quiz)
                                await session.flush()

                                q_idx = 0

                                # MCQ questions
                                for mcq in lesson_assess.mcq:
                                    question = Question(
                                        quiz_id=quiz.id,
                                        text=mcq.question,
                                        type="MCQ",
                                        points=1,
                                        explanation=mcq.explanation,
                                        order_index=q_idx,
                                    )
                                    session.add(question)
                                    await session.flush()

                                    for c_idx, option in enumerate(mcq.options):
                                        choice = QuizChoice(
                                            question_id=question.id,
                                            text=option.text,
                                            is_correct=option.is_correct,
                                            order_index=c_idx,
                                        )
                                        session.add(choice)
                                    q_idx += 1

                                # True/False questions
                                for tf in lesson_assess.true_false:
                                    question = Question(
                                        quiz_id=quiz.id,
                                        text=tf.statement,
                                        type="true_false",
                                        points=1,
                                        explanation=tf.explanation,
                                        order_index=q_idx,
                                    )
                                    session.add(question)
                                    await session.flush()

                                    session.add(QuizChoice(
                                        question_id=question.id,
                                        text="Верно",
                                        is_correct=tf.is_true,
                                        order_index=0,
                                    ))
                                    session.add(QuizChoice(
                                        question_id=question.id,
                                        text="Неверно",
                                        is_correct=not tf.is_true,
                                        order_index=1,
                                    ))
                                    q_idx += 1

                                # Matching questions (stored as MCQ with pair text)
                                for mq in lesson_assess.matching:
                                    for pair in mq.pairs:
                                        question = Question(
                                            quiz_id=quiz.id,
                                            text=f"{mq.instruction}: {pair.left} → ?",
                                            type="MCQ",
                                            points=1,
                                            explanation=f"Правильный ответ: {pair.right}",
                                            order_index=q_idx,
                                        )
                                        session.add(question)
                                        await session.flush()

                                        # Create choices: correct pair + 2 random distractors
                                        all_rights = [p.right for p in mq.pairs]
                                        choices_texts = [pair.right] + [r for r in all_rights if r != pair.right][:2]
                                        for c_idx, text in enumerate(choices_texts):
                                            session.add(QuizChoice(
                                                question_id=question.id,
                                                text=text,
                                                is_correct=(c_idx == 0),
                                                order_index=c_idx,
                                            ))
                                        q_idx += 1

        state.status = "completed"
        state.stage = "completed"
        state.progress = 100
        state.message = "Курс успешно сгенерирован!"
        completed_at = datetime.now(timezone.utc)  # noqa: UP017 -- Python 3.10 runtime
        for field_name, value in (
            ("status", state.status),
            ("stage", state.stage),
            ("progress", state.progress),
            ("message", state.message),
            ("course_id", course.id),
            ("completed_at", completed_at),
            ("updated_at", completed_at),
        ):
            setattr(job, field_name, value)
        await session.commit()
        logger.info(f"Saved generation results to DB for course {state.course_id}")

async def _check_cancelled_async(job_id: str, tenant_id: UUID | str | None = None):
    """Async check: raise CancelledError if job status is 'cancelled' in DB."""
    from sqlalchemy import text

    from app.core.db import async_session_factory
    from app.modules.ai.job_service import get_ai_job
    async with async_session_factory() as session:
        tenant_value = str(tenant_id) if tenant_id else None
        if tenant_value:
            await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_value})
        job = await get_ai_job(session, job_id, tenant_id=tenant_value)
        if job and job.status == "cancelled":
            raise asyncio.CancelledError(f"Job {job_id} cancelled")


async def run_generation_pipeline(
    job_id: str,
    documents: list[str],
    target_audience: str = "",
    num_modules: int = 3,
    lessons_per_module: int | None = None,
    max_total_lessons: int | None = None,
    language: str = "ru",
    goals: list[str] | None = None,
    course_hours: float | None = None,
    guidance: str | None = None,
    course_id: str | None = None,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    source_strategy: str = "single_topic",
    combination_goal: str = "",
    source_analysis: dict | None = None,
    reuse_reason: str | None = None,
    generation_checkpoint_repository: AIGenerationCheckpointRepository | None = None,
    delivery_id: str | None = None,
) -> GenerationState:
    """
    Full generation pipeline:
    1. Ingest documents
    2. Run Architect Agent (course structure)
    3. Run Writer Agent (content for each lesson)
    4. Run Assessment Agent (questions for each lesson)
    5. Save results to DB
    """
    state = GenerationState(
        job_id=job_id,
        course_id=course_id,
        source_document_ids=list(documents),
        source_strategy=source_strategy,
        source_combination_goal=combination_goal.strip(),
        source_analysis=dict(source_analysis or {}),
        reuse_reason=reuse_reason,
    )
    direct_mode = state.source_analysis.get("analysis_mode") == "direct_source"
    direct_corpus: DirectSourceCorpus | None = None
    map_checkpoints: SourceMapCheckpointStore | None = None
    generation_checkpoints = generation_checkpoint_repository if tenant_id else None
    generation_plan: GenerationPlan | None = None
    lease_owner = delivery_id or job_id

    try:
        # Stage 1: validate the selected source path before any model call.
        state.stage = "ingestion"
        state.progress = 5
        state.message = (
            "Проверка исходных документов..."
            if direct_mode
            else "Проверка эмбеддингов документов..."
        )
        await _update_job_db(job_id, tenant_id=tenant_id, status="running", stage="ingestion", progress=5, message=state.message)

        if direct_mode:
            if not tenant_id:
                raise DirectSourceError("tenant_id_required")
            direct_corpus = await load_direct_source_corpus(
                documents,
                tenant_id=tenant_id,
                check_cancelled=lambda: _check_cancelled_async(
                    job_id,
                    tenant_id=tenant_id,
                ),
            )
        # Semantic documents are ingested at upload time into pgvector. Keep
        # the legacy verification path unchanged for semantic generation.
        elif documents:
            from app.modules.ai.ingestion import VectorStore
            verification_store = VectorStore()
            missing_docs: list[str] = []
            for doc_id in documents:
                try:
                    chunks = await verification_store.get_all_chunks(
                        doc_ids=[doc_id],
                        tenant_id=str(tenant_id) if tenant_id else None,
                    )
                    if not chunks:
                        missing_docs.append(doc_id)
                        logger.warning(f"No embeddings found for doc {doc_id} вЂ” may need re-upload")
                except Exception as e:
                    logger.warning(
                        "Could not check embeddings for %s error_type=%s",
                        doc_id,
                        type(e).__name__,
                    )
            if len(missing_docs) == len(documents):
                raise ValueError(
                    f"None of the {len(documents)} selected document(s) have embeddings. "
                    "Re-upload them and try again."
                )
            if missing_docs:
                logger.warning(
                    f"Proceeding with {len(documents) - len(missing_docs)}/{len(documents)} "
                    f"docs that have embeddings (missing: {missing_docs})"
                )

        # Stage 2: Architect
        await _check_cancelled_async(job_id, tenant_id=tenant_id)
        state.stage = "architect"
        state.progress = 10
        state.message = "Проектирование структуры курса..."
        await _update_job_db(job_id, tenant_id=tenant_id, stage="architect", progress=10, message=state.message)

        llm = await ResilientLLMClient.from_settings_async(tenant_id=tenant_id)
        semantic_store: VectorStore | None = None
        semantic_embeddings_provider: EmbeddingsProvider | None = None
        architect_tools: dict | None = None
        document_profile: _DocumentProfile
        if direct_mode:
            if direct_corpus is None:
                raise DirectSourceError("direct_source_unavailable")
            document_profile = {
                "all_job_instructions": all(
                    document.category == "job_instruction"
                    for document in direct_corpus.documents
                ),
                "total_chunks": direct_corpus.total_chunks,
            }
        else:
            semantic_store = VectorStore()
            semantic_embeddings_provider = EmbeddingsProvider(tenant_id=tenant_id)
            architect_tools = create_architect_tools(
                summaries_dir="./summaries",
                chroma_dir="./chroma_data",
                doc_ids=documents if documents else None,
                embeddings_client=semantic_embeddings_provider,
                vector_store=semantic_store,
                tenant_id=str(tenant_id) if tenant_id else None,
            )
            document_profile = await _selected_document_profile(documents, tenant_id)
        effective_guidance = guidance
        if document_profile["all_job_instructions"]:
            compact_instruction = (
                "This source is a job instruction. Build a concise onboarding course, "
                "not a general professional or legal curriculum. Use no more than two "
                "lessons per module and no more than six lessons in total. Group related "
                "duties together. Do not create standalone lessons about legislation, "
                "industry regulation, safety, ethics, or qualifications unless the "
                "instruction contains enough operational detail to teach and test them."
            )
            effective_guidance = "\n\n".join(
                part for part in (guidance, compact_instruction) if part
            )

        if generation_checkpoints is not None and tenant_id is not None:
            async with async_session_factory() as session:
                try:
                    generation_plan = await generation_checkpoints.load_plan(
                        session,
                        tenant_id=str(tenant_id),
                        generation_key=job_id,
                    )
                except AIGenerationCheckpointError as exc:
                    if str(exc) != "generation_plan_not_found":
                        raise

        if generation_plan is not None:
            structure = _structure_from_generation_plan(
                generation_plan,
                documents=documents,
            )
            state.message = "Продолжаем ранее начатую генерацию по сохранённому плану..."
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                stage="architect",
                progress=10,
                message=state.message,
            )
        elif direct_mode:
            if direct_corpus is None:
                raise DirectSourceError("direct_source_unavailable")
            map_checkpoints = _source_map_checkpoint_store(llm, tenant_id, job_id, {
                "goals": goals, "course_hours": course_hours, "num_modules": num_modules,
                "lessons_per_module": lessons_per_module, "language": language,
                "max_total_lessons": max_total_lessons,
                "guidance": effective_guidance, "target_audience": target_audience,
                "source_strategy": source_strategy, "combination_goal": combination_goal,
            })
            structure = await run_direct_architect(
                llm,
                direct_corpus,
                goals=goals,
                course_hours=course_hours,
                num_modules=num_modules,
                lessons_per_module=lessons_per_module,
                max_total_lessons=max_total_lessons,
                language=language,
                guidance=effective_guidance,
                target_audience=target_audience,
                source_strategy=source_strategy,
                combination_goal=combination_goal,
                checkpoint_store=map_checkpoints,
                check_cancelled=lambda: _check_cancelled_async(
                    job_id,
                    tenant_id=tenant_id,
                ),
            )
        else:
            if architect_tools is None:
                raise RuntimeError("semantic_architect_tools_unavailable")
            structure = await run_architect(
                llm=llm,
                tools=architect_tools,
                goals=goals,
                course_hours=course_hours,
                num_modules=num_modules,
                lessons_per_module=lessons_per_module,
                max_total_lessons=max_total_lessons,
                language=language,
                guidance=effective_guidance,
                on_message=lambda msg: asyncio.create_task(_update_job_db(job_id, tenant_id=tenant_id, message=f"Architect: {msg}")),
                tenant_id=str(tenant_id) if tenant_id else None,
                target_audience=target_audience,
                source_strategy=source_strategy,
                combination_goal=combination_goal,
            )

        plan_options: dict[str, object] = {
            "target_audience": target_audience,
            "num_modules": num_modules,
            "lessons_per_module": lessons_per_module,
            "max_total_lessons": max_total_lessons,
            "language": language,
            "goals": list(goals or []),
            "course_hours": course_hours,
            "guidance": effective_guidance or "",
            "source_strategy": source_strategy,
            "combination_goal": combination_goal,
        }
        plan_payload = _generation_plan_payload(
            structure,
            documents=documents,
            options=plan_options,
        )
        planned_lessons = _planned_generation_lessons(structure)

        state.structure = structure
        state.progress = 25
        state.message = f"Структура спроектирована: {len(structure.modules)} модулей"
        await _update_job_db(job_id, tenant_id=tenant_id, progress=25, message=state.message)

        checkpoint_keys = {
            (planned.module_order, planned.lesson_order): (
                planned.module_key,
                planned.lesson_key,
            )
            for planned in planned_lessons
        }
        completed_content: dict[tuple[int, int], LessonContent] = {}
        completed_reviews: dict[tuple[int, int], dict[str, object]] = {}
        completed_assessments: dict[tuple[int, int], LessonAssessment] = {}
        if generation_checkpoints is not None and tenant_id is not None:
            snapshots = ()
            if generation_plan is not None:
                async with async_session_factory() as session:
                    snapshots = await generation_checkpoints.load_checkpoints(
                        session,
                        tenant_id=str(tenant_id),
                        generation_key=job_id,
                    )
            for snapshot in snapshots:
                index = (snapshot.module_order, snapshot.lesson_order)
                if checkpoint_keys.get(index) != (snapshot.module_key, snapshot.lesson_key):
                    raise AIGenerationCheckpointError(
                        "generation_plan_lesson_identity_conflict"
                    )
                expected_title = structure.modules[index[0]].lessons[index[1]].title
                if snapshot.content_payload is not None:
                    restored_content = LessonContent.from_dict(
                        dict(snapshot.content_payload)
                    )
                    if restored_content.title != expected_title:
                        raise AIGenerationCheckpointError(
                            "generation_content_identity_conflict"
                        )
                    completed_content[index] = restored_content
                if snapshot.review_payload is not None:
                    completed_reviews[index] = dict(snapshot.review_payload)
                if snapshot.assessment_payload is not None:
                    restored_assessment = LessonAssessment.from_dict(
                        dict(snapshot.assessment_payload)
                    )
                    if restored_assessment.lesson_title != expected_title:
                        raise AIGenerationCheckpointError(
                            "generation_assessment_identity_conflict"
                        )
                    completed_assessments[index] = restored_assessment

        async def ensure_generation_plan(session) -> None:
            nonlocal generation_plan
            if generation_checkpoints is None or tenant_id is None:
                return
            generation_plan = await generation_checkpoints.create_plan(
                session,
                tenant_id=str(tenant_id),
                generation_key=job_id,
                plan_revision=_generation_plan_revision(plan_payload),
                source_job_id=job_id,
                plan_payload=plan_payload,
                lessons=planned_lessons,
            )

        async def claim_generation_item(
            module_index: int,
            lesson_index: int,
            stage: str,
        ) -> None:
            if generation_checkpoints is None or tenant_id is None:
                return
            module_key, lesson_key = checkpoint_keys[(module_index, lesson_index)]
            async with async_session_factory() as session:
                claimed = await generation_checkpoints.claim_item(
                    session,
                    tenant_id=str(tenant_id),
                    generation_key=job_id,
                    module_key=module_key,
                    lesson_key=lesson_key,
                    stage=stage,
                    lease_owner=lease_owner,
                )
                await session.commit()
            if claimed is None:
                raise AIGenerationCheckpointError(
                    "generation_checkpoint_lease_unavailable"
                )

        async def checkpoint_lesson_content(
            module_index: int,
            lesson_index: int,
            lesson_content: LessonContent,
        ) -> None:
            if generation_checkpoints is None or tenant_id is None:
                return
            module_key, lesson_key = checkpoint_keys[(module_index, lesson_index)]
            async with async_session_factory() as session:
                await ensure_generation_plan(session)
                await generation_checkpoints.checkpoint_content(
                    session,
                    tenant_id=str(tenant_id),
                    generation_key=job_id,
                    module_key=module_key,
                    lesson_key=lesson_key,
                    content_payload=lesson_content.to_dict(),
                    lease_owner=lease_owner,
                )
                await session.commit()

        async def checkpoint_lesson_review(
            module_index: int,
            lesson_index: int,
            review: dict[str, object],
        ) -> None:
            if generation_checkpoints is None or tenant_id is None:
                return
            module_key, lesson_key = checkpoint_keys[(module_index, lesson_index)]
            async with async_session_factory() as session:
                await generation_checkpoints.checkpoint_review(
                    session,
                    tenant_id=str(tenant_id),
                    generation_key=job_id,
                    module_key=module_key,
                    lesson_key=lesson_key,
                    review_payload=review,
                    lease_owner=lease_owner,
                )
                await session.commit()

        async def checkpoint_lesson_assessment(
            module_index: int,
            lesson_index: int,
            lesson_assessment: LessonAssessment,
        ) -> None:
            if generation_checkpoints is None or tenant_id is None:
                return
            module_key, lesson_key = checkpoint_keys[(module_index, lesson_index)]
            async with async_session_factory() as session:
                await ensure_generation_plan(session)
                await generation_checkpoints.checkpoint_assessment(
                    session,
                    tenant_id=str(tenant_id),
                    generation_key=job_id,
                    module_key=module_key,
                    lesson_key=lesson_key,
                    assessment_payload=lesson_assessment.to_dict(),
                    lease_owner=lease_owner,
                )
                await session.commit()

        if generation_checkpoints is not None and tenant_id is not None:
            async with async_session_factory() as session:
                await ensure_generation_plan(session)
                await session.commit()

        # Stage 3: Content Generation (Writer)
        await _check_cancelled_async(job_id, tenant_id=tenant_id)
        state.stage = "content_generation"
        state.progress = 30
        state.message = "Генерация контента уроков..."
        await _update_job_db(job_id, tenant_id=tenant_id, stage="content_generation", progress=30, message=state.message)

        async def write_grounded_course(
            course_structure: CourseStructure,
        ) -> tuple[CourseContent, int]:
            total = sum(len(module.lessons) for module in course_structure.modules)
            completed = 0

            async def on_lesson_progress(msg: str):
                nonlocal completed
                completed += 1
                pct = 30 + int(completed / total * 40) if total > 0 else 70
                await _update_job_db(
                    job_id,
                    tenant_id=tenant_id,
                    progress=min(pct, 70),
                    message=msg,
                )

            if direct_mode:
                if direct_corpus is None:
                    raise DirectSourceError("direct_source_unavailable")
                generated = await write_direct_course(
                    llm,
                    direct_corpus,
                    course_structure,
                    tenant_id=tenant_id,
                    language=language,
                    on_progress=on_lesson_progress,
                    check_cancelled=lambda: _check_cancelled_async(
                        job_id,
                        tenant_id=tenant_id,
                    ),
                    completed_lessons=completed_content,
                    before_lesson_generate=lambda module_index, lesson_index: claim_generation_item(
                        module_index, lesson_index, "content"
                    ),
                    on_lesson_complete=checkpoint_lesson_content,
                )
            else:
                if semantic_store is None:
                    raise RuntimeError("semantic_store_unavailable")
                generated = await write_course(
                    llm=llm,
                    store=semantic_store,
                    structure=course_structure,
                    doc_ids=documents if documents else None,
                    language=language,
                    on_progress=on_lesson_progress,
                    embeddings_provider=semantic_embeddings_provider,
                    tenant_id=str(tenant_id) if tenant_id else None,
                    completed_lessons=completed_content,
                    before_lesson_generate=lambda module_index, lesson_index: claim_generation_item(
                        module_index, lesson_index, "content"
                    ),
                    on_lesson_complete=checkpoint_lesson_content,
                )
            return generated, total

        try:
            content, total_lessons = await write_grounded_course(structure)
        except UnsupportedLessonSourceError as exc:
            if direct_mode:
                raise
            if generation_plan is not None:
                raise AIGenerationCheckpointError(
                    "generation_plan_grounding_conflict"
                ) from exc
            state.stage = "architect_recovery"
            state.progress = 28
            state.message = (
                "Перестраиваем план: один из уроков не подтверждается выбранными источниками"
            )
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                stage=state.stage,
                progress=state.progress,
                message=state.message,
            )
            recovery_guidance = "\n\n".join(
                part
                for part in (
                    effective_guidance,
                    (
                        "The previous outline included a lesson that could not be grounded "
                        f"in the selected documents: '{exc.lesson_title}'. Redesign the whole "
                        "outline using only topics explicitly supported by document headings "
                        "and retrieved source text. Do not add legal background, industry "
                        "practice, compliance duties, rates, limits, or procedures unless they "
                        "are present in the selected sources. Every lesson must name precise "
                        "source_doc_ids and relevant_headings."
                    ),
                )
                if part
            )
            if architect_tools is None:
                raise RuntimeError("semantic_architect_tools_unavailable") from exc
            structure = await run_architect(
                llm=llm,
                tools=architect_tools,
                goals=goals,
                course_hours=course_hours,
                num_modules=num_modules,
                lessons_per_module=lessons_per_module,
                max_total_lessons=max_total_lessons,
                language=language,
                guidance=recovery_guidance,
                on_message=lambda msg: asyncio.create_task(
                    _update_job_db(
                        job_id,
                        tenant_id=tenant_id,
                        message=f"Architect recovery: {msg}",
                    )
                ),
                tenant_id=str(tenant_id) if tenant_id else None,
                target_audience=target_audience,
                source_strategy=source_strategy,
                combination_goal=combination_goal,
            )
            state.structure = structure
            plan_payload = _generation_plan_payload(
                structure,
                documents=documents,
                options=plan_options,
            )
            planned_lessons = _planned_generation_lessons(structure)
            checkpoint_keys = {
                (planned.module_order, planned.lesson_order): (
                    planned.module_key,
                    planned.lesson_key,
                )
                for planned in planned_lessons
            }
            completed_content = {}
            completed_reviews = {}
            completed_assessments = {}
            state.stage = "content_generation"
            state.progress = 30
            state.message = "Новый план подтверждён источниками. Генерация уроков..."
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                stage=state.stage,
                progress=state.progress,
                message=state.message,
            )
            content, total_lessons = await write_grounded_course(structure)

        state.content = content
        state.progress = 70
        state.message = "Контент сгенерирован"
        await _update_job_db(job_id, tenant_id=tenant_id, progress=70, message=state.message)

        # Stage 3.5: Review content quality
        await _check_cancelled_async(job_id, tenant_id=tenant_id)
        state.stage = "review"
        state.progress = 72
        state.message = "Проверка качества контента..."
        await _update_job_db(job_id, tenant_id=tenant_id, stage="review", progress=72, message=state.message)

        reviewer = ReviewerAgent(llm_client=llm)
        low_quality_lessons = []
        reviewed_lessons = 0
        for mod_idx, content_mod in enumerate(content.modules):
            for les_idx, content_les in enumerate(content_mod.lessons):
                reviewed_lessons += 1
                await _update_job_db(
                    job_id,
                    tenant_id=tenant_id,
                    progress=min(72 + int(reviewed_lessons / max(total_lessons, 1) * 3), 74),
                    message=f"Reviewing lesson {reviewed_lessons}/{total_lessons}: {content_les.title if hasattr(content_les, 'title') else ''}",
                )
                review = completed_reviews.get((mod_idx, les_idx))
                if review is None:
                    await claim_generation_item(mod_idx, les_idx, "review")
                    review = await reviewer.review_lesson(
                        lesson_content=content_les.content if hasattr(content_les, 'content') else "",
                        lesson_meta={
                            "content_type": "text",
                            "language": language,
                            "title": content_les.title if hasattr(content_les, 'title') else "",
                        },
                    )
                    await checkpoint_lesson_review(mod_idx, les_idx, review)
                if review["quality_score"] < 5.0:
                    low_quality_lessons.append({
                        "module": mod_idx,
                        "lesson": les_idx,
                        "score": review["quality_score"],
                        "issues": review["issues"],
                    })

        if low_quality_lessons:
            state.message = f"Проверка: {len(low_quality_lessons)} уроков ниже порога качества"
            await _update_job_db(job_id, tenant_id=tenant_id, message=state.message)
        else:
            state.message = "Качество контента проверено"
            await _update_job_db(job_id, tenant_id=tenant_id, message=state.message)

        # Stage 4: Assessment Generation
        await _check_cancelled_async(job_id, tenant_id=tenant_id)
        state.stage = "assessment"
        state.progress = 75
        state.message = "Генерация тестов..."
        await _update_job_db(job_id, tenant_id=tenant_id, stage="assessment", progress=75, message=state.message)

        assessments_done = 0

        async def on_assessment_progress(msg: str):
            nonlocal assessments_done
            assessments_done += 1
            pct = 75 + int(assessments_done / total_lessons * 20) if total_lessons > 0 else 95
            await _update_job_db(job_id, tenant_id=tenant_id, progress=min(pct, 95), message=msg)

        # Assessment JSON needs deterministic schema/evidence compliance.
        # Do not reuse the more creative writer client (temperature 0.7):
        # Qwen may paraphrase server-owned evidence IDs/answer excerpts.
        assessment_llm = await ResilientLLMClient.from_settings_async(
            temperature=0.2,
            max_tokens=4096,
            tenant_id=tenant_id,
        )
        assessment = await generate_course_assessment(
            llm=assessment_llm,
            course_content=content,
            language=language,
            on_progress=on_assessment_progress,
            compact=document_profile["all_job_instructions"],
            check_cancelled=lambda: _check_cancelled_async(job_id, tenant_id=tenant_id),
            completed_assessments=completed_assessments,
            before_assessment_generate=lambda module_index, lesson_index: claim_generation_item(
                module_index, lesson_index, "assessment"
            ),
            on_assessment_complete=checkpoint_lesson_assessment,
        )

        state.assessment = assessment
        state.progress = 95
        state.message = "Тесты сгенерированы"
        await _update_job_db(job_id, tenant_id=tenant_id, progress=95, message=state.message)

        if generation_checkpoints is not None and tenant_id is not None:
            async with async_session_factory() as session:
                await generation_checkpoints.assert_complete(
                    session,
                    tenant_id=str(tenant_id),
                    generation_key=job_id,
                )

        # Stage 5: Save to DB
        state.stage = "saving"
        state.progress = 98
        state.message = "Сохранение результатов..."
        await _update_job_db(job_id, tenant_id=tenant_id, stage="saving", progress=98, message=state.message)

        if tenant_id and user_id:
            await _save_generation_to_db(state, tenant_id, user_id)
        else:
            state.status = "completed"
            state.stage = "completed"
            state.progress = 100
            state.message = "Курс успешно сгенерирован!"
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                status="completed",
                stage="completed",
                progress=100,
                message=state.message,
                course_id=UUID(state.course_id) if state.course_id else None,
                completed_at=datetime.now(UTC),
            )

        logger.info(f"Generation pipeline complete for job {job_id}")

    except SoftTimeLimitExceeded:
        state.status = "interrupted"
        state.stage = "interrupted"
        state.message = (
            "Генерация приостановлена по лимиту времени. Готовые уроки сохранены — продолжите с оставшихся."
        )
        state.errors = ["generation_interrupted"]
        await _update_job_db(
            job_id,
            tenant_id=tenant_id,
            status="interrupted",
            stage="interrupted",
            message=state.message,
            errors=state.errors,
            completed_at=None,
        )
        logger.warning("Generation pipeline interrupted for job %s", job_id)
    except asyncio.CancelledError:
        state.status = "cancelled"
        state.stage = "cancelled"
        state.message = "Cancelled by user"
        logger.info("Generation pipeline cancelled for job %s", job_id)
    except Exception as e:
        state.status = "failed"
        state.message = GENERATION_FAILURE_MESSAGE
        failure_code = e.code if isinstance(e, DirectSourceError) else GENERATION_FAILURE_CODE
        state.errors.append(failure_code)
        await _update_job_db(
            job_id,
            tenant_id=tenant_id,
            status="failed",
            stage="failed",
            message=state.message,
            errors=[failure_code],
            completed_at=datetime.now(UTC),
        )
        if tenant_id and not state.course_id:
            try:
                from sqlalchemy import text

                from app.core.trial_limits import release_ai_course_generation
                from app.modules.ai.budget import refund_llm_budget

                async with async_session_factory() as session:
                    await session.execute(
                        text("SELECT set_current_tenant(:tid)"),
                        {"tid": str(tenant_id)},
                    )
                    await release_ai_course_generation(session, tenant_id)
                    await refund_llm_budget(session, str(tenant_id), "generate_course")
                    await session.commit()
            except Exception:
                logger.exception(
                    "Could not refund failed generation reservation for job %s",
                    job_id,
                )
        logger.error("Generation pipeline failed for job %s error_type=%s", job_id, type(e).__name__)
    finally:
        if generation_checkpoints is not None and tenant_id is not None:
            try:
                async with async_session_factory() as session:
                    await generation_checkpoints.release_leases(
                        session,
                        tenant_id=str(tenant_id),
                        generation_key=job_id,
                        lease_owner=lease_owner,
                    )
                    await session.commit()
            except Exception as exc:
                logger.warning(
                    "Could not release generation leases for job %s error_type=%s",
                    job_id,
                    type(exc).__name__,
                )
        if map_checkpoints is not None:
            try:
                if state.status in {"completed", "cancelled"}:
                    await map_checkpoints.clear()
            finally:
                await map_checkpoints.aclose()

    return state
