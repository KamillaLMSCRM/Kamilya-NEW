import pytest

from app.modules.ai.hybrid_retrieval import (
    RankedRetrievalItem,
    RetrievalBoundary,
    fuse_ranked_results,
)


REVISION = "document:" + "a" * 64


def _boundary(*doc_ids, tenant_id="tenant-1", revision=False):
    docs = frozenset(doc_ids or ("doc-1",))
    return RetrievalBoundary(
        tenant_id=tenant_id,
        allowed_doc_ids=docs,
        allowed_sources=(
            frozenset((doc_id, REVISION) for doc_id in docs)
            if revision
            else frozenset()
        ),
    )


def _semantic(
    chunk_id,
    *,
    doc_id="doc-1",
    tenant_id="tenant-1",
    distance=0.2,
    query="query",
    text=None,
    revision=REVISION,
):
    return RankedRetrievalItem(
        chunk_id=chunk_id,
        doc_id=doc_id,
        tenant_id=tenant_id,
        doc_name="source.pdf",
        headings=("Раздел",),
        text=text or f"text-{chunk_id}",
        source="semantic",
        query=query,
        semantic_distance=distance,
        embedding_provider="synthetic",
        embedding_model="model",
        embedding_revision="r1",
        embedding_native_dimensions=3,
        embedding_storage_dimensions=4,
        content_sha256="b" * 64,
        source_revision=revision,
        indexed_at="2026-08-23T00:00:00Z",
        chunk_index=0,
    )


def _lexical(
    chunk_id,
    *,
    doc_id="doc-1",
    tenant_id="tenant-1",
    score=2.0,
    text=None,
    revision=REVISION,
):
    return RankedRetrievalItem(
        chunk_id=chunk_id,
        doc_id=doc_id,
        tenant_id=tenant_id,
        doc_name="source.pdf",
        headings=("Раздел",),
        text=text or f"text-{chunk_id}",
        source="lexical",
        query="lexical",
        lexical_score=score,
        embedding_provider="synthetic",
        embedding_model="model",
        embedding_revision="r1",
        embedding_native_dimensions=3,
        embedding_storage_dimensions=4,
        content_sha256="b" * 64,
        source_revision=revision,
        indexed_at="2026-08-23T00:00:00Z",
        chunk_index=0,
    )


def test_rrf_consensus_beats_single_channel_hits() -> None:
    hits = fuse_ranked_results(
        [[_semantic("a"), _semantic("b")]],
        [_lexical("b"), _lexical("c")],
        boundary=_boundary("doc-1", revision=True),
    )

    assert [hit.chunk_id for hit in hits] == ["b", "a", "c"]
    assert hits[0].sources == ("lexical", "semantic")
    assert hits[0].semantic_distance == 0.2
    assert hits[0].lexical_score == 2.0


def test_semantic_query_count_is_channel_normalized() -> None:
    hits = fuse_ranked_results(
        [[_semantic("a", query="q1")], [_semantic("a", query="q2")]],
        [_lexical("b")],
        boundary=_boundary("doc-1"),
    )

    assert hits[0].rrf_score == pytest.approx(hits[1].rrf_score)
    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].queries == ("q1", "q2")


def test_duplicate_inside_one_ranking_contributes_once() -> None:
    duplicate = _semantic("a")
    hits = fuse_ranked_results(
        [[duplicate, duplicate, _semantic("b")]],
        [],
        boundary=_boundary("doc-1"),
    )

    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].rrf_score == pytest.approx(1 / 61)
    assert hits[1].rrf_score == pytest.approx(1 / 62)


def test_ties_are_deterministic_and_limit_is_applied() -> None:
    hits = fuse_ranked_results(
        [[_semantic("b", doc_id="doc-1")]],
        [_lexical("a", doc_id="doc-1")],
        limit=1,
        boundary=_boundary("doc-1"),
    )

    assert [hit.chunk_id for hit in hits] == ["b"]


def test_conflicting_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="conflicting_retrieval_identity"):
        fuse_ranked_results(
            [[_semantic("same", text="first")]],
            [_lexical("same", text="different")],
            boundary=_boundary("doc-1"),
        )


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"limit": 0}, "invalid_hybrid_limit"),
        ({"rrf_k": 0}, "invalid_rrf_k"),
        ({"semantic_weight": 0}, "invalid_semantic_weight"),
        ({"lexical_weight": float("nan")}, "invalid_lexical_weight"),
        ({"max_hits_per_document": 0}, "invalid_per_document_cap"),
    ],
)
def test_invalid_fusion_configuration_fails_closed(kwargs, code) -> None:
    with pytest.raises(ValueError, match=code):
        fuse_ranked_results([], [], **kwargs)


def test_per_document_cap_preserves_cross_document_diversity() -> None:
    hits = fuse_ranked_results(
        [[
            _semantic("a", doc_id="doc-1", distance=0.1),
            _semantic("b", doc_id="doc-1", distance=0.2),
            _semantic("c", doc_id="doc-2", distance=0.3),
        ]],
        [],
        boundary=_boundary("doc-1", "doc-2"),
        max_hits_per_document=1,
        limit=3,
    )

    assert [(hit.doc_id, hit.chunk_id) for hit in hits] == [
        ("doc-1", "a"),
        ("doc-2", "c"),
    ]


@pytest.mark.parametrize(
    "item,boundary,error",
    [
        (_semantic("a", tenant_id="tenant-2"), _boundary("doc-1"), "retrieval_tenant_boundary_violation"),
        (_semantic("a", doc_id="doc-2"), _boundary("doc-1"), "retrieval_document_boundary_violation"),
        (
            _semantic("a", revision="document:" + "c" * 64),
            _boundary("doc-1", revision=True),
            "retrieval_revision_boundary_violation",
        ),
    ],
)
def test_tenant_document_and_revision_boundaries_fail_closed(item, boundary, error) -> None:
    with pytest.raises(ValueError, match=error):
        fuse_ranked_results([[item]], [], boundary=boundary)


def test_complete_trace_survives_consensus_fusion() -> None:
    hit = fuse_ranked_results(
        [[_semantic("a", query="semantic-q")]],
        [_lexical("a")],
        boundary=_boundary("doc-1", revision=True),
    )[0]

    assert hit.sources == ("lexical", "semantic")
    assert hit.tenant_id == "tenant-1"
    assert hit.queries == ("lexical", "semantic-q")
    assert hit.embedding_provider == "synthetic"
    assert hit.embedding_model == "model"
    assert hit.embedding_revision == "r1"
    assert hit.embedding_native_dimensions == 3
    assert hit.embedding_storage_dimensions == 4
    assert hit.content_sha256 == "b" * 64
    assert hit.source_revision == REVISION
    assert hit.indexed_at == "2026-08-23T00:00:00Z"
    assert hit.chunk_index == 0


def test_incomplete_provenance_cannot_be_reported_as_traceable() -> None:
    with pytest.raises(ValueError, match="incomplete_retrieval_provenance"):
        RankedRetrievalItem(
            chunk_id="chunk",
            doc_id="doc-1",
            tenant_id="tenant-1",
            doc_name="source.pdf",
            headings=(),
            text="synthetic",
            source="semantic",
            query="query",
            semantic_distance=0.1,
            source_revision=REVISION,
        )
