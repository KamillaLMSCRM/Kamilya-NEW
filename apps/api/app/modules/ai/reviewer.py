"""AI pipeline — reviewer agent"""
"""Reviewer Agent: validates generated content and provides feedback."""
from typing import Dict, Any, List
import json


class ReviewerAgent:
    """Reviews and validates generated course content."""

    def __init__(self, llm_client=None):
        self.llm = llm_client

    async def review_lesson(
        self, lesson_content: str, lesson_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Review a lesson and return validation results."""
        # TODO: Call Qwen 3.5 when available
        content_length = len(lesson_content)
        word_count = len(lesson_content.split())

        issues = []
        suggestions = []

        # Basic checks
        if content_length < 200:
            issues.append("Content too short (< 200 characters)")
        if word_count < 100:
            issues.append("Content too short (< 100 words)")
        if not lesson_content.strip().startswith("#"):
            suggestions.append("Add heading at the start")
        if "```" not in lesson_content and lesson_meta.get("content_type") == "text":
            suggestions.append("Consider adding code examples if applicable")

        # Structure check
        has_introduction = "введение" in lesson_content.lower() or "intro" in lesson_content.lower()
        has_summary = "итог" in lesson_content.lower() or "summary" in lesson_content.lower()
        has_questions = "вопрос" in lesson_content.lower() or "quiz" in lesson_content.lower()

        if not has_introduction:
            suggestions.append("Add introduction section")
        if not has_summary:
            suggestions.append("Add summary section")
        if not has_questions:
            suggestions.append("Add self-check questions")

        quality_score = 100
        quality_score -= len(issues) * 20
        quality_score -= len(suggestions) * 5
        quality_score = max(0, quality_score)

        return {
            "is_valid": len(issues) == 0,
            "quality_score": quality_score,
            "issues": issues,
            "suggestions": suggestions,
            "stats": {
                "characters": content_length,
                "words": word_count,
                "has_introduction": has_introduction,
                "has_summary": has_summary,
                "has_questions": has_questions,
            },
        }

    async def review_course_outline(
        self, outline: Dict[str, Any]
    ) -> Dict[str, Any]:
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
