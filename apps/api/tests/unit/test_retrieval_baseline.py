import json
from pathlib import Path

import pytest

from app.modules.ai.hybrid_retrieval import (
    RankedRetrievalItem,
    RetrievalBoundary,
    fuse_ranked_results,
)
from app.modules.ai.lexical_retrieval import retrieve_lexical_hits
from app.modules.ai.retrieval_baseline import (
    BaselineCase,
    BaselineHit,
    compare_baselines,
    evaluate_baseline,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "kb_rag_hbr04_baseline.json"


@pytest.mark.asyncio
async def test_versioned_ru_kk_baseline_is_traceable_and_leak_free() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    documents = {document["doc_id"]: document for document in payload["documents"]}

    class Store:
        async def get_all_chunks(self, *, doc_ids, tenant_id):
            rows = []
            for doc_id in doc_ids:
                document = documents.get(doc_id)
                if not document or document["tenant_id"] != tenant_id:
                    continue
                for chunk in document["chunks"]:
                    if chunk["revision"] != document["active_revision"]:
                        continue
                    rows.append((chunk["text"], {
                        "chunk_id": chunk["chunk_id"], "doc_id": doc_id,
                        "doc_name": f"{doc_id}.md", "headings": chunk["headings"],
                        "embedding_provider": "synthetic", "embedding_model": "synthetic",
                        "embedding_revision": "v1", "embedding_native_dimensions": 3,
                        "embedding_storage_dimensions": 4,
                        "embedding_content_sha256": "a" * 64,
                        "embedding_source_revision": chunk["revision"],
                        "embedding_indexed_at": "2026-08-23T00:00:00+00:00",
                        "chunk_index": chunk["index"],
                    }))
            return rows

    store = Store()
    cases = []
    rankings = {}
    semantic_only_rankings = {}
    latencies = {}
    for raw_case in payload["cases"]:
        allowed_sources = tuple(
            (doc_id, documents[doc_id]["active_revision"])
            for doc_id in raw_case["doc_ids"]
            if doc_id in documents and documents[doc_id]["tenant_id"] == raw_case["tenant_id"]
        )
        cases.append(BaselineCase(
            query_id=raw_case["query_id"], query_text=raw_case["query"],
            language=raw_case["language"], category=raw_case["category"],
            tenant_id=raw_case["tenant_id"], allowed_sources=allowed_sources,
            expected_chunk_ids=tuple(raw_case["expected"]),
            should_abstain=raw_case["should_abstain"],
        ))
        lexical_hits = await retrieve_lexical_hits(
            store, [raw_case["query"]], tenant_id=raw_case["tenant_id"],
            doc_ids=raw_case["doc_ids"], limit=10,
        )
        lexical = [RankedRetrievalItem(
            chunk_id=hit.chunk_id, doc_id=hit.doc_id, doc_name=hit.doc_name,
            tenant_id=raw_case["tenant_id"], headings=hit.headings, text=hit.text,
            source="lexical", query=raw_case["query"],
            lexical_score=hit.score,
            embedding_provider=hit.embedding_provider,
            embedding_model=hit.embedding_model,
            embedding_revision=hit.embedding_revision,
            embedding_native_dimensions=hit.embedding_native_dimensions,
            embedding_storage_dimensions=hit.embedding_storage_dimensions,
            content_sha256=hit.content_sha256,
            source_revision=hit.source_revision,
            indexed_at=hit.indexed_at,
            chunk_index=hit.chunk_index,
        ) for hit in lexical_hits]
        semantic = []
        for chunk_id in raw_case["semantic"]:
            document = next(
                document for document in payload["documents"]
                if any(chunk["chunk_id"] == chunk_id for chunk in document["chunks"])
            )
            chunk = next(chunk for chunk in document["chunks"] if chunk["chunk_id"] == chunk_id)
            semantic.append(RankedRetrievalItem(
                chunk_id=chunk_id, doc_id=document["doc_id"], doc_name=f"{document['doc_id']}.md",
                tenant_id=raw_case["tenant_id"], headings=tuple(chunk["headings"]),
                text=chunk["text"], source="semantic",
                query=raw_case["query"], semantic_distance=0.2,
                embedding_provider="synthetic", embedding_model="synthetic",
                embedding_revision="v1", embedding_native_dimensions=3,
                embedding_storage_dimensions=4, content_sha256="a" * 64,
                source_revision=chunk["revision"],
                indexed_at="2026-08-23T00:00:00+00:00",
                chunk_index=chunk["index"],
            ))
        boundary = RetrievalBoundary(
            tenant_id=raw_case["tenant_id"],
            allowed_doc_ids=frozenset(raw_case["doc_ids"]),
            allowed_sources=frozenset(allowed_sources),
        )
        fused = fuse_ranked_results(
            [semantic],
            lexical,
            limit=10,
            boundary=boundary,
        )
        rankings[raw_case["query_id"]] = tuple(BaselineHit(
            chunk_id=hit.chunk_id, tenant_id=raw_case["tenant_id"], doc_id=hit.doc_id,
            source_revision=hit.source_revision,
            citation=f"synthetic/{hit.doc_id}.md:1",
        ) for hit in fused)
        semantic_only_rankings[raw_case["query_id"]] = tuple(BaselineHit(
            chunk_id=item.chunk_id, tenant_id=raw_case["tenant_id"], doc_id=item.doc_id,
            source_revision=item.source_revision,
            citation=f"synthetic/{item.doc_id}.md:1",
        ) for item in semantic)
        latencies[raw_case["query_id"]] = raw_case["latency_ms"]

    report = evaluate_baseline(cases, rankings, latency_ms=latencies)
    assert report.case_count == 7
    assert report.answerable_case_count == 5
    assert report.recall_at_5 == 1.0
    assert report.recall_at_10 == 1.0
    assert report.mrr_at_10 == 1.0
    assert report.revision_correctness == 1.0
    assert report.citation_completeness == 1.0
    assert report.abstention_accuracy == 1.0
    assert report.leakage_rate == 0.0
    assert report.latency_p95_ms == 24.0
    assert report.estimated_cost_usd == 0.0
    assert len(report.benchmark_id) == 64

    semantic_report = evaluate_baseline(
        cases,
        semantic_only_rankings,
        latency_ms=latencies,
    )
    comparison = compare_baselines(semantic_report, report)
    assert semantic_report.recall_at_5 == 0.2
    assert semantic_report.mrr_at_10 == 0.2
    assert comparison.recall_at_5_delta == pytest.approx(0.8)
    assert comparison.recall_at_10_delta == pytest.approx(0.8)
    assert comparison.mrr_at_10_delta == pytest.approx(0.8)
    assert comparison.leakage_rate_delta == 0.0
    assert comparison.latency_p95_delta_ms == 0.0
    assert comparison.estimated_cost_delta_usd == 0.0
    assert comparison.quality_improved is True
    assert comparison.no_regression is True
    assert comparison.passed is True


def test_baseline_rejects_incomplete_latency() -> None:
    case = BaselineCase(
        query_id="q", query_text="query", language="ru", category="exact",
        tenant_id="tenant", allowed_sources=(("doc", "document:" + "a" * 64),),
        expected_chunk_ids=("chunk",), should_abstain=False,
    )
    with pytest.raises(ValueError, match="complete_baseline_latency"):
        evaluate_baseline([case], {}, latency_ms={})


def test_baseline_comparison_rejects_incompatible_corpus() -> None:
    report = evaluate_baseline(
        [BaselineCase(
            query_id="q", query_text="query", language="ru", category="exact",
            tenant_id="tenant", allowed_sources=(("doc", "rev"),),
            expected_chunk_ids=("chunk",), should_abstain=False,
        )],
        {"q": ()},
        latency_ms={"q": 1.0},
    )
    incompatible = report.__class__(**{**report.as_dict(), "benchmark_id": "f" * 64})
    with pytest.raises(ValueError, match="incompatible_baseline_reports"):
        compare_baselines(report, incompatible)
