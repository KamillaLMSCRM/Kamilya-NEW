from types import SimpleNamespace

import pytest

from app.modules.ai import direct_source
from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument


def _document(name: str, texts: list[str]) -> DirectSourceDocument:
    return DirectSourceDocument(name, name, name + ".txt", "general", "document:" + "a" * 64,
        tuple(DirectSourceChunk(f"{name}:{i}", name, name, name, (), text,
            "document:" + "a" * 64, i) for i, text in enumerate(texts)))


@pytest.mark.asyncio
async def test_small_unequal_documents_do_not_lose_the_longer_document_tail() -> None:
    first = _document("long", ["A" * 1000] * 17 + ["long_tail_marker".ljust(1000, "A")])
    second = _document("short", ["short_source_marker"])
    corpus = DirectSourceCorpus("tenant", (first, second), 18019, 19)
    context = await direct_source._architect_context(corpus, None, check_cancelled=None)
    assert "long_tail_marker" in context
    assert "short_source_marker" in context


@pytest.mark.asyncio
async def test_overlap_size_selects_mapping_even_when_original_size_is_small(monkeypatch) -> None:
    document = _document("overlap", ["A" * 1000] * 25)
    corpus = DirectSourceCorpus("tenant", (document,), 19000, 25)
    seen = []

    async def mapped(*args, **kwargs):
        seen.append(True)
        return SimpleNamespace()

    monkeypatch.setattr(direct_source, "build_source_topic_map", mapped)
    monkeypatch.setattr(direct_source, "compose_architect_overview", lambda _: "complete map")
    context = await direct_source._architect_context(corpus, None, check_cancelled=None)
    assert seen == [True]
    assert context == "complete map"
