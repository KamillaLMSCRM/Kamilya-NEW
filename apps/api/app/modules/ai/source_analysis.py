"""Deterministic semantic compatibility analysis for course source documents."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

DEFAULT_CLUSTER_THRESHOLD = 0.68
MIXED_THRESHOLD = 0.35

# Allowlist of index states eligible for AI course generation. Any other
# state (pending/processing, failed, unknown future values) is rejected with
# a user-safe error instead of being silently tolerated.
GENERATION_READY_INDEX_STATUSES = frozenset({"ready", "partial"})

# Kazakh-specific Cyrillic letters (ә ғ қ ң ө ұ ү һ і). Their presence is the
# only conservative signal separating Kazakh from Russian inside the Cyrillic
# script; without them the sample is classified as Russian only when clearly
# Cyrillic-dominant, otherwise "unknown".
KAZAKH_CYRILLIC_EXTRA = set("әғқңөұүһіѴѵ")


def detect_script(codepoint: str) -> str:
    """Map one character to a coarse script family used for language mixing."""
    ordinal = ord(codepoint)
    if 0x0400 <= ordinal <= 0x04FF:
        return "cyrillic"
    if 0x0041 <= ordinal <= 0x007A:
        return "latin"
    if 0x4E00 <= ordinal <= 0x9FFF:
        return "cjk"
    if 0x0600 <= ordinal <= 0x06FF:
        return "arabic"
    return "other"


def dominant_language(sample: str) -> str | None:
    """Conservatively classify one text sample.

    Returns "kk" only when Kazakh-specific letters are present, "ru" for
    Cyrillic-dominant samples without them, coarse script names for other
    scripts, and None (unknown) when the sample has no script signal.
    """
    counts: dict[str, int] = {}
    for char in sample:
        script = detect_script(char)
        if script in ("cyrillic", "latin", "cjk", "arabic"):
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return None
    top = max(counts.items(), key=lambda item: item[1])[0]
    if top == "cyrillic":
        if any(char in KAZAKH_CYRILLIC_EXTRA for char in sample):
            return "kk"
        return "ru"
    return top


async def document_script_languages(
    db: AsyncSession,
    tenant_id: UUID,
    document_ids: list[UUID],
) -> dict[UUID, str | None]:
    """Detect a conservative language per document from verified chunk text.

    Sampling is deterministic: per document it reads the chunk with the
    lowest ``chunk_index`` that (a) belongs to the document's currently
    active embedding index revision, (b) is provenance-verified, and
    (c) matches the document's current content revision. Unreadable or
    unsampled documents map to None (unknown), never to a guess.
    """
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        return {}
    placeholders = ", ".join(f":sid_{index}" for index in range(len(unique_ids)))
    params: dict[str, str] = {"tenant_id": str(tenant_id)}
    params.update({f"sid_{index}": str(document_id) for index, document_id in enumerate(unique_ids)})
    active_revision_clause = (
        "((document_embeddings.embedding_index_revision_id IS NULL AND NOT EXISTS ("
        "SELECT 1 FROM embedding_active_revisions AS active_index "
        "WHERE active_index.tenant_id = document_embeddings.tenant_id "
        "AND active_index.document_id = document_embeddings.doc_id"
        ")) OR document_embeddings.embedding_index_revision_id = ("
        "SELECT active_index.active_revision_id "
        "FROM embedding_active_revisions AS active_index "
        "WHERE active_index.tenant_id = document_embeddings.tenant_id "
        "AND active_index.document_id = document_embeddings.doc_id"
        "))"
    )
    rows = (
        await db.execute(
            text(
                "SELECT DISTINCT ON (document_embeddings.doc_id) "
                "document_embeddings.doc_id, document_embeddings.text "
                "FROM document_embeddings "
                "JOIN documents AS sampled_document ON ("
                "sampled_document.id::text = document_embeddings.doc_id "
                "AND sampled_document.tenant_id = document_embeddings.tenant_id) "
                "WHERE document_embeddings.tenant_id = :tenant_id "
                f"AND document_embeddings.doc_id IN ({placeholders}) "
                "AND document_embeddings.embedding_provenance_state = 'verified' "
                f"AND {active_revision_clause} "
                "AND document_embeddings.embedding_source_revision = 'document:' || ("
                "SELECT active_document.content_sha256 FROM documents AS active_document "
                "WHERE active_document.id::text = document_embeddings.doc_id "
                "AND active_document.tenant_id = document_embeddings.tenant_id"
                ") "
                "ORDER BY document_embeddings.doc_id, document_embeddings.chunk_index ASC"
            ),
            params,
        )
    ).all()
    sampled = {UUID(str(doc_id)): str(chunk_text or "") for doc_id, chunk_text in rows}
    return {
        UUID(str(document_id)): dominant_language(sampled[UUID(str(document_id))][:2000])
        if UUID(str(document_id)) in sampled
        else None
        for document_id in unique_ids
    }


@dataclass(frozen=True)
class DocumentVectorProfile:
    doc_id: UUID
    title: str
    filename: str
    vector: list[float]


@dataclass(frozen=True)
class SourceCluster:
    id: str
    label: str
    documents: tuple[DocumentVectorProfile, ...]
    cohesion: float


@dataclass(frozen=True)
class CompatibilityAnalysis:
    status: str
    score: float
    requires_decision: bool
    clusters: tuple[SourceCluster, ...]


@dataclass(frozen=True)
class CourseStructurePlan:
    requested_format: str
    resolved_format: str
    module_count: int
    lessons_per_module: int
    estimated_duration_minutes: int
    quiz_count: int
    reason_codes: tuple[str, ...]


def recommend_course_structure(
    *,
    total_chunks: int,
    document_count: int,
    course_format: Literal["automatic", "brief", "standard", "detailed"] = "automatic",
    manual_modules: int | None = None,
) -> CourseStructurePlan:
    """Build a deterministic course shape from aggregate source volume."""
    chunks = max(1, int(total_chunks or 0))
    documents = max(1, int(document_count or 0))
    requested = course_format
    if manual_modules is not None:
        modules = max(1, min(10, int(manual_modules)))
        resolved = "custom"
        reasons = ("manual_module_override",)
    else:
        if course_format == "automatic":
            if chunks <= 6 and documents <= 2:
                resolved = "brief"
            elif chunks >= 24 or documents >= 4:
                resolved = "detailed"
            else:
                resolved = "standard"
        else:
            resolved = course_format
        divisor = {"brief": 8, "standard": 5, "detailed": 3}[resolved]
        minimum = {"brief": 1, "standard": 2, "detailed": 3}[resolved]
        maximum = {"brief": 3, "standard": 6, "detailed": 10}[resolved]
        modules = max(minimum, min(maximum, math.ceil(chunks / divisor), chunks))
        reasons = (
            "source_volume",
            "multiple_documents" if documents > 1 else "single_document",
            f"format_{resolved}",
        )
    lessons_per_module = max(1, min(6, math.ceil(chunks / modules)))
    duration = max(10, int(math.ceil((chunks * 4) / 5.0) * 5))
    return CourseStructurePlan(
        requested_format=requested,
        resolved_format=resolved,
        module_count=modules,
        lessons_per_module=lessons_per_module,
        estimated_duration_minutes=duration,
        quiz_count=modules,
        reason_codes=reasons,
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _minimum_similarity(
    left: list[DocumentVectorProfile],
    right: list[DocumentVectorProfile],
) -> float:
    return min(
        cosine_similarity(a.vector, b.vector)
        for a in left
        for b in right
    )


def _cluster_cohesion(items: list[DocumentVectorProfile]) -> float:
    if len(items) < 2:
        return 1.0
    return min(
        cosine_similarity(items[i].vector, items[j].vector)
        for i in range(len(items))
        for j in range(i + 1, len(items))
    )


def _cluster_label(items: list[DocumentVectorProfile]) -> str:
    labels = [item.title.strip() or item.filename for item in items]
    if len(labels) == 1:
        return labels[0]
    return " / ".join(labels[:2]) + (f" +{len(labels) - 2}" if len(labels) > 2 else "")


def analyze_profiles(
    profiles: list[DocumentVectorProfile],
    *,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
) -> CompatibilityAnalysis:
    if not profiles:
        raise ValueError("At least one document profile is required")

    clusters: list[list[DocumentVectorProfile]] = [[profile] for profile in profiles]
    while True:
        best: tuple[float, int, int] | None = None
        for left_idx in range(len(clusters)):
            for right_idx in range(left_idx + 1, len(clusters)):
                similarity = _minimum_similarity(clusters[left_idx], clusters[right_idx])
                if similarity >= cluster_threshold and (best is None or similarity > best[0]):
                    best = (similarity, left_idx, right_idx)
        if best is None:
            break
        _, left_idx, right_idx = best
        clusters[left_idx] = clusters[left_idx] + clusters[right_idx]
        del clusters[right_idx]

    source_clusters = tuple(
        SourceCluster(
            id=f"group-{index + 1}",
            label=_cluster_label(items),
            documents=tuple(items),
            cohesion=round(_cluster_cohesion(items), 4),
        )
        for index, items in enumerate(clusters)
    )

    if len(profiles) == 1:
        score = 1.0
    else:
        score = min(
            cosine_similarity(profiles[i].vector, profiles[j].vector)
            for i in range(len(profiles))
            for j in range(i + 1, len(profiles))
        )
    if len(source_clusters) == 1:
        status = "compatible"
    else:
        cross_max = max(
            cosine_similarity(a.vector, b.vector)
            for left_idx, left in enumerate(source_clusters)
            for right in source_clusters[left_idx + 1 :]
            for a in left.documents
            for b in right.documents
        )
        status = "mixed" if cross_max >= MIXED_THRESHOLD else "incompatible"

    return CompatibilityAnalysis(
        status=status,
        score=round(score, 4),
        requires_decision=len(source_clusters) > 1,
        clusters=source_clusters,
    )


def _parse_vector(value: str) -> list[float]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("Invalid document embedding centroid")
    return [float(item) for item in parsed]


async def analyze_document_set(
    db: AsyncSession,
    tenant_id: UUID,
    document_ids: list[UUID],
    *,
    lock_for_update: bool = False,
) -> CompatibilityAnalysis:
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        raise HTTPException(status_code=422, detail={"code": "documents_required"})
    document_query = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.id.in_(unique_ids),
        Document.lifecycle_status == "active",
    )
    if lock_for_update:
        document_query = document_query.with_for_update()
    documents = (await db.execute(document_query)).scalars().all()
    by_id = {document.id: document for document in documents}
    missing = [str(document_id) for document_id in unique_ids if document_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"code": "documents_not_found", "document_ids": missing},
        )

    not_ready = [str(document.id) for document in documents if document.embedding_status != "success"]
    if not_ready:
        raise HTTPException(
            status_code=409,
            detail={"code": "documents_not_ready", "document_ids": not_ready},
        )

    index_failed = [
        str(document.id)
        for document in documents
        if document.index_status == "failed"
    ]
    index_not_ready = [
        str(document.id)
        for document in documents
        if document.index_status not in GENERATION_READY_INDEX_STATUSES
        and document.index_status != "failed"
    ]
    if index_not_ready:
        raise HTTPException(
            status_code=409,
            detail={"code": "documents_index_not_ready", "document_ids": index_not_ready},
        )
    if index_failed:
        raise HTTPException(
            status_code=409,
            detail={"code": "documents_index_failed", "document_ids": index_failed},
        )

    placeholders = ", ".join(f":doc_{index}" for index in range(len(unique_ids)))
    params = {"tenant_id": str(tenant_id)}
    params.update({f"doc_{index}": str(document_id) for index, document_id in enumerate(unique_ids)})
    rows = (
        await db.execute(
            text(
                "SELECT doc_id, AVG(embedding)::text AS centroid "
                "FROM document_embeddings "
                f"WHERE tenant_id = :tenant_id AND doc_id IN ({placeholders}) "
                "GROUP BY doc_id"
            ),
            params,
        )
    ).all()
    centroids = {UUID(str(doc_id)): _parse_vector(centroid) for doc_id, centroid in rows}
    missing_embeddings = [str(document_id) for document_id in unique_ids if document_id not in centroids]
    if missing_embeddings:
        raise HTTPException(
            status_code=409,
            detail={"code": "document_embeddings_missing", "document_ids": missing_embeddings},
        )

    profiles = [
        DocumentVectorProfile(
            doc_id=document_id,
            title=by_id[document_id].title,
            filename=by_id[document_id].filename,
            vector=centroids[document_id],
        )
        for document_id in unique_ids
    ]
    return analyze_profiles(profiles)


async def document_chunk_totals(
    db: AsyncSession,
    tenant_id: UUID,
    document_ids: list[UUID],
) -> dict[UUID, int]:
    """Return indexed-chunk totals for the given tenant-owned documents.

    Used for the aggregate multi-document budget check. Documents that are
    missing, not active, or unknown are simply absent from the result; the
    readiness gate in ``analyze_document_set`` is what rejects them with
    user-safe errors.
    """
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        return {}
    rows = (
        await db.execute(
            select(Document.id, Document.index_chunks_total).where(
                Document.tenant_id == tenant_id,
                Document.id.in_(unique_ids),
                Document.lifecycle_status == "active",
            )
        )
    ).all()
    return {doc_id: int(total or 0) for doc_id, total in rows}
