"""Apply scoped, validated option repairs without changing lesson/source identity."""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from app.modules.ai.v3.models import DistractorCategory, V3Lesson, V3Option

OPTION_REPAIR_SYSTEM = """Исправь только варианты ответов и объяснения в переданных вопросах.
Сохраняй условия ситуации, формулировку вопроса, идентификаторы, смысл правильного ответа и точные цитаты.
Для каждого вопроса дай один правильный и три правдоподобных неверных ответа, без подсказки длиной; не добавляй факты вне источника.
Не создавай устойчивую подсказку ни самым длинным, ни самым коротким правильным ответом. Не дописывай вымышленные условия ради длины.
Если есть варианты одного кейса, не повторяй одинаковые ошибки между ними. Объяснение должно обосновывать правильный ответ и ошибки.
Верни только JSON: {"repairs":[{"variant_id":"...","correct":"...","distractors":[{"text":"...","category":"procedural_confusion"},{"text":"...","category":"role_confusion"},{"text":"...","category":"unauthorized_action"}],"explanation":"..."}]}.
Допустимые категории: procedural_confusion, role_confusion, timing_violation, unauthorized_action, threshold_error.
"""

REVIEWED_QUESTION_REPAIR_SYSTEM = """Исправь формулировку вопроса, варианты ответов и объяснения в переданных вопросах.
Сохраняй условия ситуации, идентификаторы, смысл правильного ответа и точные цитаты.
Для каждого вопроса дай один правильный и три правдоподобных неверных ответа, без подсказки длиной; не добавляй факты вне источника.
Не создавай устойчивую подсказку ни самым длинным, ни самым коротким правильным ответом. Не дописывай вымышленные условия ради длины.
Если есть варианты одного кейса, не повторяй одинаковые ошибки между ними. Объяснение должно обосновывать правильный ответ и ошибки.
Верни только JSON: {"repairs":[{"variant_id":"...","prompt":"...","correct":"...","distractors":[{"text":"...","category":"procedural_confusion"},{"text":"...","category":"role_confusion"},{"text":"...","category":"unauthorized_action"}],"explanation":"..."}]}.
Поле prompt обязательно и непусто. Разрешены только показанные поля; в distractors только text и category.
Допустимые категории: procedural_confusion, role_confusion, timing_violation, unauthorized_action, threshold_error.
"""

TARGETED_DISTRACTOR_SYSTEM = """Для каждого вопроса замени только три неверных варианта. Правильный ответ приведён для контекста: не переписывай его и не возвращай в результате. Неверные варианты должны явно противоречить исходным правилам с учётом ситуации и быть правдоподобными. Устрани подсказку длиной: хотя бы один неверный вариант не короче правильного, хотя бы один не длиннее; не добавляй бессмысленных слов. Не повторяй ошибки между вариантами одного кейса. Верни JSON {"repairs":[{"variant_id":"...","distractors":[{"text":"...","category":"procedural_confusion"},{"text":"...","category":"role_confusion"},{"text":"...","category":"unauthorized_action"}]}]}. Категории: procedural_confusion, role_confusion, timing_violation, unauthorized_action, threshold_error."""

TARGETED_DISTRACTOR_MEAN_SYSTEM = TARGETED_DISTRACTOR_SYSTEM + (
    " Средняя длина трёх неверных ответов должна находиться между переданными границами "
    "target_average_wrong_min и target_average_wrong_max. Сохраняй смысл и правдоподобие."
    " Для каждого неверного варианта используй правильный текст как основу: сохрани остальные условия и действия,"
    " но измени ровно одну существенную норму так, чтобы вариант противоречил источнику."
    " Три варианта должны ошибаться в разных условиях, ролях или действиях."
    " Сохраняй сопоставимую полноту, не добавляй пустые слова."
)

DISTRACTOR_FEEDBACK_SYSTEM = """Замени только указанные неверные варианты ответа. Каждый должен прямо противоречить исходному правилу с учётом ситуации, а не опираться на неподтверждённое исключение, неизвестные полномочия или отсутствие информации. Сохрани правильный ответ и все другие варианты без изменений. Новые варианты должны быть правдоподобными, различаться по смыслу и не содержать бессмысленного удлинения. Верни JSON {"repairs":[{"index":0,"replacement":"..."}]}; индексы строго совпадают с полученными замечаниями."""


class DistractorFeedbackRejectedError(ValueError):
    """A completed distractor repair violated a local preservation contract."""


async def repair_distractor_feedback(
    lesson: V3Lesson,
    variant_id: str,
    flagged: list[dict[str, Any]],
    source_fragments: list[str],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    reference_context: tuple[str, ...] = (),
    *,
    typed_output: bool = False,
) -> V3Lesson:
    """Apply one scoped critic-guided repair while preserving the correct answer."""
    matches = [
        (ci, vi, variant)
        for ci, case in enumerate(lesson.cases, 1)
        for vi, variant in enumerate(case.variants, 1)
        if variant.variant_id == variant_id
    ]
    if len(matches) != 1 or not source_fragments or not flagged:
        raise DistractorFeedbackRejectedError("v3_distractor_feedback_identity_invalid")
    ci, vi, variant = matches[0]
    assembled = variant.assemble_question(seed=100 + ci * 10 + vi)
    options = assembled.options
    indices: set[int] = set()
    feedback: list[dict[str, Any]] = []
    for item in flagged:
        index = item.get("index") if isinstance(item, dict) else None
        if (
            type(index) is not int
            or not 0 <= index < len(options)
            or index in indices
            or options[index].is_correct
            or item.get("verdict") not in {"SUPPORTED", "UNCERTAIN"}
            or not isinstance(item.get("summary"), str)
            or not item["summary"].strip()
        ):
            raise DistractorFeedbackRejectedError("v3_distractor_feedback_invalid")
        indices.add(index)
        feedback.append(
            {"index": index, "text": options[index].text, "verdict": item["verdict"], "reason": item["summary"]}
        )
    request: dict[str, Any] = {
        "source_fragments": source_fragments,
        "scenario": variant.scenario_premise,
        "question": variant.prompt,
        "correct_for_context": variant.correct_option.text,
        "other_options": [{"index": i, "text": option.text} for i, option in enumerate(options) if i not in indices],
        "feedback": feedback,
    }
    if reference_context:
        request["reference_context_not_source_quote"] = list(reference_context)
    from app.modules.ai.v3.auxiliary_response_contracts import distractor_feedback_format

    result = await invoke(
        [
            {"role": "system", "content": DISTRACTOR_FEEDBACK_SYSTEM},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ],
        distractor_feedback_format(sorted(indices)) if typed_output else {"type": "json_object"},
    )
    rows = result.get("repairs") if isinstance(result, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != len(indices)
        or any(not isinstance(row, dict) or set(row) != {"index", "replacement"} for row in rows)
    ):
        raise DistractorFeedbackRejectedError("v3_distractor_feedback_response_invalid")
    replacements: dict[int, str] = {}
    for row in rows:
        index, text = row["index"], row["replacement"]
        if (
            type(index) is not int
            or index not in indices
            or index in replacements
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise DistractorFeedbackRejectedError("v3_distractor_feedback_response_invalid")
        replacements[index] = text.strip()
    final_texts = [replacements.get(i, option.text).strip().casefold() for i, option in enumerate(options)]
    if len(set(final_texts)) != len(final_texts):
        raise DistractorFeedbackRejectedError("v3_distractor_feedback_duplicate")
    by_text = {options[i].text: value for i, value in replacements.items()}
    if len(by_text) != len(indices) or any(
        sum(opt.text == old for opt in variant.distractor_pool) != 1 for old in by_text
    ):
        raise DistractorFeedbackRejectedError("v3_distractor_feedback_identity_invalid")
    updated = replace(
        variant,
        distractor_pool=tuple(
            replace(opt, text=by_text[opt.text]) if opt.text in by_text else opt for opt in variant.distractor_pool
        ),
    )
    cases = tuple(
        replace(case, variants=tuple(updated if value.variant_id == variant_id else value for value in case.variants))
        for case in lesson.cases
    )
    questions = tuple(case.variants[0].assemble_question(seed=42) for case in cases if case.variants)
    return replace(lesson, cases=cases, questions=questions)


async def repair_length_shortcuts(
    lesson: V3Lesson,
    violations: list[str],
    source_fragments: list[str],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    reference_context: tuple[str, ...] = (),
    *,
    typed_output: bool = False,
    measured_feedback: bool = False,
) -> V3Lesson:
    """Repair only length-biased distractors; never rewrite the correct answer."""
    fix_long = any("correct answer is longest" in item for item in violations)
    fix_short = any("correct answer is shortest" in item for item in violations)
    fix_mean = any("length bias ratio" in item for item in violations)
    payload: list[dict[str, Any]] = []
    for case_index, case in enumerate(lesson.cases, 1):
        for variant_index, variant in enumerate(case.variants, 1):
            assembled = variant.assemble_question(seed=100 + case_index * 10 + variant_index)
            wrong = [option.text for option in assembled.options if not option.is_correct]
            correct = variant.correct_option.text
            if not wrong or not correct.strip():
                raise ValueError("v3_targeted_repair_question_invalid")
            average = sum(map(len, wrong)) / len(wrong)
            mean_skew = fix_mean and average > 0 and not 0.80 <= len(correct) / average <= 1.25
            if (
                (fix_long and len(correct) > max(map(len, wrong)))
                or (fix_short and len(correct) < min(map(len, wrong)))
                or mean_skew
            ):
                row = {
                    "variant_id": variant.variant_id,
                    "scenario": variant.scenario_premise,
                    "question": variant.prompt,
                    "correct_original": correct,
                    "old_wrong": wrong,
                    "correct_length": len(correct),
                }
                if measured_feedback:
                    row.update(observed_wrong_lengths=[len(text) for text in wrong],
                               required_at_least_one_wrong_length_gte=len(correct),
                               required_at_least_one_wrong_length_lte=len(correct))
                if fix_mean:
                    row.update(
                        target_average_wrong_min=math.ceil(len(correct) / 1.25),
                        target_average_wrong_max=math.floor(len(correct) / 0.80),
                    )
                payload.append(row)
    ids = [item["variant_id"] for item in payload]
    all_ids = [variant.variant_id for case in lesson.cases for variant in case.variants]
    if not source_fragments or not ids or any(not value for value in all_ids) or len(all_ids) != len(set(all_ids)):
        raise ValueError("v3_targeted_repair_evidence_invalid")
    request: dict[str, Any] = {"source_fragments": source_fragments, "questions": payload}
    if measured_feedback:
        request["violations"] = violations
    if reference_context:
        request["reference_context_not_source_quote"] = list(reference_context)
    from app.modules.ai.v3.auxiliary_response_contracts import length_repair_format

    response = await invoke(
        [
            {"role": "system", "content": TARGETED_DISTRACTOR_MEAN_SYSTEM if fix_mean else TARGETED_DISTRACTOR_SYSTEM},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ],
        length_repair_format(ids) if typed_output else {"type": "json_object"},
    )
    rows = response.get("repairs") if isinstance(response, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != len(ids)
        or any(not isinstance(row, dict) or set(row) != {"variant_id", "distractors"} for row in rows)
    ):
        raise ValueError("v3_targeted_repair_invalid")
    mapped: dict[str, tuple[V3Option, ...]] = {}
    originals = {variant.variant_id: variant for case in lesson.cases for variant in case.variants}
    for row in rows:
        variant_id, distractors = row["variant_id"], row["distractors"]
        if (
            not isinstance(variant_id, str)
            or variant_id not in ids
            or variant_id in mapped
            or not isinstance(distractors, list)
            or len(distractors) != 3
        ):
            raise ValueError("v3_targeted_repair_invalid")
        values: list[V3Option] = []
        for item in distractors:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("text"), str)
                or not item["text"].strip()
                or item.get("category") not in DistractorCategory._value2member_map_
            ):
                raise ValueError("v3_targeted_repair_invalid")
            values.append(
                V3Option(
                    text=item["text"].strip(),
                    is_correct=False,
                    distractor_category=DistractorCategory(item["category"]),
                )
            )
        all_text = [
            originals[variant_id].correct_option.text.strip().casefold(),
            *(value.text.casefold() for value in values),
        ]
        if len(set(all_text)) != 4:
            raise ValueError("v3_targeted_repair_duplicate_option")
        mapped[variant_id] = tuple(values)
    if set(mapped) != set(ids):
        raise ValueError("v3_targeted_repair_invalid")
    cases = tuple(
        replace(
            case,
            variants=tuple(
                replace(variant, distractor_pool=mapped[variant.variant_id])
                if variant.variant_id in mapped
                else variant
                for variant in case.variants
            ),
        )
        for case in lesson.cases
    )
    questions = tuple(case.variants[0].assemble_question(seed=42) for case in cases if case.variants)
    return replace(lesson, cases=cases, questions=questions)


async def repair_options(
    lesson: V3Lesson,
    violations: list[str],
    source_fragments: list[str],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    reference_context: tuple[str, ...] = (),
    accept_partial: Callable[[V3Lesson], bool] | None = None,
    *,
    repair_prompt: bool = False,
    typed_output: bool = False,
) -> V3Lesson:
    """Repair every existing variant, rejecting partial or cross-case replacement.

    This only validates the edit shape. The caller must independently rerun
    structural, source, and semantic checks before accepting any result.
    """
    variants = [variant for case in lesson.cases for variant in case.variants]
    variant_ids = [variant.variant_id for variant in variants]
    if not variants or any(not value for value in variant_ids) or len(set(variant_ids)) != len(variant_ids):
        raise ValueError("v3_option_repair_identity_invalid")
    if not source_fragments or not violations:
        raise ValueError("v3_option_repair_evidence_missing")
    payload = [
        {
            "variant_id": variant.variant_id,
            "scenario": variant.scenario_premise,
            "question": variant.prompt,
            "correct": variant.correct_option.text,
            "distractors": [option.text for option in variant.distractor_pool],
            "explanation": variant.explanation,
        }
        for variant in variants
    ]
    system = REVIEWED_QUESTION_REPAIR_SYSTEM if repair_prompt else OPTION_REPAIR_SYSTEM
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "ТОЧНЫЕ ИСХОДНЫЕ БЛОКИ:\n"
                + "\n---\n".join(source_fragments)
                + (
                    "\n\nУТОЧНЕНИЯ ССЫЛОК, НЕ ЦИТАТЫ ИСТОЧНИКА:\n" + "\n".join(reference_context)
                    if reference_context
                    else ""
                )
                + "\n\nЗАМЕЧАНИЯ ПРОВЕРКИ:\n"
                + json.dumps(violations, ensure_ascii=False)
                + "\n\nИСХОДНЫЕ ВАРИАНТЫ:\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            ),
        },
    ]
    mapped: dict[str, tuple[V3Option, tuple[V3Option, ...], str, str | None]] = {}

    def accept_repairs(raw: Any, allowed: set[str]) -> None:
        if repair_prompt and (not isinstance(raw, dict) or set(raw) != {"repairs"}):
            raise ValueError("v3_option_repair_invalid")
        repairs = raw.get("repairs") if isinstance(raw, dict) else None
        if not isinstance(repairs, list) or not repairs:
            raise ValueError("v3_option_repair_incomplete")
        for item in repairs:
            if not isinstance(item, dict):
                raise ValueError("v3_option_repair_invalid")
            if repair_prompt and (
                set(item) != {"variant_id", "prompt", "correct", "distractors", "explanation"}
                or not isinstance(item.get("prompt"), str)
                or not item["prompt"].strip()
            ):
                raise ValueError("v3_option_repair_invalid")
            variant_id, correct, distractors, explanation = (
                item.get("variant_id"),
                item.get("correct"),
                item.get("distractors"),
                item.get("explanation"),
            )
            if (
                not isinstance(variant_id, str)
                or variant_id not in allowed
                or variant_id in mapped
                or not isinstance(correct, str)
                or not correct.strip()
                or not isinstance(explanation, str)
                or not explanation.strip()
                or not isinstance(distractors, list)
                or len(distractors) != 3
            ):
                raise ValueError("v3_option_repair_invalid")
            wrong: list[V3Option] = []
            for value in distractors:
                if (
                    not isinstance(value, dict)
                    or (repair_prompt and set(value) != {"text", "category"})
                    or not isinstance(value.get("text"), str)
                    or not value["text"].strip()
                    or value.get("category") not in DistractorCategory._value2member_map_
                ):
                    raise ValueError("v3_option_repair_invalid")
                wrong.append(
                    V3Option(
                        text=value["text"].strip(),
                        is_correct=False,
                        distractor_category=DistractorCategory(value["category"]),
                    )
                )
            texts = [correct.strip().casefold(), *(option.text.casefold() for option in wrong)]
            if len(set(texts)) != 4:
                raise ValueError("v3_option_repair_duplicate_option")
            mapped[variant_id] = (
                V3Option(text=correct.strip(), is_correct=True),
                tuple(wrong),
                explanation.strip(),
                item["prompt"].strip() if repair_prompt else None,
            )

    def build_candidate() -> V3Lesson:
        def apply(variant: Any) -> Any:
            if variant.variant_id not in mapped:
                return variant
            correct, distractors, explanation, prompt = mapped[variant.variant_id]
            return replace(
                variant,
                correct_option=correct,
                distractor_pool=distractors,
                explanation=explanation,
                prompt=prompt if prompt is not None else variant.prompt,
            )

        cases = tuple(
            replace(case, variants=tuple(apply(variant) for variant in case.variants)) for case in lesson.cases
        )
        questions = tuple(case.variants[0].assemble_question(seed=42) for case in cases if case.variants)
        return replace(lesson, cases=cases, questions=questions)

    from app.modules.ai.v3.auxiliary_response_contracts import option_repair_format

    response_format = (
        option_repair_format(variant_ids, include_prompt=repair_prompt, allow_partial=True)
        if typed_output else {"type": "json_object"}
    )
    accept_repairs(await invoke(messages, response_format), set(variant_ids))
    missing = set(variant_ids) - set(mapped)
    if missing and accept_partial is not None:
        candidate = build_candidate()
        if accept_partial(candidate):
            return candidate
    if missing:
        # One targeted request; checkpointed caller prevents retry after unknown outcome.
        # Do not pass already-repaired questions or accept edits outside this subset.
        missing_payload = [item for item in payload if item["variant_id"] in missing]
        targeted = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "ТОЧНЫЕ ИСХОДНЫЕ БЛОКИ:\n"
                    + "\n---\n".join(source_fragments)
                    + (
                        "\n\nУТОЧНЕНИЯ ССЫЛОК, НЕ ЦИТАТЫ ИСТОЧНИКА:\n" + "\n".join(reference_context)
                        if reference_context
                        else ""
                    )
                    + "\n\nЗАМЕЧАНИЯ ПРОВЕРКИ:\n"
                    + json.dumps(violations, ensure_ascii=False)
                    + "\n\nИСПРАВЬ ТОЛЬКО ЭТИ ОТСУТСТВУЮЩИЕ ВАРИАНТЫ:\n"
                    + json.dumps(missing_payload, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ]
        targeted_format = (option_repair_format(sorted(missing), include_prompt=repair_prompt)
                           if typed_output else {"type": "json_object"})
        accept_repairs(await invoke(targeted, targeted_format), missing)
    if set(mapped) != set(variant_ids):
        raise ValueError("v3_option_repair_incomplete")
    return build_candidate()
