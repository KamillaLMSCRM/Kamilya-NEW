import json

import pytest

from app.modules.ai.embedding_reindex_lifecycle import (
    ChunkManifestEntry,
    IndexedChunkEvidence,
    ReindexState,
    RevisionBinding,
    activate_candidate,
    finalize_cleanup,
    record_indexed_batch,
    rollback_cutover,
    stage_reindex,
)
from app.modules.ai.embedding_reindex_store import (
    EmbeddingReindexPersistenceError,
    EmbeddingReindexRepository,
    deserialize_reindex_run,
    serialize_reindex_run,
)
from app.modules.ai.embedding_space import EmbeddingSpace


class _Result:
    def __init__(self, rows=(), *, rowcount=0):
        self.rows = list(rows)
        self.rowcount = rowcount

    def first(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Session:
    def __init__(self, responder):
        self.calls = []
        self.responder = responder

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        return self.responder(sql, params)


def _space():
    return EmbeddingSpace(
        provider="qwen-self-hosted",
        model="Qwen3-Embedding-8B",
        revision="Qwen3-Embedding-8B",
        dimensions=2,
    )


def _staged_run():
    space = _space()
    active = RevisionBinding(
        revision_id="rev-1",
        source_revision="document:" + "a" * 64,
        space=space,
        manifest_sha256="b" * 64,
    )
    manifest = (
        ChunkManifestEntry("chunk-0", 0, "c" * 64),
        ChunkManifestEntry("chunk-1", 1, "d" * 64),
    )
    return stage_reindex(
        tenant_id="11111111-1111-1111-1111-111111111111",
        document_id="22222222-2222-2222-2222-222222222222",
        run_id="run-1",
        active=active,
        candidate_revision_id="rev-2",
        candidate_source_revision="document:" + "e" * 64,
        candidate_space=space,
        manifest=manifest,
    )


def _ready_run(staged):
    evidence = tuple(
        IndexedChunkEvidence(
            chunk_id=item.chunk_id,
            chunk_index=item.chunk_index,
            content_sha256=item.content_sha256,
            source_revision=staged.candidate.source_revision,
            space=staged.candidate.space,
        )
        for item in staged.manifest
    )
    return record_indexed_batch(
        staged,
        evidence,
        event_id="batch-1",
        expected_generation=0,
    )


def test_persisted_payload_round_trips_through_validated_lifecycle_types() -> None:
    ready = _ready_run(_staged_run())

    restored = deserialize_reindex_run(
        json.loads(json.dumps(serialize_reindex_run(ready)))
    )

    assert restored == ready
    assert restored.state is ReindexState.READY


@pytest.mark.asyncio
async def test_stage_tags_legacy_active_rows_and_creates_pointer_without_commit() -> None:
    run = _staged_run()

    def respond(sql, _params):
        if "SELECT active_revision_id" in sql:
            return _Result()
        if "UPDATE document_embeddings" in sql:
            return _Result(rowcount=2)
        return _Result()

    session = _Session(respond)
    await EmbeddingReindexRepository().stage(session, run)

    sql = "\n".join(statement for statement, _ in session.calls)
    assert "FOR UPDATE" in sql
    assert "embedding_index_revision_id IS NULL" in sql
    assert "embedding_reindex_run_id IS NULL" in sql
    assert "INSERT INTO embedding_active_revisions" in sql
    assert "INSERT INTO embedding_reindex_runs" in sql
    run_params = next(
        params
        for statement, params in session.calls
        if "INSERT INTO embedding_reindex_runs" in statement
    )
    assert run_params["state"] == "staged"
    assert run_params["expected_chunk_count"] == 2


@pytest.mark.asyncio
async def test_stage_fails_closed_when_no_active_rows_can_be_bound() -> None:
    def respond(sql, _params):
        if "SELECT active_revision_id" in sql:
            return _Result()
        if "UPDATE document_embeddings" in sql:
            return _Result(rowcount=0)
        return _Result()

    with pytest.raises(
        EmbeddingReindexPersistenceError,
        match="active_embedding_revision_not_found",
    ):
        await EmbeddingReindexRepository().stage(_Session(respond), _staged_run())


@pytest.mark.asyncio
async def test_ready_transition_requires_exact_candidate_manifest_readback() -> None:
    staged = _staged_run()
    ready = _ready_run(staged)

    def respond(sql, _params):
        if "SELECT event_sha256" in sql:
            return _Result()
        if "SELECT chunk_index, embedding_content_sha256" in sql:
            return _Result([(0, "c" * 64), (1, "bad")])
        return _Result()

    with pytest.raises(
        EmbeddingReindexPersistenceError,
        match="candidate_manifest_readback_mismatch",
    ):
        await EmbeddingReindexRepository().persist_transition(
            _Session(respond), before=staged, after=ready
        )


@pytest.mark.asyncio
async def test_ready_then_active_use_cas_and_atomic_pointer_cutover() -> None:
    staged = _staged_run()
    ready = _ready_run(staged)
    active = activate_candidate(
        ready,
        event_id="activate-1",
        expected_generation=ready.generation,
        expected_candidate_revision_id=ready.candidate.revision_id,
        expected_manifest_sha256=ready.candidate.manifest_sha256,
    )

    def respond(sql, _params):
        if "SELECT event_sha256" in sql:
            return _Result()
        if "SELECT chunk_index, embedding_content_sha256" in sql:
            return _Result([(0, "c" * 64), (1, "d" * 64)])
        if "UPDATE embedding_reindex_runs" in sql:
            return _Result([(1,)], rowcount=1)
        if "UPDATE embedding_active_revisions" in sql:
            return _Result([(2,)], rowcount=1)
        return _Result()

    ready_session = _Session(respond)
    await EmbeddingReindexRepository().persist_transition(
        ready_session, before=staged, after=ready
    )
    assert not any(
        "UPDATE embedding_active_revisions" in sql for sql, _ in ready_session.calls
    )

    active_session = _Session(respond)
    await EmbeddingReindexRepository().persist_transition(
        active_session, before=ready, after=active
    )
    pointer_sql, pointer_params = next(
        (sql, params)
        for sql, params in active_session.calls
        if "UPDATE embedding_active_revisions" in sql
    )
    assert "active_revision_id = :expected_active_revision_id" in pointer_sql
    assert pointer_params["expected_active_revision_id"] == "rev-1"
    assert pointer_params["new_active_revision_id"] == "rev-2"
    assert any("INSERT INTO embedding_reindex_events" in sql for sql, _ in active_session.calls)


@pytest.mark.asyncio
async def test_stale_run_cas_fails_before_pointer_or_event_write() -> None:
    staged = _staged_run()
    ready = _ready_run(staged)

    def respond(sql, _params):
        if "SELECT event_sha256" in sql:
            return _Result()
        if "SELECT chunk_index, embedding_content_sha256" in sql:
            return _Result([(0, "c" * 64), (1, "d" * 64)])
        if "UPDATE embedding_reindex_runs" in sql:
            return _Result()
        return _Result()

    session = _Session(respond)
    with pytest.raises(
        EmbeddingReindexPersistenceError,
        match="stale_reindex_generation",
    ):
        await EmbeddingReindexRepository().persist_transition(
            session, before=staged, after=ready
        )
    assert not any("UPDATE embedding_active_revisions" in sql for sql, _ in session.calls)
    assert not any("INSERT INTO embedding_reindex_events" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_stale_pointer_cas_fails_before_event_write() -> None:
    staged = _staged_run()
    ready = _ready_run(staged)
    active = activate_candidate(
        ready,
        event_id="activate-1",
        expected_generation=ready.generation,
        expected_candidate_revision_id=ready.candidate.revision_id,
        expected_manifest_sha256=ready.candidate.manifest_sha256,
    )

    def respond(sql, _params):
        if "SELECT event_sha256" in sql:
            return _Result()
        if "SELECT chunk_index, embedding_content_sha256" in sql:
            return _Result([(0, "c" * 64), (1, "d" * 64)])
        if "UPDATE embedding_reindex_runs" in sql:
            return _Result([(active.generation,)])
        if "UPDATE embedding_active_revisions" in sql:
            return _Result()
        return _Result()

    session = _Session(respond)
    with pytest.raises(
        EmbeddingReindexPersistenceError,
        match="active_revision_conflict",
    ):
        await EmbeddingReindexRepository().persist_transition(
            session, before=ready, after=active
        )
    assert not any("INSERT INTO embedding_reindex_events" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_conflicting_persisted_event_fails_before_transition_write() -> None:
    staged = _staged_run()
    ready = _ready_run(staged)

    def respond(sql, _params):
        if "SELECT event_sha256" in sql:
            return _Result([("f" * 64, ready.generation)])
        return _Result()

    session = _Session(respond)
    with pytest.raises(
        EmbeddingReindexPersistenceError,
        match="reindex_event_conflict",
    ):
        await EmbeddingReindexRepository().persist_transition(
            session, before=staged, after=ready
        )
    assert not any("UPDATE embedding_reindex_runs" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_persisted_rollback_restores_previous_pointer_with_cas() -> None:
    staged = _staged_run()
    ready = _ready_run(staged)
    active = activate_candidate(
        ready,
        event_id="activate-1",
        expected_generation=ready.generation,
        expected_candidate_revision_id=ready.candidate.revision_id,
        expected_manifest_sha256=ready.candidate.manifest_sha256,
    )
    rolled_back = rollback_cutover(
        active,
        event_id="rollback-1",
        expected_generation=active.generation,
    )

    def respond(sql, _params):
        if "SELECT event_sha256" in sql:
            return _Result()
        if "UPDATE embedding_reindex_runs" in sql:
            return _Result([(rolled_back.generation,)])
        if "UPDATE embedding_active_revisions" in sql:
            return _Result([(3,)])
        return _Result()

    session = _Session(respond)
    await EmbeddingReindexRepository().persist_transition(
        session, before=active, after=rolled_back
    )
    _, params = next(
        (sql, params)
        for sql, params in session.calls
        if "UPDATE embedding_active_revisions" in sql
    )
    assert params["expected_active_revision_id"] == "rev-2"
    assert params["new_active_revision_id"] == "rev-1"
    assert any("INSERT INTO embedding_reindex_events" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_cleanup_is_exact_and_cannot_delete_the_active_revision() -> None:
    ready = _ready_run(_staged_run())
    active = activate_candidate(
        ready,
        event_id="activate-1",
        expected_generation=ready.generation,
        expected_candidate_revision_id=ready.candidate.revision_id,
        expected_manifest_sha256=ready.candidate.manifest_sha256,
    )
    cleaned, directive = finalize_cleanup(
        active,
        event_id="cleanup-1",
        expected_generation=active.generation,
    )
    session = _Session(lambda _sql, _params: _Result(rowcount=2))

    deleted = await EmbeddingReindexRepository().cleanup(
        session, run=cleaned, directive=directive
    )

    delete_sql, params = next(
        (sql, params)
        for sql, params in session.calls
        if "DELETE FROM document_embeddings" in sql
    )
    assert deleted == 2
    assert "ANY(CAST(:revision_ids AS text[]))" in delete_sql
    assert "<> (" in delete_sql
    assert params["revision_ids"] == ["rev-1"]
