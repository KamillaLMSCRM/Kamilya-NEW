"""Deterministic, provider-free evaluation gates for an optional KB reranker."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CorpusChunk:
    chunk_id: str
    tenant_id: str
    doc_id: str
    source_revision: str
    chunk_index: int
    heading: str
    text: str


@dataclass(frozen=True)
class QueryCase:
    query_id: str
    query_text: str
    language: str
    tenant_id: str
    allowed_sources: tuple[tuple[str, str], ...]
    candidate_chunk_ids: tuple[str, ...]
    relevance: Mapping[str, int]


@dataclass(frozen=True)
class RankedResult:
    chunk_id: str
    score: float


@dataclass(frozen=True)
class EvaluationMetrics:
    benchmark_id: str
    query_count: int
    failure_count: int
    latency_measurement_count: int
    recall_at_5: float
    mrr_at_5: float
    ndcg_at_5: float
    source_bound_violation_rate: float
    tenant_isolation_violation_rate: float
    abstention_rate: float
    false_confident_rate: float
    failure_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    estimated_cost_usd: float


@dataclass(frozen=True)
class BenchmarkDecision:
    baseline: EvaluationMetrics
    candidate: EvaluationMetrics
    verdict: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "baseline": asdict(self.baseline),
            "candidate": asdict(self.candidate),
            "deltas": {
                "recall_at_5": self.candidate.recall_at_5 - self.baseline.recall_at_5,
                "mrr_at_5": self.candidate.mrr_at_5 - self.baseline.mrr_at_5,
                "ndcg_at_5": self.candidate.ndcg_at_5 - self.baseline.ndcg_at_5,
                "latency_p95_ms": self.candidate.latency_p95_ms - self.baseline.latency_p95_ms,
                "estimated_cost_usd": self.candidate.estimated_cost_usd
                - self.baseline.estimated_cost_usd,
            },
            "verdict": self.verdict,
            "reasons": list(self.reasons),
        }


def rank_by_score(
    results: Sequence[RankedResult],
    chunks: Mapping[str, CorpusChunk],
) -> tuple[RankedResult, ...]:
    """Sort scores deterministically and reject malformed numeric output."""
    for result in results:
        if not math.isfinite(result.score):
            raise ValueError("reranker_score_must_be_finite")

    def key(result: RankedResult) -> tuple[float, str, int, str]:
        chunk = chunks.get(result.chunk_id)
        if chunk is None:
            return (-result.score, "~", 2**31 - 1, result.chunk_id)
        return (
            -result.score,
            chunk.doc_id,
            chunk.chunk_index,
            chunk.chunk_id,
        )

    return tuple(sorted(results, key=key))


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered: tuple[float, ...] = tuple(sorted(values))
    index: int = int(max(0, math.ceil(percentile * len(ordered)) - 1))
    selected_text: str = str(ordered[index])
    selected: float = float(selected_text)
    return selected


def _dcg(gains: Sequence[int]) -> float:
    total = 0.0
    for rank, gain in enumerate(gains, start=1):
        total += ((2**gain) - 1) / math.log2(rank + 1)
    return total


def _benchmark_id(
    cases: Sequence[QueryCase],
    chunks: Mapping[str, CorpusChunk],
) -> str:
    payload = []
    for case in cases:
        payload.append({
            "query_id": case.query_id,
            "query_text": case.query_text,
            "language": case.language,
            "tenant_id": case.tenant_id,
            "allowed_sources": sorted([list(source) for source in case.allowed_sources]),
            "candidate_chunk_ids": list(case.candidate_chunk_ids),
            "relevance": sorted(case.relevance.items()),
            "chunks": [asdict(chunks[chunk_id]) for chunk_id in case.candidate_chunk_ids],
        })
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def evaluate_rankings(
    cases: Sequence[QueryCase],
    chunks: Mapping[str, CorpusChunk],
    rankings: Mapping[str, Sequence[RankedResult]],
    *,
    latency_ms: Mapping[str, float] | None = None,
    failed_query_ids: frozenset[str] = frozenset(),
    confidence_threshold: float = 0.8,
    estimated_cost_usd: float = 0.0,
    k: int = 5,
) -> EvaluationMetrics:
    """Evaluate quality and hard isolation gates on one fixed query corpus."""
    if not cases:
        raise ValueError("evaluation_cases_required")
    if k <= 0:
        raise ValueError("evaluation_k_must_be_positive")
    if estimated_cost_usd < 0:
        raise ValueError("estimated_cost_must_be_nonnegative")
    if not math.isfinite(confidence_threshold) or not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold_must_be_between_zero_and_one")
    if len({case.query_id for case in cases}) != len(cases):
        raise ValueError("query_ids_must_be_unique")
    case_ids = {case.query_id for case in cases}
    if not failed_query_ids <= case_ids:
        raise ValueError("failed_query_ids_must_belong_to_corpus")
    required_latency_ids = case_ids - failed_query_ids
    if latency_ms is None or set(latency_ms) != required_latency_ids:
        raise ValueError("complete_latency_measurements_required")

    for case in cases:
        if (
            not case.query_id
            or not case.tenant_id
            or not case.allowed_sources
            or not case.candidate_chunk_ids
            or len(set(case.candidate_chunk_ids)) != len(case.candidate_chunk_ids)
        ):
            raise ValueError("invalid_query_case")
        candidate_ids = set(case.candidate_chunk_ids)
        if not set(case.relevance) <= candidate_ids:
            raise ValueError("relevance_must_reference_candidate_set")
        if any(type(gain) is not int or gain < 0 for gain in case.relevance.values()):
            raise ValueError("relevance_gain_must_be_nonnegative_integer")
        for chunk_id in case.candidate_chunk_ids:
            chunk = chunks.get(chunk_id)
            if (
                chunk is None
                or chunk.tenant_id != case.tenant_id
                or (chunk.doc_id, chunk.source_revision) not in case.allowed_sources
                or chunk.chunk_index < 0
            ):
                raise ValueError("invalid_candidate_set")

    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    abstentions = 0
    false_confident = 0
    total_returned = 0
    source_violations = 0
    tenant_violations = 0

    for case in cases:
        failed = case.query_id in failed_query_ids
        raw_results = () if failed else rank_by_score(
            tuple(rankings.get(case.query_id, ())), chunks
        )
        if not failed and not raw_results:
            abstentions += 1

        valid_results: list[RankedResult] = []
        seen: set[str] = set()
        for result in raw_results:
            total_returned += 1
            chunk = chunks.get(result.chunk_id)
            if result.chunk_id in seen:
                source_violations += 1
                continue
            seen.add(result.chunk_id)
            if chunk is None:
                source_violations += 1
                continue
            if chunk.tenant_id != case.tenant_id:
                tenant_violations += 1
                source_violations += 1
                continue
            if result.chunk_id not in case.candidate_chunk_ids:
                source_violations += 1
                continue
            if (
                (chunk.doc_id, chunk.source_revision) not in case.allowed_sources
                or chunk.chunk_index < 0
            ):
                source_violations += 1
                continue
            valid_results.append(result)

        top_results = valid_results[:k]
        gains = [max(0, int(case.relevance.get(result.chunk_id, 0))) for result in top_results]
        relevant_ranks = [rank for rank, gain in enumerate(gains, start=1) if gain > 0]
        recalls.append(1.0 if relevant_ranks else 0.0)
        reciprocal_ranks.append(1.0 / relevant_ranks[0] if relevant_ranks else 0.0)

        ideal_gains = sorted(
            (max(0, int(gain)) for gain in case.relevance.values()),
            reverse=True,
        )[:k]
        ideal_dcg = _dcg(ideal_gains)
        ndcgs.append((_dcg(gains) / ideal_dcg) if ideal_dcg else 1.0)

        if (
            top_results
            and top_results[0].score >= confidence_threshold
            and not relevant_ranks
        ):
            false_confident += 1

    denominator = float(len(cases))
    returned_denominator = float(total_returned or 1)
    latencies = [float(latency_ms[query_id]) for query_id in sorted(required_latency_ids)]
    if any(value < 0 or not math.isfinite(value) for value in latencies):
        raise ValueError("latency_must_be_finite_and_nonnegative")

    return EvaluationMetrics(
        benchmark_id=_benchmark_id(cases, chunks),
        query_count=len(cases),
        failure_count=len(failed_query_ids),
        latency_measurement_count=len(latencies),
        recall_at_5=sum(recalls) / denominator,
        mrr_at_5=sum(reciprocal_ranks) / denominator,
        ndcg_at_5=sum(ndcgs) / denominator,
        source_bound_violation_rate=source_violations / returned_denominator,
        tenant_isolation_violation_rate=tenant_violations / returned_denominator,
        abstention_rate=abstentions / denominator,
        false_confident_rate=false_confident / denominator,
        failure_rate=len(failed_query_ids) / denominator,
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        estimated_cost_usd=float(estimated_cost_usd),
    )


def decide_reranker(
    baseline: EvaluationMetrics,
    candidate: EvaluationMetrics,
    *,
    approved_max_cost_usd: float = 0.0,
) -> BenchmarkDecision:
    """Apply deterministic quality, safety, latency, failure, and cost gates."""
    def validate(metrics: EvaluationMetrics) -> None:
        rates = (
            metrics.recall_at_5,
            metrics.mrr_at_5,
            metrics.ndcg_at_5,
            metrics.source_bound_violation_rate,
            metrics.tenant_isolation_violation_rate,
            metrics.abstention_rate,
            metrics.false_confident_rate,
            metrics.failure_rate,
        )
        if (
            len(metrics.benchmark_id) != 64
            or any(character not in "0123456789abcdef" for character in metrics.benchmark_id)
            or metrics.query_count <= 0
            or not 0 <= metrics.failure_count <= metrics.query_count
            or metrics.latency_measurement_count != metrics.query_count - metrics.failure_count
            or any(not math.isfinite(rate) or not 0 <= rate <= 1 for rate in rates)
            or metrics.failure_rate != metrics.failure_count / metrics.query_count
            or not math.isfinite(metrics.latency_p50_ms)
            or not math.isfinite(metrics.latency_p95_ms)
            or metrics.latency_p50_ms < 0
            or metrics.latency_p95_ms < metrics.latency_p50_ms
            or not math.isfinite(metrics.estimated_cost_usd)
            or metrics.estimated_cost_usd < 0
        ):
            raise ValueError("invalid_evaluation_metrics")

    validate(baseline)
    validate(candidate)
    if baseline.benchmark_id != candidate.benchmark_id or baseline.query_count != candidate.query_count:
        raise ValueError("benchmark_identity_mismatch")
    if approved_max_cost_usd < 0 or not math.isfinite(approved_max_cost_usd):
        raise ValueError("invalid_approved_cost_budget")

    reasons: list[str] = []
    if baseline.source_bound_violation_rate != 0:
        reasons.append("baseline_source_bound_violation_rate_must_be_zero")
    if baseline.tenant_isolation_violation_rate != 0:
        reasons.append("baseline_tenant_isolation_violation_rate_must_be_zero")
    if baseline.failure_rate != 0:
        reasons.append("baseline_failure_rate_must_be_zero")
    if candidate.source_bound_violation_rate != 0:
        reasons.append("source_bound_violation_rate_must_be_zero")
    if candidate.tenant_isolation_violation_rate != 0:
        reasons.append("tenant_isolation_violation_rate_must_be_zero")
    if candidate.failure_rate != 0:
        reasons.append("candidate_failure_rate_must_be_zero")
    if candidate.abstention_rate > 0.05:
        reasons.append("candidate_abstention_rate_exceeds_0_05")
    if candidate.abstention_rate - baseline.abstention_rate > 0.02:
        reasons.append("candidate_abstention_regression_exceeds_0_02")
    if candidate.false_confident_rate != 0:
        reasons.append("candidate_false_confident_rate_must_be_zero")
    if candidate.recall_at_5 - baseline.recall_at_5 < -0.02:
        reasons.append("recall_at_5_regression_exceeds_0_02")
    if candidate.mrr_at_5 - baseline.mrr_at_5 < 0.03:
        reasons.append("mrr_at_5_gain_below_0_03")
    if candidate.ndcg_at_5 - baseline.ndcg_at_5 < 0.03:
        reasons.append("ndcg_at_5_gain_below_0_03")
    if candidate.latency_p95_ms - baseline.latency_p95_ms > 150.0:
        reasons.append("latency_p95_increase_exceeds_150_ms")
    if candidate.estimated_cost_usd > approved_max_cost_usd:
        reasons.append("candidate_cost_exceeds_approved_budget")

    return BenchmarkDecision(
        baseline=baseline,
        candidate=candidate,
        verdict="REJECT" if reasons else "ADOPT",
        reasons=tuple(reasons),
    )


__all__ = [
    "BenchmarkDecision",
    "CorpusChunk",
    "EvaluationMetrics",
    "QueryCase",
    "RankedResult",
    "decide_reranker",
    "evaluate_rankings",
    "rank_by_score",
]
