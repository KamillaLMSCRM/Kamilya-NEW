"""Celery entrypoint for YouTube transcript imports."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar
from uuid import UUID

from app.core.celery_app import celery_app

T = TypeVar("T")


def _run(coro: Coroutine[Any, Any, T]) -> T:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            from app.core.db import engine

            loop.run_until_complete(engine.dispose())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


@celery_app.task(name="youtube.import_transcript")  # type: ignore[untyped-decorator]
def youtube_import_task(job_id: str, tenant_id: str, user_id: str, url: str, preferred_languages: list[str], analysis_job_id: str | None = None) -> dict[str, Any]:
    from app.modules.youtube_transcript.operations import run_youtube_import

    return _run(
        run_youtube_import(
            job_id=job_id,
            tenant_id=UUID(tenant_id),
            user_id=UUID(user_id),
            url=url,
            preferred_languages=preferred_languages,
            analysis_job_id=analysis_job_id,
        )
    )


@celery_app.task(name="youtube.analyze_transcript")  # type: ignore[untyped-decorator]
def youtube_analyze_task(job_id: str, tenant_id: str, url: str, preferred_languages: list[str]) -> dict[str, Any]:
    from app.modules.youtube_transcript.operations import run_youtube_analysis

    return _run(
        run_youtube_analysis(
            job_id=job_id,
            tenant_id=UUID(tenant_id),
            url=url,
            preferred_languages=preferred_languages,
        )
    )
