"""Coverage regression tests for direct-source architecture maps."""

from __future__ import annotations

import json
import re

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
    run_direct_architect,
)
from app.modules.ai.source_topic_map import MAX_MAP_BATCHES, MAX_MAP_REQUEST_CHARS


def _catalog() -> DirectSourceCorpus:
    """1000 overlap-shaped chunks totaling ~844k characters, like the Excel run."""

    landmarks = {0: "headalpha", 500: "middlebeta", 999: "tailomega"}
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"chunk-{index}", doc_id="catalog", doc_name="catalog.xlsx",
            title="Synthetic catalog", headings=(),
            text=landmarks.get(index, "ordinary").ljust(844, " "),
            source_revision="document:" + "a" * 64, chunk_index=index,
        )
        for index in range(1000)
    )
    document = DirectSourceDocument(
        doc_id="catalog", title="Synthetic catalog", filename="catalog.xlsx",
        category="general", source_revision="document:" + "a" * 64, chunks=chunks,
    )
    return DirectSourceCorpus(
        tenant_id="synthetic", documents=(document,), total_chars=844_000, total_chunks=1000,
    )


@pytest.mark.asyncio
async def test_large_catalog_maps_every_overlap_chunk_before_architect_receives_anchors() -> None:
    """An LLM spy observes every actual source ID, not sampled landmark text."""

    class _Response:
        def __init__(self, content: str) -> None:
            self.content = content

    class _LLM:
        def __init__(self) -> None:
            self.map_batches: list[list[str]] = []
            self.map_prompts: list[str] = []
            self.architect_prompt = ""

        async def ainvoke(
            self, messages: list[dict[str, str]], config: dict | None = None,
        ) -> _Response:
            prompt = messages[-1]["content"]
            if "SOURCE_TOPIC_MAP_BATCH" in prompt:
                source_ids = re.findall(r"^source_id=(s\d+)$", prompt, flags=re.MULTILINE)
                self.map_batches.append(source_ids)
                self.map_prompts.append("".join(message["content"] for message in messages))
                return _Response(json.dumps({
                    "summary": "batch summary",
                    "topics": ["catalog"],
                }))
            self.architect_prompt = prompt
            return _Response(json.dumps({
                "title": "Catalog course", "description": "Grounded course",
                "modules": [{"title": "Catalog", "lessons": [{
                    "title": "Review", "description": "Use catalog",
                    "objectives": ["Review catalog"], "source_doc_ids": ["catalog"],
                    "relevant_headings": [],
                }]}],
            }))

    llm = _LLM()
    structure = await run_direct_architect(llm, _catalog())

    expected = [f"s{index:06d}" for index in range(1, 1001)]
    assert [source_id for batch in llm.map_batches for source_id in batch] == expected
    assert len(llm.map_batches) <= MAX_MAP_BATCHES
    assert all(batch for batch in llm.map_batches)
    assert all(len(prompt) <= MAX_MAP_REQUEST_CHARS for prompt in llm.map_prompts)
    all_map_input = "\n".join(llm.map_prompts)
    assert "headalpha" in all_map_input
    assert "middlebeta" in all_map_input
    assert "tailomega" in all_map_input
    assert "s000001" in llm.architect_prompt
    anchors = [json.loads(line) for line in llm.architect_prompt.splitlines() if line.startswith('{"batch"')]
    represented = [f"s{i:06d}" for anchor in anchors
                   for first, last in anchor['source_id_ranges_inclusive']
                   for i in range(int(first[1:]), int(last[1:]) + 1)]
    assert represented == [f"s{i:06d}" for i in range(1, 1001)]
    assert "s001000" in llm.architect_prompt
    assert structure.modules[0].lessons[0].source_doc_ids == ["catalog"]
