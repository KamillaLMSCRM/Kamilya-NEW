"""AI Generation Pipeline — orchestrates architect, writer, and assessment agents."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.writer_schema import CourseContent, ModuleContent, LessonContent
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.llm_client import LLMClient, create_llm
from app.modules.ai.ingestion import VectorStore, DocumentIngestion, EmbeddingsProvider
from app.modules.ai.architect import run_architect, create_architect_tools
from app.modules.ai.writer import write_lesson, write_course
from app.modules.ai.assessment import generate_lesson_assessment, generate_course_assessment
from app.modules.ai.reviewer import ReviewerAgent
from app.core.db import async_session_factory

logger = logging.getLogger(__name__)


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


async def _update_job_db(job_id: str, **kwargs):
    """Update job state in the database."""
    from app.modules.ai.job_service import update_ai_job
    async with async_session_factory() as session:
        await update_ai_job(session, job_id, **kwargs)
        await session.commit()


async def _save_generation_to_db(
    state: GenerationState,
    tenant_id: UUID,
    user_id: UUID,
):
    """Save generated course structure, content, and assessments to DB."""
    from app.modules.courses.models import Course
    from app.modules.lessons.models import Module, Lesson
    from app.modules.quizzes.models import Quiz, Question, QuizChoice

    async with async_session_factory() as session:
        # Create course
        course = Course(
            id=UUID(state.course_id) if state.course_id else uuid4(),
            tenant_id=tenant_id,
            title=state.structure.title if state.structure else "AI Generated Course",
            description=state.structure.description if state.structure else "",
            status="draft",
            created_by=user_id,
            ai_generated=True,
        )
        if not state.course_id:
            session.add(course)
            await session.flush()
            state.course_id = str(course.id)
        else:
            session.add(course)

        # Create modules and lessons
        if state.structure and state.content:
            for mod_idx, (struct_mod, content_mod) in enumerate(
                zip(state.structure.modules, state.content.modules)
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
                    zip(struct_mod.lessons, content_mod.lessons)
                ):
                    lesson = Lesson(
                        tenant_id=tenant_id,
                        module_id=module.id,
                        title=struct_les.title,
                        content_type="text",
                        content=content_les.content if hasattr(content_les, 'content') else "",
                        order_index=les_idx,
                        ai_generated=True,
                    )
                    session.add(lesson)
                    await session.flush()

                    # Create quiz from assessment
                    if state.assessment:
                        for lesson_assess in state.assessment.assessments:
                            if lesson_assess.lesson_title == struct_les.title:
                                quiz = Quiz(
                                    tenant_id=tenant_id,
                                    lesson_id=lesson.id,
                                    title=f"Quiz: {struct_les.title}",
                                    pass_score=80,
                                    attempt_limit=3,
                                )
                                session.add(quiz)
                                await session.flush()

                                q_idx = 0

                                # MCQ questions
                                for mcq in lesson_assess.mcq:
                                    question = Question(
                                        quiz_id=quiz.id,
                                        text=mcq.question,
                                        type="multiple_choice",
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
                                            type="multiple_choice",
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

        await session.commit()
        logger.info(f"Saved generation results to DB for course {state.course_id}")


async def run_generation_pipeline(
    job_id: str,
    documents: list[str],
    target_audience: str = "",
    num_modules: int = 3,
    language: str = "ru",
    goals: list[str] | None = None,
    course_hours: float | None = None,
    guidance: str | None = None,
    course_id: str | None = None,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> GenerationState:
    """
    Full generation pipeline:
    1. Ingest documents
    2. Run Architect Agent (course structure)
    3. Run Writer Agent (content for each lesson)
    4. Run Assessment Agent (questions for each lesson)
    5. Save results to DB
    """
    state = GenerationState(job_id=job_id, course_id=course_id)

    try:
        # Stage 1: Ingestion — actually ingest documents into vector store
        state.stage = "ingestion"
        state.progress = 5
        state.message = "Checking document embeddings..."
        await _update_job_db(job_id, status="running", stage="ingestion", progress=5, message=state.message)

        # Documents are ingested at upload time into pgvector.
        # Here we just verify embeddings exist for the requested doc_ids.
        if documents:
            from app.modules.ai.ingestion import VectorStore
            store = VectorStore()
            for doc_id in documents:
                try:
                    chunks = await store.get_all_chunks(doc_ids=[doc_id])
                    if not chunks:
                        logger.warning(f"No embeddings found for doc {doc_id} — may need re-upload")
                except Exception as e:
                    logger.warning(f"Could not check embeddings for {doc_id}: {e}")

        # Stage 2: Architect
        state.stage = "architect"
        state.progress = 10
        state.message = "Designing course structure..."
        await _update_job_db(job_id, stage="architect", progress=10, message=state.message)

        llm = create_llm()
        store = VectorStore()
        embeddings_provider = EmbeddingsProvider()
        tools = create_architect_tools(
            summaries_dir="./summaries",
            chroma_dir="./chroma_data",
            doc_ids=documents if documents else None,
            vector_store=store,
        )

        structure = await run_architect(
            llm=llm,
            tools=tools,
            goals=goals,
            course_hours=course_hours,
            num_modules=num_modules,
            language=language,
            guidance=guidance,
            on_message=lambda msg: asyncio.create_task(_update_job_db(job_id, message=f"Architect: {msg}")),
        )

        state.structure = structure
        state.progress = 25
        state.message = f"Structure designed: {len(structure.modules)} modules"
        await _update_job_db(job_id, progress=25, message=state.message)

        # Stage 3: Content Generation (Writer)
        state.stage = "content_generation"
        state.progress = 30
        state.message = "Generating lesson content..."
        await _update_job_db(job_id, stage="content_generation", progress=30, message=state.message)

        total_lessons = sum(len(m.lessons) for m in structure.modules)
        lessons_done = 0

        async def on_lesson_progress(msg: str):
            nonlocal lessons_done
            lessons_done += 1
            pct = 30 + int(lessons_done / total_lessons * 40) if total_lessons > 0 else 70
            await _update_job_db(job_id, progress=min(pct, 70), message=msg)

        content = await write_course(
            llm=llm,
            store=store,
            structure=structure,
            doc_ids=documents if documents else None,
            language=language,
            on_progress=on_lesson_progress,
            embeddings_provider=embeddings_provider,
        )

        state.content = content
        state.progress = 70
        state.message = "Content generation complete"
        await _update_job_db(job_id, progress=70, message=state.message)

        # Stage 3.5: Review content quality
        state.stage = "review"
        state.progress = 72
        state.message = "Reviewing content quality..."
        await _update_job_db(job_id, stage="review", progress=72, message=state.message)

        reviewer = ReviewerAgent(llm_client=llm)
        low_quality_lessons = []
        for mod_idx, content_mod in enumerate(content.modules):
            for les_idx, content_les in enumerate(content_mod.lessons):
                review = await reviewer.review_lesson(
                    lesson_content=content_les.content if hasattr(content_les, 'content') else "",
                    lesson_meta={
                        "content_type": "text",
                        "language": language,
                        "title": content_les.title if hasattr(content_les, 'title') else "",
                    },
                )
                if review["quality_score"] < 5.0:
                    low_quality_lessons.append({
                        "module": mod_idx,
                        "lesson": les_idx,
                        "score": review["quality_score"],
                        "issues": review["issues"],
                    })

        if low_quality_lessons:
            state.message = f"Review: {len(low_quality_lessons)} lessons below quality threshold"
            await _update_job_db(job_id, message=state.message)
        else:
            state.message = "Content quality verified"
            await _update_job_db(job_id, message=state.message)

        # Stage 4: Assessment Generation
        state.stage = "assessment"
        state.progress = 75
        state.message = "Generating assessments..."
        await _update_job_db(job_id, stage="assessment", progress=75, message=state.message)

        assessments_done = 0

        async def on_assessment_progress(msg: str):
            nonlocal assessments_done
            assessments_done += 1
            pct = 75 + int(assessments_done / total_lessons * 20) if total_lessons > 0 else 95
            await _update_job_db(job_id, progress=min(pct, 95), message=msg)

        assessment = await generate_course_assessment(
            llm=llm,
            course_content=content,
            language=language,
            on_progress=on_assessment_progress,
        )

        state.assessment = assessment
        state.progress = 95
        state.message = "Assessments generated"
        await _update_job_db(job_id, progress=95, message=state.message)

        # Stage 5: Save to DB
        state.stage = "saving"
        state.progress = 98
        state.message = "Saving results..."
        await _update_job_db(job_id, stage="saving", progress=98, message=state.message)

        if tenant_id and user_id:
            await _save_generation_to_db(state, tenant_id, user_id)

            # Auto-enroll the creator in the generated course
            if state.course_id:
                try:
                    from app.models.enrollment import Enrollment
                    from sqlalchemy import select as sa_select
                    from app.core.db import async_session_factory
                    async with async_session_factory() as session:
                        existing = await session.execute(
                            sa_select(Enrollment).where(
                                Enrollment.user_id == user_id,
                                Enrollment.course_id == UUID(state.course_id),
                                Enrollment.tenant_id == tenant_id,
                            )
                        )
                        if not existing.scalar_one_or_none():
                            enrollment = Enrollment(
                                user_id=user_id,
                                course_id=UUID(state.course_id),
                                tenant_id=tenant_id,
                                status="enrolled",
                            )
                            session.add(enrollment)
                            await session.commit()
                            logger.info(f"Auto-enrolled creator {user_id} in course {state.course_id}")
                except Exception as e:
                    logger.warning(f"Auto-enrollment failed: {e}")

        state.status = "completed"
        state.progress = 100
        state.message = "Course generation complete!"
        await _update_job_db(
            job_id,
            status="completed",
            stage="completed",
            progress=100,
            message=state.message,
            completed_at=datetime.now(timezone.utc),
        )

        logger.info(f"Generation pipeline complete for job {job_id}")

    except Exception as e:
        state.status = "failed"
        state.message = f"Error: {str(e)}"
        state.errors.append(str(e))
        await _update_job_db(job_id, status="failed", message=state.message, errors=[str(e)])
        logger.error(f"Generation pipeline failed for job {job_id}: {e}")

    return state
