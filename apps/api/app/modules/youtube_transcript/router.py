"""Tenant-safe asynchronous YouTube transcript import API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import get_db
from app.models.ai_job import AIJob
from app.models.users import User
from app.modules.ai.job_service import create_ai_job, get_ai_job, update_ai_job
from app.modules.youtube_transcript.schemas import (
    TranscriptProvenanceOut,
    YouTubeAnalysisAccepted,
    YouTubeAnalysisConfirmAccepted,
    YouTubeAnalysisConfirmRequest,
    YouTubeAnalysisStatusOut,
    YouTubeImportAccepted,
    YouTubeImportErrorOut,
    YouTubeImportRequest,
    YouTubeImportStatusOut,
    YouTubePreviewOut,
)

tenant_guard = cast(Callable[..., Any], require_tenant_user)()
methodologist_guard = cast(Callable[..., Any], require_role)("methodologist")
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(methodologist_guard)]

router = APIRouter(
    prefix="/youtube",
    tags=["youtube-transcript"],
    dependencies=[Depends(tenant_guard)],
)
logger = logging.getLogger(__name__)


def _feature_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "provider_unavailable",
            "retryable": True,
            "message_ru": "Импорт из YouTube временно недоступен.",
        },
    )


async def _dispatch_youtube_import(*, job_id: str, tenant_id: UUID, user_id: UUID, url: str, languages: list[str]) -> None:
    from app.modules.youtube_transcript.tasks import youtube_import_task

    kwargs = {
        "job_id": job_id,
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "url": url,
        "preferred_languages": languages,
    }
    if celery_app.conf.task_always_eager:
        from app.modules.youtube_transcript.operations import run_youtube_import

        await run_youtube_import(
            job_id=job_id,
            tenant_id=tenant_id,
            user_id=user_id,
            url=url,
            preferred_languages=languages,
        )
        return
    youtube_import_task.apply_async(task_id=job_id, kwargs=kwargs)


async def _dispatch_youtube_analysis(*, job_id: str, tenant_id: UUID, url: str, languages: list[str]) -> None:
    from app.modules.youtube_transcript.tasks import youtube_analyze_task

    kwargs = {"job_id": job_id, "tenant_id": str(tenant_id), "url": url, "preferred_languages": languages}
    if celery_app.conf.task_always_eager:
        from app.modules.youtube_transcript.operations import run_youtube_analysis

        await run_youtube_analysis(
            job_id=job_id,
            tenant_id=tenant_id,
            url=url,
            preferred_languages=languages,
        )
        return
    youtube_analyze_task.apply_async(task_id=job_id, kwargs=kwargs)


@router.post("/analyze", response_model=YouTubeAnalysisAccepted, status_code=status.HTTP_202_ACCEPTED)
async def analyze_youtube_transcript(
    request: YouTubeImportRequest,
    db: DatabaseSession,
    user: Methodologist,
) -> YouTubeAnalysisAccepted:
    if not get_settings().YOUTUBE_IMPORT_ENABLED:
        raise _feature_unavailable()
    ref = request.validated_video_ref()
    languages = list(dict.fromkeys(request.preferred_languages or ["ru"]))
    tenant_id = UUID(str(user.tenant_id))
    user_id = UUID(str(user.id))
    job = cast(Any, await create_ai_job(
        db, tenant_id=tenant_id, user_id=user_id,
        params={"action": "youtube_analysis", "video_id": ref.video_id, "canonical_url": ref.canonical_url, "preferred_languages": languages},
    ))
    await db.commit()
    try:
        await _dispatch_youtube_analysis(
            job_id=str(job.id),
            tenant_id=tenant_id,
            url=ref.canonical_url,
            languages=languages,
        )
    except Exception as exc:
        logger.exception("youtube_analysis_dispatch_failed job_id=%s", job.id)
        await update_ai_job(
            db, str(job.id), tenant_id=str(tenant_id), status="failed", stage="failed", progress=0,
            message="Фоновый обработчик анализа недоступен.",
            errors=[{"code": "analysis_enqueue_failed", "retryable": True}], completed_at=datetime.now(UTC),
        )
        await db.commit()
        raise _feature_unavailable() from exc
    return YouTubeAnalysisAccepted(
        job_id=str(job.id), status_url=f"/api/v1/youtube/analyses/{job.id}",
        video_id=ref.video_id, canonical_url=ref.canonical_url,
    )


@router.get("/analyses/{job_id}", response_model=YouTubeAnalysisStatusOut)
async def get_youtube_analysis(
    job_id: str,
    db: DatabaseSession,
    user: Methodologist,
) -> YouTubeAnalysisStatusOut:
    job = cast(Any, await get_ai_job(db, job_id, tenant_id=str(user.tenant_id)))
    if not job or (job.params or {}).get("action") != "youtube_analysis":
        raise HTTPException(status_code=404, detail="YouTube analysis not found")
    result: dict[str, Any] = job.result or {}
    raw_error = (job.errors or [None])[0]
    error = None
    if isinstance(raw_error, dict):
        error = YouTubeImportErrorOut(
            code=str(raw_error.get("code", "provider_unavailable")),
            retryable=bool(raw_error.get("retryable", False)),
            message_ru=str(raw_error.get("message_ru") or job.message or "Анализ не выполнен."),
        )
    public_status = "ready" if job.status == "completed" else "failed" if job.status in {"failed", "cancelled"} else "pending"
    return YouTubeAnalysisStatusOut(
        job_id=job.id, status=public_status, stage=job.stage, progress=job.progress,
        message=job.message or "", video_id=str((job.params or {}).get("video_id", "")),
        canonical_url=str((job.params or {}).get("canonical_url", "")),
        preview=YouTubePreviewOut.model_validate(result["preview"]) if result.get("preview") else None,
        error=error,
    )


@router.post("/analyses/{job_id}/confirm", response_model=YouTubeAnalysisConfirmAccepted, status_code=status.HTTP_202_ACCEPTED)
async def confirm_youtube_analysis(
    job_id: str,
    request: YouTubeAnalysisConfirmRequest,
    db: DatabaseSession,
    user: Methodologist,
) -> YouTubeAnalysisConfirmAccepted:
    tenant_id = UUID(str(user.tenant_id))
    user_id = UUID(str(user.id))
    analysis = cast(Any, await db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
    if not analysis or (analysis.params or {}).get("action") != "youtube_analysis":
        raise HTTPException(status_code=404, detail="YouTube analysis not found")
    if analysis.status != "completed" or not (analysis.result or {}).get("preview"):
        raise HTTPException(status_code=409, detail={"code": "analysis_not_ready"})
    if analysis.completed_at and analysis.completed_at < datetime.now(UTC) - timedelta(minutes=30):
        raise HTTPException(status_code=410, detail={"code": "analysis_expired"})
    if (analysis.result or {}).get("confirmation_job_id"):
        raise HTTPException(status_code=409, detail={"code": "analysis_already_confirmed"})
    result: dict[str, Any] = dict(analysis.result or {})
    canonical_url = str(result.get("canonical_url") or (analysis.params or {}).get("canonical_url"))
    languages = list(result.get("preferred_languages") or (analysis.params or {}).get("preferred_languages") or ["ru"])
    import_job = cast(Any, await create_ai_job(
        db, tenant_id=tenant_id, user_id=user_id,
        params={"action": "youtube_import", "video_id": (analysis.params or {}).get("video_id"), "canonical_url": canonical_url, "preferred_languages": languages, "analysis_job_id": analysis.id, "confirmation_action": request.action},
    ))
    result.update({"confirmation_job_id": import_job.id, "confirmation_action": request.action, "confirmed_at": datetime.now(UTC).isoformat()})
    analysis.result = result
    await db.commit()
    try:
        await _dispatch_youtube_import(
            job_id=str(import_job.id),
            tenant_id=tenant_id,
            user_id=user_id,
            url=canonical_url,
            languages=languages,
        )
    except Exception as exc:
        logger.exception("youtube_confirmation_dispatch_failed job_id=%s", import_job.id)
        await update_ai_job(
            db, str(import_job.id), tenant_id=str(tenant_id), status="failed", stage="failed", progress=0,
            message="Фоновый обработчик импорта недоступен.", errors=[{"code": "import_enqueue_failed", "retryable": True}], completed_at=datetime.now(UTC),
        )
        refreshed = cast(Any, await db.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
        if refreshed:
            restored = dict(refreshed.result or {})
            for key in ("confirmation_job_id", "confirmation_action", "confirmed_at"):
                restored.pop(key, None)
            refreshed.result = restored
        await db.commit()
        raise _feature_unavailable() from exc
    return YouTubeAnalysisConfirmAccepted(
        job_id=str(import_job.id), status_url=f"/api/v1/youtube/imports/{import_job.id}",
        video_id=str((analysis.params or {}).get("video_id", "")), canonical_url=canonical_url, action=request.action,
    )


@router.post("/import", response_model=YouTubeImportAccepted, status_code=status.HTTP_202_ACCEPTED)
async def import_youtube_transcript(
    request: YouTubeImportRequest,
    db: DatabaseSession,
    user: Methodologist,
) -> YouTubeImportAccepted:
    settings = get_settings()
    if not settings.YOUTUBE_IMPORT_ENABLED:
        raise _feature_unavailable()

    ref = request.validated_video_ref()
    languages = list(dict.fromkeys(request.preferred_languages or ["ru"]))
    tenant_id = UUID(str(user.tenant_id))
    user_id = UUID(str(user.id))
    job = cast(Any, await create_ai_job(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        params={
            "action": "youtube_import",
            "video_id": ref.video_id,
            "canonical_url": ref.canonical_url,
            "preferred_languages": languages,
        },
    ))
    await db.commit()
    try:
        await _dispatch_youtube_import(
            job_id=str(job.id),
            tenant_id=tenant_id,
            user_id=user_id,
            url=ref.canonical_url,
            languages=languages,
        )
    except Exception as exc:
        logger.exception("youtube_import_dispatch_failed job_id=%s", job.id)
        await update_ai_job(
            db,
            str(job.id),
            tenant_id=str(tenant_id),
            status="failed",
            stage="failed",
            progress=0,
            message="Фоновый обработчик импорта недоступен.",
            errors=[{"code": "import_enqueue_failed", "retryable": True}],
            completed_at=datetime.now(UTC),
        )
        await db.commit()
        raise _feature_unavailable() from exc

    return YouTubeImportAccepted(
        job_id=str(job.id),
        status_url=f"/api/v1/youtube/imports/{job.id}",
        video_id=ref.video_id,
        canonical_url=ref.canonical_url,
    )


@router.get("/imports/{job_id}", response_model=YouTubeImportStatusOut)
async def get_youtube_import(
    job_id: str,
    db: DatabaseSession,
    user: Methodologist,
) -> YouTubeImportStatusOut:
    job = cast(Any, await get_ai_job(db, job_id, tenant_id=str(user.tenant_id)))
    if not job or (job.params or {}).get("action") != "youtube_import":
        raise HTTPException(status_code=404, detail="YouTube import not found")

    params: dict[str, Any] = job.params or {}
    result: dict[str, Any] = job.result or {}
    raw_error = (job.errors or [None])[0]
    error = None
    if isinstance(raw_error, dict):
        error = YouTubeImportErrorOut(
            code=str(raw_error.get("code", "provider_unavailable")),
            retryable=bool(raw_error.get("retryable", False)),
            message_ru=str(raw_error.get("message_ru") or job.message or "Импорт не выполнен."),
        )
    provenance = result.get("provenance")
    public_status = (
        "ready"
        if job.status == "completed"
        else "failed"
        if job.status in {"failed", "cancelled"}
        else "pending"
    )
    return YouTubeImportStatusOut(
        job_id=job.id,
        status=public_status,
        stage=job.stage,
        progress=job.progress,
        message=job.message or "",
        video_id=str(params.get("video_id", "")),
        canonical_url=str(params.get("canonical_url", "")),
        document_id=result.get("document_id"),
        indexing_job_id=result.get("indexing_job_id"),
        idempotent_reuse=bool(result.get("idempotent_reuse", False)),
        provenance=TranscriptProvenanceOut.model_validate(provenance) if provenance else None,
        error=error,
    )


@router.get("/limits")
async def youtube_limits() -> dict[str, object]:
    from app.modules.youtube_transcript.provider import MAX_SEGMENTS, MIN_TOTAL_CHARS, SUPPORTED_LANGUAGES

    settings = get_settings()
    return {
        "enabled": settings.YOUTUBE_IMPORT_ENABLED,
        "max_video_duration_seconds": settings.YOUTUBE_MAX_VIDEO_DURATION_SECONDS,
        "max_total_chars": settings.YOUTUBE_MAX_TOTAL_CHARS,
        "min_total_chars": MIN_TOTAL_CHARS,
        "max_segments": MAX_SEGMENTS,
        "supported_languages": sorted(SUPPORTED_LANGUAGES),
        "max_languages_per_request": 5,
    }
