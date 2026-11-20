import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.courses.video_practice import (
    KEY,
    VideoClip,
    caption_windows,
    lesson_clip,
    public_course_metadata,
    read_proposal,
)
from app.modules.courses.video_practice_router import PracticeChange, generate_practice, read_practice, save_practice
from app.modules.youtube_transcript.provider import TranscriptSegment

VIDEO_ID = "fzSDieqvIyk"
EVIDENCE = "Частотный преобразователь меняет частоту вращения двигателя."


def _wire(evidence=EVIDENCE):
    return json.dumps({"selection": {
        "window": 0,
        "evidence": evidence,
        "correct_index": 1,
        "ru": {"question": "Что регулирует преобразователь?", "choices": ["Давление", "Частоту", "Трубу"],
               "explanation": "Он меняет частоту вращения двигателя."},
        "kk": {"question": "Түрлендіргіш нені реттейді?", "choices": ["Қысымды", "Жиілікті", "Құбырды"],
               "explanation": "Ол қозғалтқыштың айналу жиілігін өзгертеді."},
    }})


def _lesson(lesson_id, start=100, end=180):
    return {"modules": [{"lessons": [{
        "id": str(lesson_id), "content_type": "text",
        "content": f"[Видео](https://www.youtube.com/watch?v={VIDEO_ID}&start={start}&end={end})",
    }]}]}


def test_actual_caption_end_and_exact_evidence_are_used():
    clip = VideoClip(video_id=VIDEO_ID, start=100, end=180)
    windows = caption_windows(clip, [
        TranscriptSegment(90, 105, "before"),
        TranscriptSegment(110, 121.2, EVIDENCE),
        TranscriptSegment(121.2, 130, "Так агрегат подстраивается под текущую потребность в подаче."),
        TranscriptSegment(172, 180, "after"),
    ])
    assert windows == [(130, EVIDENCE + " Так агрегат подстраивается под текущую потребность в подаче.")]
    result = read_proposal(_wire(), windows, "revision")
    assert result is not None
    assert result.draft.at == 130 and result.draft.correct_index == 1
    assert result.caption_revision == "revision" and result.evidence == EVIDENCE
    with pytest.raises(ValueError, match="evidence"):
        read_proposal(_wire("Неподтверждённая моделью цитата"), windows, "revision")
    assert read_proposal('{"selection":null}', windows, "revision") is None


def test_private_proposals_are_excluded_from_the_general_course_projection():
    assert public_course_metadata({KEY: {"secret": True}, "blueprint": "kept"}) == {"blueprint": "kept"}


@pytest.mark.asyncio
async def test_only_approved_question_for_the_assigned_clip_is_visible():
    lesson_id = uuid4()
    course = SimpleNamespace(delivery_type="native", source_analysis={KEY: {str(lesson_id): {
        "clip": VideoClip(video_id=VIDEO_ID, start=100, end=180).model_dump(),
        "proposal": {"evidence": EVIDENCE}, "approved": {"at": 130},
    }}})
    user = SimpleNamespace(role="student")
    with patch("app.modules.courses.video_practice_router.require_course_access", return_value=course), \
         patch("app.modules.courses.video_practice_router.learner_snapshot", return_value=_lesson(lesson_id)) as pinned:
        assert (await read_practice(uuid4(), lesson_id, AsyncMock(), user))["practice"] == {"at": 130}
        pinned.return_value = _lesson(lesson_id, end=179)
        assert await read_practice(uuid4(), lesson_id, AsyncMock(), user) == {"practice": None}


@pytest.mark.asyncio
async def test_editor_rejects_stale_revision_without_changing_course_metadata():
    lesson_id = uuid4()
    clip = lesson_clip(_lesson(lesson_id), lesson_id)
    course = SimpleNamespace(source_analysis={"other_course_metadata": True})
    db = AsyncMock()
    with patch("app.modules.courses.video_practice_router._clip_for_author", return_value=(course, clip)):
        with pytest.raises(HTTPException) as error:
            await save_practice(uuid4(), lesson_id, PracticeChange(clip=clip, revision=5, practice=None), db, None)
    assert error.value.status_code == 409
    db.commit.assert_not_called()
    assert course.source_analysis == {"other_course_metadata": True}


@pytest.mark.asyncio
async def test_model_proposal_is_reused_and_never_published_by_generation():
    lesson_id = uuid4()
    course_id = uuid4()
    clip = lesson_clip(_lesson(lesson_id), lesson_id)
    course = SimpleNamespace(source_analysis={})
    user = SimpleNamespace(role="methodologist", tenant_id=uuid4())
    db = AsyncMock()
    db.expire = MagicMock()
    captions = SimpleNamespace(video_id=VIDEO_ID, segments=[
        TranscriptSegment(110, 130, EVIDENCE + " Так агрегат подстраивается под текущую потребность в подаче."),
    ], compute_content_hash=lambda: "revision")
    provider = SimpleNamespace(get_transcript=AsyncMock(return_value=captions))
    model = AsyncMock(side_effect=lambda tenant, windows, revision: read_proposal(_wire(), windows, revision))
    settings = SimpleNamespace(YOUTUBE_IMPORT_ENABLED=True, YOUTUBE_MAX_VIDEO_DURATION_SECONDS=3600,
                               YOUTUBE_MAX_TOTAL_CHARS=10000)
    root = "app.modules.courses.video_practice_router."
    with patch(root + "_clip_for_author", return_value=(course, clip)), \
         patch(root + "get_settings", return_value=settings), \
         patch(root + "build_runtime_caption_provider", return_value=provider), \
         patch(root + "validate_transcript"), patch(root + "propose_practice", model), \
         patch(root + "_set_tenant_security_context"):
        first = await generate_practice(course_id, lesson_id, db, user)
        second = await generate_practice(course_id, lesson_id, db, user)
    assert first == second
    assert first["proposal"]["draft"]["at"] == 130
    assert first["approved"] is None
    assert model.await_count == 1
    assert provider.get_transcript.await_count == 1
