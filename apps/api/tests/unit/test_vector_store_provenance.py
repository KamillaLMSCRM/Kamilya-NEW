import pytest

from app.modules.ai.ingestion import VectorStore


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
            return _Result([("chunk-1", "Подтвержденный текст", "doc-1", "scan.pdf", '["Раздел 1"]')])
        return _Result([("Подтвержденный текст", "doc-1", "scan.pdf", '["Раздел 1"]')])


class _BatchSession:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if "COUNT(*)" in str(statement):
            return _Result([(205,)])
        return _Result([])

    async def flush(self):
        return None

    async def commit(self):
        return None


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
                "doc_name": "scan.pdf",
                "headings": '["Раздел 1"]',
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
            "metadata": {"doc_id": "doc-1", "doc_name": "scan.pdf"},
        }
        for index in range(205)
    ]

    dropped = await VectorStore().add_chunks(
        chunks,
        [[0.1, 0.2] for _ in chunks],
        tenant_id="tenant-1",
    )

    insert_batches = [params for sql, params in primary.calls if "INSERT INTO document_embeddings" in sql]

    assert dropped == 0
    assert [len(batch) for batch in insert_batches] == [100, 100, 5]
    assert all(row["tenant_id"] == "tenant-1" for batch in insert_batches for row in batch)
    assert "set_current_tenant" in primary.calls[0][0]
    assert "set_current_tenant" in verification.calls[0][0]
