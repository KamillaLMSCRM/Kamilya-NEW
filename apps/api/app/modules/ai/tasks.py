"""Celery tasks for AI course generation."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from app.core.celery_app import celery_app
    from app.modules.ai.pipeline import run_generation_pipeline

    @celery_app.task(bind=True, name="ai.generate_course", max_retries=2)
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
    ):
        """Celery task to run the full generation pipeline."""
        logger.info(f"Starting generation task for job {job_id}")

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            result = loop.run_until_complete(
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
                )
            )

            loop.close()

            logger.info(f"Generation task complete for job {job_id}: {result.status}")
            return {
                "job_id": job_id,
                "status": result.status,
                "message": result.message,
                "progress": result.progress,
            }

        except Exception as e:
            logger.error(f"Generation task failed for job {job_id}: {e}")
            self.retry(exc=e, countdown=60)

    @celery_app.task(name="ai.ingest_document")
    def ingest_document_task(file_path: str, doc_id: str | None = None):
        """Celery task to ingest a single document."""
        from app.modules.ai.ingestion import DocumentIngestion

        logger.info(f"Ingesting document: {file_path}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        ingestion = DocumentIngestion()
        result = loop.run_until_complete(ingestion.ingest_file(file_path, doc_id))

        loop.close()

        logger.info(f"Document ingested: {result['doc_id']} ({result['chunks']} chunks)")
        return result

except Exception:
    # Redis/Celery not available — tasks won't run
    generate_course_task = None
    ingest_document_task = None
