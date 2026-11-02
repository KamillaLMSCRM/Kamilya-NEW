"""Strict local parser for one source-bound diversity repair candidate; not wired."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.modules.ai.v3.diversity_repair_selection import Selection, preserves_non_target
from app.modules.ai.v3.models import DistractorCategory, V3Lesson, V3Option, V3QuestionVariant


def parse_target_variant(lesson: V3Lesson, selected: Selection, response: Any) -> V3Lesson | None:
    """Stage exactly one variant; semantic and owned-journal validation remain mandatory."""
    try:
        keys = {"variant_id", "branch_context", "scenario_premise", "prompt", "correct", "distractors", "explanation", "source_quote"}
        if not isinstance(response, dict) or set(response) != keys or response["variant_id"] != selected.variant_id:
            return None
        text_keys = keys - {"distractors", "branch_context"}
        if any(not isinstance(response[key], str) or not response[key].strip() for key in text_keys):
            return None
        if not isinstance(response["branch_context"], str) or response["source_quote"] != selected.source_quote:
            return None
        rows = response["distractors"]
        if not isinstance(rows, list) or len(rows) != 3:
            return None
        wrong = []
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"text", "category"}
                    or not isinstance(row["text"], str) or not row["text"].strip()
                    or row["category"] not in DistractorCategory._value2member_map_):
                return None
            wrong.append(V3Option(row["text"], False, DistractorCategory(row["category"])))
        if len({response["correct"].strip().casefold(), *(x.text.strip().casefold() for x in wrong)}) != 4:
            return None
        matches = [(i, j) for i, case in enumerate(lesson.cases) for j, variant in enumerate(case.variants)
                   if case.case_id == selected.case_id and case.rule_id == selected.rule_id
                   and variant.variant_id == selected.variant_id]
        if len(matches) != 1:
            return None
        i, j = matches[0]
        variant = V3QuestionVariant(selected.variant_id, response["branch_context"], response["scenario_premise"],
            response["prompt"], V3Option(response["correct"], True), tuple(wrong), response["explanation"],
            response["source_quote"])
        case = lesson.cases[i]
        updated_case = replace(case, variants=(*case.variants[:j], variant, *case.variants[j + 1:]))
        questions = lesson.questions
        if questions and j == 0:
            questions = (*questions[:i], variant.assemble_question(seed=42), *questions[i + 1:])
        candidate = replace(lesson, cases=(*lesson.cases[:i], updated_case, *lesson.cases[i + 1:]), questions=questions)
        return candidate if preserves_non_target(lesson, candidate, selected) else None
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
