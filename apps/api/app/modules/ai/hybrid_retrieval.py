"""Boundary-aware reciprocal-rank fusion for semantic and lexical retrieval."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_REVISION_RE = re.compile(r"^document:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RankedRetrievalItem:
    chunk_id: str
    doc_id: str
    tenant_id: str
    doc_name: str
    headings: tuple[str, ...]
    text: str
    source: str
    query: str
    semantic_distance: float | None = None
    lexical_score: float | None = None
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_revision: str = ""
    embedding_native_dimensions: int | None = None
    embedding_storage_dimensions: int | None = None
    content_sha256: str = ""
    source_revision: str = ""
    indexed_at: str = ""
    chunk_index: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.chunk_id
            or not self.doc_id
            or not self.tenant_id
            or not self.text
            or not self.source_revision
        ):
            raise ValueError("untraceable_retrieval_item")
        if (
            not self.embedding_provider
            or not self.embedding_model
            or not self.embedding_revision
            or type(self.embedding_native_dimensions) is not int
            or self.embedding_native_dimensions <= 0
            or type(self.embedding_storage_dimensions) is not int
            or self.embedding_storage_dimensions < self.embedding_native_dimensions
            or not SHA256_RE.fullmatch(self.content_sha256)
            or not SOURCE_REVISION_RE.fullmatch(self.source_revision)
            or not self.indexed_at
            or type(self.chunk_index) is not int
            or self.chunk_index < 0
        ):
            raise ValueError("incomplete_retrieval_provenance")
        if self.source not in {"semantic", "lexical"}:
            raise ValueError("invalid_retrieval_source")
        if self.source == "semantic":
            if self.semantic_distance is None or not math.isfinite(self.semantic_distance):
                raise ValueError("invalid_semantic_distance")
        if self.source == "lexical":
            if self.lexical_score is None or not math.isfinite(self.lexical_score):
                raise ValueError("invalid_lexical_score")


@dataclass(frozen=True, slots=True)
class RetrievalBoundary:
    tenant_id: str
    allowed_doc_ids: frozenset[str] = frozenset()
    allowed_sources: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("retrieval_boundary_tenant_required")
        if any(not doc_id.strip() for doc_id in self.allowed_doc_ids):
            raise ValueError("invalid_retrieval_boundary_doc_id")
        if any(not doc_id.strip() or not revision.strip() for doc_id, revision in self.allowed_sources):
            raise ValueError("invalid_retrieval_boundary_source")
        if self.allowed_doc_ids and any(
            doc_id not in self.allowed_doc_ids for doc_id, _ in self.allowed_sources
        ):
            raise ValueError("retrieval_boundary_source_outside_documents")


@dataclass(frozen=True, slots=True)
class HybridRetrievalHit:
    chunk_id: str
    doc_id: str
    tenant_id: str
    doc_name: str
    headings: tuple[str, ...]
    text: str
    sources: tuple[str, ...]
    queries: tuple[str, ...]
    rrf_score: float
    semantic_distance: float | None
    lexical_score: float | None
    embedding_provider: str
    embedding_model: str
    embedding_revision: str
    embedding_native_dimensions: int | None
    embedding_storage_dimensions: int | None
    content_sha256: str
    source_revision: str
    indexed_at: str
    chunk_index: int | None


def _identity(item: RankedRetrievalItem) -> tuple[str, str]:
    return item.doc_id, item.chunk_id


def _same_content(left: RankedRetrievalItem, right: RankedRetrievalItem) -> bool:
    return (
        left.doc_name == right.doc_name
        and left.headings == right.headings
        and left.text == right.text
        and left.embedding_provider == right.embedding_provider
        and left.embedding_model == right.embedding_model
        and left.embedding_revision == right.embedding_revision
        and left.embedding_native_dimensions == right.embedding_native_dimensions
        and left.embedding_storage_dimensions == right.embedding_storage_dimensions
        and left.content_sha256 == right.content_sha256
        and left.source_revision == right.source_revision
        and left.indexed_at == right.indexed_at
        and left.chunk_index == right.chunk_index
    )


def fuse_ranked_results(
    semantic_rankings: Sequence[Sequence[RankedRetrievalItem]],
    lexical_ranking: Sequence[RankedRetrievalItem],
    *,
    limit: int = 10,
    rrf_k: int = 60,
    semantic_weight: float = 1.0,
    lexical_weight: float = 1.0,
    boundary: RetrievalBoundary | None = None,
    max_hits_per_document: int = 3,
) -> list[HybridRetrievalHit]:
    """Fuse independent channels inside an explicit tenant/document boundary.

    Exact-token, heading, and document-name signals are components of the
    lexical ranker rather than fake duplicate retrieval channels.
    """

    if type(limit) is not int or limit <= 0:
        raise ValueError("invalid_hybrid_limit")
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("invalid_rrf_k")
    if not math.isfinite(semantic_weight) or semantic_weight <= 0:
        raise ValueError("invalid_semantic_weight")
    if not math.isfinite(lexical_weight) or lexical_weight <= 0:
        raise ValueError("invalid_lexical_weight")
    if type(max_hits_per_document) is not int or max_hits_per_document <= 0:
        raise ValueError("invalid_per_document_cap")

    nonempty_semantic = [tuple(ranking) for ranking in semantic_rankings if ranking]
    rankings: list[tuple[tuple[RankedRetrievalItem, ...], float, str]] = []
    if nonempty_semantic:
        per_query_weight = semantic_weight / len(nonempty_semantic)
        rankings.extend(
            (ranking, per_query_weight, "semantic") for ranking in nonempty_semantic
        )
    if lexical_ranking:
        rankings.append((tuple(lexical_ranking), lexical_weight, "lexical"))
    if rankings and boundary is None:
        raise ValueError("retrieval_boundary_required")

    canonical: dict[tuple[str, str], RankedRetrievalItem] = {}
    scores: dict[tuple[str, str], float] = {}
    sources: dict[tuple[str, str], set[str]] = {}
    queries: dict[tuple[str, str], set[str]] = {}
    semantic_distances: dict[tuple[str, str], list[float]] = {}
    lexical_scores: dict[tuple[str, str], list[float]] = {}

    for ranking, weight, expected_source in rankings:
        seen_in_ranking: set[tuple[str, str]] = set()
        effective_rank = 0
        for item in ranking:
            if item.source != expected_source:
                raise ValueError("retrieval_channel_mismatch")
            if boundary is None or item.tenant_id != boundary.tenant_id:
                raise ValueError("retrieval_tenant_boundary_violation")
            if boundary.allowed_doc_ids and item.doc_id not in boundary.allowed_doc_ids:
                raise ValueError("retrieval_document_boundary_violation")
            if boundary.allowed_sources and (
                item.doc_id,
                item.source_revision,
            ) not in boundary.allowed_sources:
                raise ValueError("retrieval_revision_boundary_violation")
            identity = _identity(item)
            if identity in seen_in_ranking:
                continue
            seen_in_ranking.add(identity)
            effective_rank += 1
            existing = canonical.get(identity)
            if existing is not None and not _same_content(existing, item):
                raise ValueError("conflicting_retrieval_identity")
            canonical.setdefault(identity, item)
            scores[identity] = scores.get(identity, 0.0) + weight / (rrf_k + effective_rank)
            sources.setdefault(identity, set()).add(item.source)
            if item.query:
                queries.setdefault(identity, set()).add(item.query)
            if item.semantic_distance is not None:
                semantic_distances.setdefault(identity, []).append(item.semantic_distance)
            if item.lexical_score is not None:
                lexical_scores.setdefault(identity, []).append(item.lexical_score)

    hits = [
        HybridRetrievalHit(
            chunk_id=item.chunk_id,
            doc_id=item.doc_id,
            tenant_id=item.tenant_id,
            doc_name=item.doc_name,
            headings=item.headings,
            text=item.text,
            sources=tuple(sorted(sources[identity])),
            queries=tuple(sorted(queries.get(identity, set()))),
            rrf_score=scores[identity],
            semantic_distance=(
                min(semantic_distances[identity])
                if identity in semantic_distances
                else None
            ),
            lexical_score=(
                max(lexical_scores[identity])
                if identity in lexical_scores
                else None
            ),
            embedding_provider=item.embedding_provider,
            embedding_model=item.embedding_model,
            embedding_revision=item.embedding_revision,
            embedding_native_dimensions=item.embedding_native_dimensions,
            embedding_storage_dimensions=item.embedding_storage_dimensions,
            content_sha256=item.content_sha256,
            source_revision=item.source_revision,
            indexed_at=item.indexed_at,
            chunk_index=item.chunk_index,
        )
        for identity, item in canonical.items()
    ]
    hits.sort(
        key=lambda hit: (
            -hit.rrf_score,
            hit.semantic_distance if hit.semantic_distance is not None else math.inf,
            -(hit.lexical_score if hit.lexical_score is not None else -math.inf),
            hit.doc_id,
            hit.chunk_id,
        )
    )
    selected: list[HybridRetrievalHit] = []
    per_document: dict[str, int] = {}
    for hit in hits:
        count = per_document.get(hit.doc_id, 0)
        if count >= max_hits_per_document:
            continue
        selected.append(hit)
        per_document[hit.doc_id] = count + 1
        if len(selected) == limit:
            break
    return selected


__all__ = [
    "HybridRetrievalHit",
    "RankedRetrievalItem",
    "RetrievalBoundary",
    "fuse_ranked_results",
]
