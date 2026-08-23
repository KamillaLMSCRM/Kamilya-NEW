"""Fail-closed expansion of ranked chunks into bounded document context windows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast


class ContextWindowStore(Protocol):
    async def get_context_window(
        self, **kwargs: object
    ) -> list[tuple[str, dict[str, object]]]: ...


@dataclass(frozen=True, slots=True)
class ContextChunk:
    chunk_id: str
    doc_id: str
    tenant_id: str
    doc_name: str
    headings: tuple[str, ...]
    text: str
    source_revision: str
    chunk_index: int
    content_sha256: str
    indexed_at: str
    embedding_provider: str
    embedding_model: str
    embedding_revision: str
    embedding_native_dimensions: int
    embedding_storage_dimensions: int
    is_anchor: bool


@dataclass(frozen=True, slots=True)
class ContextWindow:
    anchor_chunk_id: str
    doc_id: str
    tenant_id: str
    source_revision: str
    anchor_chunk_index: int
    chunks: tuple[ContextChunk, ...]


def _document_revision(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("document:"):
        return False
    digest = value.removeprefix("document:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _headings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return ()
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _embedding_space(
    provider: object,
    model: object,
    revision: object,
    native_dimensions: object,
    storage_dimensions: object,
) -> tuple[str, str, str, int, int] | None:
    if (
        not isinstance(provider, str)
        or not provider
        or not isinstance(model, str)
        or not model
        or not isinstance(revision, str)
        or not revision
        or type(native_dimensions) is not int
        or native_dimensions <= 0
        or type(storage_dimensions) is not int
        or storage_dimensions < native_dimensions
    ):
        return None
    return provider, model, revision, native_dimensions, storage_dimensions


def _anchor_values(
    hit: object,
) -> tuple[str, str, str, str, int, tuple[str, str, str, int, int]]:
    chunk_id = getattr(hit, "chunk_id", None)
    doc_id = getattr(hit, "doc_id", None)
    tenant_id = getattr(hit, "tenant_id", None)
    source_revision = getattr(hit, "source_revision", None)
    chunk_index = getattr(hit, "chunk_index", None)
    embedding_space = _embedding_space(
        getattr(hit, "embedding_provider", None),
        getattr(hit, "embedding_model", None),
        getattr(hit, "embedding_revision", None),
        getattr(hit, "embedding_native_dimensions", None),
        getattr(hit, "embedding_storage_dimensions", None),
    )
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ValueError("incomplete_context_anchor")
    if not isinstance(doc_id, str) or not doc_id:
        raise ValueError("incomplete_context_anchor")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("incomplete_context_anchor")
    if not isinstance(source_revision, str) or not _document_revision(source_revision):
        raise ValueError("incomplete_context_anchor")
    if type(chunk_index) is not int or chunk_index < 0:
        raise ValueError("incomplete_context_anchor")
    if embedding_space is None:
        raise ValueError("incomplete_context_anchor")
    return chunk_id, doc_id, tenant_id, source_revision, chunk_index, embedding_space


async def expand_context_windows(
    store: ContextWindowStore,
    hits: Sequence[object],
    *,
    tenant_id: str,
    radius: int = 1,
    max_chars_per_window: int = 12_000,
) -> list[ContextWindow]:
    """Expand each ranked hit without crossing tenant, document, or revision."""

    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id_required")
    if type(radius) is not int or radius < 0 or radius > 3:
        raise ValueError("invalid_context_radius")
    if type(max_chars_per_window) is not int or max_chars_per_window <= 0:
        raise ValueError("invalid_context_budget")

    windows: list[ContextWindow] = []
    used_window_chunks: set[tuple[str, str, str, str]] = set()
    normalized_tenant = tenant_id.strip()
    for hit in hits:
        (
            anchor_id,
            doc_id,
            anchor_tenant,
            source_revision,
            anchor_index,
            anchor_space,
        ) = _anchor_values(hit)
        if anchor_tenant != normalized_tenant:
            raise ValueError("context_anchor_tenant_mismatch")
        rows = await store.get_context_window(
            doc_id=doc_id,
            source_revision=source_revision,
            chunk_index=anchor_index,
            radius=radius,
            tenant_id=normalized_tenant,
        )
        candidates: list[ContextChunk] = []
        seen: set[tuple[int, str]] = set()
        for text, metadata in rows:
            if not isinstance(text, str) or not text or not isinstance(metadata, Mapping):
                continue
            chunk_id = metadata.get("chunk_id")
            row_doc_id = metadata.get("doc_id")
            row_tenant_id = metadata.get("tenant_id")
            row_revision = metadata.get("embedding_source_revision")
            row_index = metadata.get("chunk_index")
            row_space = _embedding_space(
                metadata.get("embedding_provider"),
                metadata.get("embedding_model"),
                metadata.get("embedding_revision"),
                metadata.get("embedding_native_dimensions"),
                metadata.get("embedding_storage_dimensions"),
            )
            if (
                not isinstance(chunk_id, str)
                or not chunk_id
                or row_doc_id != doc_id
                or row_tenant_id != normalized_tenant
                or row_revision != source_revision
                or type(row_index) is not int
                or abs(row_index - anchor_index) > radius
                or not _sha256(metadata.get("embedding_content_sha256"))
                or not isinstance(metadata.get("embedding_indexed_at"), str)
                or not metadata.get("embedding_indexed_at")
                or row_space != anchor_space
            ):
                continue
            identity = (row_index, chunk_id)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(
                ContextChunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    tenant_id=normalized_tenant,
                    doc_name=str(metadata.get("doc_name") or ""),
                    headings=_headings(metadata.get("headings")),
                    text=text,
                    source_revision=source_revision,
                    chunk_index=row_index,
                    content_sha256=cast(str, metadata["embedding_content_sha256"]),
                    indexed_at=cast(str, metadata["embedding_indexed_at"]),
                    embedding_provider=cast(str, metadata["embedding_provider"]),
                    embedding_model=cast(str, metadata["embedding_model"]),
                    embedding_revision=cast(str, metadata["embedding_revision"]),
                    embedding_native_dimensions=cast(
                        int, metadata["embedding_native_dimensions"]
                    ),
                    embedding_storage_dimensions=cast(
                        int, metadata["embedding_storage_dimensions"]
                    ),
                    is_anchor=chunk_id == anchor_id,
                )
            )
        if not any(candidate.is_anchor for candidate in candidates):
            raise ValueError("context_anchor_not_found")

        candidates.sort(
            key=lambda candidate: (
                abs(candidate.chunk_index - anchor_index),
                candidate.chunk_index,
                candidate.chunk_id,
            )
        )
        selected: list[ContextChunk] = []
        used_chars = 0
        for candidate in candidates:
            if candidate.is_anchor or used_chars + len(candidate.text) <= max_chars_per_window:
                selected.append(candidate)
                used_chars += len(candidate.text)
        selected.sort(key=lambda candidate: (candidate.chunk_index, candidate.chunk_id))
        selected_identities = {
            (candidate.tenant_id, candidate.doc_id, candidate.source_revision, candidate.chunk_id)
            for candidate in selected
        }
        if used_window_chunks.intersection(selected_identities):
            raise ValueError("overlapping_context_windows")
        used_window_chunks.update(selected_identities)
        windows.append(
            ContextWindow(
                anchor_chunk_id=anchor_id,
                doc_id=doc_id,
                tenant_id=normalized_tenant,
                source_revision=source_revision,
                anchor_chunk_index=anchor_index,
                chunks=tuple(selected),
            )
        )
    return windows


__all__ = ["ContextChunk", "ContextWindow", "expand_context_windows"]
