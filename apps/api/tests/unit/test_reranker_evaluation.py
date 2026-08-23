import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.modules.ai.reranker_evaluation import (
    CorpusChunk,
    QueryCase,
    RankedResult,
    decide_reranker,
    evaluate_rankings,
    rank_by_score,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "kb_rag_hbr08_corpus.json"


def _benchmark():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    chunks = {}
    cases = []
    baseline = {}
    candidate = {}
    baseline_latency = {}
    candidate_latency = {}
    for offset, document in enumerate(payload["documents"]):
        relevance = {}
        candidate_ids = []
        for chunk_data in document["chunks"]:
            chunk_id = chunk_data["chunk_id"]
            candidate_ids.append(chunk_id)
            relevance[chunk_id] = chunk_data["relevance"]
            chunks[chunk_id] = CorpusChunk(
                chunk_id=chunk_id,
                tenant_id=chunk_data["tenant_id"],
                doc_id=chunk_data["doc_id"],
                source_revision=chunk_data["source_revision"],
                chunk_index=chunk_data["chunk_index"],
                heading=chunk_data["heading"],
                text=chunk_data["text"],
            )
        query_id = f"q-{offset:02d}"
        cases.append(
            QueryCase(
                query_id=query_id,
                query_text=document["query"],
                language=document["language"],
                tenant_id=document["tenant_id"],
                allowed_sources=((document["doc_id"], document["source_revision"]),),
                candidate_chunk_ids=tuple(candidate_ids),
                relevance=relevance,
            )
        )
        baseline[query_id] = (
            RankedResult(candidate_ids[0], 0.91),
            RankedResult(candidate_ids[1], 0.89),
        )
        candidate[query_id] = (
            RankedResult(candidate_ids[1], 0.95),
            RankedResult(candidate_ids[0], 0.30),
        )
        baseline_latency[query_id] = 20.0 + offset
        candidate_latency[query_id] = 80.0 + offset
    return payload, chunks, cases, baseline, candidate, baseline_latency, candidate_latency


def test_corpus_is_synthetic_bilingual_and_two_tenant() -> None:
    payload, *_ = _benchmark()
    documents = payload["documents"]
    assert len(documents) == 12
    assert {document["tenant_id"] for document in documents} == {"tenant-alpha", "tenant-beta"}
    assert sum(document["language"] == "ru" for document in documents) == 4
    assert sum(document["language"] == "kk" for document in documents) == 4
    assert sum(document["language"] == "ru-kk" for document in documents) == 4


def test_local_candidate_meets_deterministic_adoption_gates() -> None:
    _, chunks, cases, baseline, candidate, baseline_latency, candidate_latency = _benchmark()
    baseline_metrics = evaluate_rankings(
        cases,
        chunks,
        baseline,
        latency_ms=baseline_latency,
    )
    candidate_metrics = evaluate_rankings(
        cases,
        chunks,
        candidate,
        latency_ms=candidate_latency,
    )
    decision = decide_reranker(baseline_metrics, candidate_metrics)

    assert baseline_metrics.recall_at_5 == 1.0
    assert candidate_metrics.recall_at_5 == 1.0
    assert candidate_metrics.mrr_at_5 - baseline_metrics.mrr_at_5 >= 0.03
    assert candidate_metrics.ndcg_at_5 - baseline_metrics.ndcg_at_5 >= 0.03
    assert candidate_metrics.source_bound_violation_rate == 0
    assert candidate_metrics.tenant_isolation_violation_rate == 0
    assert decision.verdict == "ADOPT"
    assert decision.reasons == ()
    assert decision.as_dict()["verdict"] == "ADOPT"


def test_foreign_unknown_duplicate_and_wrong_revision_are_hard_rejects() -> None:
    _, chunks, cases, baseline, _, latency, _ = _benchmark()
    case = cases[0]
    foreign_id = next(
        chunk_id for chunk_id, chunk in chunks.items() if chunk.tenant_id != case.tenant_id
    )
    wrong_revision = CorpusChunk(
        chunk_id="wrong-revision",
        tenant_id=case.tenant_id,
        doc_id=case.allowed_sources[0][0],
        source_revision=f"document:{'9' * 64}",
        chunk_index=2,
        heading="Wrong revision",
        text="Synthetic wrong-revision candidate.",
    )
    contaminated_chunks = {**chunks, wrong_revision.chunk_id: wrong_revision}
    contaminated = {
        case.query_id: (
            RankedResult(foreign_id, 0.99),
            RankedResult("unknown", 0.98),
            RankedResult(wrong_revision.chunk_id, 0.97),
            RankedResult(next(iter(case.relevance)), 0.96),
            RankedResult(next(iter(case.relevance)), 0.95),
        )
    }
    baseline_metrics = evaluate_rankings(
        [case], contaminated_chunks, {case.query_id: baseline[case.query_id]}, latency_ms={case.query_id: 10}
    )
    candidate_metrics = evaluate_rankings(
        [case], contaminated_chunks, contaminated, latency_ms={case.query_id: 10}
    )
    decision = decide_reranker(baseline_metrics, candidate_metrics)

    assert candidate_metrics.source_bound_violation_rate > 0
    assert candidate_metrics.tenant_isolation_violation_rate > 0
    assert decision.verdict == "REJECT"
    assert "source_bound_violation_rate_must_be_zero" in decision.reasons
    assert "tenant_isolation_violation_rate_must_be_zero" in decision.reasons


def test_failures_abstention_false_confidence_and_cost_are_reported() -> None:
    _, chunks, cases, baseline, _, latency, _ = _benchmark()
    selected = cases[:3]
    rankings = {
        selected[0].query_id: (),
        selected[1].query_id: (RankedResult(selected[1].relevance.keys().__iter__().__next__(), 0.99),),
        selected[2].query_id: (RankedResult(next(iter(selected[2].relevance)), 0.99),),
    }
    # Force query 1 to be confidently irrelevant by selecting its zero-gain chunk.
    irrelevant_id = next(chunk_id for chunk_id, gain in selected[1].relevance.items() if gain == 0)
    rankings[selected[1].query_id] = (RankedResult(irrelevant_id, 0.99),)
    metrics = evaluate_rankings(
        selected,
        chunks,
        rankings,
        latency_ms={
            case.query_id: latency[case.query_id]
            for case in selected
            if case.query_id != selected[2].query_id
        },
        failed_query_ids=frozenset({selected[2].query_id}),
        estimated_cost_usd=0.01,
    )

    assert metrics.abstention_rate == pytest.approx(1 / 3)
    assert metrics.false_confident_rate == pytest.approx(1 / 3)
    assert metrics.failure_rate == pytest.approx(1 / 3)
    assert metrics.estimated_cost_usd == 0.01


def test_score_sorting_is_stable_and_rejects_non_finite_values() -> None:
    _, chunks, *_ = _benchmark()
    same_doc = [chunk for chunk in chunks.values() if chunk.doc_id == "ru-fire-a"]
    results = [RankedResult(chunk.chunk_id, 0.5) for chunk in reversed(same_doc)]
    ranked = rank_by_score(results, chunks)
    assert [result.chunk_id for result in ranked] == ["ru-fire-a-0", "ru-fire-a-1"]

    with pytest.raises(ValueError, match="finite"):
        rank_by_score([RankedResult("ru-fire-a-0", float("nan"))], chunks)


def test_latency_and_quality_regressions_reject_candidate() -> None:
    _, chunks, cases, baseline, candidate, baseline_latency, candidate_latency = _benchmark()
    baseline_metrics = evaluate_rankings(cases, chunks, baseline, latency_ms=baseline_latency)
    slow_latency = {query_id: value + 300 for query_id, value in candidate_latency.items()}
    candidate_metrics = evaluate_rankings(cases, chunks, baseline, latency_ms=slow_latency)
    decision = decide_reranker(baseline_metrics, candidate_metrics)

    assert decision.verdict == "REJECT"
    assert "mrr_at_5_gain_below_0_03" in decision.reasons
    assert "ndcg_at_5_gain_below_0_03" in decision.reasons
    assert "latency_p95_increase_exceeds_150_ms" in decision.reasons


def test_evaluator_sorts_rankings_and_requires_complete_latency() -> None:
    _, chunks, cases, _, _, _, _ = _benchmark()
    case = cases[0]
    answer = next(chunk_id for chunk_id, gain in case.relevance.items() if gain > 0)
    noise = next(chunk_id for chunk_id, gain in case.relevance.items() if gain == 0)
    metrics = evaluate_rankings(
        [case],
        chunks,
        {case.query_id: (RankedResult(answer, 0.2), RankedResult(noise, 0.9))},
        latency_ms={case.query_id: 10},
    )
    assert metrics.mrr_at_5 == 0.5
    with pytest.raises(ValueError, match="complete_latency"):
        evaluate_rankings([case], chunks, {}, latency_ms={})


def test_unknown_failure_id_and_mismatched_benchmark_are_rejected() -> None:
    _, chunks, cases, baseline, candidate, baseline_latency, candidate_latency = _benchmark()
    with pytest.raises(ValueError, match="failed_query_ids"):
        evaluate_rankings(
            cases,
            chunks,
            baseline,
            latency_ms=baseline_latency,
            failed_query_ids=frozenset({"not-in-corpus"}),
        )
    baseline_metrics = evaluate_rankings(cases, chunks, baseline, latency_ms=baseline_latency)
    candidate_metrics = evaluate_rankings(
        cases[1:],
        chunks,
        {case.query_id: candidate[case.query_id] for case in cases[1:]},
        latency_ms={case.query_id: candidate_latency[case.query_id] for case in cases[1:]},
    )
    with pytest.raises(ValueError, match="benchmark_identity_mismatch"):
        decide_reranker(baseline_metrics, candidate_metrics)

    with pytest.raises(ValueError, match="invalid_evaluation_metrics"):
        decide_reranker(
            replace(baseline_metrics, benchmark_id="x" * 64),
            candidate_metrics,
        )


def test_abstention_and_false_confidence_are_adoption_gates() -> None:
    _, chunks, cases, baseline, candidate, baseline_latency, candidate_latency = _benchmark()
    baseline_metrics = evaluate_rankings(cases, chunks, baseline, latency_ms=baseline_latency)
    abstaining = dict(candidate)
    abstaining[cases[0].query_id] = ()
    abstaining_metrics = evaluate_rankings(cases, chunks, abstaining, latency_ms=candidate_latency)
    abstaining_decision = decide_reranker(baseline_metrics, abstaining_metrics)
    assert "candidate_abstention_rate_exceeds_0_05" in abstaining_decision.reasons

    confidently_wrong = dict(candidate)
    noise = next(chunk_id for chunk_id, gain in cases[0].relevance.items() if gain == 0)
    confidently_wrong[cases[0].query_id] = (RankedResult(noise, 0.99),)
    wrong_metrics = evaluate_rankings(cases, chunks, confidently_wrong, latency_ms=candidate_latency)
    wrong_decision = decide_reranker(baseline_metrics, wrong_metrics)
    assert "candidate_false_confident_rate_must_be_zero" in wrong_decision.reasons
