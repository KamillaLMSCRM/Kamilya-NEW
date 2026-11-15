"""Lossless model-input projection without database or provider dependencies."""
import copy
import hashlib
from typing import Any


def compact_course_context(body: dict[str, Any]) -> dict[str, Any]:
    """Intern verbatim citation text, preserving all source and teaching content.

    This is a model-input projection only. The registry contains draft claims,
    never another authoritative source. Identical strings share a reference;
    unequal strings (including whitespace differences) remain distinct.
    """
    result = copy.deepcopy(body)
    registry: dict[str, str] = dict(result.get("quote_texts", {}))

    def intern(value: Any) -> Any:
        if isinstance(value, list):
            return [intern(item) for item in value]
        if not isinstance(value, dict):
            return value
        projected = {}
        for key, item in value.items():
            if key in {"quote", "source_quote", "excerpt"} and isinstance(item, str) and item:
                handle = "quote-" + hashlib.sha256(item.encode()).hexdigest()
                registry[handle] = item
                projected[key] = {"quote_ref": handle}
            else:
                projected[key] = intern(item)
        return projected

    result["modules"] = intern(result["modules"])
    result["quote_texts"] = registry
    lessons = [lesson for module in result["modules"] for lesson in module["lessons"]]
    result["inventory"] = {
        "lesson_count": len(lessons),
        "question_count": sum(len(quiz["questions"]) for lesson in lessons for quiz in lesson["quizzes"]),
        "lessons": [{"lesson_id": lesson["id"], "title": lesson["title"],
            "question_ids": [q["id"] for quiz in lesson["quizzes"] for q in quiz["questions"]]}
            for lesson in lessons],
    }
    return result
