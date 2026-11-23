"""Timed practice lives beside the lesson release and never writes learner results."""

from hashlib import sha256
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, get_current_user, require_role
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models.courses import Course
from app.models.users import User
from app.modules.courses.access import require_course_access
from app.modules.courses.localization_router import _author_course
from app.modules.courses.localizations import author_snapshot, learner_snapshot
from app.modules.courses.video_practice import (
    KEY,
    PROPOSAL_VERSION,
    PracticeDraft,
    UnsupportedPracticeProposalError,
    VideoClip,
    caption_windows,
    lesson_clip,
    practice_record,
    propose_practice,
    stored_record,
)
from app.modules.youtube_transcript.provider import (
    MAX_TOTAL_CHARS,
    TranscriptAcquisitionError,
    TranscriptResult,
    validate_transcript,
)
from app.modules.youtube_transcript.remote_caption_adapter import build_runtime_caption_provider
from app.modules.youtube_transcript.timed_subtitles import parse_timed_subtitles
from app.modules.youtube_transcript.url_resolver import extract_video_id

router = APIRouter(prefix="/courses/{course_id}/lessons/{lesson_id}/video-practice", tags=["video practice"])
Db = Annotated[AsyncSession, Depends(get_db)]
Author = Annotated[User, Depends(require_role("superadmin", "methodologist"))]
CurrentUser = Annotated[User, Depends(get_current_user)]


class PracticeChange(BaseModel):
    clip: VideoClip
    revision: int = Field(ge=0)
    practice: PracticeDraft | None


class PracticeProposalRequest(BaseModel):
    subtitles: str = Field(min_length=1, max_length=MAX_TOTAL_CHARS)


def author_state(clip: VideoClip | None, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "clip": clip,
        "approved": record.get("approved"),
        "proposal": record.get("proposal"),
        "pending": bool(record.get("pending")),
        "error": record.get("error"),
        "revision": record.get("revision", 0),
    }


def update_record(course: Course, lesson_id: UUID, record: dict[str, Any]) -> None:
    metadata = dict(cast(dict[str, Any], course.source_analysis or {}))
    metadata[KEY] = {**(metadata.get(KEY) or {}), str(lesson_id): record}
    cast(Any, course).source_analysis = metadata


def _record_for(course: Course, lesson_id: UUID, clip: VideoClip | None) -> dict[str, Any]:
    return stored_record(cast(dict[str, Any], course.source_analysis or {}), lesson_id, clip) if clip else {}


async def _clip_for_author(
    db: Db, course_id: UUID, lesson_id: UUID, author: User, *, lock: bool = False,
) -> tuple[Course, VideoClip | None]:
    course = await _author_course(db, course_id, author, locked=lock)
    return course, lesson_clip(await author_snapshot(db, course), lesson_id)


@router.get("")
async def read_practice(course_id: UUID, lesson_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    course = await require_course_access(db, course_id, user)
    if course.delivery_type != "native":
        return {"practice": None}
    snapshot = await learner_snapshot(db, course, user) if user.role == "student" else await author_snapshot(db, course)
    clip = lesson_clip(snapshot, lesson_id)
    record = _record_for(course, lesson_id, clip)
    return {"practice": record.get("approved"), "clip": clip} if record.get("approved") else {"practice": None}


@router.get("/editor")
async def practice_editor(course_id: UUID, lesson_id: UUID, db: Db, author: Author) -> dict[str, Any]:
    course, clip = await _clip_for_author(db, course_id, lesson_id, author)
    return author_state(clip, _record_for(course, lesson_id, clip))


async def _practice_transcript(clip: VideoClip, settings: Settings) -> TranscriptResult:
    ref = extract_video_id(f"https://www.youtube.com/watch?v={clip.video_id}")
    transcript = await build_runtime_caption_provider(settings).get_transcript(ref, ["ru", "kk", "en"])
    validate_transcript(
        transcript, max_video_duration_seconds=settings.YOUTUBE_MAX_VIDEO_DURATION_SECONDS,
        max_total_chars=settings.YOUTUBE_MAX_TOTAL_CHARS,
    )
    if transcript.video_id != clip.video_id:
        raise ValueError("Caption identity mismatch")
    return transcript


@router.get("/editor/captions")
async def check_practice_captions(course_id: UUID, lesson_id: UUID, db: Db, author: Author) -> dict[str, Any]:
    _, clip = await _clip_for_author(db, course_id, lesson_id, author)
    if not clip:
        raise HTTPException(422, detail="video_practice_timed_clip_required")
    settings = get_settings()
    if not settings.YOUTUBE_IMPORT_ENABLED:
        return {"available": False, "error": "provider_unavailable"}
    await db.rollback()
    try:
        transcript = await _practice_transcript(clip, settings)
    except TranscriptAcquisitionError as failure:
        return {"available": False, "error": failure.code}
    except (RuntimeError, ValueError):
        return {"available": False, "error": "provider_unavailable"}
    if not caption_windows(clip, transcript.segments):
        return {"available": False, "error": "no_caption_evidence"}
    return {"available": True, "error": None}


@router.put("/editor")
async def save_practice(
    course_id: UUID, lesson_id: UUID, payload: PracticeChange, db: Db, author: Author,
) -> dict[str, Any]:
    course, clip = await _clip_for_author(db, course_id, lesson_id, author, lock=True)
    if not clip or clip != payload.clip:
        raise HTTPException(409, detail="video_practice_clip_changed")
    prior = _record_for(course, lesson_id, clip)
    if prior.get("revision", 0) != payload.revision or prior.get("pending"):
        raise HTTPException(409, detail="video_practice_revision_changed")
    if payload.practice and not clip.start < payload.practice.at < clip.end:
        raise HTTPException(422, detail="video_practice_outside_clip")
    record = practice_record(
        clip, prior, approved=payload.practice.model_dump(mode="json") if payload.practice else None,
    )
    update_record(course, lesson_id, record)
    await db.commit()
    return author_state(clip, record)


@router.post("/editor/propose")
async def generate_practice(
    course_id: UUID, lesson_id: UUID, db: Db, author: Author,
    payload: PracticeProposalRequest | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    course, clip = await _clip_for_author(db, course_id, lesson_id, author, lock=True)
    if not clip:
        raise HTTPException(422, detail="video_practice_timed_clip_required")
    previous = _record_for(course, lesson_id, clip)
    caption_input = sha256(payload.subtitles.encode()).hexdigest() if payload else None
    if previous.get("pending") or (
        previous.get("proposal") and previous.get("caption_input") == caption_input
        and previous.get("proposal_version") == PROPOSAL_VERSION
    ):
        return author_state(clip, previous)
    tenant_id = cast(UUID, author.tenant_id)
    if payload:
        try:
            segments = parse_timed_subtitles(payload.subtitles)
        except ValueError as invalid_subtitles:
            raise HTTPException(422, detail="captions_invalid") from invalid_subtitles
    if not payload and not settings.YOUTUBE_IMPORT_ENABLED:
        raise HTTPException(503, detail="provider_unavailable")
    record = practice_record(
        clip, previous, pending=True, error=None, caption_input=caption_input, proposal_version=PROPOSAL_VERSION,
    )
    update_record(course, lesson_id, record)
    await db.commit()

    proposal = None
    error = None
    pending = False
    try:
        if payload:
            revision = sha256(f"{clip.video_id}:{caption_input}".encode()).hexdigest()
        else:
            transcript = await _practice_transcript(clip, settings)
            segments, revision = transcript.segments, transcript.compute_content_hash()
    except TranscriptAcquisitionError as failure:
        error = failure.code
    except (RuntimeError, ValueError):
        error = "provider_unavailable"
    else:
        windows = caption_windows(clip, segments)
        if not windows:
            error = "no_caption_evidence"
        else:
            try:
                proposal = await propose_practice(tenant_id, windows, revision)
                if proposal is None:
                    error = "no_caption_evidence"
            except UnsupportedPracticeProposalError:
                error = "proposal_not_grounded"
            except ValueError:
                error = "invalid_proposal"
            except Exception:
                error = "outcome_unknown"
                pending = True

    await _set_tenant_security_context(db, str(tenant_id))
    db.expire(course)
    current, current_clip = await _clip_for_author(db, course_id, lesson_id, author, lock=True)
    if current_clip != clip or _record_for(current, lesson_id, clip) != record:
        raise HTTPException(409, detail="video_practice_revision_changed")
    finished = practice_record(
        clip, record, pending=pending, proposal=proposal.model_dump(mode="json") if proposal else None, error=error,
    )
    update_record(current, lesson_id, finished)
    await db.commit()
    return author_state(clip, finished)
