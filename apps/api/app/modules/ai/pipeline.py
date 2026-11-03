"""AI generation pipeline for the single evidence-backed course engine."""
from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]

from app.core.db import async_session_factory
from app.modules.ai import timeout_context
from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id, lock_owned_delivery
from app.modules.ai.direct_source import (
    DirectSourceCorpus,
    DirectSourceError,
    load_direct_source_corpus,
)
from app.modules.ai.evidence_engine.application import (
    generate_evidence_course,
    to_generation_artifacts,
)
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError
from app.modules.ai.generation_engine import (
    RETIRED_GENERATION_ENGINE_CODE,
    uses_current_generation_engine,
)
from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    ResilientEmbeddingsClient,
    ResilientLLMClient,
)
from app.modules.ai.v3.cooperative_budget import PreclaimYieldError
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.writer_schema import CourseContent
from app.modules.courses.source_uncertainty import preserve_generated_source_uncertainty

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models.ai_job import AIJob

GENERATION_FAILURE_CODE = "generation_failed"
GENERATION_FAILURE_MESSAGE = (
    "Не удалось сгенерировать курс. Повторите попытку или обратитесь к администратору."
)
GENERATION_PROVIDER_INTERRUPTED_CODE = "generation_provider_interrupted"
GENERATION_PROVIDER_INTERRUPTED_MESSAGE = (
    "Сервисы ИИ временно недоступны. Готовые уроки сохранены — "
    "продолжите генерацию с оставшихся."
)


def _estimate_lesson_duration_seconds(
    content: str | None,
    assessment_question_count: int = 0,
) -> int:
    """Estimate study time from reading plus one minute per question."""
    word_count = len((content or "").split())
    reading_minutes = max(2, math.ceil(word_count / 150))
    question_minutes = max(0, int(assessment_question_count))
    return (reading_minutes + question_minutes) * 60


def _generation_completion_message(content: CourseContent | None) -> str:
    if content is not None:
        notices = list(content.source_warnings)
        if content.omitted_lesson_titles:
            notices.insert(0, "Сохранён неполный черновик. Не подготовлены темы: " + "; ".join(content.omitted_lesson_titles))
        if notices:
            return "\n".join(notices)
    return "Курс успешно сгенерирован!"


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
    server_source_review_required: bool = False
    owned_v3_source_context: Any = field(default=None, repr=False)
    owned_v3_route_fingerprint: str | None = field(default=None, repr=False)
    reuse_reason: str | None = None


async def _update_job_db(
    job_id: str,
    tenant_id: UUID | str | None = None,
    saved_v2_state: GenerationState | None = None,
    **kwargs: object,
) -> bool:
    """Update job state; return whether a saved V2 review outcome was restored."""
    from sqlalchemy import text

    from app.modules.ai.job_service import get_ai_job, update_ai_job
    async with async_session_factory() as session:
        tenant_value = str(tenant_id) if tenant_id else None
        if not tenant_value and delivery_id.get() is not None:
            raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
        if tenant_value:
            await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_value})
        if tenant_value:
            await lock_owned_delivery(session, job_id, tenant_value, require_running=True)
            if kwargs.get("status") in {"failed", "interrupted", "cancelled", "completed"}:
                from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
                from app.modules.ai.v3.pending_stage_transactions import has_pending

                locked_job = await get_ai_job(session, job_id, tenant_id=tenant_value, for_update=True)
                if locked_job is not None and has_pending(locked_job.result):
                    raise ExtractionOutcomeUnknownError("generation_stage_outcome_unknown")
        progress_detail_supplied = "progress_detail" in kwargs
        progress_detail = kwargs.pop("progress_detail", None)
        completion_result = kwargs.pop("completion_result", None)
        job = await update_ai_job(session, job_id, tenant_id=tenant_value, **kwargs)
        # update_ai_job holds the cancellation row lock. Restore before commit,
        # so a resume cannot publish a new running state for this saved outcome.
        if job is not None and saved_v2_state is not None:
            if job.status == "cancelled":
                raise asyncio.CancelledError(f"Job {job_id} cancelled")
            if _restore_saved_v2_outcome(saved_v2_state, job):
                await session.commit()
                return True
        if job is not None and isinstance(completion_result, dict):
            if job.status == "cancelled":
                raise asyncio.CancelledError(f"Job {job_id} cancelled")
            job.result = {**(job.result or {}), **completion_result}  # type: ignore[assignment]
            job.params = {**(job.params or {}), "completion": completion_result}  # type: ignore[assignment]
        if job is not None and progress_detail_supplied:
            params = dict(job.params or {})
            if progress_detail is None:
                params.pop("progress_detail", None)
            else:
                params["progress_detail"] = progress_detail
            job.params = params  # type: ignore[assignment]
        await session.commit()
        return False


async def _persist_pending_stage_hold(job_id: str, tenant_id: UUID | None, user_id: UUID | None,
                                      *, expected_qa_marker: object = None) -> bool:
    """Persist an owned reconciliation hold, retaining or establishing a durable fence.

    A killed worker or unavailable database cannot perform this transition.
    """
    from app.modules.ai.v3.pending_stage_transactions import _locked_job, has_pending
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    if tenant_id is None or user_id is None:
        return False
    journal = WorkerCycleJournal(str(tenant_id), job_id, async_session_factory)
    try:
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            if not has_pending(job.result):
                from app.modules.ai.qa_luna_dev_route import QA_TENANT
                from app.modules.ai.v3.pending_stage_transactions import KEY
                from app.modules.ai.v3.qa_luna_pending_policy import (
                    DIRECT_POLICY,
                    DIRECT_POLICY_V1,
                    DIRECT_POLICY_V2,
                    MANAGED_POLICY,
                    POLICY,
                )
                from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_KEY

                params = job.params if isinstance(job.params, dict) else {}
                analysis = params.get("source_analysis")
                if (tenant_id != QA_TENANT or expected_qa_marker not in (POLICY, DIRECT_POLICY, DIRECT_POLICY_V1, DIRECT_POLICY_V2, MANAGED_POLICY) or job.course_id is not None
                        or not isinstance(analysis, dict) or analysis.get(QA_KEY) != expected_qa_marker
                        or analysis.get("generation_engine") != "evidence_v3"):
                    return False
                job.result = {**(job.result if isinstance(job.result, dict) else {}), KEY: None}
            job.status = job.stage = "interrupted"
            job.message = "Результат этапа требует проверки."
            job.errors = ["generation_stage_outcome_unknown"]
            job.completed_at = None
            job.updated_at = datetime.now(UTC)
            await session.commit()
            return True
    except Exception:
        return False


async def _release_generation_reservation(
    job_id: str,
    tenant_id: UUID | str,
) -> bool:
    """Release a new-course reservation in an independent transaction."""

    from sqlalchemy import text

    from app.modules.ai.job_service import _lock_tenant_row, release_generation_reservation_once

    tenant_value = str(tenant_id)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_value})
        await _lock_tenant_row(session, tenant_value)
        await lock_owned_delivery(session, job_id, tenant_value, allowed_statuses=frozenset({"failed", "cancelled"}))
        released = await release_generation_reservation_once(
            session,
            job_id=job_id,
            tenant_id=tenant_value,
        )
        await session.commit()
        return released


def _timed_progress_detail(
    completed: int,
    total: int,
    started_at: float,
) -> dict[str, int | str]:
    """Build count-based progress with an estimate derived only from completed units."""
    if total < 1 or completed < 0 or completed > total:
        raise ValueError("invalid_progress_detail")
    detail: dict[str, int | str] = {"current": completed, "total": total}
    if completed == total:
        detail["estimated_remaining_seconds"] = 0
    elif completed > 0:
        elapsed = max(0.0, time.monotonic() - started_at)
        detail["estimated_remaining_seconds"] = math.ceil(
            (total - completed) * elapsed / completed
        )
    return detail


def _completed_progress_detail(content: CourseContent) -> dict[str, int] | None:
    """Describe the exact number of lessons that reached the saved course."""
    total = sum(len(module.lessons) for module in content.modules)
    if total < 1:
        return None
    return {"current": total, "total": total, "estimated_remaining_seconds": 0}


ASSESSMENT_NO_VALID_QUESTIONS_CODE = "assessment_no_valid_questions"
ASSESSMENT_NO_VALID_QUESTIONS_MESSAGE = (
    "Уроки сохранены в черновике, но действительных вопросов для теста нет. "
    "Проверьте и добавьте тесты перед публикацией курса."
)
ASSESSMENT_COVERAGE_INCOMPLETE_CODE = "assessment_coverage_incomplete"
ASSESSMENT_REVIEW_MESSAGES = {
    ASSESSMENT_NO_VALID_QUESTIONS_CODE: ASSESSMENT_NO_VALID_QUESTIONS_MESSAGE,
    ASSESSMENT_COVERAGE_INCOMPLETE_CODE: (
        "Черновик курса и готовые вопросы сохранены. Тесты не покрывают часть "
        "содержательных тем; проверьте их перед публикацией."
    ),
}


def _assessment_question_count(assessment: CourseAssessment | None) -> int:
    if assessment is None:
        return 0
    return sum(
        len(lesson.mcq) + len(lesson.true_false) + sum(len(item.pairs) for item in lesson.matching)
        for lesson in assessment.assessments
    )


def _require_supported_question_export_ready(assessment: CourseAssessment | None) -> None:
    """Do not silently discard support evidence while verified export is unavailable."""
    if assessment is not None and any(
        question.supporting_source_evidence is not None
        for lesson in assessment.assessments
        for question in lesson.mcq
    ):
        raise ValueError("support_source_export_unavailable")


def _evidence_v2_completion_detail(state: GenerationState) -> dict[str, object]:
    """Return bounded V2 completion facts suitable for job params and result."""
    content = state.content
    assessment = state.assessment
    modules = len(content.modules) if content is not None else 0
    lessons = sum(len(module.lessons) for module in content.modules) if content is not None else 0
    questions = _assessment_question_count(assessment)
    quizzes = sum(
        1
        for lesson in (assessment.assessments if assessment is not None else [])
        if len(lesson.mcq) + len(lesson.true_false) + sum(len(item.pairs) for item in lesson.matching)
    )
    omitted_titles = list(content.omitted_lesson_titles) if content is not None else []
    diagnostics = state.source_analysis.get("evidence_v2", {})
    assessment_review = diagnostics.get("assessment_review", {})
    coverage = assessment_review.get("coverage") if isinstance(assessment_review, dict) else None
    coverage_requires_review = not (
        isinstance(coverage, dict) and coverage.get("requires_review") is False
    )
    source_count = diagnostics.get("uncertain_source_fact_count", 0)
    editorial_count = diagnostics.get("source_editorial_review_document_count")
    source_requires_review = (not (type(source_count) is int and source_count == 0)
                              or not (type(editorial_count) is int and editorial_count == 0))
    return {
        "outcome": (
            ASSESSMENT_NO_VALID_QUESTIONS_CODE if questions == 0 else
            ASSESSMENT_COVERAGE_INCOMPLETE_CODE if coverage_requires_review or source_requires_review else "completed"
        ),
        "counts": {
            "modules": modules,
            "lessons": lessons,
            "quizzes": quizzes,
            "questions": questions,
        },
        "omitted_lessons": [
            {"title": title, "reasons": ["lesson_omitted"]} for title in omitted_titles
        ],
        "omitted_assessments": [
            {"title": lesson.lesson_title, "reasons": [ASSESSMENT_NO_VALID_QUESTIONS_CODE]}
            for lesson in (assessment.assessments if assessment is not None else [])
            if not (lesson.mcq or lesson.true_false or any(item.pairs for item in lesson.matching))
        ],
        "source_warnings": list(content.source_warnings) if content is not None else [],
        "source_admission_requires_review": source_requires_review,
        "assessment_review": assessment_review,
    }


def _apply_evidence_v2_completion_outcome(state: GenerationState) -> None:
    """Keep a saved V2 draft reviewable when every assessment question was rejected."""
    if state.source_analysis.get("generation_engine") != "evidence_v2":
        return
    completion = _evidence_v2_completion_detail(state)
    state.source_analysis = {**state.source_analysis, "completion": completion}
    state.errors = []
    if completion["outcome"] not in ASSESSMENT_REVIEW_MESSAGES:
        return
    state.status = "interrupted"
    state.stage = "interrupted"
    state.progress = 100
    code = str(completion["outcome"])
    state.message = ASSESSMENT_REVIEW_MESSAGES[code]
    if completion.get("source_admission_requires_review"):
        state.message = (
            "Черновик курса и готовые вопросы сохранены. Некоторые фрагменты исходных "
            "материалов не удалось надёжно разобрать; проверьте полноту уроков и тестов "
            "по оригиналу перед публикацией."
        )
    state.errors = [code]


def _job_completion_result(
    state: GenerationState, *, course_id: str | None = None,
) -> dict[str, object] | None:
    if state.source_analysis.get("generation_engine") != "evidence_v2":
        return None
    completion = state.source_analysis.get("completion")
    if not isinstance(completion, dict):
        return None
    result = dict(completion)
    if course_id or state.course_id:
        result["course_id"] = course_id or state.course_id
    return result


def _restore_saved_v2_outcome(state: GenerationState, job: AIJob) -> bool:
    """A saved assessment-review draft is not a resumable generation checkpoint."""
    if state.source_analysis.get("generation_engine") != "evidence_v2" or not job.course_id:
        return False
    completion = cast(dict[str, object], job.params or {}).get("completion")
    if not isinstance(completion, dict) or completion.get("outcome") not in ASSESSMENT_REVIEW_MESSAGES:
        return False
    state.course_id = str(job.course_id)
    state.status = state.stage = "interrupted"
    state.progress = 100
    code = str(completion["outcome"])
    state.message = ASSESSMENT_REVIEW_MESSAGES[code]
    state.errors = [code]
    state.source_analysis = {**state.source_analysis, "completion": dict(completion)}
    counts = completion.get("counts", {})
    lessons = counts.get("lessons") if isinstance(counts, dict) else None
    if type(lessons) is int and lessons > 0:
        job.params = {  # type: ignore[assignment]
            **(job.params or {}),
            "progress_detail": {"current": lessons, "total": lessons, "estimated_remaining_seconds": 0},
        }
    for name in ("status", "stage", "progress", "message", "errors"):
        setattr(job, name, getattr(state, name))
    job.completed_at = None  # type: ignore[assignment]
    job.updated_at = datetime.now(UTC)  # type: ignore[assignment]
    return True


async def _run_evidence_v2_generation(
    state: GenerationState,
    corpus: DirectSourceCorpus,
    *,
    tenant_id: UUID,
    target_audience: str,
    guidance: str | None,
    goals: list[str] | None,
    max_total_lessons: int | None,
) -> None:
    """Populate the existing persistence state from one complete V2 result."""

    # Evidence V2 asks the model to faithfully reorganize supplied facts. A
    # low temperature makes the strict evidence contract reproducible and
    # avoids needless failover caused by creative paraphrases.
    from app.core.config import get_settings
    from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings, runtime_settings_scope
    from app.modules.ai.qa_luna_dev_route import qa_luna_dev_client

    policy = await resolve_runtime_settings()
    with runtime_settings_scope(policy):
        generation_client = await qa_luna_dev_client(
            settings=get_settings(), tenant_id=tenant_id,
            temperature=policy.number("generation.temperature"),
        )
        if generation_client is None:
            generation_client = await ResilientLLMClient.from_settings_async(
                tenant_id=tenant_id,
                temperature=policy.number("generation.temperature"),
            )

    embedding_client = await ResilientEmbeddingsClient.from_settings_async(
        tenant_id=tenant_id
    )
    realization_started = time.monotonic()
    assessment_started: float | None = None

    embedding_started = time.monotonic()
    from app.modules.ai.worker_lesson_cycle import create_dev_lesson_assessor

    settings = get_settings()
    lesson_assessor = create_dev_lesson_assessor(
        settings=settings, tenant_id=str(tenant_id), job_id=state.job_id, client=generation_client,
        session_factory=async_session_factory,
        checkpoint=lambda: _check_cancelled_async(state.job_id, tenant_id=tenant_id),
    )

    async def report_progress(
        stage: str,
        current: int,
        total: int,
        provider: str | None,
        attempt: int | None,
    ) -> None:
        nonlocal assessment_started
        if stage == "evidence_plan":
            progress, message, detail = 15, "Построен доказательный план курса", None
        elif stage == "embeddings":
            progress = 15 + math.floor(10 * current / max(1, total))
            message = f"Семантический анализ: {current} из {total}"
            detail = _timed_progress_detail(current, total, embedding_started)
            if provider:
                detail["provider"] = provider
            if attempt is not None:
                detail["attempt"] = attempt
        elif stage == "realization":
            progress = 25 + math.floor(65 * current / max(1, total))
            message = f"Создание уроков: {current} из {total}"
            detail = _timed_progress_detail(current, total, realization_started)
        elif stage == "assessment":
            if assessment_started is None:
                assessment_started = time.monotonic()
            progress = 90 + math.floor(4 * current / max(1, total))
            message = f"Создание и проверка тестов: {current} из {total} смысловых блоков"
            detail = _timed_progress_detail(current, total, assessment_started)
        elif stage == "lesson_cycle":
            progress = 25 + math.floor(69 * current / max(1, total))
            message = f"Обработано уроков с проверкой тестов: {current} из {total}"
            detail = _timed_progress_detail(current, total, realization_started)
        elif stage == "quality":
            progress, message, detail = 95, "Проверка уроков и тестов завершена", None
        else:
            raise ValueError("unknown_evidence_v2_progress_stage")
        state.stage = stage
        state.progress = progress
        state.message = message
        await _update_job_db(
            state.job_id,
            tenant_id=tenant_id,
            stage=stage,
            progress=progress,
            message=message,
            progress_detail=detail,
        )

    generated = await generate_evidence_course(
        corpus,
        intent=CourseIntent(
            purpose=(guidance or "").strip(),
            audience=target_audience.strip(),
            emphasis=tuple(value.strip() for value in (goals or []) if value.strip()),
        ),
        generation_client=generation_client,
        embedding_client=embedding_client,
        max_lessons=max_total_lessons,
        lesson_assessor=lesson_assessor,
        progress_callback=report_progress,
        cancellation_callback=lambda: _check_cancelled_async(
            state.job_id,
            tenant_id=tenant_id,
        ),
    )
    state.server_source_review_required = any(document.review_only_source_context or document.review_only_source_unresolved for document in generated.corpus.documents)
    artifacts = to_generation_artifacts(generated)
    state.structure = artifacts.structure
    state.content = artifacts.content
    state.assessment = artifacts.assessment
    state.source_analysis = {
        **state.source_analysis,
        "evidence_v2": artifacts.diagnostics,
    }


async def _load_owned_reference_decisions(
    job_id: str, tenant_id: UUID, user_id: UUID | None, documents: list[str],
) -> tuple[Any, ...]:
    """Read decisions from the owned persisted job, never from queue payload metadata."""
    from sqlalchemy import text

    from app.modules.ai.job_service import get_ai_job
    from app.modules.ai.v3.source_reference_decisions import hydrate_reference_decisions

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        await lock_owned_delivery(session, job_id, str(tenant_id), require_running=True)
        job = await get_ai_job(session, job_id, tenant_id=str(tenant_id))
        if job is None or user_id is None or job.user_id != user_id or job.status != "running":
            raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
        _validate_generation_source_selection(job.params, documents)
        params: dict[str, Any] = job.params if isinstance(job.params, dict) else {}
        return hydrate_reference_decisions(params.get("reference_decisions", []), str(tenant_id), str(user_id), documents)


async def _load_owned_revision_policy(
    job_id: str, tenant_id: UUID, user_id: UUID | None, documents: list[str],
) -> str | None:
    """Read only the persisted marker under the current owned delivery lock."""
    from app.modules.ai.v3.revision_policy import read_policy
    return read_policy(await _load_owned_generation_analysis(job_id, tenant_id, user_id, documents))


async def _load_owned_generation_analysis(
    job_id: str, tenant_id: UUID, user_id: UUID | None, documents: list[str],
) -> dict[str, Any]:
    from sqlalchemy import text

    from app.modules.ai.job_service import get_ai_job

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        await lock_owned_delivery(session, job_id, str(tenant_id), require_running=True)
        job = await get_ai_job(session, job_id, tenant_id=str(tenant_id))
        if job is None or user_id is None or job.user_id != user_id or job.status != "running":
            raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
        _validate_generation_source_selection(job.params, documents)
        params: dict[str, Any] = job.params if isinstance(job.params, dict) else {}
        analysis = params.get("source_analysis")
        if not isinstance(analysis, dict):
            raise ValueError("v3_revision_analysis_invalid")
        return analysis


async def _run_v3_generation(
    state: GenerationState,
    corpus: DirectSourceCorpus,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    target_audience: str,
    guidance: str | None,
    goals: list[str] | None,
    max_total_lessons: int | None,
) -> None:
    """Populate the existing persistence state from one complete V3 result."""
    from app.core.config import get_settings
    from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings, runtime_settings_scope
    from app.modules.ai.qa_luna_dev_route import qa_luna_dev_client
    from app.modules.ai.v3.service import generate_v3_course_from_corpus
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    if str(corpus.tenant_id) != str(tenant_id):
        raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.qa_luna_pending_policy import (
        DIRECT_POLICY,
        DIRECT_POLICY_V2,
        MANAGED_POLICY,
        OWNED_POLICIES,
        check_worker_marker,
    )
    from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_PENDING_KEY

    journal: Any = WorkerCycleJournal(str(tenant_id), state.job_id, async_session_factory)
    pending_mode = False
    authenticated_qa_policy: str | None = None
    owned_source_context: Any = None
    direct_client: Any = None
    revision_policy = await _load_owned_revision_policy(state.job_id, tenant_id, user_id, list(corpus.document_ids))
    from app.modules.ai.v3.revision_policy import POLICY as PROFILE_REVISION_POLICY
    from app.modules.ai.v3.revision_policy import read_review_policy
    review_policy = (read_review_policy(await _load_owned_generation_analysis(
        state.job_id, tenant_id, user_id, list(corpus.document_ids)))
        if revision_policy == PROFILE_REVISION_POLICY else None)
    if tenant_id == QA_TENANT and state.source_analysis.get(QA_PENDING_KEY) is not None:
        from app.modules.ai.v3.owned_source_context import load_owned_source_context
        from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
        from app.modules.ai.v3.pending_stage_transactions import _locked_job

        if not isinstance(user_id, UUID):
            raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            analysis = job.params.get("source_analysis") if isinstance(job.params, dict) else None
            stored = analysis.get(QA_PENDING_KEY) if isinstance(analysis, dict) else None
            dispatched = state.source_analysis.get(QA_PENDING_KEY)
            try:
                pending_mode = check_worker_marker(settings=get_settings(), tenant_id=tenant_id, user_id=user_id,
                                                   stored=stored, dispatched=dispatched, course_id=job.course_id)
            except ValueError as exc:
                raise ExtractionOutcomeUnknownError("qa_luna_pending_route_unverified") from exc
        if pending_mode:
            authenticated_qa_policy = stored
            journal = PendingStageJournal(str(tenant_id), user_id, state.job_id, async_session_factory)
            from app.modules.ai.v3.completed_extraction_reuse import read_parent_marker
            journal.completed_extraction_parent_job_id = read_parent_marker(job.params, stored)
            context = await load_owned_source_context(journal=journal, tenant_id=tenant_id,
                                                      user_id=user_id, job_id=state.job_id)
            owned_source_context = context
            if stored in OWNED_POLICIES:
                state.owned_v3_source_context = context
            async def verify_qa_source(session: Any, job: Any, plan: dict[str, Any]) -> bool:
                from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY
                from app.modules.ai.v3.owned_route_binding import POLICY as ROUTE_POLICY

                current = job.params.get("source_analysis") if isinstance(job.params, dict) else None
                from app.modules.ai.v3.revision_policy import policy_matches

                route_valid = (stored not in OWNED_POLICIES or (direct_client is not None
                    and isinstance(job.result, dict) and job.result.get(ROUTE_KEY) == {
                        "policy": ROUTE_POLICY, "fingerprint": direct_client.cache_fingerprint()}))
                return (isinstance(current, dict) and policy_matches(current, revision_policy)
                        and read_review_policy(current) == review_policy
                        and current.get(QA_PENDING_KEY) == stored
                        and route_valid
                        and read_parent_marker(job.params, stored) == journal.completed_extraction_parent_job_id
                        and await context.verify_locked(session, job, plan) is True)
            journal.verify_source = verify_qa_source
            corpus = context.corpus
    reference_decisions = await _load_owned_reference_decisions(
        state.job_id, tenant_id, user_id, list(corpus.document_ids),
    )
    if revision_policy is not None and not pending_mode:
        import hashlib

        from app.modules.ai.v3.owned_source_context import OwnedSourceContext

        if not isinstance(user_id, UUID):
            raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
        if revision_policy == PROFILE_REVISION_POLICY:
            from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
            journal = PendingStageJournal(str(tenant_id), user_id, state.job_id, async_session_factory)
        source_text = "\n\n".join(item.source_text for item in corpus.documents if item.source_text)
        journal.expected_revision_policy = revision_policy
        journal.expected_revision_actor = user_id
        journal.expected_revision_source = OwnedSourceContext(
            corpus, journal, tenant_id, user_id, state.job_id, tuple(str(value) for value in corpus.document_ids))
        journal.expected_revision_plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": str(tenant_id),
            "job_id": state.job_id, "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest()}
        if revision_policy == PROFILE_REVISION_POLICY:
            async def verify_native_source(session: Any, job: Any, plan: dict[str, Any]) -> bool:
                from app.modules.ai.v3.revision_policy import policy_matches
                analysis = job.params.get("source_analysis") if isinstance(job.params, dict) else None
                return (policy_matches(analysis, revision_policy)
                        and read_review_policy(analysis) == review_policy
                        and await journal.expected_revision_source.verify_locked(session, job, plan) is True)
            journal.verify_source = verify_native_source
    if revision_policy == PROFILE_REVISION_POLICY:
        journal.review_policy_bound = True
        journal.expected_review_policy = review_policy

    policy = await resolve_runtime_settings()
    with runtime_settings_scope(policy):
        if pending_mode and state.source_analysis.get(QA_PENDING_KEY) in (DIRECT_POLICY, DIRECT_POLICY_V2, MANAGED_POLICY):
            from app.modules.ai.direct_luna_responses_factory import (
                create_direct_qa_responses_client,
                create_managed_qa_client,
            )

            try:
                if authenticated_qa_policy == MANAGED_POLICY:
                    direct_client = await create_managed_qa_client(settings=get_settings(), tenant_id=tenant_id,
                        user_id=user_id, job_id=state.job_id)
                else:
                    direct_client = create_direct_qa_responses_client(settings=get_settings(), tenant_id=tenant_id,
                        user_id=user_id, job_id=state.job_id)
            except ValueError as exc:
                raise ExtractionOutcomeUnknownError("direct_qa_responses_unavailable") from exc
            generation_client = direct_client
            if authenticated_qa_policy in OWNED_POLICIES:
                from app.modules.ai.v3.owned_route_binding import bind_owned_route

                try:
                    state.owned_v3_route_fingerprint = await bind_owned_route(
                        journal=journal, user_id=user_id, client=direct_client)
                except BaseException:
                    direct_client.close()
                    raise
        else:
            generation_client = await qa_luna_dev_client(
                settings=get_settings(), tenant_id=tenant_id, temperature=policy.number("generation.temperature"),
            )
        if generation_client is None:
            if pending_mode:
                raise ExtractionOutcomeUnknownError("qa_luna_pending_provider_unavailable")
            generation_client = await ResilientLLMClient.from_settings_async(
                tenant_id=tenant_id,
                temperature=policy.number("generation.temperature"),
            )
        if (revision_policy == PROFILE_REVISION_POLICY and authenticated_qa_policy is None
                and direct_client is None and type(generation_client) is ResilientLLMClient):
            from app.modules.ai.v3.native_profile_binding import bind_native_profile
            from app.modules.ai.v3.provider_profile import V3ProfiledClient
            from app.modules.ai.v3.revision_policy import REVIEW_POLICY
            cooperative_native = review_policy == REVIEW_POLICY
            generation_client = V3ProfiledClient(
                generation_client, policy, job_id=state.job_id,
                **({"cooperative_deadline": True} if cooperative_native else {}),
            )
            if cooperative_native:
                journal.native_generation_seconds = generation_client.generation_deadline_seconds
            await bind_native_profile(journal=journal, user_id=user_id, client=generation_client)

    realization_started = time.monotonic()

    async def report_progress(
        stage: str,
        current: int,
        total: int,
        provider: str | None,
        attempt: int | None,
    ) -> None:
        if stage == "quality":
            progress, message, detail = 95, "Проверка уроков и тестов V3 завершена", None
        else:
            progress = 20 + math.floor(70 * current / max(1, total))
            message = f"V3 Создание уроков и банка кейсов: {current} из {total}"
            detail = _timed_progress_detail(current, total, realization_started)
            if provider:
                detail["provider"] = provider
            if attempt is not None:
                detail["attempt"] = attempt
        state.stage = stage
        state.progress = progress
        state.message = message
        await _update_job_db(
            state.job_id,
            tenant_id=tenant_id,
            stage=stage,
            progress=progress,
            message=message,
            progress_detail=detail,
        )

    try:
        artifacts = await generate_v3_course_from_corpus(
            corpus,
            intent=CourseIntent(
                purpose=(guidance or "").strip(),
                audience=target_audience.strip(),
                emphasis=tuple(value.strip() for value in (goals or []) if value.strip()),
            ),
            generation_client=generation_client,
            progress_callback=report_progress,
            cancellation_callback=lambda: _check_cancelled_async(
                state.job_id,
                tenant_id=tenant_id,
            ),
            extraction_journal=journal,
            route_fingerprint=generation_client.cache_fingerprint(),
            reference_decisions=reference_decisions,
            direct_client=direct_client,
            authenticated_qa_policy=authenticated_qa_policy,
            owned_source_context=owned_source_context,
            revision_policy=revision_policy,
            review_policy=review_policy,
        )
    finally:
        if direct_client is not None:
            direct_client.close()

    requires_review = bool(
        artifacts.diagnostics.get("requires_source_review", True)
        or any(
            lesson.requires_source_review()
            for module in artifacts.content.modules
            for lesson in module.lessons
        )
    )
    state.server_source_review_required = requires_review
    state.structure = artifacts.structure
    state.content = artifacts.content
    state.assessment = artifacts.assessment
    state.source_analysis = {
        **state.source_analysis,
        "generation_engine": "evidence_v3",
        "evidence_v3": artifacts.diagnostics,
    }


def _apply_assessment_omission_notices(state: GenerationState) -> None:
    """Keep usable lessons while making absent generated quizzes visible."""
    if state.assessment is None or state.content is None:
        return
    missing = [
        item.lesson_title for item in state.assessment.assessments
        if not item.mcq and not item.true_false and not item.matching
    ]
    if not missing:
        return
    notice = (
        "Сохранены уроки без теста: " + "; ".join(missing)
        + ". Вопросы не прошли проверку качества; перед публикацией добавьте или проверьте тесты."
    )
    if notice not in state.content.source_warnings:
        state.content.source_warnings.append(notice)
    if notice not in state.content.description:
        state.content.description = "\n\n".join(filter(None, (state.content.description, notice)))
    if state.structure is not None and notice not in state.structure.description:
        state.structure.description = "\n\n".join(filter(None, (state.structure.description, notice)))


async def _verify_fresh_v3_final_source(
    session: Any, job: Any, state: GenerationState, tenant_id: UUID, user_id: UUID,
    *, final_intent: dict[str, Any] | None = None,
) -> None:
    """Fence fresh direct-QA completion inside its owned save transaction."""
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.final_save_contract import FENCE_POLICY, INTENT_KEY
    from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY
    from app.modules.ai.v3.owned_route_binding import POLICY as ROUTE_POLICY
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
    from app.modules.ai.v3.pending_stage_transactions import has_pending
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, OWNED_POLICIES

    params = job.params if isinstance(job.params, dict) else {}
    analysis = params.get("source_analysis")
    stored = analysis.get(KEY) if isinstance(analysis, dict) else None
    dispatched = state.source_analysis.get(KEY)
    if stored not in OWNED_POLICIES and dispatched not in OWNED_POLICIES and state.owned_v3_source_context is None:
        return
    if delivery_id.get() is None:
        raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
    context = state.owned_v3_source_context
    matching_final_fence = (final_intent is not None and isinstance(job.result, dict)
        and job.result.get(INTENT_KEY) == final_intent
        and job.result.get(PENDING_KEY) == {"policy": FENCE_POLICY,
            "intent_digest": final_intent.get("intent_digest"), "attempt_id": final_intent.get("attempt_id")})
    if (stored not in OWNED_POLICIES or dispatched != stored or tenant_id != QA_TENANT
            or not isinstance(analysis, dict) or analysis.get("generation_engine") != "evidence_v3"
            or analysis.get("analysis_mode") != "direct_source" or (has_pending(job.result) and not matching_final_fence)
            or not isinstance(state.owned_v3_route_fingerprint, str)
            or not isinstance(job.result, dict)
            or job.result.get(ROUTE_KEY) != {"policy": ROUTE_POLICY,
                                             "fingerprint": state.owned_v3_route_fingerprint}
            or (isinstance(job.result, dict) and any(key in job.result for key in (
                "source_first_commit_intent", "source_first_partitioned_commit_intent")))
            or type(context) is not OwnedSourceContext or context.tenant_id != tenant_id
            or context.user_id != user_id or context.job_id != state.job_id
            or context.selection != tuple(state.source_document_ids)
            or tuple(context.corpus.document_ids) != context.selection):
        raise ExtractionOutcomeUnknownError("v3_final_source_unverified")
    source_texts = [doc.source_text for doc in context.corpus.documents]
    if any(not isinstance(text, str) or not text for text in source_texts):
        raise ExtractionOutcomeUnknownError("v3_final_source_unverified")
    source = "\n\n".join(cast(str, text) for text in source_texts)
    plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": str(tenant_id), "job_id": state.job_id,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
    try:
        valid = await context.verify_locked(session, job, plan)
    except BaseException:
        valid = False
    if valid is not True:
        raise ExtractionOutcomeUnknownError("v3_final_source_unverified")


async def _save_generation_to_db(
    state: GenerationState,
    tenant_id: UUID,
    user_id: UUID,
    *, final_intent: dict[str, Any] | None = None,
) -> None:
    if final_intent is not None:
        try:
            await _save_generation_to_db_transaction(state, tenant_id, user_id, final_intent=final_intent)
        except BaseException as exc:
            raise ExtractionOutcomeUnknownError("v3_final_save_outcome_unknown") from exc
        return
    await _save_generation_to_db_transaction(state, tenant_id, user_id)


async def _prepare_fresh_v3_final_intent(state: GenerationState, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    """Freeze final output and durably fence a fresh owned QA-v3 save."""
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.final_save_contract import make_intent, output_digest
    from app.modules.ai.v3.final_save_owned_checkpoint import checkpoint_final_output
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, OWNED_POLICIES

    try:
        context = state.owned_v3_source_context
        current_delivery = delivery_id.get()
        if (tenant_id != QA_TENANT or state.source_analysis.get(KEY) not in OWNED_POLICIES
                or type(context) is not OwnedSourceContext or context.tenant_id != tenant_id
                or context.user_id != user_id or context.job_id != state.job_id
                or state.course_id is not None or not isinstance(current_delivery, str) or not current_delivery
                or not isinstance(state.owned_v3_route_fingerprint, str)):
            raise ValueError("v3_final_prepare_scope_invalid")
        _apply_assessment_omission_notices(state)
        documents = []
        for doc in context.corpus.documents:
            if not isinstance(doc.source_text, str):
                raise ValueError("v3_final_prepare_source_invalid")
            documents.append({"doc_id": doc.doc_id, "revision": doc.source_revision,
                              "text_sha256": hashlib.sha256(doc.source_text.encode("utf-8")).hexdigest()})
        digest = output_digest(structure=state.structure, content=state.content, assessment=state.assessment,
            source_document_ids=state.source_document_ids, source_strategy=state.source_strategy,
            source_combination_goal=state.source_combination_goal, source_analysis=state.source_analysis,
            source_review_required=state.server_source_review_required, reuse_reason=state.reuse_reason)
        intent = make_intent(tenant_id=str(tenant_id), user_id=str(user_id), job_id=state.job_id,
            delivery_id=current_delivery, route_policy=state.source_analysis[KEY], route_fingerprint=state.owned_v3_route_fingerprint,
            documents=documents, output_digest=digest)
        await checkpoint_final_output(journal=context.journal, context=context, state=state, intent=intent)
        return intent
    except ExtractionOutcomeUnknownError:
        raise
    except BaseException as exc:
        raise ExtractionOutcomeUnknownError("v3_final_prepare_unverified") from exc


async def _save_generation_to_db_transaction(
    state: GenerationState, tenant_id: UUID, user_id: UUID, *, final_intent: dict[str, Any] | None = None,
) -> None:
    """Save generated course structure, content, and assessments to DB."""
    _require_supported_question_export_ready(state.assessment)
    from sqlalchemy import delete, select, text

    from app.models.ai_job import AIJob
    from app.modules.courses.models import Course
    from app.modules.lessons.models import Lesson, Module
    from app.modules.quizzes.models import Question, Quiz, QuizChoice

    _apply_assessment_omission_notices(state)
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        await lock_owned_delivery(session, state.job_id, str(tenant_id), require_running=True)
        job = await session.scalar(
            select(AIJob)
            .where(AIJob.id == state.job_id, AIJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if not job:
            raise RuntimeError("Generation job does not exist in this tenant")
        await _verify_fresh_v3_final_source(session, job, state, tenant_id, user_id, final_intent=final_intent)
        final_snapshot = None
        if final_intent is not None:
            from app.modules.ai.v3.final_save_snapshot import make_snapshot, validate_snapshot

            if (state.course_id is not None or job.course_id is not None
                    or final_intent.get("tenant_id") != str(tenant_id)
                    or final_intent.get("user_id") != str(user_id)
                    or final_intent.get("job_id") != state.job_id
                    or final_intent.get("delivery_id") != delivery_id.get()
                    or final_intent.get("route_fingerprint") != state.owned_v3_route_fingerprint):
                raise ExtractionOutcomeUnknownError("v3_final_destination_unverified")
            expected_snapshot = make_snapshot(state, final_intent)
            checkpoint_key = "v3-final-snapshot:" + final_intent["intent_digest"]
            checkpoint_plan = {"schema": "v3-final-snapshot-v1", "intent_digest": final_intent["intent_digest"]}
            final_snapshot = await state.owned_v3_source_context.journal.read_owned_value_in_session(
                session, checkpoint_key, checkpoint_plan)
            if (final_snapshot != expected_snapshot or not validate_snapshot(
                    final_snapshot, expected_intent_digest=final_intent["intent_digest"])):
                raise ExtractionOutcomeUnknownError("v3_final_snapshot_unverified")
        if job.status == "cancelled":
            raise asyncio.CancelledError(f"Job {state.job_id} cancelled")
        if job.user_id is None or job.user_id != user_id:
            raise DirectSourceError("generation_source_job_mismatch")
        # A late concurrent delivery may have generated against the original
        # null course_id while another delivery saved the review-required draft.
        if _restore_saved_v2_outcome(state, job):
            await session.commit()
            return
        if job.status != "running":
            raise RuntimeError(f"Generation job is not active: {job.status}")
        _validate_generation_source_selection(job.params, state.source_document_ids)
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
                source_analysis=preserve_generated_source_uncertainty({}, (
                    {**state.source_analysis, "reuse_reason": state.reuse_reason}
                    if state.reuse_reason
                    else state.source_analysis
                ), source_review_required=state.server_source_review_required),
            )
            session.add(course)
            await session.flush()
        else:
            course = await session.scalar(
                select(Course).where(
                    Course.id == UUID(state.course_id),
                    Course.tenant_id == tenant_id,
                ).with_for_update().execution_options(populate_existing=True)
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
            cast(Any, course).source_analysis = preserve_generated_source_uncertainty(course.source_analysis, (
                {**state.source_analysis, "reuse_reason": state.reuse_reason}
                if state.reuse_reason
                else state.source_analysis
            ), source_review_required=state.server_source_review_required)
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
        if state.structure and state.assessment and state.assessment.assessments:
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
                    lesson_assess = assessment_by_position.get((mod_idx, les_idx))
                    assessment_question_count = 0
                    if lesson_assess is not None:
                        assessment_question_count = (
                            len(lesson_assess.mcq)
                            + len(lesson_assess.true_false)
                            + sum(len(mq.pairs) for mq in lesson_assess.matching)
                        )
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
                            content_les.content if hasattr(content_les, "content") else "",
                            assessment_question_count,
                        ),
                        order_index=les_idx,
                        ai_generated=True,
                        source_document_ids=actual_source_ids,
                        source_references=list(content_les.source_references),
                        source_validation_status="needs_review" if content_les.requires_source_review() else "verified",
                    )
                    session.add(lesson)
                    await session.flush()

                    # Create quiz from assessment
                    if state.assessment:
                        for saved_assessment in (lesson_assess,):
                            if saved_assessment is not None and saved_assessment.lesson_title == struct_les.title:
                                question_count = (
                                    len(saved_assessment.mcq)
                                    + len(saved_assessment.true_false)
                                    + sum(len(mq.pairs) for mq in saved_assessment.matching)
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
                                for mcq in saved_assessment.mcq:
                                    question = Question(
                                        quiz_id=quiz.id,
                                        text=mcq.question,
                                        type="MCQ",
                                        points=1,
                                        explanation=mcq.explanation,
                                        source_quote=mcq.source_quote or None,
                                        order_index=q_idx,
                                        pool_group=getattr(mcq, "pool_group", None),
                                    )
                                    session.add(question)
                                    await session.flush()

                                    correct_options = [option for option in mcq.options if option.is_correct]
                                    incorrect_options = [option for option in mcq.options if not option.is_correct]
                                    ordered_options = list(incorrect_options)
                                    if len(correct_options) == 1:
                                        correct_position = q_idx % len(mcq.options)
                                        ordered_options.insert(correct_position, correct_options[0])
                                    else:
                                        ordered_options = list(mcq.options)
                                    for c_idx, option in enumerate(ordered_options):
                                        choice = QuizChoice(
                                            question_id=question.id,
                                            text=option.text,
                                            is_correct=option.is_correct,
                                            order_index=c_idx,
                                        )
                                        session.add(choice)
                                    q_idx += 1

                                # True/False questions
                                for tf in saved_assessment.true_false:
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
                                for mq in saved_assessment.matching:
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
        state.message = _generation_completion_message(state.content)
        _apply_evidence_v2_completion_outcome(state)
        updated_at = datetime.now(timezone.utc)  # noqa: UP017 -- Python 3.10 runtime
        completed_at = None if state.status == "interrupted" else updated_at
        for field_name, value in (
            ("status", state.status),
            ("stage", state.stage),
            ("progress", state.progress),
            ("message", state.message),
            ("course_id", course.id),
            ("completed_at", completed_at),
            ("updated_at", updated_at),
        ):
            setattr(job, field_name, value)
        params = dict(getattr(job, "params", None) or {})
        completed_progress = (
            _completed_progress_detail(state.content)
            if state.content is not None
            else None
        )
        if completed_progress is not None:
            params["progress_detail"] = completed_progress
        else:
            params.pop("progress_detail", None)
        completion_result = _job_completion_result(state, course_id=str(course.id))
        if completion_result is not None:
            params["completion"] = completion_result
            job.result = {**(job.result or {}), **completion_result}  # type: ignore[assignment]
            job.errors = state.errors  # type: ignore[assignment]
            # SQLAlchemy's legacy JSON Column annotation lacks instance typing.
            cast(Any, course).source_analysis = preserve_generated_source_uncertainty(course.source_analysis, {
                **state.source_analysis,
                **({"reuse_reason": state.reuse_reason} if state.reuse_reason else {}),
            }, source_review_required=state.server_source_review_required)
        job.params = params  # type: ignore[assignment]
        if final_intent is not None:
            from app.modules.ai.v3.final_save_completed_reader import completed_receipt
            from app.modules.ai.v3.final_save_contract import RECEIPT_KEY, resolve_intent

            completed = resolve_intent(job.result, final_intent, course_id=str(course.id),
                                       output_digest=final_intent["output_digest"])
            completed[RECEIPT_KEY] = completed_receipt(final_intent, final_snapshot, str(course.id))
            job.result = completed
        await session.commit()
        state.course_id = str(course.id)
        logger.info(f"Saved generation results to DB for course {state.course_id}")

async def _check_cancelled_async(
    job_id: str,
    tenant_id: UUID | str | None = None,
) -> None:
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


def _validate_generation_source_selection(params: Any, documents: list[str]) -> None:
    """Require the exact ordered job selection, preserving duplicate multiplicity."""
    try:
        requested = [str(UUID(value)) for value in documents]
    except (ValueError, TypeError, AttributeError) as exc:
        raise DirectSourceError("generation_source_job_mismatch") from exc
    if not requested:
        raise DirectSourceError("generation_source_job_mismatch")
    stored = params.get("documents") if isinstance(params, dict) else None
    if not isinstance(stored, list):
        raise DirectSourceError("generation_source_job_mismatch")
    try:
        selected = [str(UUID(value)) for value in stored]
    except (ValueError, TypeError, AttributeError) as exc:
        raise DirectSourceError("generation_source_job_mismatch") from exc
    if selected != requested:
        raise DirectSourceError("generation_source_job_mismatch")


class GenerationJobOwnerMismatchError(DirectSourceError):
    """A delivery cannot mutate or refund a job owned by another user."""


class OwnedGenerationCancelledError(asyncio.CancelledError):
    """The tenant-scoped job was observed cancelled after owner validation."""


async def _check_generation_source_job(job_id: str, tenant_id: UUID, documents: list[str],
                                       user_id: UUID | None, expected_engine: str | None = None,
                                       expected_qa_marker: Any = None) -> None:
    """Check the live job selection; this is not an atomic source snapshot."""
    from sqlalchemy import text

    from app.core.db import async_session_factory
    from app.modules.ai.job_service import get_ai_job

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        job = await get_ai_job(session, job_id, tenant_id=str(tenant_id))
        if job is None:
            raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
        if user_id is None or job.user_id is None or job.user_id != user_id:
            raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
        if job.status == "cancelled":
            raise OwnedGenerationCancelledError(f"Job {job_id} cancelled")
        if job.status != "running":
            raise DirectSourceError("generation_source_job_mismatch")
        _validate_generation_source_selection(job.params, documents)
        if expected_engine is not None:
            params: dict[str, Any] = job.params if isinstance(job.params, dict) else {}
            analysis = params.get("source_analysis")
            stored_engine = analysis.get("generation_engine") if isinstance(analysis, dict) else None
            if stored_engine != expected_engine:
                raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
            if expected_engine == "evidence_v3":
                from app.modules.ai.v3.qa_luna_pending_policy import (
                    DIRECT_POLICY,
                    DIRECT_POLICY_V1,
                    DIRECT_POLICY_V2,
                    KEY,
                    MANAGED_POLICY,
                    POLICY,
                )
                if isinstance(analysis, dict) and KEY in analysis and analysis[KEY] not in (POLICY, DIRECT_POLICY, DIRECT_POLICY_V1, DIRECT_POLICY_V2, MANAGED_POLICY):
                    raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
                if (analysis.get(KEY) if isinstance(analysis, dict) else None) != expected_qa_marker:
                    raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")


async def _run_generation_pipeline_inner(
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
) -> GenerationState:
    """Generate a course exclusively through the evidence_v2 engine."""
    state = GenerationState(
        job_id=job_id,
        course_id=course_id,
        source_document_ids=list(documents),
        source_strategy=source_strategy,
        source_combination_goal=combination_goal.strip(),
        source_analysis=dict(source_analysis or {}),
        reuse_reason=reuse_reason,
    )
    reservation_required = course_id is None
    initial_identity_checked = False
    timeout_boundary = "initial_owner_check"

    try:
        # Before identity and selection are checked, this caller has no authority
        # to change a job or its reservation. A successful read is not a lease.
        try:
            from app.modules.ai.v3.qa_luna_pending_policy import (
                DIRECT_POLICY,
                DIRECT_POLICY_V1,
                DIRECT_POLICY_V2,
                MANAGED_POLICY,
            )
            from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_PENDING_KEY
            from app.modules.ai.v3.qa_luna_pending_policy import POLICY as QA_PENDING_POLICY

            if QA_PENDING_KEY in state.source_analysis and state.source_analysis[QA_PENDING_KEY] not in (QA_PENDING_POLICY, DIRECT_POLICY, DIRECT_POLICY_V1, DIRECT_POLICY_V2, MANAGED_POLICY):
                raise GenerationJobOwnerMismatchError("generation_source_job_mismatch")
            if not uses_current_generation_engine(state.source_analysis):
                raise DirectSourceError(RETIRED_GENERATION_ENGINE_CODE)
            if tenant_id is None:
                raise DirectSourceError("tenant_id_required")
            await _check_generation_source_job(job_id, tenant_id, documents, user_id,
                                               str(state.source_analysis.get("generation_engine", "")),
                                               state.source_analysis.get("qa_luna_pending_journal_policy"))
            initial_identity_checked = True
            if re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", str(job_id)):
                timeout_context.job_id.set(str(job_id))
        except asyncio.CancelledError:
            raise
        except SoftTimeLimitExceeded:
            raise
        except Exception as error:
            if isinstance(error, TimeoutError):
                timeout_context.emit(logger, timeout_boundary)
            state.status = "failed"
            state.stage = "failed"
            state.message = GENERATION_FAILURE_MESSAGE
            state.errors = [error.code if isinstance(error, DirectSourceError) else GENERATION_FAILURE_CODE]
            return state
        state.stage = "ingestion"
        state.progress = 5
        state.message = "Проверка исходных документов..."
        timeout_boundary = "job_state_db"
        restored = await _update_job_db(
            job_id,
            tenant_id=tenant_id,
            saved_v2_state=state,
            status="running",
            stage="ingestion",
            progress=5,
            message=state.message,
        )
        if restored is True:
            return state

        timeout_boundary = "source_owner_db"
        await _check_generation_source_job(job_id, tenant_id, documents, user_id,
                                               str(state.source_analysis.get("generation_engine", "")),
                                               state.source_analysis.get("qa_luna_pending_journal_policy"))
        timeout_boundary = "direct_source"
        corpus = await load_direct_source_corpus(
            documents,
            tenant_id=tenant_id,
            check_cancelled=lambda: _check_cancelled_async(job_id, tenant_id=tenant_id),
        )
        timeout_boundary = "source_owner_db"
        await _check_generation_source_job(job_id, tenant_id, documents, user_id,
                                               str(state.source_analysis.get("generation_engine", "")),
                                               state.source_analysis.get("qa_luna_pending_journal_policy"))
        timeout_boundary = "generation_execution"
        engine_name = str(state.source_analysis.get("generation_engine", ""))
        if engine_name in ("evidence_v3", "v3_cogen") or not engine_name:
            await _run_v3_generation(
                state,
                corpus,
                tenant_id=tenant_id,
                user_id=user_id,
                target_audience=target_audience,
                guidance=guidance,
                goals=goals,
                max_total_lessons=max_total_lessons,
            )
        else:
            await _run_evidence_v2_generation(
                state,
                corpus,
                tenant_id=tenant_id,
                target_audience=target_audience,
                guidance=guidance,
                goals=goals,
                max_total_lessons=max_total_lessons,
            )
        timeout_boundary = "post_generation_cancellation_check"
        await _check_cancelled_async(job_id, tenant_id=tenant_id)
        state.stage = "saving"
        state.progress = 98
        state.message = "Сохранение результатов..."
        timeout_boundary = "saving_progress_db"
        await _update_job_db(
            job_id,
            tenant_id=tenant_id,
            stage="saving",
            progress=98,
            message=state.message,
            progress_detail=None,
        )
        timeout_boundary = "assessment_export_validation"
        _require_supported_question_export_ready(state.assessment)
        if user_id:
            timeout_boundary = "save_generation_db"
            from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_PENDING_KEY
            from app.modules.ai.v3.qa_luna_pending_policy import OWNED_POLICIES

            if state.source_analysis.get(QA_PENDING_KEY) in OWNED_POLICIES:
                final_intent = await _prepare_fresh_v3_final_intent(state, tenant_id, user_id)
                await _save_generation_to_db(state, tenant_id, user_id, final_intent=final_intent)
            else:
                await _save_generation_to_db(state, tenant_id, user_id)
        else:
            assert state.content is not None
            _apply_assessment_omission_notices(state)
            state.status = "completed"
            state.stage = "completed"
            state.progress = 100
            state.message = _generation_completion_message(state.content)
            _apply_evidence_v2_completion_outcome(state)
            timeout_boundary = "completion_update_db"
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                status=state.status,
                stage=state.stage,
                progress=state.progress,
                message=state.message,
                course_id=UUID(state.course_id) if state.course_id else None,
                errors=state.errors,
                completed_at=(None if state.status == "interrupted" else datetime.now(UTC)),
                progress_detail=_completed_progress_detail(state.content),
                completion_result=_job_completion_result(state),
            )
        logger.info("Evidence V2 generation complete for job %s", job_id)
        return state
    except PreclaimYieldError as interruption:
        # This exception is raised strictly before a new generation claim. The
        # SQL update additionally fences delivery/status and rejects ANY pending
        # marker; it preserves params, completed checkpoints and the reservation.
        if not initial_identity_checked or tenant_id is None or delivery_id.get() is None:
            raise DeliveryOwnershipLostError("generation_preclaim_interruption_unowned") from None
        from app.modules.ai.job_service import interrupt_claimed_generation_execution
        from app.modules.ai.v3.reference_source_view import SourceReferenceReviewRequiredError
        source_review = isinstance(interruption, SourceReferenceReviewRequiredError)

        async with async_session_factory() as session:
            interrupted = await interrupt_claimed_generation_execution(
                session, job_id, str(tenant_id), delivery_id.get(),
                **({"reason": "source_reference_review_required"} if source_review else {}))
        if not interrupted:
            raise DeliveryOwnershipLostError("generation_preclaim_interruption_unverified") from None
        state.status = state.stage = "interrupted"
        state.message = ("Проверьте подтвержденные отсылки источника. Готовые части генерации сохранены."
                         if source_review else "Готовые этапы сохранены. Продолжите генерацию с оставшихся этапов.")
        state.errors = ["source_reference_review_required" if source_review else "generation_interrupted"]
    except ExtractionOutcomeUnknownError as error:
        from app.modules.ai.qa_luna_dev_route import QA_TENANT
        from app.modules.ai.v3.owned_source_context import OwnedSourceContext
        from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_PENDING_KEY
        from app.modules.ai.v3.qa_luna_pending_policy import OWNED_POLICIES

        context = state.owned_v3_source_context
        if (str(error) == "v3_final_save_outcome_unknown" and not isinstance(error.__cause__, asyncio.CancelledError)
                and tenant_id == QA_TENANT and isinstance(user_id, UUID)
                and state.source_analysis.get(QA_PENDING_KEY) in OWNED_POLICIES
                and type(context) is OwnedSourceContext and context.tenant_id == tenant_id
                and context.user_id == user_id and context.job_id == job_id):
            from app.modules.ai.v3.final_save_recovery import recover_completed_course_id

            try:
                recovered = await asyncio.wait_for(recover_completed_course_id(session_factory=async_session_factory,
                    tenant_id=tenant_id, authenticated_actor_id=user_id, job_id=UUID(job_id)), timeout=100)
            except Exception:
                recovered = None
            if recovered is not None:
                state.status = state.stage = "completed"
                state.progress = 100
                state.course_id = str(recovered)
                state.message = _generation_completion_message(state.content) if state.content else ""
                state.errors = []
                return state
        state.status = state.stage = "interrupted"
        state.message = "Результат этапа требует проверки."
        state.errors = ["generation_stage_outcome_unknown"]
        await _persist_pending_stage_hold(job_id, tenant_id, user_id,
                                          expected_qa_marker=state.source_analysis.get("qa_luna_pending_journal_policy"))
    except GenerationJobOwnerMismatchError as error:
        # A delivery without owner authority must not update or refund this job.
        state.status = "failed"
        state.stage = "failed"
        state.message = GENERATION_FAILURE_MESSAGE
        state.errors = [error.code]
    except AllProvidersFailedError:
        state.status = "interrupted"
        state.stage = "interrupted"
        state.message = GENERATION_PROVIDER_INTERRUPTED_MESSAGE
        state.errors = [GENERATION_PROVIDER_INTERRUPTED_CODE]
        try:
            await _update_job_db(
                job_id, tenant_id=tenant_id, status="interrupted", stage="interrupted",
                message=state.message, errors=state.errors, completed_at=None,
            )
        except ExtractionOutcomeUnknownError:
            state.message = "Результат этапа требует проверки."
            state.errors = ["generation_stage_outcome_unknown"]
            await _persist_pending_stage_hold(job_id, tenant_id, user_id,
                                              expected_qa_marker=state.source_analysis.get("qa_luna_pending_journal_policy"))
        logger.warning("Evidence V2 paused after provider exhaustion for job %s", job_id)
    except SoftTimeLimitExceeded:
        if not initial_identity_checked:
            raise
        state.status = "interrupted"
        state.stage = "interrupted"
        state.message = "Генерация приостановлена по лимиту времени. Продолжите задачу позднее."
        state.errors = ["generation_interrupted"]
        try:
            await _update_job_db(
                job_id, tenant_id=tenant_id, status="interrupted", stage="interrupted",
                message=state.message, errors=state.errors, completed_at=None,
            )
        except ExtractionOutcomeUnknownError:
            state.message = "Результат этапа требует проверки."
            state.errors = ["generation_stage_outcome_unknown"]
            await _persist_pending_stage_hold(job_id, tenant_id, user_id,
                                              expected_qa_marker=state.source_analysis.get("qa_luna_pending_journal_policy"))
        logger.warning("Evidence V2 interrupted for job %s", job_id)
    except asyncio.CancelledError as error:
        if not initial_identity_checked and not isinstance(error, OwnedGenerationCancelledError):
            raise
        state.status = "cancelled"
        state.stage = "cancelled"
        state.message = "Cancelled by user"
        try:
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                status="cancelled",
                stage="cancelled",
                message=state.message,
                completed_at=datetime.now(UTC),
                progress_detail=None,
            )
        except ExtractionOutcomeUnknownError:
            state.status = state.stage = "interrupted"
            state.message = "Результат этапа требует проверки."
            state.errors = ["generation_stage_outcome_unknown"]
            await _persist_pending_stage_hold(job_id, tenant_id, user_id,
                                              expected_qa_marker=state.source_analysis.get("qa_luna_pending_journal_policy"))
            return state
        except Exception:
            logger.exception("Could not persist cancelled generation job %s", job_id)
        if tenant_id and reservation_required:
            try:
                await _release_generation_reservation(job_id, tenant_id)
            except Exception:
                logger.exception(
                    "Could not refund cancelled generation reservation for job %s",
                    job_id,
                )
        logger.info("Evidence V2 cancelled for job %s", job_id)
    except DeliveryOwnershipLostError:
        raise
    except Exception as error:
        if isinstance(error, TimeoutError):
            timeout_context.emit(logger, timeout_boundary)
        state.status = "failed"
        state.stage = "failed"
        state.message = GENERATION_FAILURE_MESSAGE
        failure_code = (
            error.code if isinstance(error, DirectSourceError) else GENERATION_FAILURE_CODE
        )
        state.errors = [failure_code]
        try:
            await _update_job_db(
                job_id,
                tenant_id=tenant_id,
                status="failed",
                stage="failed",
                message=state.message,
                errors=state.errors,
                completed_at=datetime.now(UTC),
            )
        except ExtractionOutcomeUnknownError:
            state.status = state.stage = "interrupted"
            state.message = "Результат этапа требует проверки."
            state.errors = ["generation_stage_outcome_unknown"]
            await _persist_pending_stage_hold(job_id, tenant_id, user_id,
                                              expected_qa_marker=state.source_analysis.get("qa_luna_pending_journal_policy"))
            return state
        except Exception:
            logger.exception("Could not persist failed generation job %s", job_id)
        if tenant_id and reservation_required:
            try:
                await _release_generation_reservation(job_id, tenant_id)
            except Exception:
                logger.exception(
                    "Could not refund failed generation reservation for job %s",
                    job_id,
                )
        logger.error(
            "Evidence V2 failed for job %s error_type=%s",
            job_id,
            type(error).__name__,
        )
    return state


@functools.wraps(_run_generation_pipeline_inner)
async def run_generation_pipeline(*args: Any, **kwargs: Any) -> GenerationState:
    token = timeout_context.job_id.set(None)
    try:
        return await _run_generation_pipeline_inner(*args, **kwargs)
    finally:
        timeout_context.job_id.reset(token)
