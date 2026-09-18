from __future__ import annotations

from .domain import AdapterResult, Decision, EvaluationFinding

_SEVERITY: dict[Decision, int] = {"pass": 0, "review": 1, "reject": 2}


def _signals(result: AdapterResult) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, answer in result.answers.items():
        answer_type = answer.get("type")
        if answer_type == "noul":
            values[key] = float(answer["noul"])
        elif answer_type == "score":
            values[key] = float(answer["score"])
    return values


def evaluate_lesson_policy(*, target_id: str, title: str, result: AdapterResult) -> EvaluationFinding:
    signals = _signals(result)
    reject = tuple(key for key, threshold in {"claims_supported": 0.70}.items() if signals.get(key, 0.0) < threshold)
    review = tuple(
        key
        for key, threshold in {
            "objective_alignment": 0.65,
            "coherent_focus": 0.65,
            "practical_value": 1.50,
        }.items()
        if signals.get(key, 0.0) < threshold
    )
    if signals.get("mostly_source_repetition", 1.0) > 0.70:
        review += ("mostly_source_repetition",)
    decision: Decision = "reject" if reject else "review" if review else "pass"
    return EvaluationFinding(
        target_id=target_id,
        title=title,
        decision=decision,
        reasons=reject + review,
        signals=signals,
        model=result.model,
        latency_ms=result.latency_ms,
    )


def evaluate_question_policy(*, target_id: str, title: str, result: AdapterResult) -> EvaluationFinding:
    signals = _signals(result)
    reject = tuple(
        key
        for key, threshold in {
            "source_support": 0.70,
            "exactly_one_correct": 0.70,
            "explanation_grounded": 0.65,
        }.items()
        if signals.get(key, 0.0) < threshold
    )
    review = tuple(
        key
        for key, threshold in {
            "distractors_distinct": 0.65,
            "distractors_plausible": 0.55,
            "atomic": 0.65,
            "educational_value": 1.50,
        }.items()
        if signals.get(key, 0.0) < threshold
    )
    decision: Decision = "reject" if reject else "review" if review else "pass"
    return EvaluationFinding(
        target_id=target_id,
        title=title,
        decision=decision,
        reasons=reject + review,
        signals=signals,
        model=result.model,
        latency_ms=result.latency_ms,
    )


def overall_decision(findings: tuple[EvaluationFinding, ...]) -> Decision:
    if not findings:
        return "review"
    return max((finding.decision for finding in findings), key=_SEVERITY.__getitem__)
