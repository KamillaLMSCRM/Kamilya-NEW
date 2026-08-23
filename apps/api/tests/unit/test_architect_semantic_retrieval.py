import json

import pytest

from app.modules.ai.architect import create_architect_tools


class _Embeddings:
    def __init__(self):
        self.queries = []
        self.batch = object()

    async def embed_query_with_provenance(self, query):
        self.queries.append(query)
        return self.batch


class _Store:
    def __init__(self):
        self.calls = []

    async def query(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "documents": [["Подтвержденный текст"]],
            "metadatas": [[{"doc_name": "source.pdf", "headings": '["Раздел"]'}]],
            "distances": [[0.2]],
        }


def test_architect_tools_require_tenant_before_any_retrieval() -> None:
    with pytest.raises(ValueError, match="tenant_id_required"):
        create_architect_tools(vector_store=_Store(), embeddings_client=_Embeddings())


@pytest.mark.asyncio
async def test_architect_semantic_search_passes_provenance_batch_and_exact_scope() -> None:
    embeddings = _Embeddings()
    store = _Store()
    tools = create_architect_tools(
        doc_ids=["doc-1"],
        vector_store=store,
        embeddings_client=embeddings,
        tenant_id="tenant-1",
    )

    result = json.loads(await tools["search_documents"]("эвакуация"))

    assert embeddings.queries == ["эвакуация"]
    assert store.calls == [
        {
            "query_embedding_batch": embeddings.batch,
            "n_results": 10,
            "where": {"doc_id": {"$in": ["doc-1"]}},
            "include": ["documents", "metadatas", "distances"],
            "tenant_id": "tenant-1",
        }
    ]
    assert result == [
        {
            "text": "Подтвержденный текст",
            "doc_name": "source.pdf",
            "headings": '["Раздел"]',
        }
    ]
