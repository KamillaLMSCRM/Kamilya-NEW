"""Tenant-scoped deterministic lexical retrieval for document chunks."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

_TOKEN_RE = re.compile(r"[^\W_]{3,}", re.UNICODE)
_KAZAKH_MARKER_RE = re.compile(r"[әғқңөұүһі]", re.IGNORECASE)
_RUSSIAN_SUFFIXES = tuple(
    sorted(
        {
            # Russian noun/adjective endings. This intentionally is not a
            # general morphological analyzer: it only collapses high-value
            # search inflections while retaining a stem of at least 4 chars.
            "иями", "ями", "ами", "его", "ого", "ему", "ому",
            "иях", "ах", "ях", "ов", "ев", "ие", "ия", "ии",
            "ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые",
            "ую", "юю", "ем", "им", "ым", "ом", "их", "ых",
            "а", "я", "ы", "и", "у", "ю", "е", "о",
        },
        key=len,
        reverse=True,
    )
)
_KAZAKH_SUFFIXES = tuple(
    sorted(
        {
            "дардың", "дердің", "лардың", "лердің",
            "тарға", "терге", "ларға", "лерге",
            "ларда", "лерде", "лары", "лері", "тары", "тері",
            "лар", "лер", "дар", "дер", "тар", "тер",
            "ның", "нің", "ға", "ге", "қа", "ке", "да", "де", "та", "те",
            "ды", "ді", "ты", "ті",
        },
        key=len,
        reverse=True,
    )
)
_BM25_K1 = 1.2
_BM25_B = 0.75
_HEADING_TERM_WEIGHT = 2.0
_METADATA_TERM_WEIGHT = 1.5
_EXACT_PHRASE_BOOST = 1.5
_PREFERRED_HEADING_BOOST = 2.0


class LexicalChunkStore(Protocol):
    async def get_all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> list[tuple[str, dict[str, object]]]: ...


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk_id: str
    doc_id: str
    doc_name: str
    headings: tuple[str, ...]
    text: str
    score: float
    matched_terms: tuple[str, ...]
    preferred_heading_match: bool
    exact_phrase_match: bool
    heading_term_match: bool
    metadata_term_match: bool
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_revision: str = ""
    embedding_native_dimensions: int | None = None
    embedding_storage_dimensions: int | None = None
    content_sha256: str = ""
    source_revision: str = ""
    indexed_at: str = ""
    chunk_index: int | None = None


@dataclass(frozen=True, slots=True)
class _Candidate:
    chunk_id: str
    doc_id: str
    doc_name: str
    headings: tuple[str, ...]
    text: str
    body_tokens: tuple[str, ...]
    heading_tokens: tuple[str, ...]
    metadata_tokens: tuple[str, ...]
    embedding_provider: str
    embedding_model: str
    embedding_revision: str
    embedding_native_dimensions: int | None
    embedding_storage_dimensions: int | None
    content_sha256: str
    source_revision: str
    indexed_at: str
    chunk_index: int | None


def _normalize_token(token: str, suffixes: Sequence[str]) -> str:
    normalized = token.casefold().replace("ё", "е")
    for suffix in suffixes:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized


def _tokens(value: str) -> tuple[str, ...]:
    suffixes = _KAZAKH_SUFFIXES if _KAZAKH_MARKER_RE.search(value) else _RUSSIAN_SUFFIXES
    return tuple(_normalize_token(token, suffixes) for token in _TOKEN_RE.findall(value))


def _parse_headings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return ()
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _matches_preferred_heading(
    headings: Sequence[str],
    preferred_headings: Sequence[str],
) -> bool:
    for preferred in preferred_headings:
        preferred_tokens = set(_tokens(preferred))
        if not preferred_tokens:
            continue
        for heading in headings:
            heading_tokens = set(_tokens(heading))
            if not heading_tokens:
                continue
            overlap = len(preferred_tokens & heading_tokens)
            if overlap / min(len(preferred_tokens), len(heading_tokens)) >= 0.8:
                return True
    return False


def _validated_scope(tenant_id: str, doc_ids: Sequence[str], limit: int) -> tuple[str, list[str]]:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id_required")
    if type(limit) is not int or limit <= 0:
        raise ValueError("invalid_lexical_limit")
    if not isinstance(doc_ids, Sequence) or isinstance(doc_ids, str | bytes):
        raise ValueError("selected_doc_ids_required")

    normalized: list[str] = []
    for doc_id in doc_ids:
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ValueError("invalid_selected_doc_id")
        value = doc_id.strip()
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("selected_doc_ids_required")
    return tenant_id.strip(), normalized


async def retrieve_lexical_hits(
    store: LexicalChunkStore,
    queries: Sequence[str],
    *,
    tenant_id: str,
    doc_ids: Sequence[str],
    preferred_headings: Sequence[str] | None = None,
    limit: int = 10,
) -> list[LexicalHit]:
    """Rank traceable chunks inside an explicit tenant and document boundary."""

    tenant, selected_doc_ids = _validated_scope(tenant_id, doc_ids, limit)
    query_terms = tuple(
        dict.fromkeys(
            token
            for query in queries
            if isinstance(query, str)
            for token in _tokens(query)
        )
    )
    if not query_terms:
        return []

    postgres_search = getattr(store, "search_full_text", None)
    if callable(postgres_search):
        rows = await postgres_search(
            query_text=" ".join(query for query in queries if isinstance(query, str)),
            doc_ids=selected_doc_ids,
            tenant_id=tenant,
            limit=min(100, max(limit * 3, 30)),
        )
    else:
        rows = await store.get_all_chunks(
            doc_ids=selected_doc_ids,
            tenant_id=tenant,
        )
    allowed_doc_ids = frozenset(selected_doc_ids)
    raw_candidates: list[_Candidate] = []
    for text, metadata in rows:
        if not isinstance(metadata, Mapping) or not isinstance(text, str) or not text.strip():
            continue
        chunk_id = metadata.get("chunk_id")
        doc_id = metadata.get("doc_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            continue
        if not isinstance(doc_id, str) or doc_id not in allowed_doc_ids:
            continue
        headings = _parse_headings(metadata.get("headings", ()))
        raw_candidates.append(
            _Candidate(
                chunk_id=chunk_id.strip(),
                doc_id=doc_id,
                doc_name=str(metadata.get("doc_name") or ""),
                headings=headings,
                text=text,
                body_tokens=_tokens(text),
                heading_tokens=_tokens(" ".join(headings)),
                metadata_tokens=_tokens(str(metadata.get("doc_name") or "")),
                embedding_provider=str(metadata.get("embedding_provider") or ""),
                embedding_model=str(metadata.get("embedding_model") or ""),
                embedding_revision=str(metadata.get("embedding_revision") or ""),
                embedding_native_dimensions=metadata.get("embedding_native_dimensions"),
                embedding_storage_dimensions=metadata.get("embedding_storage_dimensions"),
                content_sha256=str(metadata.get("embedding_content_sha256") or ""),
                source_revision=str(metadata.get("embedding_source_revision") or ""),
                indexed_at=str(metadata.get("embedding_indexed_at") or ""),
                chunk_index=metadata.get("chunk_index"),
            )
        )

    # Stable sorting before de-duplication prevents database row order from
    # changing the result if corrupted input repeats a chunk identity.
    raw_candidates.sort(key=lambda item: (item.doc_id, item.chunk_id, item.text))
    candidates: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in raw_candidates:
        identity = (candidate.doc_id, candidate.chunk_id)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(candidate)
    if not candidates:
        return []

    document_count = len(candidates)
    average_length = max(
        sum(max(len(candidate.body_tokens), 1) for candidate in candidates) / document_count,
        1.0,
    )
    document_frequency = {
        term: sum(
            1
            for candidate in candidates
            if term in set(candidate.body_tokens) | set(candidate.heading_tokens)
            | set(candidate.metadata_tokens)
        )
        for term in query_terms
    }
    preferred = tuple(preferred_headings or ())
    hits: list[LexicalHit] = []
    for candidate in candidates:
        body_counts = Counter(candidate.body_tokens)
        heading_counts = Counter(candidate.heading_tokens)
        metadata_counts = Counter(candidate.metadata_tokens)
        matched_terms = tuple(
            term
            for term in query_terms
            if body_counts[term] or heading_counts[term] or metadata_counts[term]
        )
        if not matched_terms:
            continue

        length = max(len(candidate.body_tokens), 1)
        score = 0.0
        for term in matched_terms:
            frequency = (
                body_counts[term]
                + _HEADING_TERM_WEIGHT * heading_counts[term]
                + _METADATA_TERM_WEIGHT * metadata_counts[term]
            )
            frequency_normalizer = frequency + _BM25_K1 * (
                1.0 - _BM25_B + _BM25_B * length / average_length
            )
            inverse_frequency = math.log(
                1.0
                + (document_count - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            score += inverse_frequency * frequency * (_BM25_K1 + 1.0) / frequency_normalizer

        normalized_phrase = " ".join(query_terms)
        exact_phrase_match = normalized_phrase in " ".join(candidate.body_tokens)
        heading_term_match = any(heading_counts[term] for term in query_terms)
        metadata_term_match = any(metadata_counts[term] for term in query_terms)
        if exact_phrase_match:
            score += _EXACT_PHRASE_BOOST
        preferred_match = _matches_preferred_heading(candidate.headings, preferred)
        if preferred_match:
            score += _PREFERRED_HEADING_BOOST
        hits.append(
            LexicalHit(
                chunk_id=candidate.chunk_id,
                doc_id=candidate.doc_id,
                doc_name=candidate.doc_name,
                headings=candidate.headings,
                text=candidate.text,
                score=score,
                matched_terms=matched_terms,
                preferred_heading_match=preferred_match,
                exact_phrase_match=exact_phrase_match,
                heading_term_match=heading_term_match,
                metadata_term_match=metadata_term_match,
                embedding_provider=candidate.embedding_provider,
                embedding_model=candidate.embedding_model,
                embedding_revision=candidate.embedding_revision,
                embedding_native_dimensions=candidate.embedding_native_dimensions,
                embedding_storage_dimensions=candidate.embedding_storage_dimensions,
                content_sha256=candidate.content_sha256,
                source_revision=candidate.source_revision,
                indexed_at=candidate.indexed_at,
                chunk_index=candidate.chunk_index,
            )
        )

    if any(hit.preferred_heading_match for hit in hits):
        hits = [hit for hit in hits if hit.preferred_heading_match]
    hits.sort(
        key=lambda hit: (
            -int(hit.preferred_heading_match),
            -hit.score,
            hit.doc_id,
            hit.chunk_id,
        )
    )
    return hits[:limit]


__all__ = ["LexicalHit", "retrieve_lexical_hits"]
