import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.architect_schema import CourseStructure, LearningObjective, Lesson, Module
from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
    DirectSourceError,
    select_lesson_source_chunks,
    write_direct_course,
)
from app.modules.ai.llm_client import AllProvidersFailedError, ProviderFailedError


def _corpus(tenant_id: str, *texts: str) -> DirectSourceCorpus:
    documents = []
    for index, text in enumerate(texts):
        doc_id = f"doc-{index}"
        documents.append(
            DirectSourceDocument(
                doc_id=doc_id,
                title=doc_id,
                filename=f"{doc_id}.txt",
                category="general",
                source_revision=f"document:revision-{index}",
                chunks=(
                    DirectSourceChunk(
                        chunk_id=f"chunk-{index}",
                        doc_id=doc_id,
                        doc_name=f"{doc_id}.txt",
                        title=doc_id,
                        headings=("Safety",),
                        text=text,
                        source_revision=f"document:revision-{index}",
                        chunk_index=0,
                    ),
                ),
            )
        )
    return DirectSourceCorpus(tenant_id=tenant_id, documents=tuple(documents), total_chars=sum(map(len, texts)), total_chunks=len(texts))


class _Embedding:
    async def embed_query_with_provenance(self, text):
        return SimpleNamespace(space=SimpleNamespace(provider="synthetic", model="synthetic", revision="v1"))


class _Store:
    def __init__(self, documents, metadatas):
        self.documents = documents
        self.metadatas = metadatas
        self.calls = []

    async def query(self, batch, **kwargs):
        self.calls.append(kwargs)
        return {"documents": [self.documents], "metadatas": [self.metadatas], "distances": [[0.1] * len(self.documents)]}


class _LLM:
    def __init__(self):
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages[-1]["content"])
        return SimpleNamespace(content="Grounded lesson")


def _structure(doc_ids: list[str]) -> CourseStructure:
    return CourseStructure(
        title="Synthetic course",
        modules=[
            Module(
                title="Safety",
                lessons=[
                    Lesson(
                        title="Emergency response",
                        objectives=[LearningObjective("respond safely")],
                        source_doc_ids=doc_ids,
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_selector_uses_only_exact_verified_corpus_text_and_requires_all_documents():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "Original fire procedure", "Original first-aid procedure")
    store = _Store(
        ["Original first-aid procedure", "untrusted retrieved text", "Original fire procedure"],
        [
            {"doc_id": "doc-1", "tenant_id": tenant_id},
            {"doc_id": "doc-0", "tenant_id": tenant_id},
            {"doc_id": "doc-0", "tenant_id": tenant_id},
        ],
    )
    selected = await select_lesson_source_chunks(
        corpus,
        document_ids=["doc-0", "doc-1"],
        query="emergency response",
        preferred_headings=[],
        tenant_id=tenant_id,
        embeddings=_Embedding(),
        vector_store=store,
    )
    assert [chunk.text for chunk in selected] == ["Original fire procedure", "Original first-aid procedure"]
    assert store.calls[0]["n_results"] == 24
    assert store.calls[0]["tenant_id"] == tenant_id
    assert store.calls[0]["where"] == {"doc_id": {"$in": ["doc-0", "doc-1"]}}


@pytest.mark.asyncio
async def test_selector_falls_back_lexically_on_exhausted_provider_or_incomplete_index():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "Fire procedure emergency exit", "First aid response")

    class _Unavailable(_Embedding):
        async def embed_query_with_provenance(self, text):
            raise AllProvidersFailedError("embedding providers exhausted")

    checkpoints = []

    async def checkpoint():
        checkpoints.append("checkpoint")

    with pytest.raises(AllProvidersFailedError):
        await select_lesson_source_chunks(
            corpus,
            document_ids=["doc-0", "doc-1"],
            query="fire procedure",
            preferred_headings=[],
            tenant_id=tenant_id,
            embeddings=_Unavailable(),
            vector_store=_Store([], []),
            check_cancelled=checkpoint,
        )
    assert len(checkpoints) == 2

    incomplete = _Store(["Fire procedure emergency exit"], [{"doc_id": "doc-0", "tenant_id": tenant_id}])
    selected = await select_lesson_source_chunks(
        corpus,
        document_ids=["doc-0", "doc-1"],
        query="fire procedure",
        preferred_headings=[],
        tenant_id=tenant_id,
        embeddings=_Embedding(),
        vector_store=incomplete,
    )
    assert {chunk.doc_id for chunk in selected} == {"doc-0", "doc-1"}


@pytest.mark.asyncio
async def test_writer_invokes_selector_once_and_falls_back_on_expected_exhaustion():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "Fire procedure emergency exit")
    structure = _structure(["doc-0"])
    llm = _LLM()
    calls = []

    async def selector(corpus_arg, **kwargs):
        calls.append({"corpus": corpus_arg, **kwargs})
        return list(corpus_arg.documents[0].chunks)

    result = await write_direct_course(llm, corpus, structure, tenant_id=tenant_id, semantic_selector=selector)
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == tenant_id
    assert result.modules[0].lessons[0].source_chunks == ["Fire procedure emergency exit"]


@pytest.mark.asyncio
async def test_auth_wrapper_is_not_misclassified_but_timeout_is_expected_exhaustion():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "Fire procedure")
    request = httpx.Request("POST", "https://provider.invalid/v1/embeddings")
    auth_failure = ProviderFailedError(
        "synthetic",
        httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request)),
    )

    class _AuthFailure(_Embedding):
        async def embed_query_with_provenance(self, text):
            raise AllProvidersFailedError("embedding providers failed") from auth_failure

    with pytest.raises(AllProvidersFailedError):
        await select_lesson_source_chunks(
            corpus,
            document_ids=["doc-0"],
            query="fire",
            preferred_headings=[],
            tenant_id=tenant_id,
            embeddings=_AuthFailure(),
            vector_store=_Store([], []),
        )

    timeout = ProviderFailedError("synthetic", httpx.ReadTimeout("timed out", request=request))

    llm = _LLM()

    async def selector(corpus_arg, **kwargs):
        raise AllProvidersFailedError("embedding providers exhausted") from timeout

    result = await write_direct_course(llm, corpus, _structure(["doc-0"]), tenant_id=tenant_id, semantic_selector=selector)
    assert result.modules[0].lessons[0].source_chunks == ["Fire procedure"]

@pytest.mark.asyncio
async def test_writer_rejects_multi_document_selection_that_cannot_fit_without_truncation():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "A" * 16000, "B" * 16000)
    with pytest.raises(DirectSourceError, match="direct_source_prompt_budget_exceeded"):
        await write_direct_course(
            _LLM(),
            corpus,
            _structure(["doc-0", "doc-1"]),
            tenant_id=tenant_id,
            semantic_selector=lambda *args, **kwargs: _too_large_selection(corpus),
        )


async def _too_large_selection(corpus):
    return [chunk for document in corpus.documents for chunk in document.chunks]


@pytest.mark.asyncio
async def test_lexical_fallback_bounds_whole_chunks_and_keeps_each_document():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "A" * 7000, "B" * 7000)
    corpus = replace(
        corpus,
        documents=tuple(
            replace(
                document,
                chunks=tuple(
                    replace(document.chunks[0], chunk_id=f"{document.doc_id}-{index}", chunk_index=index)
                    for index in range(3)
                ),
            )
            for document in corpus.documents
        ),
        total_chars=42000,
        total_chunks=6,
    )
    request = httpx.Request("POST", "https://provider.invalid/v1/embeddings")
    timeout = ProviderFailedError("synthetic", httpx.ReadTimeout("timed out", request=request))

    async def unavailable(*args, **kwargs):
        raise AllProvidersFailedError("embedding providers exhausted") from timeout

    result = await write_direct_course(
        _LLM(), corpus, _structure(["doc-0", "doc-1"]),
        tenant_id=tenant_id, semantic_selector=unavailable,
    )
    lesson = result.modules[0].lessons[0]
    assert sum(map(len, lesson.source_chunks)) <= 24000
    assert all(len(chunk) == 7000 for chunk in lesson.source_chunks)
    assert {reference["doc_id"] for reference in lesson.source_references} == {"doc-0", "doc-1"}


@pytest.mark.asyncio
async def test_selector_does_not_swallow_cancellation_or_resolver_errors():
    tenant_id = str(uuid4())
    corpus = _corpus(tenant_id, "Fire procedure")

    class _Cancelled(_Embedding):
        async def embed_query_with_provenance(self, text):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await select_lesson_source_chunks(
            corpus,
            document_ids=["doc-0"],
            query="fire",
            preferred_headings=[],
            tenant_id=tenant_id,
            embeddings=_Cancelled(),
            vector_store=_Store([], []),
        )

    class _ResolverFailure(_Embedding):
        async def embed_query_with_provenance(self, text):
            raise RuntimeError("tenant_provider_resolution_unavailable")

    with pytest.raises(RuntimeError, match="tenant_provider_resolution_unavailable"):
        await select_lesson_source_chunks(
            corpus,
            document_ids=["doc-0"],
            query="fire",
            preferred_headings=[],
            tenant_id=tenant_id,
            embeddings=_ResolverFailure(),
            vector_store=_Store([], []),
        )
