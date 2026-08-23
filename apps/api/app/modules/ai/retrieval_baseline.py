"""Pure metrics for the versioned synthetic RU/KK retrieval baseline."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

CITATION_RE = re.compile(r"^[^\r\n]+:[1-9][0-9]*(?::[1-9][0-9]*)?$")


@dataclass(frozen=True)
class BaselineCase:
    query_id: str
    query_text: str
    language: str
    category: str
    tenant_id: str
    allowed_sources: tuple[tuple[str, str], ...]
    expected_chunk_ids: tuple[str, ...]
    should_abstain: bool


@dataclass(frozen=True)
class BaselineHit:
    chunk_id: str
    tenant_id: str
    doc_id: str
    source_revision: str
    citation: str


@dataclass(frozen=True)
class BaselineReport:
    benchmark_id: str
    case_count: int
    answerable_case_count: int
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    revision_correctness: float
    citation_completeness: float
    abstention_accuracy: float
    leakage_rate: float
    latency_p95_ms: float
    estimated_cost_usd: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BaselineComparison:
    benchmark_id: str
    recall_at_5_delta: float
    recall_at_10_delta: float
    mrr_at_10_delta: float
    revision_correctness_delta: float
    citation_completeness_delta: float
    abstention_accuracy_delta: float
    leakage_rate_delta: float
    latency_p95_delta_ms: float
    estimated_cost_delta_usd: float
    quality_improved: bool
    no_regression: bool
    passed: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def evaluate_baseline(
    cases: Sequence[BaselineCase],
    rankings: Mapping[str, Sequence[BaselineHit]],
    *,
    latency_ms: Mapping[str, float],
    estimated_cost_usd: float = 0.0,
) -> BaselineReport:
    if not cases or len({case.query_id for case in cases}) != len(cases):
        raise ValueError("valid_unique_baseline_cases_required")
    case_ids = {case.query_id for case in cases}
    if set(latency_ms) != case_ids:
        raise ValueError("complete_baseline_latency_required")
    latencies = [float(latency_ms[case.query_id]) for case in cases]
    if any(value < 0 or not math.isfinite(value) for value in latencies):
        raise ValueError("baseline_latency_must_be_finite_and_nonnegative")
    if estimated_cost_usd < 0 or not math.isfinite(estimated_cost_usd):
        raise ValueError("baseline_cost_must_be_finite_and_nonnegative")

    answerable = [case for case in cases if not case.should_abstain]
    abstention_cases = [case for case in cases if case.should_abstain]
    recalls_5: list[float] = []
    recalls_10: list[float] = []
    reciprocal_ranks: list[float] = []
    returned = 0
    leakage = 0
    cited = 0
    relevant_returned = 0
    relevant_revision_correct = 0
    correct_abstentions = 0

    for case in cases:
        hits = tuple(rankings.get(case.query_id, ()))
        returned += len(hits)
        allowed_sources = set(case.allowed_sources)
        valid_hits = []
        seen = set()
        for hit in hits:
            if hit.chunk_id in seen:
                leakage += 1
                continue
            seen.add(hit.chunk_id)
            if hit.tenant_id != case.tenant_id or (hit.doc_id, hit.source_revision) not in allowed_sources:
                leakage += 1
                continue
            valid_hits.append(hit)
            if CITATION_RE.fullmatch(hit.citation):
                cited += 1

        if case.should_abstain:
            if not hits:
                correct_abstentions += 1
            continue

        expected = set(case.expected_chunk_ids)
        top_5 = [hit.chunk_id for hit in valid_hits[:5]]
        top_10 = [hit.chunk_id for hit in valid_hits[:10]]
        recalls_5.append(1.0 if expected.intersection(top_5) else 0.0)
        recalls_10.append(1.0 if expected.intersection(top_10) else 0.0)
        first_rank = next(
            (index for index, chunk_id in enumerate(top_10, start=1) if chunk_id in expected),
            None,
        )
        reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        for hit in valid_hits:
            if hit.chunk_id in expected:
                relevant_returned += 1
                if (hit.doc_id, hit.source_revision) in allowed_sources:
                    relevant_revision_correct += 1

    payload = [asdict(case) for case in cases]
    benchmark_id = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    answerable_count = len(answerable)
    return BaselineReport(
        benchmark_id=benchmark_id,
        case_count=len(cases),
        answerable_case_count=answerable_count,
        recall_at_5=sum(recalls_5) / answerable_count,
        recall_at_10=sum(recalls_10) / answerable_count,
        mrr_at_10=sum(reciprocal_ranks) / answerable_count,
        revision_correctness=(relevant_revision_correct / relevant_returned) if relevant_returned else 0.0,
        citation_completeness=(cited / returned) if returned else 1.0,
        abstention_accuracy=(correct_abstentions / len(abstention_cases)) if abstention_cases else 1.0,
        leakage_rate=leakage / float(returned or 1),
        latency_p95_ms=_percentile(latencies, 0.95),
        estimated_cost_usd=float(estimated_cost_usd),
    )


def compare_baselines(
    baseline: BaselineReport,
    candidate: BaselineReport,
    *,
    max_latency_regression_ms: float = 0.0,
    max_cost_regression_usd: float = 0.0,
) -> BaselineComparison:
    if (
        baseline.benchmark_id != candidate.benchmark_id
        or baseline.case_count != candidate.case_count
        or baseline.answerable_case_count != candidate.answerable_case_count
    ):
        raise ValueError("incompatible_baseline_reports")
    if (
        not math.isfinite(max_latency_regression_ms)
        or max_latency_regression_ms < 0
        or not math.isfinite(max_cost_regression_usd)
        or max_cost_regression_usd < 0
    ):
        raise ValueError("invalid_baseline_regression_budget")

    recall_5_delta = candidate.recall_at_5 - baseline.recall_at_5
    recall_10_delta = candidate.recall_at_10 - baseline.recall_at_10
    mrr_delta = candidate.mrr_at_10 - baseline.mrr_at_10
    revision_delta = candidate.revision_correctness - baseline.revision_correctness
    citation_delta = candidate.citation_completeness - baseline.citation_completeness
    abstention_delta = candidate.abstention_accuracy - baseline.abstention_accuracy
    leakage_delta = candidate.leakage_rate - baseline.leakage_rate
    latency_delta = candidate.latency_p95_ms - baseline.latency_p95_ms
    cost_delta = candidate.estimated_cost_usd - baseline.estimated_cost_usd
    quality_improved = any(delta > 0 for delta in (recall_5_delta, recall_10_delta, mrr_delta))
    no_regression = (
        recall_5_delta >= 0
        and recall_10_delta >= 0
        and mrr_delta >= 0
        and revision_delta >= 0
        and citation_delta >= 0
        and abstention_delta >= 0
        and candidate.leakage_rate == 0.0
        and leakage_delta <= 0
        and latency_delta <= max_latency_regression_ms
        and cost_delta <= max_cost_regression_usd
    )
    return BaselineComparison(
        benchmark_id=baseline.benchmark_id,
        recall_at_5_delta=recall_5_delta,
        recall_at_10_delta=recall_10_delta,
        mrr_at_10_delta=mrr_delta,
        revision_correctness_delta=revision_delta,
        citation_completeness_delta=citation_delta,
        abstention_accuracy_delta=abstention_delta,
        leakage_rate_delta=leakage_delta,
        latency_p95_delta_ms=latency_delta,
        estimated_cost_delta_usd=cost_delta,
        quality_improved=quality_improved,
        no_regression=no_regression,
        passed=quality_improved and no_regression,
    )


__all__ = [
    "BaselineCase",
    "BaselineComparison",
    "BaselineHit",
    "BaselineReport",
    "compare_baselines",
    "evaluate_baseline",
]
