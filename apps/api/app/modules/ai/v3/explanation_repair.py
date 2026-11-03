"""Repair order-dependent explanations without changing the question or its answers."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from app.modules.ai.v3.models import V3Lesson
from app.modules.ai.v3.validator import has_order_dependent_feedback

_SYSTEM = (
    "Исправь только объяснение для каждого вопроса. Варианты ответов перемешиваются: "
    "называй действия по содержанию, не по номеру, букве или порядку. "
    "Опирайся на исходные фрагменты, сохраняй существенные условия. Подтверждённые уточнения ссылок "
    "используй как контекст, а не как цитату источника. Не меняй вопрос, "
    'цитату и варианты. Верни JSON {"repairs":[{"variant_id":"...","explanation":"..."}]} '
    "ровно для переданных идентификаторов."
)


async def repair_order_dependent_explanations(
    lesson: V3Lesson,
    source_fragments_by_rule: dict[str, list[str]],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    reference_context: tuple[str, ...] = (),
    *,
    typed_output: bool = False,
) -> tuple[V3Lesson, bool]:
    """One batch only; modified explanations still require independent semantic QA."""
    identified = [
        (case, v) for case in lesson.cases for v in case.variants if has_order_dependent_feedback(v.explanation)
    ]
    variants = [v for _, v in identified]
    if not variants:
        return lesson, False
    ids = [v.variant_id for v in variants]
    all_ids = [v.variant_id for case in lesson.cases for v in case.variants]
    if (
        any(not source_fragments_by_rule.get(case.rule_id) for case, _ in identified)
        or any(not item for item in all_ids)
        or len(all_ids) != len(set(all_ids))
        or len({q.question_id for q in lesson.questions}) != len(lesson.questions)
    ):
        return lesson, False
    for variant in variants:
        matches = [q for q in lesson.questions if q.question_id == f"{variant.variant_id}-assembled"]
        if matches:
            q = matches[0]
            expected = variant.assemble_question(seed=42)
            all_options = {(v.text, v.is_correct) for v in (variant.correct_option, *variant.distractor_pool)}
            if (
                q.scenario_premise != expected.scenario_premise
                or q.prompt != variant.prompt
                or q.source_quote != variant.source_quote
                or q.explanation != variant.explanation
                or len(q.options) != 4
                or any((option.text, option.is_correct) not in all_options for option in q.options)
                or [option.text for option in q.options if option.is_correct] != [variant.correct_option.text]
            ):
                return lesson, False
    payload = {
        "reference_context_not_source_quote": list(reference_context),
        "questions": [
            {
                "variant_id": v.variant_id,
                "scenario": v.scenario_premise,
                "question": v.prompt,
                "correct_answer": v.correct_option.text,
                "incorrect_answers": [o.text for o in v.distractor_pool],
                "original_explanation": v.explanation,
                "source_quote": v.source_quote,
                "source_fragments": source_fragments_by_rule[case.rule_id],
            }
            for case, v in identified
        ],
    }
    from app.modules.ai.v3.auxiliary_response_contracts import explanation_repair_format

    result = await invoke(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        explanation_repair_format(ids) if typed_output else {"type": "json_object"},
    )
    repairs = result.get("repairs") if isinstance(result, dict) else None
    if not isinstance(repairs, list) or len(repairs) != len(ids):
        return lesson, False
    mapped: dict[str, str] = {}
    for item in repairs:
        if not isinstance(item, dict) or set(item) != {"variant_id", "explanation"}:
            return lesson, False
        variant_id, explanation = item["variant_id"], item["explanation"]
        if (
            not isinstance(variant_id, str)
            or variant_id not in ids
            or variant_id in mapped
            or not isinstance(explanation, str)
            or not explanation.strip()
            or has_order_dependent_feedback(explanation)
        ):
            return lesson, False
        mapped[variant_id] = explanation.strip()
    if set(mapped) != set(ids):
        return lesson, False
    cases = tuple(
        replace(
            case,
            variants=tuple(
                replace(v, explanation=mapped[v.variant_id]) if v.variant_id in mapped else v for v in case.variants
            ),
        )
        for case in lesson.cases
    )
    by_question = {f"{variant_id}-assembled": explanation for variant_id, explanation in mapped.items()}
    questions = tuple(
        replace(q, explanation=by_question[q.question_id]) if q.question_id in by_question else q
        for q in lesson.questions
    )
    return replace(lesson, cases=cases, questions=questions), True
