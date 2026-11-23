import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.courses.video_practice import (
    KEY,
    UnsupportedPracticeProposalError,
    VideoClip,
    caption_windows,
    lesson_clip,
    propose_practice,
    public_course_metadata,
    read_proposal,
)
from app.modules.courses.video_practice_router import (
    PracticeChange,
    PracticeProposalRequest,
    generate_practice,
    read_practice,
    save_practice,
)
from app.modules.youtube_transcript.provider import TranscriptProviderError, TranscriptSegment
from app.modules.youtube_transcript.timed_subtitles import parse_timed_subtitles

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


@pytest.mark.parametrize("source", [
    f"1\n00:01:50,000 --> 00:02:10,000\n{EVIDENCE}\n",
    f"\ufeffWEBVTT\r\n\r\n01:50.000 --> 02:10.000 align:start\r\n<b>{EVIDENCE}</b>\r\n",
])
def test_reads_timed_subtitles_and_excludes_text_outside_clip(source):
    assert parse_timed_subtitles(source) == [TranscriptSegment(110, 130, EVIDENCE)]
    assert caption_windows(VideoClip(video_id=VIDEO_ID, start=131, end=150), parse_timed_subtitles(source)) == []
    with pytest.raises(ValueError):
        parse_timed_subtitles("00:00:08,000 --> 00:00:07,000\nInvalid")


@pytest.mark.asyncio
async def test_youtube_block_offers_attach_path_without_automatic_retry():
    lesson_id, course_id = uuid4(), uuid4()
    clip = lesson_clip(_lesson(lesson_id), lesson_id)
    course = SimpleNamespace(source_analysis={})
    author = SimpleNamespace(tenant_id=uuid4())
    db = AsyncMock()
    db.expire = MagicMock()
    provider = SimpleNamespace(get_transcript=AsyncMock(side_effect=TranscriptProviderError("provider_blocked")))
    model = AsyncMock(side_effect=lambda tenant, windows, revision: read_proposal(_wire(), windows, revision))
    scope = "app.modules.courses.video_practice_router."
    with patch(scope + "_clip_for_author", return_value=(course, clip)), \
         patch(scope + "get_settings", return_value=SimpleNamespace(YOUTUBE_IMPORT_ENABLED=True)), \
         patch(scope + "build_runtime_caption_provider", return_value=provider), \
         patch(scope + "_set_tenant_security_context"), patch(scope + "propose_practice", model):
        failure = await generate_practice(course_id, lesson_id, db, author)
        assert failure["error"] == "provider_blocked"
        model.assert_not_awaited()
        subtitles = PracticeProposalRequest(subtitles=f"1\n00:01:50,000 --> 00:02:10,000\n{EVIDENCE}")
        result = await generate_practice(course_id, lesson_id, db, author, subtitles)
        assert await generate_practice(course_id, lesson_id, db, author, subtitles) == result
    assert result["proposal"]["evidence"] == EVIDENCE
    assert result["approved"] is None
    assert result["proposal"]["draft"]["at"] == 130
    assert EVIDENCE not in course.source_analysis[KEY][str(lesson_id)]["caption_input"]
    provider.get_transcript.assert_awaited_once()
    model.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("review, expected_index", [
    ({"supported": True, "ru_answer": "Частоту", "kk_answer": "Жиілікті"}, 1),
    ({"supported": True, "ru_answer": "Частоту", "kk_answer": "Қысымды"}, None),
    ({"supported": True, "ru_answer": "Не предложенный ответ", "kk_answer": "Жиілікті"}, None),
    ({"supported": True}, None),
    ({"supported": False}, None),
])
async def test_exact_quote_alone_is_insufficient_for_bilingual_model_review(review, expected_index):
    client = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        SimpleNamespace(content=_wire()),
        SimpleNamespace(content=json.dumps(review)),
    ]))
    with patch("app.modules.ai.llm_client.ResilientLLMClient.from_settings_async",
               return_value=SimpleNamespace(for_provider=lambda name: client)):
        if expected_index is not None:
            result = await propose_practice(uuid4(), [(130, EVIDENCE)], "rev")
            assert result.evidence == EVIDENCE and result.draft.correct_index == expected_index
        else:
            with pytest.raises(UnsupportedPracticeProposalError):
                await propose_practice(uuid4(), [(130, EVIDENCE)], "rev")
    critic = json.loads(client.ainvoke.call_args.args[0][1]["content"])
    assert critic["captions"] == EVIDENCE and "correct_index" not in critic["draft"]
    assert client.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_mit_reynolds_replay_uses_the_reviewed_answer_instead_of_the_authors_wrong_key():
    evidence = "when you increase the velocity, the dye wavers and then breaks into turbulence."
    ru = ["Краситель колеблется, и поток становится турбулентным.", "Краситель движется ровнее.", "Скорость не влияет."]
    kk = ["Бояғыш тербеліп, ағыс турбулентті болады.", "Бояғыш бірқалыпты ағады.", "Жылдамдық әсер етпейді."]
    author = {"selection": {"window": 0, "evidence": evidence, "correct_index": 1,
                            "ru": {"question": "Что происходит при росте скорости?", "choices": ru, "explanation": ru[0]},
                            "kk": {"question": "Жылдамдық артқанда не болады?", "choices": kk, "explanation": kk[0]}}}
    reviewer = {"supported": True, "ru_answer": ru[0], "kk_answer": kk[0]}
    client = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        SimpleNamespace(content=json.dumps(author)), SimpleNamespace(content=json.dumps(reviewer)),
    ]))
    with patch("app.modules.ai.llm_client.ResilientLLMClient.from_settings_async",
               return_value=SimpleNamespace(for_provider=lambda name: client)):
        proposal = await propose_practice(uuid4(), [(144, evidence)], "mit-revision")
    assert proposal.draft.correct_index == 0
    assert proposal.draft.ru.choices[proposal.draft.correct_index] == ru[0]
    assert proposal.draft.kk.choices[proposal.draft.correct_index] == kk[0]
