"""Celery tasks for AI course generation."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from uuid import UUID

logger = logging.getLogger(__name__)


def _run_async[T](awaitable: Awaitable[T]) -> T:
    """Run one Celery coroutine without leaking pooled DB connections.

    Celery tasks are synchronous entrypoints. Each invocation gets its own
    event loop, so SQLAlchemy connections created in that loop must be disposed
    before the loop closes. Otherwise the next task can reuse a Future bound to
    the previous loop.
    """

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(awaitable)
    finally:
        try:
            from app.core.db import engine

            loop.run_until_complete(engine.dispose())
        except Exception:
            logger.exception("Could not dispose the async database engine")
        finally:
            asyncio.set_event_loop(None)
            loop.close()

try:
    from app.core.celery_app import celery_app
    from app.modules.ai.pipeline import run_generation_pipeline

    @celery_app.task(bind=True, name="ai.generate_course")
    def generate_course_task(
        self,
        job_id: str,
        documents: list[str],
        target_audience: str = "",
        num_modules: int = 3,
        language: str = "ru",
        goals: list[str] | None = None,
        course_hours: float | None = None,
        guidance: str | None = None,
        course_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        source_strategy: str = "single_topic",
        combination_goal: str = "",
        source_analysis: dict | None = None,
        reuse_reason: str | None = None,
    ):
        """Celery task to run the full generation pipeline."""
        logger.info(f"Starting generation task for job {job_id}")

        try:
            from app.core.db import async_session_factory
            from app.modules.ai.job_service import claim_generation_execution

            async def claim() -> bool:
                async with async_session_factory() as session:
                    return await claim_generation_execution(session, job_id, tenant_id)

            if not _run_async(claim()):
                logger.info("Skipping duplicate or terminal generation delivery for job %s", job_id)
                return {"job_id": job_id, "status": "skipped"}

            result = _run_async(
                run_generation_pipeline(
                    job_id=job_id,
                    documents=documents,
                    target_audience=target_audience,
                    num_modules=num_modules,
                    language=language,
                    goals=goals,
                    course_hours=course_hours,
                    guidance=guidance,
                    course_id=course_id,
                    tenant_id=UUID(tenant_id) if tenant_id else None,
                    user_id=UUID(user_id) if user_id else None,
                    source_strategy=source_strategy,
                    combination_goal=combination_goal,
                    source_analysis=source_analysis,
                    reuse_reason=reuse_reason,
                )
            )

            if result.status == "failed":
                # ``run_generation_pipeline`` owns durable diagnostics and
                # terminal state. Never replay provider work automatically.
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "message": result.message,
                    "progress": result.progress,
                }

            logger.info(f"Generation task complete for job {job_id}: {result.status}")
            return {
                "job_id": job_id,
                "status": result.status,
                "message": result.message,
                "progress": result.progress,
            }

        except Exception as e:
            logger.error(f"Generation task failed for job {job_id}: {e}")
            # The pipeline may already have called providers before an error.
            # Without durable stage artifacts, replaying it can duplicate cost
            # or drafts, so leave it terminal for explicit user recovery.
            from app.core.db import async_session_factory
            from app.modules.ai.job_service import fail_claimed_generation_execution

            async def fail_claimed() -> bool:
                async with async_session_factory() as session:
                    return await fail_claimed_generation_execution(session, job_id, str(e), tenant_id)

            _run_async(fail_claimed())
            return {"job_id": job_id, "status": "failed", "message": str(e)}

    @celery_app.task(bind=True, name="ai.regenerate_module", max_retries=2)
    def regenerate_module_task(
        self,
        job_id: str,
        module_id: str,
        guidance: str,
        language: str,
        tenant_id: str,
        user_id: str,
    ):
        """Run module regeneration in the durable worker queue."""
        from app.modules.ai.router import _regenerate_module_job

        try:
            return _run_async(
                _regenerate_module_job(
                    job_id=job_id,
                    module_id=UUID(module_id),
                    guidance=guidance,
                    language=language,
                    tenant_id=UUID(tenant_id),
                    user_id=UUID(user_id),
                )
            )
        except asyncio.CancelledError:
            return {"job_id": job_id, "status": "cancelled"}
        except Exception as exc:
            logger.error("Module regeneration failed for job %s: %s", job_id, exc)
            raise self.retry(exc=exc, countdown=60) from exc

    @celery_app.task(bind=True, name="ai.regenerate_lesson", max_retries=2)
    def regenerate_lesson_task(
        self,
        job_id: str,
        lesson_id: str,
        guidance: str,
        regenerate_quiz: bool,
        tenant_id: str,
        user_id: str,
    ):
        """Run lesson regeneration in the durable worker queue."""
        from app.modules.ai.router import _regenerate_lesson_job

        try:
            return _run_async(
                _regenerate_lesson_job(
                    job_id=job_id,
                    lesson_id=UUID(lesson_id),
                    guidance=guidance,
                    regenerate_quiz=regenerate_quiz,
                    tenant_id=UUID(tenant_id),
                    user_id=UUID(user_id),
                )
            )
        except asyncio.CancelledError:
            return {"job_id": job_id, "status": "cancelled"}
        except Exception as exc:
            logger.error("Lesson regeneration failed for job %s: %s", job_id, exc)
            raise self.retry(exc=exc, countdown=60) from exc

    @celery_app.task(name="ai.ingest_document")
    def ingest_document_task(file_path: str, doc_id: str | None = None, tenant_id: str | None = None):
        """Celery task to ingest a single document."""
        from app.modules.ai.ingestion import DocumentIngestion

        logger.info(f"Ingesting document: {file_path}")

        ingestion = DocumentIngestion()
        result = _run_async(
            ingestion.ingest_file(file_path, doc_id, tenant_id=tenant_id)
        )

        logger.info(f"Document ingested: {result['doc_id']} ({result['chunks']} chunks)")
        return result

    @celery_app.task(bind=True, name="documents.cleanup", max_retries=5)
    def document_cleanup_task(self, job_id: str, document_id: str, tenant_id: str):
        """Remove a tombstoned document and all of its persisted artifacts."""
        from app.modules.documents.cleanup import run_document_cleanup

        try:
            return _run_async(
                run_document_cleanup(
                    job_id=job_id,
                    document_id=UUID(document_id),
                    tenant_id=UUID(tenant_id),
                )
            )
        except Exception as exc:
            raise self.retry(
                exc=exc,
                countdown=min(60 * (self.request.retries + 1), 300),
            ) from exc

    @celery_app.task(bind=True, name="documents.reindex", max_retries=5)
    def document_reindex_task(
        self,
        job_id: str,
        document_id: str,
        tenant_id: str,
        revision: int,
    ):
        """Rebuild a document index from the persisted source blob."""
        from app.modules.documents.operations import run_document_reindex

        try:
            return _run_async(
                run_document_reindex(
                    job_id=job_id,
                    document_id=UUID(document_id),
                    tenant_id=UUID(tenant_id),
                    revision=revision,
                )
            )
        except Exception as exc:
            raise self.retry(
                exc=exc,
                countdown=min(60 * (self.request.retries + 1), 300),
            ) from exc

    @celery_app.task(bind=True, name="documents.hash_backfill", max_retries=3)
    def document_hash_backfill_task(self, job_id: str, tenant_id: str):
        """Populate missing document content hashes for one tenant."""
        from app.modules.documents.operations import run_document_hash_backfill

        try:
            return _run_async(
                run_document_hash_backfill(
                    job_id=job_id,
                    tenant_id=UUID(tenant_id),
                )
            )
        except Exception as exc:
            raise self.retry(
                exc=exc,
                countdown=min(60 * (self.request.retries + 1), 300),
            ) from exc

except Exception:
    # Redis/Celery not available — tasks won't run
    generate_course_task = None
    regenerate_module_task = None
    regenerate_lesson_task = None
    ingest_document_task = None
    document_cleanup_task = None
    document_reindex_task = None
    document_hash_backfill_task = None
