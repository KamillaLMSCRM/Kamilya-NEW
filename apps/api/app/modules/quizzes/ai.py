"""AI quiz generation helpers (2026-06-26).

Wraps the resilient LLM client for the two quiz AI endpoints:
- generate: produce a draft quiz from lesson content
- rewrite: improve wording / balance of an existing quiz's questions

The model is asked to return STRICT JSON in a fixed shape so we can parse
without an additional LLM call. If the model wraps it in ```json fences
or adds prose, the parser is forgiving — see `_extract_json_block`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.modules.ai.llm_client import ResilientLLMClient

logger = logging.getLogger(__name__)


# --- Prompt building ---------------------------------------------------------


# Keep the lesson content small — Qwen has a 32K context but we want to leave
# headroom for system prompt + JSON output (~4-6K tokens for 10 questions).
_LESSON_CONTENT_MAX_CHARS = 6000


def _build_generate_prompt(
    *,
    lesson_title: str,
    lesson_content: str,
    num_questions: int,
    difficulty: str,
    language: str,
    guidance: str | None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the draft-generation call.

    The system prompt locks the output to strict JSON; the user prompt
    carries the lesson context + parameters."""

    # Truncate to keep token budget sane. Prefer cutting the tail because
    # lesson content often has boilerplate footer / "next steps" sections
    # at the end which carry less signal than the head.
    trimmed = lesson_content.strip()
    if len(trimmed) > _LESSON_CONTENT_MAX_CHARS:
        trimmed = trimmed[:_LESSON_CONTENT_MAX_CHARS] + "\n[…truncated]"

    system = (
        "Ты — ассистент методолога LMS Kamilya. Генерируешь тестовые вопросы "
        "для проверки знаний сотрудников после прохождения урока. "
        "Все вопросы и варианты — на русском языке, грамотно, кратко. "
        "Не используй markdown внутри текста вопросов и вариантов. "
        "Каждый вопрос должен иметь ровно 4 варианта ответа. "
        "Ровно один вариант должен быть правильным (is_correct=true), "
        "остальные три — правдоподобные дистракторы. "
        "Дистракторы должны быть похожи по длине и стилю на правильный "
        "ответ, но однозначно неверные. "
        "Избегай вопросов-ловушек ('все вышеперечисленное', 'ничего из вышеперечисленного'). "
        "Поле explanation — короткое пояснение (1-2 предложения) почему "
        "именно этот вариант правильный; обязательно для каждого вопроса.\n\n"
        "ФОРМАТ ОТВЕТА — строго JSON без markdown-обёрток и без пояснений до/после. "
        "Верни ТОЛЬКО валидный JSON-объект следующей формы:\n"
        "{\n"
        '  "title": "Quiz: <краткое название теста, до 80 символов>",\n'
        '  "pass_score": <целое 50-95, рекомендуемый проходной>,\n'
        '  "questions": [\n'
        "    {\n"
        '      "text": "Текст вопроса?",\n'
        '      "points": 1,\n'
        '      "explanation": "Пояснение",\n'
        '      "choices": [\n'
        '        {"text": "вариант 1", "is_correct": true},\n'
        '        {"text": "вариант 2", "is_correct": false},\n'
        '        {"text": "вариант 3", "is_correct": false},\n'
        '        {"text": "вариант 4", "is_correct": false}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    user_parts = [
        f"Урок: {lesson_title}",
        "",
        "Текст урока:",
        trimmed,
        "",
        f"Параметры:",
        f"- Количество вопросов: {num_questions}",
        f"- Сложность: {difficulty}",
        f"- Язык: {language}",
    ]
    if guidance:
        user_parts.append(f"- Дополнительные пожелания методолога: {guidance}")
    user_parts.append("")
    user_parts.append("Верни только JSON.")

    return system, "\n".join(user_parts)


# --- JSON extraction ---------------------------------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply.

    LLMs occasionally wrap the JSON in ```json … ``` fences or add a
    short intro line ("Here's the quiz:"). We try the fence first, then
    a permissive substring match. Raises if nothing parses — caller
    surfaces a 502 to the user."""
    if not raw or not raw.strip():
        raise ValueError("empty model reply")

    m = _JSON_FENCE_RE.search(raw)
    candidate = m.group(1) if m else None
    if candidate is None:
        # Greedy match for the outermost braces. If the model wrapped the
        # JSON in trailing prose, we may pick up extra trailing text —
        # json.loads will fail with "Extra data", and we fall through.
        m2 = _JSON_BLOCK_RE.search(raw)
        if m2:
            candidate = m2.group(0)

    if not candidate:
        raise ValueError("no JSON object in model reply")

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: try to find a clean prefix. Some models add a
        # trailing '},' or ']\n' garbage. We retry by trimming to the
        # last '}'.
        last_brace = candidate.rfind("}")
        if last_brace > 0:
            parsed = json.loads(candidate[: last_brace + 1])
        else:
            raise

    if not isinstance(parsed, dict):
        raise ValueError("model reply is not a JSON object")

    return parsed


# --- Validation --------------------------------------------------------------


def _normalize_question(q: dict[str, Any], idx: int) -> dict[str, Any] | None:
    """Coerce a model question dict into our draft schema.

    Returns None if the question is unusable (e.g. <2 choices or no
    correct answer). The caller drops these from the draft rather than
    failing the whole request."""
    text = (q.get("text") or "").strip()
    if not text:
        return None

    choices_raw = q.get("choices") or []
    if not isinstance(choices_raw, list) or len(choices_raw) < 2:
        return None

    choices: list[dict[str, Any]] = []
    correct_count = 0
    for ch in choices_raw:
        if not isinstance(ch, dict):
            continue
        ct = (ch.get("text") or "").strip()
        if not ct:
            continue
        ic = bool(ch.get("is_correct"))
        choices.append({"text": ct, "is_correct": ic})
        if ic:
            correct_count += 1

    if correct_count != 1 or len(choices) < 2:
        # Auto-correct: if 0 correct, mark the first as correct.
        # If >1 correct, keep only the first.
        if correct_count == 0 and choices:
            choices[0]["is_correct"] = True
            correct_count = 1
        elif correct_count > 1:
            seen_correct = False
            for ch in choices:
                if ch["is_correct"]:
                    if seen_correct:
                        ch["is_correct"] = False
                    else:
                        seen_correct = True

    if correct_count == 0:
        return None

    points = q.get("points")
    if not isinstance(points, int) or points < 1:
        points = 1

    explanation = q.get("explanation")
    if explanation is not None:
        explanation = str(explanation).strip() or None

    return {
        "text": text,
        "type": str(q.get("type") or "MCQ"),
        "points": points,
        "explanation": explanation,
        "order_index": idx,
        "choices": choices,
    }


def _normalize_draft(payload: dict[str, Any], num_questions: int) -> dict[str, Any]:
    """Validate + clamp the model JSON into the response shape.

    Returns a dict that matches QuizGenerateResponse fields. We clamp
    to `num_questions` so the UI gets exactly what it asked for even
    if the model over/under-shoots."""
    title = (payload.get("title") or "").strip()
    if not title:
        title = "Quiz: без названия"
    if len(title) > 80:
        title = title[:77] + "…"

    pass_score = payload.get("pass_score")
    if not isinstance(pass_score, int) or not (50 <= pass_score <= 95):
        pass_score = 80

    questions_raw = payload.get("questions") or []
    if not isinstance(questions_raw, list):
        questions_raw = []

    questions: list[dict[str, Any]] = []
    for i, q in enumerate(questions_raw):
        nq = _normalize_question(q, len(questions))
        if nq:
            questions.append(nq)
        if len(questions) >= num_questions:
            break

    return {
        "suggested_title": title,
        "suggested_pass_score": pass_score,
        "questions": questions,
    }


# --- Public entry points ----------------------------------------------------


async def generate_quiz_draft(
    *,
    lesson_title: str,
    lesson_content: str,
    num_questions: int,
    difficulty: str,
    language: str,
    guidance: str | None,
) -> dict[str, Any]:
    """Call the LLM and return a normalized draft.

    Raises:
        RuntimeError: LLM is unavailable or returned unparseable output.
        The router translates this into a 502."""
    system, user = _build_generate_prompt(
        lesson_title=lesson_title,
        lesson_content=lesson_content,
        num_questions=num_questions,
        difficulty=difficulty,
        language=language,
        guidance=guidance,
    )

    # num_questions question with 4 choices + title + explanation each
    # comes to roughly 250-400 output tokens per question. Cap at 4096
    # to keep DeepSeek fallback under $0.001 per call.
    llm = await ResilientLLMClient.from_settings_async(
        temperature=0.4, max_tokens=4096
    )

    t0 = time.monotonic()
    try:
        resp = await llm.ainvoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
    except Exception as e:
        logger.error(f"AI quiz draft LLM call failed: {e}", exc_info=True)
        raise RuntimeError("AI assistant is unavailable, try again") from e

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = (resp.content or "").strip()

    try:
        payload = _extract_json_object(raw)
    except ValueError as e:
        logger.warning(
            "AI quiz draft returned non-JSON reply (%d chars): %s",
            len(raw),
            raw[:300],
        )
        raise RuntimeError(
            f"AI returned an unexpected reply format. Try again or rephrase the guidance."
        ) from e

    draft = _normalize_draft(payload, num_questions)

    # The resilient client doesn't expose which tier answered (only the
    # final content is returned). We do expose the latency so the UI
    # can show "took 8.2s" which is useful feedback for slow models.
    return {
        **draft,
        "latency_ms": elapsed_ms,
        "model_used": None,
    }