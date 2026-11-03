"""One source-grounded compatibility recheck for malformed model judgments."""

from __future__ import annotations

import json
from typing import Any


async def recheck_compatibility(
    pipeline: Any,
    scenario: str,
    question: str,
    options: list[str],
    flags: list[bool],
    source: list[str],
    context: tuple[str, ...],
    original: Any,
    evidence: dict[str, Any],
) -> tuple[bool, str]:
    """Retain original and recheck only structural inconsistency, never normalize claims."""
    from app.modules.ai.v3.service import _validate_question_entailment

    evidence["compatibility"] = original
    substantive = _substantive_compatibility_failure(original, flags)
    if substantive:
        return False, substantive
    valid, error = _validate_question_entailment(original, flags)
    if valid:
        return True, ""
    repairable = ("нет корректной проверки полноты ответа", "вердикт проверки ответа противоречит статусам утверждений")
    if not source or not any(marker in error for marker in repairable):
        return False, error
    evidence["compatibility_recheck"] = {"original_error": error, "result": None}
    feedback = "Предыдущий ответ для проверки согласованности: " + json.dumps(
        original, ensure_ascii=False, sort_keys=True
    )
    result = await pipeline.review_question_compatibility(
        scenario, question, options, source, context, consistency_feedback=feedback
    )
    evidence["compatibility_recheck"]["result"] = result
    return _validate_question_entailment(result, flags)


def _substantive_compatibility_failure(value: Any, flags: list[bool]) -> str:
    """Find answer-key or claim-status failures hidden behind an earlier shape error."""
    from app.modules.ai.v3.service import _validate_answer_entailment

    if not isinstance(value, dict) or not isinstance(value.get("options"), list):
        return ""
    by_index = {
        item.get("index"): item for item in value["options"]
        if isinstance(item, dict) and type(item.get("index")) is int
    }
    for index, expected_correct in enumerate(flags):
        item = by_index.get(index)
        if not isinstance(item, dict):
            continue
        expected = "SUPPORTED" if expected_correct else "CONTRADICTED"
        verdict = item.get("verdict")
        if not isinstance(verdict, str):
            return f"вариант {index}: невалидный вердикт проверки ответа"
        if verdict in {"SUPPORTED", "CONTRADICTED", "UNCERTAIN"} and verdict != expected:
            return f"вариант {index}: ожидался {expected}, получен {verdict}"
        claims = item.get("claims")
        statuses = [claim.get("status") for claim in claims
                    if isinstance(claim, dict) and isinstance(claim.get("status"), str)] \
            if isinstance(claims, list) else []
        if ((verdict == "SUPPORTED" and any(status != "SUPPORTED" for status in statuses))
                or (verdict == "CONTRADICTED" and "CONTRADICTED" not in statuses)
                or (verdict == "UNCERTAIN" and ("UNCERTAIN" not in statuses or "CONTRADICTED" in statuses))):
            return f"вариант {index}: вердикт проверки ответа противоречит статусам утверждений"
        valid, error = _validate_answer_entailment(item)
        if not valid:
            if "вердикт проверки ответа противоречит статусам утверждений" in error:
                return f"вариант {index}: {error}"
            if error != "":
                return f"вариант {index}: {error}"
        omissions = item.get("omitted_required_elements")
        if expected_correct and isinstance(omissions, list) and omissions:
            return f"вариант {index}: пропущены обязательные элементы ответа"
    return ""
