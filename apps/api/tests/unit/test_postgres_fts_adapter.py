from contextlib import asynccontextmanager

import pytest

from app.modules.ai.ingestion import VectorStore
from app.modules.ai.lexical_retrieval import retrieve_lexical_hits


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_vector_store_fts_is_explicitly_tenant_document_and_verified_scoped(monkeypatch) -> None:
    row = (
        "chunk-1", "Порядок эвакуации", "doc-1", "source.pdf", '["Эвакуация"]',
        "provider", "model", "revision", 3, 4, "a" * 64,
        "document:" + "b" * 64, "2026-08-23T00:00:00+00:00", 2, 0.75,
    )
    session = _Session([row])

    @asynccontextmanager
    async def factory():
        yield session

    tenant_calls = []

    async def set_tenant(self, active_session, tenant_id):
        tenant_calls.append((active_session, tenant_id))

    monkeypatch.setattr("app.core.db.async_session_factory", factory)
    monkeypatch.setattr(VectorStore, "_set_tenant_context", set_tenant)
    rows = await VectorStore().search_full_text(
        query_text="эвакуация",
        tenant_id="00000000-0000-0000-0000-000000000001",
        doc_ids=["doc-1"],
        limit=10,
    )

    sql, params = session.calls[0]
    assert tenant_calls == [(session, "00000000-0000-0000-0000-000000000001")]
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "embedding_provenance_state = 'verified'" in sql
    assert "embedding_source_revision = 'document:'" in sql
    assert "active_document.content_sha256" in sql
    assert "embedding_fts @@ query.value" in sql
    assert "doc_id IN (:doc_id_0)" in sql
    assert params["doc_id_0"] == "doc-1"
    assert rows[0][1]["postgres_fts_score"] == 0.75


@pytest.mark.asyncio
async def test_vector_store_fts_rejects_invalid_input_before_db() -> None:
    store = VectorStore()
    with pytest.raises(ValueError, match="tenant_id_required"):
        await store.search_full_text(query_text="x", tenant_id=None, doc_ids=["doc"], limit=1)
    with pytest.raises(ValueError, match="full_text_query_required"):
        await store.search_full_text(query_text="", tenant_id="tenant", doc_ids=["doc"], limit=1)
    with pytest.raises(ValueError, match="document_ids_required"):
        await store.search_full_text(query_text="x", tenant_id="tenant", doc_ids=[], limit=1)


@pytest.mark.asyncio
async def test_lexical_retrieval_prefers_postgres_candidate_adapter() -> None:
    class Store:
        def __init__(self):
            self.call = None

        async def search_full_text(self, **kwargs):
            self.call = kwargs
            return [(
                "Порядок эвакуации сотрудников.",
                {
                    "chunk_id": "chunk-1", "doc_id": "doc-1", "doc_name": "source.pdf",
                    "headings": '["Эвакуация"]', "embedding_provider": "provider",
                    "embedding_model": "model", "embedding_revision": "revision",
                    "embedding_native_dimensions": 3, "embedding_storage_dimensions": 4,
                    "embedding_content_sha256": "a" * 64,
                    "embedding_source_revision": "document:" + "b" * 64,
                    "embedding_indexed_at": "2026-08-23T00:00:00+00:00", "chunk_index": 0,
                },
            )]

        async def get_all_chunks(self, **kwargs):
            raise AssertionError("production path must use PostgreSQL FTS candidates")

    store = Store()
    hits = await retrieve_lexical_hits(
        store,
        ["эвакуация"],
        tenant_id="tenant-1",
        doc_ids=["doc-1"],
        limit=5,
    )
    assert [hit.chunk_id for hit in hits] == ["chunk-1"]
    assert store.call == {
        "query_text": "эвакуация",
        "doc_ids": ["doc-1"],
        "tenant_id": "tenant-1",
        "limit": 30,
    }
