from datetime import datetime, timezone

import pytest

from app.modules.ai.embedding_space import EmbeddingSpace
from app.modules.ai.ingestion import VectorStore
from app.modules.ai.llm_client import EmbeddingBatchResult


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class _Session:
    def __init__(self, count_result=1):
        self.calls = []
        self.count_result = count_result

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "COUNT(*)" in sql:
            return _Result([(self.count_result,)])
        return _Result()

    async def flush(self):
        return None

    async def commit(self):
        return None


def _batch(count=1):
    return EmbeddingBatchResult(
        space=EmbeddingSpace(
            provider="qwen-self-hosted",
            model="Qwen3-Embedding-8B",
            revision="Qwen3-Embedding-8B",
            dimensions=2,
        ),
        native_dimensions=2,
        storage_dimensions=2,
        vectors=tuple((0.1, 0.2) for _ in range(count)),
    )


def _chunk():
    return {
        "text": "candidate",
        "metadata": {
            "doc_id": "11111111-1111-1111-1111-111111111111",
            "doc_name": "source.pdf",
            "source_revision": "document:" + "d" * 64,
            "chunk_index": 0,
        },
    }


@pytest.mark.asyncio
async def test_candidate_write_requires_complete_revision_run_binding_before_db(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.core.db.async_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("database must not open")),
    )
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )
    store = VectorStore()

    with pytest.raises(ValueError, match="embedding_reindex_binding_required"):
        await store.add_chunks(
            [_chunk()], _batch(), tenant_id="tenant-1", index_revision_id="rev-2"
        )
    with pytest.raises(ValueError, match="embedding_reindex_binding_required"):
        await store.add_chunks(
            [_chunk()],
            _batch(),
            tenant_id="tenant-1",
            reindex_run_id="22222222-2222-2222-2222-222222222222",
        )
    with pytest.raises(ValueError, match="invalid_embedding_reindex_run_id"):
        await store.add_chunks(
            [_chunk()],
            _batch(),
            tenant_id="tenant-1",
            index_revision_id="rev-2",
            reindex_run_id="unsafe id",
        )


@pytest.mark.asyncio
async def test_candidate_write_is_revision_scoped_and_verified_exactly(monkeypatch) -> None:
    primary = _Session()
    verification = _Session()
    sessions = [primary, verification]
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: sessions.pop(0))
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )
    run_id = "22222222-2222-2222-2222-222222222222"

    await VectorStore().add_chunks(
        [_chunk()],
        _batch(),
        tenant_id="tenant-1",
        index_revision_id="rev-2",
        reindex_run_id=run_id,
    )

    insert_sql, insert_rows = next(
        (sql, params)
        for sql, params in primary.calls
        if "INSERT INTO document_embeddings" in sql
    )
    row = insert_rows[0]
    assert "embedding_index_revision_id" in insert_sql
    assert "embedding_reindex_run_id" in insert_sql
    assert row["embedding_index_revision_id"] == "rev-2"
    assert row["embedding_reindex_run_id"] == run_id
    verify_sql, verify_params = next(
        (sql, params) for sql, params in verification.calls if "COUNT(*)" in sql
    )
    assert "embedding_index_revision_id = :index_revision_id" in verify_sql
    assert "embedding_reindex_run_id = :reindex_run_id" in verify_sql
    assert verify_params["index_revision_id"] == "rev-2"
    assert verify_params["reindex_run_id"] == run_id


@pytest.mark.asyncio
async def test_candidate_identity_changes_with_revision_or_run(monkeypatch) -> None:
    sessions = [_Session() for _ in range(6)]
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: sessions.pop(0))
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )
    store = VectorStore()

    first_primary = sessions[0]
    await store.add_chunks(
        [_chunk()],
        _batch(),
        tenant_id="tenant-1",
        index_revision_id="rev-2",
        reindex_run_id="run-1",
    )
    second_primary = sessions[0]
    await store.add_chunks(
        [_chunk()],
        _batch(),
        tenant_id="tenant-1",
        index_revision_id="rev-3",
        reindex_run_id="run-1",
    )
    third_primary = sessions[0]
    await store.add_chunks(
        [_chunk()],
        _batch(),
        tenant_id="tenant-1",
        index_revision_id="rev-2",
        reindex_run_id="run-2",
    )

    ids = {
        next(
            params[0]["id"]
            for sql, params in primary.calls
            if "INSERT INTO document_embeddings" in sql
        )
        for primary in (first_primary, second_primary, third_primary)
    }
    assert len(ids) == 3


@pytest.mark.asyncio
async def test_every_retrieval_path_filters_to_the_active_index_revision(monkeypatch) -> None:
    sessions = [_Session() for _ in range(4)]
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: sessions.pop(0))
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )
    store = VectorStore()

    first, second, third, fourth = sessions
    await store.query(_batch(), tenant_id="tenant-1")
    await store.search_full_text(
        query_text="проверка", tenant_id="tenant-1", doc_ids=["doc-1"]
    )
    await store.get_all_chunks(doc_ids=["doc-1"], tenant_id="tenant-1")
    await store.get_context_window(
        doc_id="doc-1",
        source_revision="document:" + "d" * 64,
        chunk_index=0,
        tenant_id="tenant-1",
    )

    for session in (first, second, third, fourth):
        sql = next(sql for sql, _ in session.calls if "FROM document_embeddings" in sql)
        assert "embedding_active_revisions AS active_index" in sql
        assert "embedding_index_revision_id IS NULL AND NOT EXISTS" in sql
        assert "embedding_index_revision_id = (" in sql
        assert "active_index.active_revision_id" in sql
