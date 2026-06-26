"""Tests for quiz AI draft generation — prompt + JSON parsing.

We split these into pure-function tests so we don't need to mock the
LLM client. The only path we mock is `generate_quiz_draft` itself when
testing higher-level behaviour. See test_quiz_ai_endpoint.py for the
router integration tests.
"""
import json

import pytest

from app.modules.quizzes.ai import (
    _build_generate_prompt,
    _extract_json_object,
    _normalize_draft,
    _normalize_question,
)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_build_prompt_includes_lesson_title_and_content():
    sys, user = _build_generate_prompt(
        lesson_title="Охрана труда",
        lesson_content="Работодатель обязан обеспечить безопасные условия.",
        num_questions=5,
        difficulty="medium",
        language="ru",
        guidance=None,
    )
    assert "Охрана труда" in user
    assert "Работодатель обязан" in user
    assert "5" in user
    assert "medium" in user
    # System prompt locks JSON output.
    assert "JSON" in sys
    assert "is_correct" in sys
    assert "explanation" in sys


def test_build_prompt_truncates_long_content():
    long = "x" * 50_000
    _, user = _build_generate_prompt(
        lesson_title="T",
        lesson_content=long,
        num_questions=8,
        difficulty="easy",
        language="ru",
        guidance=None,
    )
    # Should be cut to 6000 chars + truncation marker
    assert "truncated" in user.lower() or "…" in user
    assert len(user) < 15_000


def test_build_prompt_appends_guidance_when_provided():
    _, user = _build_generate_prompt(
        lesson_title="T",
        lesson_content="C",
        num_questions=5,
        difficulty="hard",
        language="ru",
        guidance="сфокусируйся на штрафах",
    )
    assert "штрафах" in user
    assert "пожелания методолога" in user


# ---------------------------------------------------------------------------
# JSON extraction — the failure-prone bit
# ---------------------------------------------------------------------------


def test_extract_clean_json():
    raw = '{"title": "x", "questions": []}'
    out = _extract_json_object(raw)
    assert out["title"] == "x"


def test_extract_json_in_code_fence():
    raw = "Вот ваш тест:\n```json\n{\"title\": \"x\", \"questions\": []}\n```\nУдачи!"
    out = _extract_json_object(raw)
    assert out["title"] == "x"


def test_extract_json_with_trailing_garbage():
    # Trailing prose after the JSON object — greedy match picks up
    # the prose, json.loads fails, the rfind('}') fallback recovers.
    raw = '{"title": "x", "questions": []}\nВот ваш тест!'
    out = _extract_json_object(raw)
    assert out["title"] == "x"


def test_extract_empty_reply_raises():
    with pytest.raises(ValueError):
        _extract_json_object("")


def test_extract_no_json_raises():
    with pytest.raises(ValueError):
        _extract_json_object("Sorry, I cannot help with that.")


def test_extract_invalid_json_raises():
    with pytest.raises(ValueError):
        _extract_json_object("{not valid json}")


# ---------------------------------------------------------------------------
# Question normalization — keeps the draft usable even if model is sloppy
# ---------------------------------------------------------------------------


def test_normalize_well_formed_question():
    q = {
        "text": "Какой штраф за отсутствие СИЗ?",
        "points": 1,
        "explanation": "По ст. 54 ТК РК",
        "choices": [
            {"text": "100 МРП", "is_correct": True},
            {"text": "50 МРП", "is_correct": False},
            {"text": "200 МРП", "is_correct": False},
            {"text": "Без штрафа", "is_correct": False},
        ],
    }
    out = _normalize_question(q, 0)
    assert out is not None
    assert out["text"].startswith("Какой штраф")
    assert len(out["choices"]) == 4
    assert sum(1 for c in out["choices"] if c["is_correct"]) == 1
    assert out["order_index"] == 0


def test_normalize_question_without_correct_choice_marks_first():
    q = {
        "text": "Q",
        "choices": [
            {"text": "a", "is_correct": False},
            {"text": "b", "is_correct": False},
        ],
    }
    out = _normalize_question(q, 0)
    assert out is not None
    assert out["choices"][0]["is_correct"] is True
    assert out["choices"][1]["is_correct"] is False


def test_normalize_question_with_multiple_correct_keeps_only_first():
    q = {
        "text": "Q",
        "choices": [
            {"text": "a", "is_correct": True},
            {"text": "b", "is_correct": True},
            {"text": "c", "is_correct": True},
        ],
    }
    out = _normalize_question(q, 0)
    assert out is not None
    correct = [c for c in out["choices"] if c["is_correct"]]
    assert len(correct) == 1


def test_normalize_question_with_no_choices_returns_none():
    q = {"text": "Q", "choices": []}
    assert _normalize_question(q, 0) is None


def test_normalize_question_with_empty_text_returns_none():
    q = {"text": "   ", "choices": [{"text": "a", "is_correct": True}]}
    assert _normalize_question(q, 0) is None


def test_normalize_question_strips_garbage_choices():
    q = {
        "text": "Q",
        "choices": [
            {"text": "valid", "is_correct": True},
            {"text": "", "is_correct": False},  # blank
            {"text": "another valid", "is_correct": False},
        ],
    }
    out = _normalize_question(q, 0)
    assert out is not None
    assert len(out["choices"]) == 2


# ---------------------------------------------------------------------------
# Full draft normalization
# ---------------------------------------------------------------------------


def test_normalize_draft_clamps_to_num_questions():
    payload = {
        "title": "Quiz: T",
        "pass_score": 80,
        "questions": [
            {
                "text": f"Q{i}",
                "choices": [{"text": "ok", "is_correct": True}, {"text": "no", "is_correct": False}],
            }
            for i in range(20)
        ],
    }
    out = _normalize_draft(payload, num_questions=5)
    assert len(out["questions"]) == 5
    assert out["suggested_title"] == "Quiz: T"
    assert out["suggested_pass_score"] == 80


def test_normalize_draft_clamps_pass_score_to_range():
    for bad in [10, 30, 100, 150]:
        payload = {
            "title": "T",
            "pass_score": bad,
            "questions": [],
        }
        out = _normalize_draft(payload, num_questions=3)
        assert 50 <= out["suggested_pass_score"] <= 95


def test_normalize_draft_truncates_long_title():
    payload = {
        "title": "x" * 200,
        "pass_score": 80,
        "questions": [],
    }
    out = _normalize_draft(payload, num_questions=3)
    assert len(out["suggested_title"]) <= 80


def test_normalize_draft_handles_missing_title():
    payload = {"pass_score": 80, "questions": []}
    out = _normalize_draft(payload, num_questions=3)
    # Falls back to a stable default rather than raising — UI can edit it.
    assert out["suggested_title"] != ""


def test_normalize_draft_drops_unusable_questions():
    payload = {
        "title": "T",
        "pass_score": 80,
        "questions": [
            {"text": "good", "choices": [{"text": "a", "is_correct": True}, {"text": "b", "is_correct": False}]},
            {"text": "", "choices": []},  # unusable
            {"text": "no choices at all", "choices": []},  # unusable
            {"text": "also good", "choices": [{"text": "x", "is_correct": True}, {"text": "y", "is_correct": False}]},
        ],
    }
    out = _normalize_draft(payload, num_questions=10)
    # 2 questions survive, indices are re-assigned 0..N-1
    assert len(out["questions"]) == 2
    assert [q["order_index"] for q in out["questions"]] == [0, 1]