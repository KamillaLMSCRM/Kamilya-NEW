"""Reviewer Agent: validates generated content with LLM-as-judge + heuristic fallback."""
from __future__ import annotations

import json
import logging
from typing import Any

from packages.ml_pipeline import get_renderer

logger = logging.getLogger(__name__)


def _load_review_prompt() -> str:
    """Load the static reviewer base prompt from Jinja2 template."""
    return get_renderer().render("reviewer/system.md")


REVIEW_PROMPT = _load_review_prompt()


class ReviewerAgent:
    """Reviews and validates generated course content."""

    def __init__(self, llm_client=None):
        self.llm = llm_client
        self._llm_available: bool | None = None

    async def _try_llm_review(
        self, lesson_content: str, lesson_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Try LLM-as-judge review. Returns None if unavailable."""
        if self._llm_available is False:
            return None

        lang = lesson_meta.get("language", "ru")
        lang_names = {"ru": "Russian", "kk": "Kazakh", "en": "English"}
        lang_name = lang_names.get(lang, lang)

        prompt = f"""{REVIEW_PROMPT}

Lesson title: {lesson_meta.get('title', 'Unknown')}
Target language: {lang_name}

Content:
{lesson_content[:6000]}
"""
        try:
            response = await self.llm.ainvoke([{"role": "user", "content": prompt}])
            text = response.content.strip()
            # Extract JSON from response
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            result = json.loads(text)
            self._llm_available = True
            logger.info("LLM-as-judge review succeeded (score=%s)", result.get("quality_score"))
            return result
        except Exception as e:
            self._llm_available = False
            logger.warning("LLM review failed, falling back to heuristic: %s", e)
            return None

    def _heuristic_review(
        self, lesson_content: str, lesson_meta: dict[str, Any]
    ) -> dict[str, Any]:
        """Fallback heuristic review when LLM is unavailable."""
        content_length = len(lesson_content)
        word_count = len(lesson_content.split())

        issues = []
        suggestions = []

        if content_length < 200:
            issues.append("Content too short (< 200 characters)")
        if word_count < 100:
            issues.append("Content too short (< 100 words)")
        if not lesson_content.strip().startswith("#"):
            suggestions.append("Add heading at the start")
        if "```" not in lesson_content and lesson_meta.get("content_type") == "text":
            suggestions.append("Consider adding code examples if applicable")

        lower = lesson_content.lower()
        has_introduction = any(w in lower for w in ["введение", "intro", "вступление"])
        has_summary = any(w in lower for w in ["итог", "summary", "заключение", "резюме"])
        has_questions = any(w in lower for w in ["вопрос", "quiz", "задание", "упражнение"])
        has_practical = any(w in lower for w in ["пример", "practice", "практика", "задача"])

        if not has_introduction:
            suggestions.append("Add introduction section")
        if not has_summary:
            suggestions.append("Add summary section")
        if not has_questions:
            suggestions.append("Add self-check questions")
        if not has_practical:
            suggestions.append("Add practical examples")

        quality_score = 100
        quality_score -= len(issues) * 20
        quality_score -= len(suggestions) * 5
        quality_score = max(0, min(100, quality_score))

        return {
            "quality_score": round(quality_score / 10, 1),
            "issues": issues,
            "suggestions": suggestions,
            "language_match": True,
            "has_introduction": has_introduction,
            "has_summary": has_summary,
            "has_practical": has_practical,
            "topic_relevance": 5,
        }

    async def review_lesson(
        self, lesson_content: str, lesson_meta: dict[str, Any]
    ) -> dict[str, Any]:
        """Review a lesson — LLM-as-judge first, heuristic fallback."""
        # Try LLM review first
        if self.llm is not None:
            llm_result = await self._try_llm_review(lesson_content, lesson_meta)
            if llm_result is not None:
                return {
                    "is_valid": len(llm_result.get("issues", [])) == 0,
                    **llm_result,
                    "reviewer": "llm",
                    "stats": {
                        "characters": len(lesson_content),
                        "words": len(lesson_content.split()),
                    },
                }

        # Heuristic fallback
        result = self._heuristic_review(lesson_content, lesson_meta)
        return {
            "is_valid": len(result["issues"]) == 0,
            **result,
            "reviewer": "heuristic",
            "stats": {
                "characters": len(lesson_content),
                "words": len(lesson_content.split()),
            },
        }

    async def review_course_outline(
        self, outline: dict[str, Any]
    ) -> dict[str, Any]:
        """Review course outline for completeness."""
        issues = []
        suggestions = []

        modules = outline.get("modules", [])
        if len(modules) < 2:
            issues.append("Course should have at least 2 modules")
        if not outline.get("title"):
            issues.append("Course title is missing")
        if not outline.get("description"):
            suggestions.append("Add course description")
        if not outline.get("learning_objectives"):
            suggestions.append("Add learning objectives")

        total_lessons = sum(len(m.get("lessons", [])) for m in modules)
        if total_lessons < 5:
            suggestions.append("Consider adding more lessons (currently < 5)")

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "suggestions": suggestions,
            "stats": {
                "modules": len(modules),
                "total_lessons": total_lessons,
            },
        }
