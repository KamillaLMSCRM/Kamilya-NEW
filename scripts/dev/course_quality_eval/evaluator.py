from __future__ import annotations

import time
from datetime import UTC, datetime

from .domain import (
    CourseArtifact,
    EvaluationReport,
    EvaluationRequest,
    Evaluator,
    Rubric,
    UsageSummary,
)
from .policy import evaluate_lesson_policy, evaluate_question_policy, overall_decision
from .privacy import assert_deidentified

_JEV_INPUT_USD_PER_MILLION = 0.042


def evaluate_generation(
    artifact: CourseArtifact,
    *,
    evaluator: Evaluator,
    rubric: Rubric,
) -> EvaluationReport:
    """Evaluate a frozen course artifact without importing the production app."""

    started = time.perf_counter()
    assert_deidentified(artifact)
    lesson_findings = []
    question_findings = []
    results = []
    for lesson in artifact.lessons:
        result = evaluator.evaluate(
            EvaluationRequest(
                model=rubric.model,
                state={
                    "kind": "lesson",
                    "source": lesson.source,
                    "objectives": list(lesson.objectives),
                    "lesson_title": lesson.title,
                    "lesson_content": lesson.content,
                },
                questions=rubric.lesson_questions,
            )
        )
        results.append(result)
        lesson_findings.append(
            evaluate_lesson_policy(target_id=lesson.id, title=lesson.title, result=result)
        )
    for question in artifact.questions:
        result = evaluator.evaluate(
            EvaluationRequest(
                model=rubric.model,
                state={
                    "kind": "question",
                    "source": question.source,
                    "lesson_title": question.lesson_title,
                    "question": question.text,
                    "options": list(question.options),
                    "keyed_correct_option_indexes": list(question.correct_indexes),
                    "explanation": question.explanation,
                },
                questions=rubric.question_questions,
            )
        )
        results.append(result)
        question_findings.append(
            evaluate_question_policy(target_id=question.id, title=question.text, result=result)
        )
    all_findings = tuple([*lesson_findings, *question_findings])
    input_tokens = sum(result.input_tokens for result in results)
    live_results = [result for result in results if not result.cached]
    return EvaluationReport(
        schema_version=1,
        generated_at=datetime.now(UTC).isoformat(),
        rubric_version=rubric.version,
        requested_model=rubric.model,
        resolved_models=tuple(sorted({result.model for result in results})),
        enforcement=rubric.enforcement,
        decision=overall_decision(all_findings),
        artifact=artifact.identity,
        lessons=tuple(lesson_findings),
        questions=tuple(question_findings),
        usage=UsageSummary(
            input_tokens=input_tokens,
            output_tokens=sum(result.output_tokens for result in results),
            calls=len(results),
            live_calls=len(live_results),
            cache_hits=sum(result.cached for result in results),
            provider_latency_ms=sum(result.latency_ms for result in results),
            evaluation_wall_ms=round((time.perf_counter() - started) * 1000),
            estimated_cost_usd=round(
                sum(result.input_tokens for result in live_results)
                / 1_000_000
                * _JEV_INPUT_USD_PER_MILLION,
                8,
            ),
        ),
    )
