"""Reviewer Agent tests — heuristic review, outline review."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.ai.reviewer import ReviewerAgent


def test_heuristic_review_long_content():
    agent = ReviewerAgent(llm_client=None)
    long_content = "# Введение\n\nКратко о Python\n" + "Весь текст " * 200
    meta = {"title": "Введение в Python"}
    result = agent._heuristic_review(long_content, meta)
    assert result["quality_score"] >= 8.0
    assert len(long_content.split()) > 100


def test_heuristic_review_short_content():
    agent = ReviewerAgent(llm_client=None)
    meta = {"title": "Короткая тема"}
    result = agent._heuristic_review("Коротко", meta)
    assert result["quality_score"] < 5.0
    assert len(result["issues"]) > 0


def test_heuristic_review_with_heading():
    agent = ReviewerAgent(llm_client=None)
    content = "# Заголовок\n\nДлинный текст повторение " * 100
    meta = {"title": "Тема"}
    result = agent._heuristic_review(content, meta)
    heading_suggestions = [s for s in result["suggestions"] if "heading" in s.lower()]
    assert len(heading_suggestions) == 0


def test_heuristic_review_missing_introduction():
    agent = ReviewerAgent(llm_client=None)
    content = "Просто текст без всяких введений.\n" * 50
    meta = {}
    result = agent._heuristic_review(content, meta)
    intro_suggestions = [s for s in result["suggestions"] if "introduction" in s.lower() or "введение" in s.lower()]
    assert len(intro_suggestions) > 0


def test_review_course_outline_valid():
    """Test that valid outline passes checks."""
    agent = ReviewerAgent(llm_client=None)
    content = "# Курс"
    meta = {"title": "Python", "language": "ru"}
    result = agent._heuristic_review(content, meta)
    assert "quality_score" in result


def test_heuristic_review_quality_score_range():
    """Quality score should be 1-10."""
    agent = ReviewerAgent(llm_client=None)
    result = agent._heuristic_review("# Курс\n\nКратко " * 50, {})
    assert 1.0 <= result["quality_score"] <= 10.0


@pytest.mark.asyncio
async def test_review_lesson_heuristic_no_llm():
    """Test review_lesson with no LLM — should use heuristic."""
    agent = ReviewerAgent(llm_client=None)
    content = "# Lesson\n\nКраткий материал " * 50
    meta = {"title": "Test"}
    result = await agent.review_lesson(content, meta)
    assert result["is_valid"] is True
    assert result["reviewer"] == "heuristic"
    assert "stats" in result
    assert result["stats"]["words"] > 50


@pytest.mark.asyncio
async def test_review_lesson_long_insufficient():
    """Test review_lesson with long but insufficient content."""
    agent = ReviewerAgent(llm_client=None)
    content = "Просто слова " * 150
    meta = {"title": "Test"}
    result = await agent.review_lesson(content, meta)
    assert result["is_valid"] is True
    assert result["reviewer"] == "heuristic"


@pytest.mark.asyncio
async def test_review_lesson_llm_fallback_to_heuristic():
    """Test review_lesson when LLM fails — should fall back to heuristic."""
    llm_mock = AsyncMock()
    llm_mock.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))
    agent = ReviewerAgent(llm_client=llm_mock)
    content = "# Введение\n\nДлинный текст " * 200
    meta = {"title": "Test", "language": "ru"}
    result = await agent.review_lesson(content, meta)
    assert result["reviewer"] == "heuristic"
    assert result["is_valid"] is True


@pytest.mark.asyncio
async def test_review_lesson_short_is_invalid():
    """Test review_lesson with short content — should be invalid."""
    agent = ReviewerAgent(llm_client=None)
    content = "Коротко"
    meta = {"title": "Test"}
    result = await agent.review_lesson(content, meta)
    assert result["is_valid"] is False

