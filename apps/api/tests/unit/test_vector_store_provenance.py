import hashlib
from datetime import UTC, datetime

import pytest

from app.modules.ai.embedding_space import EmbeddingSpace
from app.modules.ai.ingestion import EmbeddingsProvider, VectorStore
from app.modules.ai.llm_client import EmbeddingBatchResult


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else 0


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "set_config" in sql or "set_current_tenant" in sql:
            return _Result([])
        if "SELECT id, text" in sql:
            return _Result([(
                "chunk-1", "Подтвержденный текст", "doc-1", "tenant-1", "scan.pdf", '["Раздел 1"]',
                "qwen-self-hosted", "Qwen3-Embedding-8B", "Qwen3-Embedding-8B",
                2, 2, "a" * 64, "document:" + "d" * 64,
                datetime(2026, 8, 23, tzinfo=UTC), 0,
            )])
        return _Result([("Подтвержденный текст", "doc-1", "scan.pdf", '["Раздел 1"]')])


class _BatchSession:
    def __init__(self, count_result: int = 205):
        self.calls = []
        self.count_result = count_result

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if "COUNT(*)" in str(statement):
            return _Result([(self.count_result,)])
        return _Result([])

    async def flush(self):
        return None

    async def commit(self):
        return None


class _SemanticSession:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "set_current_tenant" in sql:
            return _Result([])
        return _Result(
            [
                (
                    "chunk-1",
                    "Подтвержденный текст",
                    "doc-1",
                    "tenant-1",
                    "scan.pdf",
                    '["Раздел 1"]',
                    "qwen-self-hosted",
                    "Qwen3-Embedding-8B",
                    "Qwen3-Embedding-8B",
                    2,
                    2,
                    "a" * 64,
                    "document:" + "d" * 64,
                    datetime(2026, 8, 23, tzinfo=UTC),
                    0,
                    0.2,
                )
            ]
        )


class _ContextSession:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "set_current_tenant" in sql:
            return _Result([])
        return _Result([
            (
                "chunk-1", "center", "doc-1", "tenant-1", "source.pdf", '["Раздел"]',
                "qwen-self-hosted", "Qwen3-Embedding-8B", "Qwen3-Embedding-8B",
                2, 2, "a" * 64, "document:" + "d" * 64,
                datetime(2026, 8, 23, tzinfo=UTC), 4,
            )
        ])


def _embedding_batch(
    count: int,
    *,
    native_dimensions: int = 2,
    storage_dimensions: int = 2,
) -> EmbeddingBatchResult:
    return EmbeddingBatchResult(
        space=EmbeddingSpace(
            provider="qwen-self-hosted",
            model="Qwen3-Embedding-8B",
            revision="Qwen3-Embedding-8B",
            dimensions=native_dimensions,
        ),
        native_dimensions=native_dimensions,
        storage_dimensions=storage_dimensions,
        vectors=tuple(
            tuple([0.1] * native_dimensions + [0.0] * (storage_dimensions - native_dimensions))
            for _ in range(count)
        ),
    )


@pytest.mark.asyncio
async def test_get_all_chunks_preserves_chunk_id_for_lexical_provenance(
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: _Session())

    chunks = await VectorStore().get_all_chunks(
        doc_ids=["doc-1"],
        tenant_id="tenant-1",
    )

    assert chunks == [
        (
            "Подтвержденный текст",
            {
                    "chunk_id": "chunk-1",
                    "doc_id": "doc-1",
                    "tenant_id": "tenant-1",
                    "doc_name": "scan.pdf",
                "headings": '["Раздел 1"]',
                "embedding_provider": "qwen-self-hosted",
                "embedding_model": "Qwen3-Embedding-8B",
                "embedding_revision": "Qwen3-Embedding-8B",
                "embedding_native_dimensions": 2,
                "embedding_storage_dimensions": 2,
                "embedding_content_sha256": "a" * 64,
                "embedding_source_revision": "document:" + "d" * 64,
                "embedding_indexed_at": "2026-08-23T00:00:00+00:00",
                "chunk_index": 0,
            },
        )
    ]


@pytest.mark.asyncio
async def test_add_chunks_uses_bounded_executemany_batches(monkeypatch) -> None:
    primary = _BatchSession()
    verification = _BatchSession()
    sessions = [primary, verification]

    def session_factory():
        return sessions.pop(0)

    monkeypatch.setattr("app.core.db.async_session_factory", session_factory)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )
    chunks = [
        {
            "text": f"chunk-{index}",
            "metadata": {
                "doc_id": "doc-1",
                "doc_name": "scan.pdf",
                "source_revision": "document:" + "d" * 64,
                "chunk_index": index,
            },
        }
        for index in range(205)
    ]

    dropped = await VectorStore().add_chunks(
        chunks,
        _embedding_batch(len(chunks)),
        tenant_id="tenant-1",
    )

    insert_batches = [params for sql, params in primary.calls if "INSERT INTO document_embeddings" in sql]

    assert dropped == 0
    assert [len(batch) for batch in insert_batches] == [100, 100, 5]
    assert all(row["tenant_id"] == "tenant-1" for batch in insert_batches for row in batch)
    rows = [row for batch in insert_batches for row in batch]
    assert all(row["embedding_provenance_state"] == "verified" for row in rows)
    assert all(row["embedding_provider"] == "qwen-self-hosted" for row in rows)
    assert all(row["embedding_model"] == "Qwen3-Embedding-8B" for row in rows)
    assert all(row["embedding_revision"] == "Qwen3-Embedding-8B" for row in rows)
    assert all(row["embedding_native_dimensions"] == 2 for row in rows)
    assert all(row["embedding_storage_dimensions"] == 2 for row in rows)
    first_text = chunks[0]["text"]
    assert rows[0]["embedding_content_sha256"] == hashlib.sha256(
        first_text.encode("utf-8")
    ).hexdigest()
    assert rows[0]["embedding_source_revision"] == "document:" + "d" * 64
    assert [row["chunk_index"] for row in rows] == list(range(205))
    assert all(isinstance(row["embedding_indexed_at"], datetime) for row in rows)
    assert all(row["embedding_indexed_at"].tzinfo is not None for row in rows)
    assert {row["embedding_indexed_at"] for row in rows} == {rows[0]["embedding_indexed_at"]}
    insert_sql = next(sql for sql, _ in primary.calls if "INSERT INTO document_embeddings" in sql)
    assert "ON CONFLICT (id) DO UPDATE SET" in insert_sql
    assert "WHERE document_embeddings.tenant_id = EXCLUDED.tenant_id" in insert_sql
    assert "set_current_tenant" in primary.calls[0][0]
    assert "set_current_tenant" in verification.calls[0][0]
    verification_sql, verification_params = next(
        (sql, params) for sql, params in verification.calls if "COUNT(*)" in sql
    )
    assert "embedding_provenance_state = 'verified'" in verification_sql
    assert "doc_id = CAST(:doc_id AS text)" in verification_sql
    assert "doc_id = CAST(:doc_id AS uuid)" not in verification_sql
    assert verification_params == {
        "ids": [row["id"] for row in rows],
        "tenant_id": "tenant-1",
        "doc_id": "doc-1",
        "source_revision": "document:" + "d" * 64,
    }


@pytest.mark.asyncio
async def test_add_chunks_rejects_unlabelled_or_mismatched_batches_before_db(
    monkeypatch,
) -> None:
    def forbidden_factory():
        raise AssertionError("database must not be opened")

    monkeypatch.setattr("app.core.db.async_session_factory", forbidden_factory)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )
    chunks = [{
        "text": "one",
        "metadata": {
            "doc_id": "doc-1",
            "source_revision": "document:" + "d" * 64,
            "chunk_index": 0,
        },
    }]

    with pytest.raises(ValueError, match="tenant_id_required"):
        await VectorStore().add_chunks(chunks, _embedding_batch(1))
    with pytest.raises(TypeError, match="embedding_batch_required"):
        await VectorStore().add_chunks(chunks, [[0.1, 0.2]], tenant_id="tenant-1")
    with pytest.raises(ValueError, match="embedding_batch_chunk_count_mismatch"):
        await VectorStore().add_chunks(chunks, _embedding_batch(2), tenant_id="tenant-1")
    with pytest.raises(ValueError, match="embedding_batch_storage_dimension_mismatch"):
        await VectorStore().add_chunks(
            chunks,
            _embedding_batch(1, native_dimensions=2, storage_dimensions=3),
            tenant_id="tenant-1",
        )


@pytest.mark.asyncio
async def test_embeddings_provider_exposes_exact_provenance_batch(monkeypatch) -> None:
    expected = _embedding_batch(1)

    class _Client:
        async def embed_documents_with_provenance(self, texts):
            assert texts == ["safety"]
            return expected

    provider = EmbeddingsProvider()
    monkeypatch.setattr(provider, "_get_client", lambda: _async_value(_Client()))

    assert await provider.embed_documents_with_provenance(["safety"]) is expected


@pytest.mark.asyncio
async def test_add_chunks_fails_when_fresh_readback_is_incomplete(monkeypatch) -> None:
    primary = _BatchSession(count_result=1)
    verification = _BatchSession(count_result=0)
    sessions = [primary, verification]

    monkeypatch.setattr("app.core.db.async_session_factory", lambda: sessions.pop(0))
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )

    with pytest.raises(RuntimeError, match="embedding_write_verification_failed"):
        await VectorStore().add_chunks(
            [{
                "text": "one",
                "metadata": {
                    "doc_id": "doc-1",
                    "source_revision": "document:" + "d" * 64,
                    "chunk_index": 0,
                },
            }],
            _embedding_batch(1),
            tenant_id="tenant-1",
        )


@pytest.mark.asyncio
async def test_semantic_query_filters_exact_verified_embedding_space(monkeypatch) -> None:
    session = _SemanticSession()
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("Settings", (), {"EMBEDDING_DIMENSIONS": 2})(),
    )

    result = await VectorStore().query(
        query_embedding_batch=_embedding_batch(1),
        where={"doc_id": {"$in": ["doc-1", "doc-2"]}},
        tenant_id="tenant-1",
    )

    sql, params = next((sql, params) for sql, params in session.calls if "SELECT id, text" in sql)
    for predicate in (
        "embedding_provenance_state = 'verified'",
        "embedding_provider = :embedding_provider",
        "embedding_model = :embedding_model",
        "embedding_revision = :embedding_revision",
        "embedding_native_dimensions = :embedding_native_dimensions",
        "embedding_storage_dimensions = :embedding_storage_dimensions",
    ):
        assert predicate in sql
    assert params["embedding_provider"] == "qwen-self-hosted"
    assert params["embedding_model"] == "Qwen3-Embedding-8B"
    assert params["embedding_revision"] == "Qwen3-Embedding-8B"
    assert params["embedding_native_dimensions"] == 2
    assert params["embedding_storage_dimensions"] == 2
    assert params["emb"].startswith("[") and params["emb"].endswith("]")
    assert params["doc_id_0"] == "doc-1"
    assert params["doc_id_1"] == "doc-2"
    assert result["metadatas"][0][0]["embedding_provider"] == "qwen-self-hosted"
    assert result["metadatas"][0][0]["tenant_id"] == "tenant-1"
    assert result["metadatas"][0][0]["embedding_content_sha256"] == "a" * 64
    assert result["metadatas"][0][0]["embedding_source_revision"] == "document:" + "d" * 64
    assert result["metadatas"][0][0]["chunk_index"] == 0
    assert result["distances"] == [[0.2]]
    assert "set_current_tenant" in session.calls[0][0]


@pytest.mark.asyncio
async def test_semantic_query_rejects_unlabelled_missing_tenant_or_multi_vector_before_db(
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

    with pytest.raises(ValueError, match="tenant_id_required"):
        await store.query(query_embedding_batch=_embedding_batch(1))
    with pytest.raises(TypeError, match="embedding_batch_required"):
        await store.query(query_embedding_batch=[[0.1, 0.2]], tenant_id="tenant-1")
    with pytest.raises(ValueError, match="single_query_embedding_required"):
        await store.query(query_embedding_batch=_embedding_batch(2), tenant_id="tenant-1")


@pytest.mark.asyncio
async def test_context_window_is_tenant_document_revision_and_radius_scoped(monkeypatch) -> None:
    session = _ContextSession()
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: session)

    rows = await VectorStore().get_context_window(
        doc_id="doc-1",
        source_revision="document:" + "d" * 64,
        chunk_index=4,
        radius=1,
        tenant_id="tenant-1",
    )

    sql, params = next((sql, params) for sql, params in session.calls if "SELECT id, text" in sql)
    assert "embedding_provenance_state = 'verified'" in sql
    assert "embedding_source_revision = :source_revision" in sql
    assert "chunk_index BETWEEN :lower_index AND :upper_index" in sql
    assert params == {
        "doc_id": "doc-1",
        "source_revision": "document:" + "d" * 64,
        "lower_index": 3,
        "upper_index": 5,
    }
    assert rows[0][1]["chunk_index"] == 4
    assert rows[0][1]["tenant_id"] == "tenant-1"
    assert rows[0][1]["embedding_source_revision"] == "document:" + "d" * 64
    assert "set_current_tenant" in session.calls[0][0]


@pytest.mark.asyncio
async def test_context_window_rejects_invalid_scope_before_db(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.db.async_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("database must not open")),
    )
    store = VectorStore()

    with pytest.raises(ValueError, match="tenant_id_required"):
        await store.get_context_window(
            doc_id="doc-1", source_revision="document:" + "d" * 64, chunk_index=0
        )
    with pytest.raises(ValueError, match="invalid_document_source_revision"):
        await store.get_context_window(
            doc_id="doc-1", source_revision="legacy", chunk_index=0, tenant_id="tenant-1"
        )
    with pytest.raises(ValueError, match="invalid_context_radius"):
        await store.get_context_window(
            doc_id="doc-1",
            source_revision="document:" + "d" * 64,
            chunk_index=0,
            radius=4,
            tenant_id="tenant-1",
        )


async def _async_value(value):
    return value
