"""AI Generation Pipeline — orchestrates architect, writer, and assessment agents."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable
from dataclasses import dataclass, field

from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.writer_schema import CourseContent, ModuleContent, LessonContent
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.llm_client import LLMClient, create_llm
from app.modules.ai.ingestion import VectorStore, DocumentIngestion
from app.modules.ai.architect import run_architect, create_architect_tools
from app.modules.ai.writer import write_lesson, write_course
from app.modules.ai.assessment import generate_lesson_assessment, generate_course_assessment

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


# In-memory job store (replace with Redis/DB in production)
_jobs: dict[str, GenerationState] = {}


def get_job_state(job_id: str) -> GenerationState | None:
    return _jobs.get(job_id)


def update_job(job_id: str, **kwargs):
    if job_id in _jobs:
        for k, v in kwargs.items():
            setattr(_jobs[job_id], k, v)


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
    _jobs[job_id] = state

    try:
        # Stage 1: Ingestion
        state.stage = "ingestion"
        state.progress = 5
        state.message = "Ingesting documents..."
        update_job(job_id, status="running", stage="ingestion", progress=5)

        ingestion = DocumentIngestion()
        # TODO: Download documents from storage and ingest
        # For now, assume documents are already ingested

        # Stage 2: Architect
        state.stage = "architect"
        state.progress = 10
        state.message = "Designing course structure..."
        update_job(job_id, stage="architect", progress=10)

        llm = create_llm()
        store = VectorStore()
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
            on_message=lambda msg: update_job(job_id, message=f"Architect: {msg}"),
        )

        state.structure = structure
        state.progress = 25
        state.message = f"Structure designed: {len(structure.modules)} modules"
        update_job(job_id, progress=25, message=state.message)

        # Stage 3: Content Generation (Writer)
        state.stage = "content_generation"
        state.progress = 30
        state.message = "Generating lesson content..."
        update_job(job_id, stage="content_generation", progress=30)

        total_lessons = sum(len(m.lessons) for m in structure.modules)
        lessons_done = 0

        async def on_lesson_progress(msg: str):
            nonlocal lessons_done
            lessons_done += 1
            pct = 30 + int(lessons_done / total_lessons * 40)
            update_job(job_id, progress=min(pct, 70), message=msg)

        content = await write_course(
            llm=llm,
            store=store,
            structure=structure,
            doc_ids=documents if documents else None,
            language=language,
            on_progress=on_lesson_progress,
        )

        state.content = content
        state.progress = 70
        state.message = "Content generation complete"
        update_job(job_id, progress=70, message=state.message)

        # Stage 4: Assessment Generation
        state.stage = "assessment"
        state.progress = 75
        state.message = "Generating assessments..."
        update_job(job_id, stage="assessment", progress=75)

        assessments_done = 0

        async def on_assessment_progress(msg: str):
            nonlocal assessments_done
            assessments_done += 1
            pct = 75 + int(assessments_done / total_lessons * 20)
            update_job(job_id, progress=min(pct, 95), message=msg)

        assessment = await generate_course_assessment(
            llm=llm,
            course_content=content,
            language=language,
            on_progress=on_assessment_progress,
        )

        state.assessment = assessment
        state.progress = 95
        state.message = "Assessments generated"
        update_job(job_id, progress=95, message=state.message)

        # Stage 5: Save to DB
        state.stage = "saving"
        state.progress = 98
        state.message = "Saving results..."
        update_job(job_id, stage="saving", progress=98)

        # TODO: Save to PostgreSQL
        # - Create/update course with structure
        # - Create modules, lessons, content blocks
        # - Create quizzes, questions, choices

        state.status = "completed"
        state.progress = 100
        state.message = "Course generation complete!"
        update_job(job_id, status="completed", progress=100, message=state.message)

        logger.info(f"Generation pipeline complete for job {job_id}")

    except Exception as e:
        state.status = "failed"
        state.message = f"Error: {str(e)}"
        state.errors.append(str(e))
        update_job(job_id, status="failed", message=state.message)
        logger.error(f"Generation pipeline failed for job {job_id}: {e}")

    return state


def start_generation_job(
    documents: list[str],
    target_audience: str = "",
    num_modules: int = 3,
    language: str = "ru",
    goals: list[str] | None = None,
    course_hours: float | None = None,
    guidance: str | None = None,
    course_id: str | None = None,
) -> str:
    """Start a generation job (sync wrapper for Celery)."""
    import uuid
    job_id = str(uuid.uuid4())
    state = GenerationState(job_id=job_id, course_id=course_id)
    _jobs[job_id] = state
    return job_id
