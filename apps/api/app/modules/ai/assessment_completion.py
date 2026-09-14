"""One bounded objective-focused supplement; never rerun the course or pad counts."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Any

from app.modules.ai.assessment import _normalize_evidence_text, generate_lesson_assessment
from app.modules.ai.assessment_audit import AssessmentAuditError, AssessmentAuditResult, _check, audit_course_assessment
from app.modules.ai.assessment_schema import CourseAssessment
from app.modules.ai.writer_schema import CourseContent


async def _audit_with_contract_retry(llm: Any, content: CourseContent, assessment: CourseAssessment, callback: Callable[[], Any] | None) -> AssessmentAuditResult:
    try:
        return await audit_course_assessment(llm, content, assessment, callback)
    except AssessmentAuditError:
        # One bounded protocol retry, never regenerate lessons or treat failure
        # as acceptance. Provider failures and cancellation retain their types.
        await _check(callback)
        return await audit_course_assessment(llm, content, assessment, callback)


async def finalize_course_assessment(
    llm: Any,
    course_content: CourseContent,
    assessment: CourseAssessment,
    language: str = "ru",
    compact: bool = False,
    check_cancelled: Callable[[], Any] | None = None,
    on_progress: Callable[[str], Any] | None = None,
) -> AssessmentAuditResult:
    """Audit, attempt uncovered objectives once per lesson, then audit the union.

    Good questions and original lessons remain unchanged. Remaining gaps are
    returned explicitly; an empty supplement never triggers another attempt.
    """
    initial = await _audit_with_contract_retry(llm, course_content, assessment, check_cancelled)
    if not initial.uncovered_objectives:
        return initial
    lessons = [lesson for module in course_content.modules for lesson in module.lessons]
    gaps: dict[int, list[int]] = {}
    for li, oi in initial.uncovered_objectives:
        gaps.setdefault(li, []).append(oi)
    supplemented = list(initial.assessment.assessments)
    excluded = {
        (_normalize_evidence_text(q.source_quote), _normalize_evidence_text(o.text))
        for item in supplemented for q in item.mcq for o in q.options if o.is_correct
    }
    added = False
    for number, (li, indices) in enumerate(gaps.items(), start=1):
        await _check(check_cancelled)
        if on_progress:
            message = f"Проверка непокрытых тем {number}/{len(gaps)}: {lessons[li].title}"
            await _check(partial(on_progress, message))
        objectives = [lessons[li].objectives[oi] for oi in indices]
        # This temporary retrieval scope cannot mutate persisted lesson content.
        focused = replace(lessons[li], title="; ".join(objectives), objectives=objectives)
        extra = await generate_lesson_assessment(
            llm, focused, language=language, compact=compact,
            check_cancelled=check_cancelled, excluded_fact_keys=frozenset(excluded),
        )
        await _check(check_cancelled)
        if extra.mcq:
            added = True
            supplemented[li] = replace(supplemented[li], mcq=[*supplemented[li].mcq, *extra.mcq])
            excluded.update(
                (_normalize_evidence_text(q.source_quote), _normalize_evidence_text(o.text))
                for q in extra.mcq for o in q.options if o.is_correct
            )
    if not added:
        return initial
    final = await _audit_with_contract_retry(
        llm, course_content, CourseAssessment(assessments=supplemented), check_cancelled,
    )
    # A later stochastic verdict must not silently erase an earlier coverage
    # concern. This is a methodologist review list, not proof of remaining gaps.
    final.uncovered_objectives = sorted(set(initial.uncovered_objectives) | set(final.uncovered_objectives))
    return final
