"""Deterministic semantic compatibility analysis for course source documents."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

DEFAULT_CLUSTER_THRESHOLD = 0.68
MIXED_THRESHOLD = 0.35


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
) -> CompatibilityAnalysis:
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        raise HTTPException(status_code=422, detail={"code": "documents_required"})

    documents = (
        await db.execute(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.id.in_(unique_ids),
            )
        )
    ).scalars().all()
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
