"""Pure fail-closed lifecycle for controlled embedding reindex cutovers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from app.modules.ai.embedding_space import EmbeddingSpace

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_REVISION_RE = re.compile(r"^document:[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class ReindexLifecycleError(ValueError):
    """Stable sanitized failure for a rejected reindex transition."""


class ReindexState(str, Enum):
    STAGED = "staged"
    RUNNING = "running"
    READY = "ready"
    ACTIVE = "active"
    ABORTED = "aborted"
    ROLLED_BACK = "rolled_back"
    CLEANED = "cleaned"


def _safe_id(value: object, code: str) -> str:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ReindexLifecycleError(code)
    return value


def _sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ReindexLifecycleError(code)
    return value


def _source_revision(value: object) -> str:
    if not isinstance(value, str) or not SOURCE_REVISION_RE.fullmatch(value):
        raise ReindexLifecycleError("invalid_reindex_source_revision")
    return value


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChunkManifestEntry:
    chunk_id: str
    chunk_index: int
    content_sha256: str

    def __post_init__(self) -> None:
        _safe_id(self.chunk_id, "invalid_manifest_chunk_id")
        if type(self.chunk_index) is not int or self.chunk_index < 0:
            raise ReindexLifecycleError("invalid_manifest_chunk_index")
        _sha256(self.content_sha256, "invalid_manifest_content_sha256")


@dataclass(frozen=True, slots=True)
class RevisionBinding:
    revision_id: str
    source_revision: str
    space: EmbeddingSpace
    manifest_sha256: str

    def __post_init__(self) -> None:
        _safe_id(self.revision_id, "invalid_embedding_revision_id")
        _source_revision(self.source_revision)
        if not isinstance(self.space, EmbeddingSpace):
            raise ReindexLifecycleError("invalid_embedding_revision_space")
        _sha256(self.manifest_sha256, "invalid_embedding_manifest_sha256")


@dataclass(frozen=True, slots=True)
class IndexedChunkEvidence:
    chunk_id: str
    chunk_index: int
    content_sha256: str
    source_revision: str
    space: EmbeddingSpace

    def __post_init__(self) -> None:
        ChunkManifestEntry(self.chunk_id, self.chunk_index, self.content_sha256)
        _source_revision(self.source_revision)
        if not isinstance(self.space, EmbeddingSpace):
            raise ReindexLifecycleError("invalid_indexed_chunk_space")


@dataclass(frozen=True, slots=True)
class CleanupDirective:
    tenant_id: str
    document_id: str
    run_id: str
    revision_ids: tuple[str, ...]
    expected_generation: int

    def __post_init__(self) -> None:
        _safe_id(self.tenant_id, "invalid_cleanup_tenant")
        _safe_id(self.document_id, "invalid_cleanup_document")
        _safe_id(self.run_id, "invalid_cleanup_run")
        if not self.revision_ids or len(set(self.revision_ids)) != len(self.revision_ids):
            raise ReindexLifecycleError("invalid_cleanup_revisions")
        for revision_id in self.revision_ids:
            _safe_id(revision_id, "invalid_cleanup_revision")
        if type(self.expected_generation) is not int or self.expected_generation < 0:
            raise ReindexLifecycleError("invalid_cleanup_generation")


@dataclass(frozen=True, slots=True)
class ReindexRun:
    tenant_id: str
    document_id: str
    run_id: str
    state: ReindexState
    generation: int
    active: RevisionBinding
    candidate: RevisionBinding
    previous_active: RevisionBinding | None
    manifest: tuple[ChunkManifestEntry, ...]
    completed: tuple[IndexedChunkEvidence, ...]
    events: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _safe_id(self.tenant_id, "invalid_reindex_tenant")
        _safe_id(self.document_id, "invalid_reindex_document")
        _safe_id(self.run_id, "invalid_reindex_run_id")
        if not isinstance(self.state, ReindexState):
            raise ReindexLifecycleError("invalid_reindex_state")
        if type(self.generation) is not int or self.generation < 0:
            raise ReindexLifecycleError("invalid_reindex_generation")
        if not isinstance(self.active, RevisionBinding) or not isinstance(
            self.candidate, RevisionBinding
        ):
            raise ReindexLifecycleError("invalid_reindex_binding")
        if (
            self.state
            in {
                ReindexState.STAGED,
                ReindexState.RUNNING,
                ReindexState.READY,
                ReindexState.ABORTED,
                ReindexState.ROLLED_BACK,
            }
            and self.active.revision_id == self.candidate.revision_id
        ):
            raise ReindexLifecycleError("candidate_revision_must_be_distinct")
        if self.state is ReindexState.ACTIVE and self.active != self.candidate:
            raise ReindexLifecycleError("active_cutover_binding_mismatch")
        if not self.manifest:
            raise ReindexLifecycleError("empty_reindex_manifest")
        manifest_ids = [entry.chunk_id for entry in self.manifest]
        manifest_indices = [entry.chunk_index for entry in self.manifest]
        if len(set(manifest_ids)) != len(manifest_ids):
            raise ReindexLifecycleError("duplicate_manifest_chunk_id")
        if len(set(manifest_indices)) != len(manifest_indices):
            raise ReindexLifecycleError("duplicate_manifest_chunk_index")
        if tuple(sorted(self.manifest, key=lambda item: (item.chunk_index, item.chunk_id))) != self.manifest:
            raise ReindexLifecycleError("manifest_must_be_sorted")
        completed_ids = [entry.chunk_id for entry in self.completed]
        if len(set(completed_ids)) != len(completed_ids):
            raise ReindexLifecycleError("duplicate_completed_chunk")
        event_ids = [event_id for event_id, _ in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ReindexLifecycleError("duplicate_reindex_event")


def _space_payload(space: EmbeddingSpace) -> dict[str, object]:
    return {
        "provider": space.provider,
        "model": space.model,
        "revision": space.revision,
        "dimensions": space.dimensions,
    }


def _manifest_digest(
    *,
    tenant_id: str,
    document_id: str,
    source_revision: str,
    space: EmbeddingSpace,
    manifest: Sequence[ChunkManifestEntry],
) -> str:
    return _digest(
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "source_revision": source_revision,
            "space": _space_payload(space),
            "chunks": [
                {
                    "chunk_id": entry.chunk_id,
                    "chunk_index": entry.chunk_index,
                    "content_sha256": entry.content_sha256,
                }
                for entry in manifest
            ],
        }
    )


def stage_reindex(
    *,
    tenant_id: str,
    document_id: str,
    run_id: str,
    active: RevisionBinding,
    candidate_revision_id: str,
    candidate_source_revision: str,
    candidate_space: EmbeddingSpace,
    manifest: Sequence[ChunkManifestEntry],
) -> ReindexRun:
    tenant = _safe_id(tenant_id, "invalid_reindex_tenant")
    document = _safe_id(document_id, "invalid_reindex_document")
    run = _safe_id(run_id, "invalid_reindex_run_id")
    candidate_id = _safe_id(candidate_revision_id, "invalid_embedding_revision_id")
    source_revision = _source_revision(candidate_source_revision)
    if not isinstance(active, RevisionBinding) or not isinstance(candidate_space, EmbeddingSpace):
        raise ReindexLifecycleError("invalid_reindex_binding")
    ordered_manifest = tuple(sorted(manifest, key=lambda item: (item.chunk_index, item.chunk_id)))
    if not ordered_manifest:
        raise ReindexLifecycleError("empty_reindex_manifest")
    candidate = RevisionBinding(
        revision_id=candidate_id,
        source_revision=source_revision,
        space=candidate_space,
        manifest_sha256=_manifest_digest(
            tenant_id=tenant,
            document_id=document,
            source_revision=source_revision,
            space=candidate_space,
            manifest=ordered_manifest,
        ),
    )
    return ReindexRun(
        tenant_id=tenant,
        document_id=document,
        run_id=run,
        state=ReindexState.STAGED,
        generation=0,
        active=active,
        candidate=candidate,
        previous_active=None,
        manifest=ordered_manifest,
        completed=(),
        events=(),
    )


def _event(
    run: ReindexRun,
    *,
    event_id: str,
    operation: str,
    payload: object,
    expected_generation: int,
) -> tuple[str, bool]:
    event = _safe_id(event_id, "invalid_reindex_event_id")
    digest = _digest({"operation": operation, "payload": payload})
    known = dict(run.events)
    if event in known:
        if known[event] != digest:
            raise ReindexLifecycleError("reindex_event_conflict")
        return digest, True
    if expected_generation != run.generation:
        raise ReindexLifecycleError("stale_reindex_generation")
    return digest, False


def record_indexed_batch(
    run: ReindexRun,
    evidence: Sequence[IndexedChunkEvidence],
    *,
    event_id: str,
    expected_generation: int,
) -> ReindexRun:
    if run.state not in {ReindexState.STAGED, ReindexState.RUNNING}:
        raise ReindexLifecycleError("reindex_batch_not_allowed")
    ordered = tuple(sorted(evidence, key=lambda item: (item.chunk_index, item.chunk_id)))
    if not ordered:
        raise ReindexLifecycleError("empty_reindex_batch")
    payload = [
        {
            "chunk_id": item.chunk_id,
            "chunk_index": item.chunk_index,
            "content_sha256": item.content_sha256,
            "source_revision": item.source_revision,
            "space": _space_payload(item.space),
        }
        for item in ordered
    ]
    event_digest, replay = _event(
        run,
        event_id=event_id,
        operation="record_batch",
        payload=payload,
        expected_generation=expected_generation,
    )
    if replay:
        return run

    manifest = {entry.chunk_id: entry for entry in run.manifest}
    completed = {entry.chunk_id: entry for entry in run.completed}
    for item in ordered:
        expected = manifest.get(item.chunk_id)
        if expected is None:
            raise ReindexLifecycleError("unexpected_reindex_chunk")
        if (
            item.chunk_index != expected.chunk_index
            or item.content_sha256 != expected.content_sha256
        ):
            raise ReindexLifecycleError("reindex_chunk_manifest_mismatch")
        if item.source_revision != run.candidate.source_revision:
            raise ReindexLifecycleError("mixed_reindex_source_revision")
        if item.space != run.candidate.space:
            raise ReindexLifecycleError("mixed_reindex_embedding_space")
        existing = completed.get(item.chunk_id)
        if existing is not None and existing != item:
            raise ReindexLifecycleError("conflicting_reindex_chunk_evidence")
        completed[item.chunk_id] = item

    complete = len(completed) == len(manifest)
    return replace(
        run,
        state=ReindexState.READY if complete else ReindexState.RUNNING,
        generation=run.generation + 1,
        completed=tuple(
            sorted(completed.values(), key=lambda item: (item.chunk_index, item.chunk_id))
        ),
        events=run.events + ((event_id, event_digest),),
    )


def active_query_binding(run: ReindexRun) -> RevisionBinding:
    """Return the only revision that queries are allowed to use."""
    return run.active


def activate_candidate(
    run: ReindexRun,
    *,
    event_id: str,
    expected_generation: int,
    expected_candidate_revision_id: str,
    expected_manifest_sha256: str,
) -> ReindexRun:
    payload = {
        "candidate_revision_id": expected_candidate_revision_id,
        "manifest_sha256": expected_manifest_sha256,
    }
    event_digest, replay = _event(
        run,
        event_id=event_id,
        operation="activate",
        payload=payload,
        expected_generation=expected_generation,
    )
    if replay:
        return run
    if run.state is not ReindexState.READY:
        raise ReindexLifecycleError("incomplete_reindex_cannot_activate")
    if expected_candidate_revision_id != run.candidate.revision_id:
        raise ReindexLifecycleError("candidate_revision_activation_mismatch")
    if expected_manifest_sha256 != run.candidate.manifest_sha256:
        raise ReindexLifecycleError("candidate_manifest_activation_mismatch")
    return replace(
        run,
        state=ReindexState.ACTIVE,
        generation=run.generation + 1,
        previous_active=run.active,
        active=run.candidate,
        events=run.events + ((event_id, event_digest),),
    )


def abort_reindex(
    run: ReindexRun,
    *,
    event_id: str,
    expected_generation: int,
) -> ReindexRun:
    event_digest, replay = _event(
        run,
        event_id=event_id,
        operation="abort",
        payload={"candidate_revision_id": run.candidate.revision_id},
        expected_generation=expected_generation,
    )
    if replay:
        return run
    if run.state not in {ReindexState.STAGED, ReindexState.RUNNING, ReindexState.READY}:
        raise ReindexLifecycleError("reindex_abort_not_allowed")
    return replace(
        run,
        state=ReindexState.ABORTED,
        generation=run.generation + 1,
        events=run.events + ((event_id, event_digest),),
    )


def rollback_cutover(
    run: ReindexRun,
    *,
    event_id: str,
    expected_generation: int,
) -> ReindexRun:
    event_digest, replay = _event(
        run,
        event_id=event_id,
        operation="rollback",
        payload={"active_revision_id": run.active.revision_id},
        expected_generation=expected_generation,
    )
    if replay:
        return run
    if run.state is not ReindexState.ACTIVE or run.previous_active is None:
        raise ReindexLifecycleError("reindex_rollback_not_allowed")
    return replace(
        run,
        state=ReindexState.ROLLED_BACK,
        generation=run.generation + 1,
        active=run.previous_active,
        events=run.events + ((event_id, event_digest),),
    )


def finalize_cleanup(
    run: ReindexRun,
    *,
    event_id: str,
    expected_generation: int,
) -> tuple[ReindexRun, CleanupDirective]:
    if run.state is ReindexState.ACTIVE:
        if run.previous_active is None:
            raise ReindexLifecycleError("missing_previous_active_revision")
        revision_ids = (run.previous_active.revision_id,)
    elif run.state in {ReindexState.ABORTED, ReindexState.ROLLED_BACK}:
        revision_ids = (run.candidate.revision_id,)
    else:
        raise ReindexLifecycleError("reindex_cleanup_not_allowed")
    event_digest, replay = _event(
        run,
        event_id=event_id,
        operation="cleanup",
        payload={"revision_ids": revision_ids},
        expected_generation=expected_generation,
    )
    if replay:
        raise ReindexLifecycleError("cleanup_event_already_finalized")
    cleaned = replace(
        run,
        state=ReindexState.CLEANED,
        generation=run.generation + 1,
        events=run.events + ((event_id, event_digest),),
    )
    return cleaned, CleanupDirective(
        tenant_id=run.tenant_id,
        document_id=run.document_id,
        run_id=run.run_id,
        revision_ids=revision_ids,
        expected_generation=cleaned.generation,
    )


__all__ = [
    "ChunkManifestEntry",
    "CleanupDirective",
    "IndexedChunkEvidence",
    "ReindexLifecycleError",
    "ReindexRun",
    "ReindexState",
    "RevisionBinding",
    "abort_reindex",
    "activate_candidate",
    "active_query_binding",
    "finalize_cleanup",
    "record_indexed_batch",
    "rollback_cutover",
    "stage_reindex",
]
