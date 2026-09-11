from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
    run_direct_architect,
)


def _corpus() -> DirectSourceCorpus:
    revision = "document:" + "a" * 64
    chunks = (
        DirectSourceChunk(
            chunk_id="direct:doc-1:0",
            doc_id="doc-1",
            doc_name="source.xlsx",
            title="Product source",
            headings=("[Worksheet] Collections",),
            text="Collection | Benefit\nChicago | Modular storage",
            source_revision=revision,
            chunk_index=0,
        ),
        DirectSourceChunk(
            chunk_id="direct:doc-1:1",
            doc_id="doc-1",
            doc_name="source.xlsx",
            title="Product source",
            headings=("[Worksheet] SKU catalog",),
            text="SKU | Item | Price\nSKU-1 | Wardrobe | 199000",
            source_revision=revision,
            chunk_index=1,
        ),
    )
    return DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-1",
                title="Product source",
                filename="source.xlsx",
                category="general",
                source_revision=revision,
                chunks=chunks,
            ),
        ),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=2,
    )


def _structure(heading: str) -> str:
    return json.dumps(
        {
            "title": "Product course",
            "description": "Product knowledge",
            "modules": [
                {
                    "title": "Products",
                    "description": "Collections and examples",
                    "lessons": [
                        {
                            "title": "Product selection",
                            "description": "How to choose a product",
                            "objectives": ["Explain the customer benefit"],
                            "source_doc_ids": ["doc-1"],
                            "relevant_headings": [heading],
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_architect_uses_passport_and_repairs_omitted_primary_section() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure("[Worksheet] SKU catalog"),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].relevant_headings == ["[Worksheet] Collections"]
    assert 'section="Collections" role=primary' in llm.prompts[0]
    assert 'section="SKU catalog" role=supporting' in llm.prompts[0]
    assert "direct_source_lesson_primary_section_missing" in llm.prompts[1]


@pytest.mark.asyncio
async def test_low_confidence_passport_is_advisory_not_a_generation_blocker() -> None:
    revision = "document:" + "a" * 64
    chunks = (
        DirectSourceChunk(
            chunk_id="direct:doc-1:0",
            doc_id="doc-1",
            doc_name="source.xlsx",
            title="Ambiguous source",
            headings=("[Worksheet] Sheet1",),
            text="Alpha | Beta\nOne | Two",
            source_revision=revision,
            chunk_index=0,
        ),
        DirectSourceChunk(
            chunk_id="direct:doc-1:1",
            doc_id="doc-1",
            doc_name="source.xlsx",
            title="Ambiguous source",
            headings=("[Worksheet] Sheet2",),
            text="Gamma | Delta\nThree | Four",
            source_revision=revision,
            chunk_index=1,
        ),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-1",
                title="Ambiguous source",
                filename="source.xlsx",
                category="general",
                source_revision=revision,
                chunks=chunks,
            ),
        ),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=2,
    )

    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(content=_structure("[Worksheet] Sheet2"))

    llm = LLM()
    result = await run_direct_architect(llm, corpus, max_total_lessons=4)

    assert result.modules[0].lessons[0].relevant_headings == ["[Worksheet] Sheet2"]
    assert llm.calls == 1
