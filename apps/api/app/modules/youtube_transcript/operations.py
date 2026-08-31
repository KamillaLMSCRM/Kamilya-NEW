"""Durable YouTube transcript import into the ordinary document pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.core.storage import get_storage
from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.ai.job_service import create_ai_job
from app.modules.youtube_transcript.normalizer import TranscriptLimitError, normalize_transcript
from app.modules.youtube_transcript.provider import TranscriptAcquisitionError, TranscriptProvider
from app.modules.youtube_transcript.remote_caption_adapter import build_runtime_caption_provider
from app.modules.youtube_transcript.schemas import YouTubeImportRequest

logger = logging.getLogger(__name__)

_ANALYSIS_ARTIFACT_VERSION = 1
_ANALYSIS_ARTIFACT_TTL = timedelta(minutes=30)


class YouTubeAnalysisArtifactError(RuntimeError):
    """A referenced provisional transcript artifact cannot be trusted."""


def _artifact_key(tenant_id: UUID, job_id: str) -> str:
    return f"tenants/{tenant_id}/youtube-analysis/{job_id}.json"


def _serialize_analysis_artifact(
    *,
    tenant_id: UUID,
    analysis_job_id: str,
    normalized: Any,
    transcript: Any,
    expires_at: datetime,
) -> tuple[str, str, bytes, datetime]:
    artifact = {
        "version": _ANALYSIS_ARTIFACT_VERSION,
        "tenant_id": str(tenant_id),
        "analysis_job_id": analysis_job_id,
        "expires_at": expires_at.isoformat(),
        "video_id": transcript.video_id,
        "canonical_url": transcript.canonical_url,
        "language": transcript.language,
        "content_sha256": normalized.content_sha256,
        "document": {
            "title": normalized.title,
            "filename": normalized.filename,
            "content_type": normalized.content_type,
            "plain_text": normalized.plain_text,
            "source_revision": normalized.source_revision,
            "content_sha256": normalized.content_sha256,
            "provenance": normalized.provenance,
        },
    }
    payload = json.dumps(artifact, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return _artifact_key(tenant_id, analysis_job_id), digest, payload, expires_at


def _load_analysis_artifact(
    *,
    storage: Any,
    artifact_key: str,
    artifact_sha256: str,
    tenant_id: UUID,
    analysis_job_id: str,
    expected_video_id: str,
    expected_canonical_url: str,
    expected_preferred_languages: list[str],
    now: datetime | None = None,
) -> tuple[Any, str]:
    if artifact_key != _artifact_key(tenant_id, analysis_job_id):
        raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
    try:
        payload = storage.get_bytes(artifact_key)
        if not isinstance(payload, bytes) or hashlib.sha256(payload).hexdigest() != artifact_sha256:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        artifact = json.loads(payload.decode("utf-8"))
        expires_at = datetime.fromisoformat(str(artifact["expires_at"]))
        if expires_at.tzinfo is None:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        if (now or datetime.now(UTC)) >= expires_at:
            raise YouTubeAnalysisArtifactError("analysis_artifact_expired")
        if artifact["version"] != _ANALYSIS_ARTIFACT_VERSION:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        if artifact["tenant_id"] != str(tenant_id) or artifact["analysis_job_id"] != analysis_job_id:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        if artifact["video_id"] != expected_video_id or artifact["canonical_url"] != expected_canonical_url:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        document = artifact["document"]
        if artifact["language"] not in expected_preferred_languages or artifact["language"] != document["provenance"]["language"]:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        content_sha256 = hashlib.sha256(str(document["plain_text"]).encode("utf-8")).hexdigest()
        if content_sha256 != artifact["content_sha256"] or content_sha256 != document["content_sha256"]:
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        if document["source_revision"] != f"document:{content_sha256}":
            raise YouTubeAnalysisArtifactError("analysis_artifact_invalid")
        from app.modules.youtube_transcript.normalizer import NormalizedTranscriptSource

        normalized = NormalizedTranscriptSource(
            title=str(document["title"]),
            filename=str(document["filename"]),
            content_type=str(document["content_type"]),
            plain_text=str(document["plain_text"]),
            source_revision=str(document["source_revision"]),
            content_sha256=content_sha256,
            provenance=dict(document["provenance"]),
        )
        return normalized, str(artifact["language"])
    except YouTubeAnalysisArtifactError:
        raise
    except Exception as exc:
        raise YouTubeAnalysisArtifactError("analysis_artifact_invalid") from exc


def delete_expired_analysis_artifact(*, storage: Any, metadata: Any, tenant_id: UUID, analysis_job_id: str) -> None:
    if not isinstance(metadata, dict):
        return
    key = metadata.get("key")
    if key == _artifact_key(tenant_id, analysis_job_id):
        try:
            storage.delete_bytes(key)
        except Exception:
            logger.exception("Could not remove expired YouTube analysis artifact job_id=%s", analysis_job_id)


def _delete_consumed_analysis_artifact(*, storage: Any, artifact_key: str | None, job_id: str) -> None:
    if not artifact_key:
        return
    try:
        storage.delete_bytes(artifact_key)
    except Exception:
        logger.exception("Could not remove consumed YouTube analysis artifact job_id=%s", job_id)


def _preview_summary(text: str, *, limit: int = 320) -> str:
    compact = " ".join(text.split())
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", compact) if part.strip()]
    summary = " ".join(sentences[:2]) if sentences else compact
    if len(summary) <= limit:
        return summary
    clipped = summary[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped}…"


def _preview_format(*, duration_seconds: float | None, total_chars: int) -> str:
    if (duration_seconds is not None and duration_seconds <= 12 * 60) or total_chars <= 6000:
        return "brief"
    if (duration_seconds is not None and duration_seconds >= 45 * 60) or total_chars >= 30000:
        return "detailed"
    return "standard"


async def run_youtube_analysis(
    *,
    job_id: str,
    tenant_id: UUID,
    url: str,
    preferred_languages: list[str],
    provider: TranscriptProvider | None = None,
) -> dict[str, Any]:
    """Fetch and validate captions without creating a permanent Document."""
    settings = get_settings()
    ref = YouTubeImportRequest(url=url, preferred_languages=preferred_languages).validated_video_ref()
    provider = provider or build_runtime_caption_provider(settings)
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
        if not job:
            return {"job_id": job_id, "status": "missing"}
        job.status = "processing"
        job.stage = "fetching_transcript"
        job.progress = 20
        job.message = "Получаем и проверяем субтитры YouTube."
        job.started_at = job.started_at or datetime.now(UTC)
        await session.commit()
    try:
        transcript = await provider.get_transcript(ref, preferred_languages)
        normalized = normalize_transcript(
            transcript,
            max_video_duration_seconds=settings.YOUTUBE_MAX_VIDEO_DURATION_SECONDS,
            max_total_chars=settings.YOUTUBE_MAX_TOTAL_CHARS,
        )
    except TranscriptAcquisitionError as exc:
        return await _finish_failed(job_id, tenant_id, code=exc.code, message=exc.message_ru, retryable=exc.retryable)
    except TranscriptLimitError as exc:
        return await _finish_failed(job_id, tenant_id, code=exc.code, message=exc.message_ru, retryable=False)
    except Exception:
        logger.exception("YouTube transcript analysis failed job_id=%s", job_id)
        return await _finish_failed(
            job_id, tenant_id, code="provider_unavailable",
            message="Сервис получения субтитров недоступен. Повторите попытку позже.", retryable=True,
        )
    result: dict[str, Any] = {
        "video_id": ref.video_id,
        "canonical_url": ref.canonical_url,
        "preferred_languages": preferred_languages,
        "preview": {
            "title": normalized.title,
            "channel": transcript.channel,
            "summary": _preview_summary(transcript.to_plain_text()),
            "language": transcript.language,
            "is_auto_generated": transcript.is_auto_generated,
            "duration_seconds": transcript.duration_seconds,
            "recommended_course_format": _preview_format(
                duration_seconds=transcript.duration_seconds,
                total_chars=transcript.total_chars(),
            ),
            "quality_warnings": ["automatic_captions_review_required"] if transcript.is_auto_generated else [],
        },
    }
    expires_at = datetime.now(UTC) + _ANALYSIS_ARTIFACT_TTL
    artifact_key, artifact_sha256, artifact_payload, _ = _serialize_analysis_artifact(
        tenant_id=tenant_id,
        analysis_job_id=job_id,
        normalized=normalized,
        transcript=transcript,
        expires_at=expires_at,
    )
    try:
        get_storage().put_bytes(artifact_key, artifact_payload, content_type="application/json")
    except Exception:
        logger.exception("YouTube analysis artifact persistence failed job_id=%s", job_id)
        return await _finish_failed(
            job_id, tenant_id, code="analysis_artifact_persistence_failed",
            message="Не удалось сохранить результат анализа.", retryable=True,
        )
    result["analysis_artifact"] = {
        "key": artifact_key,
        "sha256": artifact_sha256,
        "expires_at": expires_at.isoformat(),
    }
    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
            if job and job.status != "cancelled":
                now = datetime.now(UTC)
                job.status = "completed"
                job.stage = "preview_ready"
                job.progress = 100
                job.message = "Видео проанализировано. Проверьте описание и продолжите."
                job.result = result
                job.updated_at = now
                job.completed_at = now
                await session.commit()
            else:
                _delete_consumed_analysis_artifact(storage=get_storage(), artifact_key=artifact_key, job_id=job_id)
    except Exception:
        _delete_consumed_analysis_artifact(storage=get_storage(), artifact_key=artifact_key, job_id=job_id)
        raise
    return result


async def _set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})


async def _finish_failed(job_id: str, tenant_id: UUID, *, code: str, message: str, retryable: bool) -> dict[str, Any]:
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
        if job and job.status not in {"completed", "cancelled"}:
            now = datetime.now(UTC)
            job.status = "failed"
            job.stage = "failed"
            job.progress = 100
            job.message = message[:1000]
            job.errors = [{"code": code, "retryable": retryable, "message_ru": message[:1000]}]
            job.updated_at = now
            job.completed_at = now
            await session.commit()
    return {"job_id": job_id, "status": "failed", "code": code}


async def _finish_completed(job_id: str, tenant_id: UUID, result: dict[str, Any]) -> dict[str, Any]:
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
        if job and job.status != "cancelled":
            now = datetime.now(UTC)
            job.status = "completed"
            job.stage = "completed"
            job.progress = 100
            job.message = "Субтитры сохранены. Документ индексируется."
            job.result = result
            job.updated_at = now
            job.completed_at = now
            await session.commit()
    return result


def _dispatch_index(job_id: str, document_id: UUID, tenant_id: UUID) -> None:
    from app.modules.ai.tasks import document_reindex_task

    if document_reindex_task is None:
        raise RuntimeError("document indexing worker unavailable")
    document_reindex_task.delay(job_id=job_id, document_id=str(document_id), tenant_id=str(tenant_id), revision=1)


async def run_youtube_import(
    *,
    job_id: str,
    tenant_id: UUID,
    user_id: UUID,
    url: str,
    preferred_languages: list[str],
    analysis_job_id: str | None = None,
    provider: TranscriptProvider | None = None,
    storage: Any | None = None,
    index_dispatcher: Callable[[str, UUID, UUID], None] | None = None,
) -> dict[str, Any]:
    """Fetch captions, persist an ordinary Document, and enqueue indexing."""

    settings = get_settings()
    request = YouTubeImportRequest(url=url, preferred_languages=preferred_languages)
    ref = request.validated_video_ref()
    provider = provider or build_runtime_caption_provider(settings)
    storage = storage or get_storage()
    index_dispatcher = index_dispatcher or _dispatch_index

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
        if not job:
            return {"job_id": job_id, "status": "missing"}
        if job.status in {"completed", "cancelled"}:
            return job.result or {"job_id": job_id, "status": job.status}
        job.status = "processing"
        job.stage = "fetching_transcript"
        job.progress = 10
        job.message = "Получаем субтитры YouTube."
        job.started_at = job.started_at or datetime.now(UTC)
        await session.commit()

    artifact_key: str | None = None
    if analysis_job_id:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            analysis = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == analysis_job_id, AIJob.tenant_id == tenant_id)))
        metadata = (analysis.result or {}).get("analysis_artifact") if analysis else None
        if not isinstance(metadata, dict) or not all(isinstance(metadata.get(key), str) for key in ("key", "sha256", "expires_at")):
            return await _finish_failed(job_id, tenant_id, code="analysis_artifact_invalid", message="Результат анализа недоступен для импорта.", retryable=False)
        artifact_key = str(metadata["key"])
        try:
            normalized, artifact_language = _load_analysis_artifact(
                storage=storage,
                artifact_key=artifact_key,
                artifact_sha256=str(metadata["sha256"]),
                tenant_id=tenant_id,
                analysis_job_id=analysis_job_id,
                expected_video_id=ref.video_id,
                expected_canonical_url=ref.canonical_url,
                expected_preferred_languages=preferred_languages,
            )
        except YouTubeAnalysisArtifactError as exc:
            return await _finish_failed(job_id, tenant_id, code=str(exc), message="Результат анализа недоступен для импорта.", retryable=False)
        transcript_language = artifact_language
    else:
        try:
            transcript = await provider.get_transcript(ref, preferred_languages)
            normalized = normalize_transcript(
                transcript,
                max_video_duration_seconds=settings.YOUTUBE_MAX_VIDEO_DURATION_SECONDS,
                max_total_chars=settings.YOUTUBE_MAX_TOTAL_CHARS,
            )
            transcript_language = transcript.language
        except TranscriptAcquisitionError as exc:
            return await _finish_failed(job_id, tenant_id, code=exc.code, message=exc.message_ru, retryable=exc.retryable)
        except TranscriptLimitError as exc:
            return await _finish_failed(job_id, tenant_id, code=exc.code, message=exc.message_ru, retryable=False)
        except Exception:
            logger.exception("YouTube transcript acquisition failed job_id=%s", job_id)
            return await _finish_failed(job_id, tenant_id, code="provider_unavailable", message="Сервис получения субтитров недоступен. Повторите попытку позже.", retryable=True)

    blob = normalized.plain_text.encode("utf-8")
    doc_id = uuid4()
    s3_key = f"tenants/{tenant_id}/documents/{doc_id}.md"
    blob_persisted = False
    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            existing = cast(Any, await session.scalar(
                select(Document).where(
                    Document.tenant_id == tenant_id,
                    Document.content_sha256 == normalized.content_sha256,
                    Document.lifecycle_status == "active",
                ).limit(1)
            ))
            job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
            if not job or job.status == "cancelled":
                return {"job_id": job_id, "status": "cancelled"}
            if existing:
                result: dict[str, Any] = {
                    "document_id": str(existing.id),
                    "indexing_job_id": None,
                    "idempotent_reuse": True,
                    "provenance": normalized.provenance,
                }
                now = datetime.now(UTC)
                job.status = "completed"
                job.stage = "completed"
                job.progress = 100
                job.message = "Документ уже был в библиотеке и использован повторно."
                job.result = result
                job.updated_at = now
                job.completed_at = now
                await session.commit()
                _delete_consumed_analysis_artifact(storage=storage, artifact_key=artifact_key, job_id=job_id)
                return result

            document = Document(
                id=doc_id,
                tenant_id=tenant_id,
                uploaded_by=user_id,
                title=normalized.title,
                filename=normalized.filename,
                content_type=normalized.content_type,
                file_url=ref.canonical_url,
                size=len(blob),
                s3_key=s3_key,
                description=(
                    f"Импортировано из YouTube. Язык: {transcript_language}. "
                    f"Автоматические субтитры: {'да' if normalized.provenance.get('is_auto_generated') else 'нет'}."
                ),
                category="general",
                embedding_status="pending",
                source_family_id=doc_id,
                version=1,
                content_sha256=normalized.content_sha256,
                lifecycle_status="active",
                index_status="processing",
                index_revision=1,
            )
            session.add(document)
            index_job = await create_ai_job(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                params={"action": "document_reindex", "document_id": str(doc_id), "revision": 1},
            )
            index_job_id = str(index_job.id)
            await session.flush()
            storage.put_bytes(s3_key, blob, content_type=normalized.content_type)
            blob_persisted = True
            result = {
                "document_id": str(doc_id),
                "indexing_job_id": index_job_id,
                "idempotent_reuse": False,
                "provenance": normalized.provenance,
            }
            job.status = "processing"
            job.stage = "indexing"
            job.progress = 90
            job.message = "Субтитры сохранены. Запускаем индексацию."
            job.result = result
            await session.commit()
    except IntegrityError:
        if blob_persisted:
            try:
                storage.delete_bytes(s3_key)
            except Exception:
                logger.exception("Could not remove orphaned YouTube import blob doc_id=%s", doc_id)
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            existing = cast(Any, await session.scalar(
                select(Document).where(
                    Document.tenant_id == tenant_id,
                    Document.content_sha256 == normalized.content_sha256,
                    Document.lifecycle_status == "active",
                ).limit(1)
            ))
            if existing:
                job = cast(Any, await session.scalar(select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()))
                result = {
                    "document_id": str(existing.id),
                    "indexing_job_id": None,
                    "idempotent_reuse": True,
                    "provenance": normalized.provenance,
                }
                if job:
                    now = datetime.now(UTC)
                    job.status = "completed"
                    job.stage = "completed"
                    job.progress = 100
                    job.message = "Документ уже был в библиотеке и использован повторно."
                    job.result = result
                    job.updated_at = now
                    job.completed_at = now
                    await session.commit()
                    _delete_consumed_analysis_artifact(storage=storage, artifact_key=artifact_key, job_id=job_id)
                return result
        raise
    except Exception:
        if blob_persisted:
            try:
                storage.delete_bytes(s3_key)
            except Exception:
                logger.exception("Could not remove failed YouTube import blob doc_id=%s", doc_id)
        logger.exception("YouTube document persistence failed job_id=%s", job_id)
        return await _finish_failed(
            job_id,
            tenant_id,
            code="document_persistence_failed",
            message="Не удалось сохранить субтитры в библиотеку документов.",
            retryable=True,
        )

    try:
        index_dispatcher(index_job_id, doc_id, tenant_id)
    except Exception:
        logger.exception("Could not enqueue YouTube document indexing job_id=%s", index_job_id)
        return await _finish_failed(
            job_id,
            tenant_id,
            code="index_enqueue_failed",
            message="Документ сохранён, но индексация не запустилась.",
            retryable=True,
        )
    completed = await _finish_completed(job_id, tenant_id, result)
    _delete_consumed_analysis_artifact(storage=storage, artifact_key=artifact_key, job_id=job_id)
    return completed
