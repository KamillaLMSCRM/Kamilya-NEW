import pytest

from app.modules.ai.ingestion import VectorStore


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


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
            return _Result(
                [("chunk-1", "Подтвержденный текст", "doc-1", "scan.pdf", '["Раздел 1"]')]
            )
        return _Result(
            [("Подтвержденный текст", "doc-1", "scan.pdf", '["Раздел 1"]')]
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
                "doc_name": "scan.pdf",
                "headings": '["Раздел 1"]',
            },
        )
    ]
