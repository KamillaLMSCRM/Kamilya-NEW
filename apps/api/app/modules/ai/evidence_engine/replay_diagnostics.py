"""Pure diagnostics for completed Evidence V2 replay artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .provider_engine import _REDUNDANCY_GENERIC_TOKENS, _grounding_tokens


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _question_fingerprint(questions: list[Mapping[str, Any]]) -> str:
    canonical = sorted(
        (
            _normalized(question.get("lesson_id")),
            _normalized(question.get("prompt")),
            _normalized(question.get("correct_answer")),
            tuple(sorted(str(item) for item in question.get("evidence_fact_ids", ()) or ())),
        )
        for question in questions
    )
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _covered(tokens: set[str], previous: list[set[str]]) -> bool:
    return len(tokens) >= 3 and any(
        len(tokens) <= len(available)
        and len(tokens & available) / len(tokens) >= 0.85
        for available in previous
    )


def _generic_token_ablation(lessons: list[Mapping[str, Any]]) -> dict[str, int]:
    changed = 0
    inspected = 0
    for lesson in lessons:
        current_previous: list[set[str]] = []
        unfiltered_previous: list[set[str]] = []
        content = str(lesson.get("content") or "")
        sentences = [
            match.group(0).strip()
            for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", content)
            if match.group(0).strip()
        ]
        for sentence in sentences:
            unfiltered = {token[:4] for token in _grounding_tokens(sentence)}
            current = unfiltered - _REDUNDANCY_GENERIC_TOKENS
            if _covered(current, current_previous) != _covered(
                unfiltered, unfiltered_previous
            ):
                changed += 1
            current_previous.append(current)
            unfiltered_previous.append(unfiltered)
            inspected += 1
    return {"sentences_inspected": inspected, "decisions_changed": changed}


def summarize_assessment_replay(
    artifact: Mapping[str, Any], *, question_cap: int = 3
) -> dict[str, Any]:
    """Aggregate quality diagnostics without provider, database or tenant access."""

    review = _mapping(artifact.get("assessment_review"))
    if not review:
        review = _mapping(_mapping(artifact.get("diagnostics")).get("assessment_review"))
    assessment = _mapping(artifact.get("realized_assessment"))
    course = _mapping(artifact.get("realized_course"))
    questions = _rows(assessment.get("questions"))
    lessons = _rows(course.get("lessons"))
    axes = _rows(review.get("axis_outcomes"))
    blocks = _rows(review.get("block_outcomes"))

    questions_per_lesson: Counter[str] = Counter(
        str(question.get("lesson_id") or "") for question in questions
    )
    assessable_axes_per_lesson: Counter[str] = Counter(
        str(axis.get("lesson_id") or "")
        for axis in axes
        if axis.get("state") != "unassessable"
    )
    axis_states = Counter(str(axis.get("state") or "unknown") for axis in axes)
    omission_reasons = Counter(
        str(axis.get("reason") or "unspecified")
        for axis in axes
        if axis.get("state") in {"omitted", "unassessable", "uncovered"}
    )
    block_outcomes = Counter(str(block.get("outcome") or "unknown") for block in blocks)
    all_lesson_ids = sorted(
        {
            *(str(lesson.get("lesson_id") or "") for lesson in lessons),
            *questions_per_lesson,
            *assessable_axes_per_lesson,
        }
        - {""}
    )
    high_density = [
        lesson_id
        for lesson_id in all_lesson_ids
        if assessable_axes_per_lesson[lesson_id] > question_cap
    ]
    saturated = [
        lesson_id
        for lesson_id in all_lesson_ids
        if questions_per_lesson[lesson_id] >= question_cap
    ]
    prompts = [_normalized(question.get("prompt")) for question in questions]

    return {
        "policy": "evidence-v2-replay-diagnostics-v1",
        "review_diagnostics_available": bool(review),
        "question_cap": question_cap,
        "lesson_count": len(all_lesson_ids),
        "question_count": len(questions),
        "question_fingerprint": _question_fingerprint(questions),
        "duplicate_prompt_count": len(prompts) - len(set(prompts)),
        "questions_per_lesson": dict(sorted(questions_per_lesson.items())),
        "assessable_axes_per_lesson": dict(sorted(assessable_axes_per_lesson.items())),
        "cap_saturated_lesson_ids": saturated,
        "high_density_lesson_ids": high_density,
        "high_density_cap_saturated_lesson_ids": sorted(set(saturated) & set(high_density)),
        "axis_states": dict(sorted(axis_states.items())),
        "omission_reasons": dict(sorted(omission_reasons.items())),
        "block_outcomes": dict(sorted(block_outcomes.items())),
        "coverage": dict(_mapping(review.get("coverage"))),
        "contract_coverage": dict(_mapping(review.get("contract_coverage"))),
        "generic_token_ablation": _generic_token_ablation(lessons),
    }
