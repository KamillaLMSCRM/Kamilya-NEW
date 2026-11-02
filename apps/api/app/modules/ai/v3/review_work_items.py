"""Prepare the same review calls as the scoped lesson loop, without inference."""
from __future__ import annotations

from typing import Any

from app.modules.ai.v3.models import V3Lesson


def lesson_review_items(lesson: V3Lesson, parts: list[V3Lesson], rules: list[Any], corpus: Any,
                        source_fragments: list[str], source_units: list[str], reference_context: tuple[str, ...],
                        *, explanation_consistency: bool,
                        held_question_ids: frozenset[str] = frozenset()) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    # Import the existing selectors so batching cannot invent a second split or question order.
    from app.modules.ai.v3.service import (
        _direct_explanation_requires_hold,
        _lesson_claim_sections,
        _lesson_claim_subparts,
        _lesson_claim_table_parts,
        _lesson_objective_section,
        _question_explanation,
        _question_option_inputs,
        _review_source_unit_fragments,
    )

    items: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    for part in parts:
        items.append(("review_lesson", (part, rules), {"source_fragments": source_fragments,
            "partial_case": len(parts) > 1, "reference_context": reference_context}))
    if source_units and lesson.content.strip():
        sections = _lesson_claim_sections(lesson.content)
        for section_index, section in enumerate(sections, 1):
            table_parts = _lesson_claim_table_parts(section)
            for table_index, (table_text, table_context) in enumerate(table_parts, 1):
                subparts = _lesson_claim_subparts(table_text)
                for subpart_index, (part_text, parent_heading) in enumerate(subparts, 1):
                    scenario = (f"Часть {section_index} из {len(sections)} одного урока; "
                                "не делайте выводов о содержании отсутствующих частей.")
                    if len(table_parts) > 1:
                        scenario += (f"\nГруппа строк таблицы {table_index} из {len(table_parts)}; "
                                     "заголовок таблицы из урока для контекста:\n" + table_context)
                    if len(subparts) > 1:
                        scenario += (f"\nГруппа подразделов {subpart_index} из {len(subparts)}; "
                                     "родительский заголовок урока для контекста:\n" + parent_heading)
                    items.append(("review_answer", (scenario, "Фактические утверждения текста урока", part_text,
                        source_units, reference_context), {"lesson_claims": _lesson_objective_section(section),
                                                          "source_prose": True}))
    for question_id, scenario, question, options, rule_id in _question_option_inputs(lesson):
        if question_id in held_question_ids:
            continue
        if (not source_units or not question_id or not question or len(options) != 4
                or sum(flag for _, flag in options) != 1 or any(not value.strip() for value, _ in options)):
            continue
        explanation = _question_explanation(lesson, question_id)
        if explanation_consistency and _direct_explanation_requires_hold(explanation):
            continue
        linked = [rule for rule in rules if rule.rule_id == rule_id]
        if len(linked) != 1 or not _review_source_unit_fragments(linked, corpus):
            continue
        texts = [value for value, _ in options]
        blind = (scenario, question, texts, source_units, reference_context)
        items.append(("review_question_options", blind, {}))
        items.append(("review_question_compatibility", blind, {}))
        answer = next(value for value, flag in options if flag)
        items.append(("review_answer_completeness", (scenario, question, answer, source_units, reference_context),
                      {"explanation": explanation, "options": texts}))
    return items
