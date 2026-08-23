"""Transactional persistence seam for the pure embedding reindex lifecycle."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.modules.ai.embedding_reindex_lifecycle import (
    ChunkManifestEntry,
    CleanupDirective,
    IndexedChunkEvidence,
    ReindexRun,
    ReindexState,
    RevisionBinding,
)
from app.modules.ai.embedding_space import EmbeddingSpace


class EmbeddingReindexPersistenceError(RuntimeError):
    """Stable sanitized failure for a rejected persistence operation."""


def _space_payload(space: EmbeddingSpace) -> dict[str, object]:
    return {
        "provider": space.provider,
        "model": space.model,
        "revision": space.revision,
        "dimensions": space.dimensions,
    }


def _binding_payload(binding: RevisionBinding | None) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "revision_id": binding.revision_id,
        "source_revision": binding.source_revision,
        "space": _space_payload(binding.space),
        "manifest_sha256": binding.manifest_sha256,
    }


def serialize_reindex_run(run: ReindexRun) -> dict[str, object]:
    """Serialize only validated lifecycle state; no document text is persisted."""
    return {
        "tenant_id": run.tenant_id,
        "document_id": run.document_id,
        "run_id": run.run_id,
        "state": run.state.value,
        "generation": run.generation,
        "active": _binding_payload(run.active),
        "candidate": _binding_payload(run.candidate),
        "previous_active": _binding_payload(run.previous_active),
        "manifest": [
            {
                "chunk_id": item.chunk_id,
                "chunk_index": item.chunk_index,
                "content_sha256": item.content_sha256,
            }
            for item in run.manifest
        ],
        "completed": [
            {
                "chunk_id": item.chunk_id,
                "chunk_index": item.chunk_index,
                "content_sha256": item.content_sha256,
                "source_revision": item.source_revision,
                "space": _space_payload(item.space),
            }
            for item in run.completed
        ],
        "events": [list(item) for item in run.events],
    }


def _space(value: dict[str, Any]) -> EmbeddingSpace:
    return EmbeddingSpace(
        provider=value["provider"],
        model=value["model"],
        revision=value["revision"],
        dimensions=value["dimensions"],
    )


def _binding(value: dict[str, Any] | None) -> RevisionBinding | None:
    if value is None:
        return None
    return RevisionBinding(
        revision_id=value["revision_id"],
        source_revision=value["source_revision"],
        space=_space(value["space"]),
        manifest_sha256=value["manifest_sha256"],
    )


def deserialize_reindex_run(payload: dict[str, Any]) -> ReindexRun:
    """Revalidate all persisted data through immutable lifecycle types."""
    active = _binding(payload["active"])
    candidate = _binding(payload["candidate"])
    if active is None or candidate is None:
        raise EmbeddingReindexPersistenceError("invalid_persisted_reindex_binding")
    return ReindexRun(
        tenant_id=payload["tenant_id"],
        document_id=payload["document_id"],
        run_id=payload["run_id"],
        state=ReindexState(payload["state"]),
        generation=payload["generation"],
        active=active,
        candidate=candidate,
        previous_active=_binding(payload.get("previous_active")),
        manifest=tuple(ChunkManifestEntry(**item) for item in payload["manifest"]),
        completed=tuple(
            IndexedChunkEvidence(
                chunk_id=item["chunk_id"],
                chunk_index=item["chunk_index"],
                content_sha256=item["content_sha256"],
                source_revision=item["source_revision"],
                space=_space(item["space"]),
            )
            for item in payload["completed"]
        ),
        events=tuple((item[0], item[1]) for item in payload["events"]),
    )


def _first(result):
    row = result.first()
    return row


def _row_value(row, name: str, index: int):
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping[name]
    return row[index]


class EmbeddingReindexRepository:
    """Persist lifecycle transitions atomically in a caller-owned transaction."""

    async def _set_tenant(self, session, tenant_id: str) -> None:
        await session.execute(
            text("SELECT set_current_tenant(:tenant_id)"),
            {"tenant_id": tenant_id},
        )

    async def stage(self, session, run: ReindexRun) -> None:
        if run.state is not ReindexState.STAGED or run.generation != 0:
            raise EmbeddingReindexPersistenceError("reindex_stage_state_required")
        await self._set_tenant(session, run.tenant_id)
        pointer_result = await session.execute(
            text(
                """
                SELECT active_revision_id
                FROM embedding_active_revisions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND document_id = CAST(:document_id AS uuid)
                FOR UPDATE
                """
            ),
            {"tenant_id": run.tenant_id, "document_id": run.document_id},
        )
        pointer = _first(pointer_result)
        if pointer is None:
            tagged = await session.execute(
                text(
                    """
                    UPDATE document_embeddings
                    SET embedding_index_revision_id = :active_revision_id,
                        embedding_reindex_run_id = :run_id
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND doc_id = CAST(:document_id AS uuid)
                      AND embedding_index_revision_id IS NULL
                      AND embedding_reindex_run_id IS NULL
                      AND embedding_provenance_state = 'verified'
                      AND embedding_source_revision = :active_source_revision
                    """
                ),
                {
                    "tenant_id": run.tenant_id,
                    "document_id": run.document_id,
                    "active_revision_id": run.active.revision_id,
                    "active_source_revision": run.active.source_revision,
                    "run_id": run.run_id,
                },
            )
            if tagged.rowcount < 1:
                raise EmbeddingReindexPersistenceError(
                    "active_embedding_revision_not_found"
                )
            await session.execute(
                text(
                    """
                    INSERT INTO embedding_active_revisions (
                        tenant_id, document_id, active_revision_id, generation
                    ) VALUES (
                        CAST(:tenant_id AS uuid), CAST(:document_id AS uuid),
                        :active_revision_id, 1
                    )
                    """
                ),
                {
                    "tenant_id": run.tenant_id,
                    "document_id": run.document_id,
                    "active_revision_id": run.active.revision_id,
                },
            )
        elif _row_value(pointer, "active_revision_id", 0) != run.active.revision_id:
            raise EmbeddingReindexPersistenceError("active_revision_conflict")

        payload = json.dumps(serialize_reindex_run(run), sort_keys=True)
        await session.execute(
            text(
                """
                INSERT INTO embedding_reindex_runs (
                    tenant_id, document_id, run_id, state, generation,
                    active_revision_id, candidate_revision_id, previous_revision_id,
                    candidate_manifest_sha256, expected_chunk_count,
                    completed_chunk_count, lifecycle_payload
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:document_id AS uuid), :run_id,
                    :state, :generation, :active_revision_id, :candidate_revision_id,
                    NULL, :candidate_manifest_sha256, :expected_chunk_count, 0,
                    CAST(:lifecycle_payload AS jsonb)
                )
                """
            ),
            {
                "tenant_id": run.tenant_id,
                "document_id": run.document_id,
                "run_id": run.run_id,
                "state": run.state.value,
                "generation": run.generation,
                "active_revision_id": run.active.revision_id,
                "candidate_revision_id": run.candidate.revision_id,
                "candidate_manifest_sha256": run.candidate.manifest_sha256,
                "expected_chunk_count": len(run.manifest),
                "lifecycle_payload": payload,
            },
        )

    async def load(self, session, *, tenant_id: str, document_id: str, run_id: str) -> ReindexRun:
        await self._set_tenant(session, tenant_id)
        result = await session.execute(
            text(
                """
                SELECT lifecycle_payload
                FROM embedding_reindex_runs
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND document_id = CAST(:document_id AS uuid)
                  AND run_id = :run_id
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id, "run_id": run_id},
        )
        row = _first(result)
        if row is None:
            raise EmbeddingReindexPersistenceError("reindex_run_not_found")
        payload = _row_value(row, "lifecycle_payload", 0)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return deserialize_reindex_run(payload)

    async def _verify_candidate_rows(self, session, run: ReindexRun) -> None:
        result = await session.execute(
            text(
                """
                SELECT chunk_index, embedding_content_sha256
                FROM document_embeddings
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND doc_id = CAST(:document_id AS uuid)
                  AND embedding_index_revision_id = :candidate_revision_id
                  AND embedding_reindex_run_id = :run_id
                  AND embedding_provenance_state = 'verified'
                  AND embedding_source_revision = :source_revision
                  AND embedding_provider = :provider
                  AND embedding_model = :model
                  AND embedding_revision = :embedding_revision
                  AND embedding_native_dimensions = :dimensions
                  AND embedding_storage_dimensions = :dimensions
                ORDER BY chunk_index ASC
                """
            ),
            {
                "tenant_id": run.tenant_id,
                "document_id": run.document_id,
                "candidate_revision_id": run.candidate.revision_id,
                "run_id": run.run_id,
                "source_revision": run.candidate.source_revision,
                "provider": run.candidate.space.provider,
                "model": run.candidate.space.model,
                "embedding_revision": run.candidate.space.revision,
                "dimensions": run.candidate.space.dimensions,
            },
        )
        observed = tuple(
            (
                _row_value(row, "chunk_index", 0),
                _row_value(row, "embedding_content_sha256", 1),
            )
            for row in result.fetchall()
        )
        expected = tuple(
            (item.chunk_index, item.content_sha256) for item in run.manifest
        )
        if observed != expected:
            raise EmbeddingReindexPersistenceError("candidate_manifest_readback_mismatch")

    async def persist_transition(
        self,
        session,
        *,
        before: ReindexRun,
        after: ReindexRun,
    ) -> None:
        identity_before = (before.tenant_id, before.document_id, before.run_id)
        identity_after = (after.tenant_id, after.document_id, after.run_id)
        if identity_before != identity_after:
            raise EmbeddingReindexPersistenceError("reindex_identity_changed")
        if after is before:
            return
        if after.generation != before.generation + 1 or len(after.events) != len(before.events) + 1:
            raise EmbeddingReindexPersistenceError("invalid_reindex_transition_generation")
        if after.events[:-1] != before.events:
            raise EmbeddingReindexPersistenceError("invalid_reindex_event_history")

        await self._set_tenant(session, before.tenant_id)
        event_id, event_sha256 = after.events[-1]
        existing_event = await session.execute(
            text(
                """
                SELECT event_sha256, generation
                FROM embedding_reindex_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND document_id = CAST(:document_id AS uuid)
                  AND run_id = :run_id
                  AND event_id = :event_id
                """
            ),
            {
                "tenant_id": before.tenant_id,
                "document_id": before.document_id,
                "run_id": before.run_id,
                "event_id": event_id,
            },
        )
        event_row = _first(existing_event)
        if event_row is not None:
            if (
                _row_value(event_row, "event_sha256", 0) != event_sha256
                or _row_value(event_row, "generation", 1) != after.generation
            ):
                raise EmbeddingReindexPersistenceError("reindex_event_conflict")
            return

        if after.state in {ReindexState.READY, ReindexState.ACTIVE}:
            await self._verify_candidate_rows(session, after)

        payload = json.dumps(serialize_reindex_run(after), sort_keys=True)
        updated = await session.execute(
            text(
                """
                UPDATE embedding_reindex_runs
                SET state = :new_state,
                    generation = :new_generation,
                    active_revision_id = :new_active_revision_id,
                    previous_revision_id = :previous_revision_id,
                    completed_chunk_count = :completed_chunk_count,
                    lifecycle_payload = CAST(:lifecycle_payload AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND document_id = CAST(:document_id AS uuid)
                  AND run_id = :run_id
                  AND state = :expected_state
                  AND generation = :expected_generation
                RETURNING generation
                """
            ),
            {
                "tenant_id": before.tenant_id,
                "document_id": before.document_id,
                "run_id": before.run_id,
                "new_state": after.state.value,
                "new_generation": after.generation,
                "new_active_revision_id": after.active.revision_id,
                "previous_revision_id": (
                    after.previous_active.revision_id if after.previous_active else None
                ),
                "completed_chunk_count": len(after.completed),
                "lifecycle_payload": payload,
                "expected_state": before.state.value,
                "expected_generation": before.generation,
            },
        )
        if _first(updated) is None:
            raise EmbeddingReindexPersistenceError("stale_reindex_generation")

        if after.state in {ReindexState.ACTIVE, ReindexState.ROLLED_BACK}:
            pointer = await session.execute(
                text(
                    """
                    UPDATE embedding_active_revisions
                    SET active_revision_id = :new_active_revision_id,
                        generation = generation + 1,
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND document_id = CAST(:document_id AS uuid)
                      AND active_revision_id = :expected_active_revision_id
                    RETURNING generation
                    """
                ),
                {
                    "tenant_id": before.tenant_id,
                    "document_id": before.document_id,
                    "new_active_revision_id": after.active.revision_id,
                    "expected_active_revision_id": before.active.revision_id,
                },
            )
            if _first(pointer) is None:
                raise EmbeddingReindexPersistenceError("active_revision_conflict")

        await session.execute(
            text(
                """
                INSERT INTO embedding_reindex_events (
                    tenant_id, document_id, run_id, event_id, event_sha256, generation
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:document_id AS uuid), :run_id,
                    :event_id, :event_sha256, :generation
                )
                """
            ),
            {
                "tenant_id": before.tenant_id,
                "document_id": before.document_id,
                "run_id": before.run_id,
                "event_id": event_id,
                "event_sha256": event_sha256,
                "generation": after.generation,
            },
        )

    async def cleanup(self, session, *, run: ReindexRun, directive: CleanupDirective) -> int:
        if run.state is not ReindexState.CLEANED:
            raise EmbeddingReindexPersistenceError("cleaned_reindex_state_required")
        if (
            directive.tenant_id != run.tenant_id
            or directive.document_id != run.document_id
            or directive.run_id != run.run_id
            or directive.expected_generation != run.generation
        ):
            raise EmbeddingReindexPersistenceError("cleanup_directive_mismatch")
        await self._set_tenant(session, run.tenant_id)
        result = await session.execute(
            text(
                """
                DELETE FROM document_embeddings AS doomed
                WHERE doomed.tenant_id = CAST(:tenant_id AS uuid)
                  AND doomed.doc_id = CAST(:document_id AS uuid)
                  AND doomed.embedding_index_revision_id = ANY(CAST(:revision_ids AS text[]))
                  AND doomed.embedding_index_revision_id <> (
                      SELECT active.active_revision_id
                      FROM embedding_active_revisions AS active
                      WHERE active.tenant_id = doomed.tenant_id
                        AND active.document_id = doomed.doc_id
                  )
                """
            ),
            {
                "tenant_id": run.tenant_id,
                "document_id": run.document_id,
                "revision_ids": list(directive.revision_ids),
            },
        )
        return result.rowcount


__all__ = [
    "EmbeddingReindexPersistenceError",
    "EmbeddingReindexRepository",
    "deserialize_reindex_run",
    "serialize_reindex_run",
]
