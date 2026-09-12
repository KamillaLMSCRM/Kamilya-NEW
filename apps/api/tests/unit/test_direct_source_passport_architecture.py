from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
    DirectSourceError,
    _render_primary_tabular_lesson,
    run_direct_architect,
)
from app.modules.ai.document_passport import build_document_passport


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


def _structure(
    heading: str,
    *,
    module_title: str = "Products",
    lesson_title: str = "Collection facts",
    lesson_description: str = "Facts stated in the source",
    objectives: list[str] | None = None,
    additional_headings: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "title": "Product course",
            "description": "Product knowledge",
            "modules": [
                {
                    "title": module_title,
                    "description": "Collections and examples",
                    "lessons": [
                        {
                            "title": lesson_title,
                            "description": lesson_description,
                            "objectives": objectives or ["Describe the source values"],
                            "source_doc_ids": ["doc-1"],
                            "relevant_headings": [heading, *(additional_headings or [])],
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_architect_rejects_generic_supporting_catalog_objective() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] Collections",
                    objectives=["List SKUs, article numbers, and prices"],
                    additional_headings=["[Worksheet] SKU catalog"],
                ),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].objectives[0].text == "Describe the source values"
    assert len(llm.prompts) == 2
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]


@pytest.mark.asyncio
async def test_architect_rejects_supporting_objective_even_when_title_shares_product_word() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] Collections",
                    lesson_title="Product facts",
                    objectives=["List product SKUs and prices"],
                    additional_headings=["[Worksheet] SKU catalog"],
                ),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].objectives[0].text == "Describe the source values"
    assert len(llm.prompts) == 2
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]


@pytest.mark.asyncio
async def test_primary_action_evidence_is_scoped_by_document_and_worksheet() -> None:
    revision = "document:" + "a" * 64
    doc_primary = DirectSourceDocument(
        doc_id="doc-primary",
        title="Collections",
        filename="collections.xlsx",
        category="general",
        source_revision=revision,
        chunks=(
            DirectSourceChunk(
                chunk_id="direct:doc-primary:0",
                doc_id="doc-primary",
                doc_name="collections.xlsx",
                title="Collections",
                headings=("[Worksheet] Shared",),
                text="Collection | Benefit\nChicago | Modular storage",
                source_revision=revision,
                chunk_index=0,
            ),
        ),
    )
    doc_mixed = DirectSourceDocument(
        doc_id="doc-mixed",
        title="Guide and catalog",
        filename="mixed.xlsx",
        category="general",
        source_revision=revision,
        chunks=(
            DirectSourceChunk(
                chunk_id="direct:doc-mixed:0",
                doc_id="doc-mixed",
                doc_name="mixed.xlsx",
                title="Guide and catalog",
                headings=("[Worksheet] Guide",),
                text="Instruction | Procedure\nOpen the product card | Read the facts",
                source_revision=revision,
                chunk_index=0,
            ),
            DirectSourceChunk(
                chunk_id="direct:doc-mixed:1",
                doc_id="doc-mixed",
                doc_name="mixed.xlsx",
                title="Guide and catalog",
                headings=("[Worksheet] Shared",),
                text="SKU | Catalog | Price | Selection\nSKU-1 | Wardrobe | 199000 | Recommended",
                source_revision=revision,
                chunk_index=1,
            ),
        ),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(doc_primary, doc_mixed),
        total_chars=sum(len(chunk.text) for document in (doc_primary, doc_mixed) for chunk in document.chunks),
        total_chunks=3,
    )
    invalid = json.dumps(
        {
            "title": "Product selection",
            "description": "Grounded course",
            "modules": [
                {
                    "title": "Product knowledge",
                    "description": "Source facts",
                    "lessons": [
                        {
                            "title": "Collection facts",
                            "description": "Collection facts",
                            "objectives": ["Describe collection benefits"],
                            "source_doc_ids": ["doc-primary"],
                            "relevant_headings": ["[Worksheet] Shared"],
                        },
                        {
                            "title": "Guide facts",
                            "description": "Guide facts",
                            "objectives": ["Describe the instruction"],
                            "source_doc_ids": ["doc-mixed"],
                            "relevant_headings": ["[Worksheet] Guide"],
                        },
                    ],
                }
            ],
        }
    )

    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(content=invalid)

    llm = LLM()
    with pytest.raises(DirectSourceError) as exc_info:
        await run_direct_architect(
            llm,
            corpus,
            max_total_lessons=4,
            combination_goal="Use both sources in one grounded training course.",
        )

    assert exc_info.value.code == "direct_source_structure_claim_unverified"
    assert llm.calls == 4


@pytest.mark.asyncio
async def test_same_name_primary_does_not_hide_supporting_subject_in_multi_document_lesson() -> None:
    revision = "document:" + "a" * 64
    primary_shared = DirectSourceChunk(
        chunk_id="direct:doc-primary:0",
        doc_id="doc-primary",
        doc_name="primary.xlsx",
        title="Primary",
        headings=("[Worksheet] Shared",),
        text="Collection | Benefit\nChicago | Modular storage",
        source_revision=revision,
        chunk_index=0,
    )
    guide = DirectSourceChunk(
        chunk_id="direct:doc-mixed:0",
        doc_id="doc-mixed",
        doc_name="mixed.xlsx",
        title="Mixed",
        headings=("[Worksheet] Guide",),
        text="Instruction | Procedure\nOpen the product card | Read the facts",
        source_revision=revision,
        chunk_index=0,
    )
    supporting_shared = DirectSourceChunk(
        chunk_id="direct:doc-mixed:1",
        doc_id="doc-mixed",
        doc_name="mixed.xlsx",
        title="Mixed",
        headings=("[Worksheet] Shared",),
        text="SKU | Catalog | Price\nSKU-1 | Wardrobe | 199000",
        source_revision=revision,
        chunk_index=1,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-primary",
                title="Primary",
                filename="primary.xlsx",
                category="general",
                source_revision=revision,
                chunks=(primary_shared,),
            ),
            DirectSourceDocument(
                doc_id="doc-mixed",
                title="Mixed",
                filename="mixed.xlsx",
                category="general",
                source_revision=revision,
                chunks=(guide, supporting_shared),
            ),
        ),
        total_chars=sum(len(chunk.text) for chunk in (primary_shared, guide, supporting_shared)),
        total_chunks=3,
    )
    invalid = json.dumps(
        {
            "title": "Product course",
            "description": "Grounded course",
            "modules": [
                {
                    "title": "Product knowledge",
                    "description": "Source facts",
                    "lessons": [
                        {
                            "title": "Collection facts",
                            "description": "Collection facts",
                            "objectives": ["Describe collection benefits"],
                            "source_doc_ids": ["doc-primary"],
                            "relevant_headings": ["[Worksheet] Shared"],
                        },
                        {
                            "title": "Shared facts",
                            "description": "Shared facts",
                            "objectives": ["Describe the instruction"],
                            "source_doc_ids": ["doc-primary", "doc-mixed"],
                            "relevant_headings": ["[Worksheet] Guide"],
                        },
                    ],
                }
            ],
        }
    )

    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(content=invalid)

    llm = LLM()
    with pytest.raises(DirectSourceError) as exc_info:
        await run_direct_architect(
            llm,
            corpus,
            max_total_lessons=4,
            combination_goal="Use both sources in one grounded training course.",
        )

    assert exc_info.value.code == "direct_source_supporting_section_promoted"
    assert llm.calls == 4


def test_primary_tabular_renderer_does_not_read_same_named_supporting_sheet() -> None:
    revision = "document:" + "a" * 64
    primary = DirectSourceChunk(
        chunk_id="direct:doc-primary:0",
        doc_id="doc-primary",
        doc_name="primary.xlsx",
        title="Primary",
        headings=("[Worksheet] Shared",),
        text=(
            "| Collection | Benefit |\n"
            "| --- | --- |\n"
            "| Chicago | Modular storage |\n"
            "| Phoenix | Compact storage |"
        ),
        source_revision=revision,
        chunk_index=0,
    )
    supporting = DirectSourceChunk(
        chunk_id="direct:doc-support:0",
        doc_id="doc-support",
        doc_name="support.xlsx",
        title="Supporting",
        headings=("[Worksheet] Shared",),
        text=(
            "| SKU | Catalog | Price |\n"
            "| --- | --- | --- |\n"
            "| SKU-1 | Wardrobe | 199000 |\n"
            "| SKU-2 | Cabinet | 299000 |\n"
            "| SKU-3 | Mirror | 399000 |"
        ),
        source_revision=revision,
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-primary",
                title="Primary",
                filename="primary.xlsx",
                category="general",
                source_revision=revision,
                chunks=(primary,),
            ),
            DirectSourceDocument(
                doc_id="doc-support",
                title="Supporting",
                filename="support.xlsx",
                category="general",
                source_revision=revision,
                chunks=(supporting,),
            ),
        ),
        total_chars=len(primary.text) + len(supporting.text),
        total_chunks=2,
    )

    rendered = _render_primary_tabular_lesson(
        chunks=(primary, supporting),
        passport=build_document_passport(corpus),
        title="Collection facts",
        objectives=("Describe collection benefits",),
        language="en",
    )

    assert rendered is not None
    content, selected_source = rendered
    assert "Modular storage" in content
    assert "199000" not in content
    assert "199000" not in selected_source


def test_primary_tabular_renderer_omits_note_only_source_rows() -> None:
    revision = "document:" + "b" * 64
    primary = DirectSourceChunk(
        chunk_id="direct:doc-primary:0",
        doc_id="doc-primary",
        doc_name="primary.xlsx",
        title="Primary",
        headings=("[Worksheet] Collections",),
        text=(
            "| Field | Phoenix | Chicago |\n"
            "| --- | --- | --- |\n"
            "| Style | modern | industrial |\n"
            "| Material | chipboard | metal |\n"
            "| Source: manufacturer website |  |  |"
        ),
        source_revision=revision,
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-primary",
                title="Primary",
                filename="primary.xlsx",
                category="general",
                source_revision=revision,
                chunks=(primary,),
            ),
        ),
        total_chars=len(primary.text),
        total_chunks=1,
    )

    rendered = _render_primary_tabular_lesson(
        chunks=(primary,),
        passport=build_document_passport(corpus),
        title="Collection facts",
        objectives=("Describe the source table",),
        language="en",
    )

    assert rendered is not None
    content, selected_source = rendered
    assert "manufacturer website" not in content
    assert "manufacturer website" not in selected_source


@pytest.mark.asyncio
async def test_architect_allows_supporting_catalog_facts_inside_primary_lesson() -> None:
    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(
                content=_structure(
                    "[Worksheet] Collections",
                    lesson_description=(
                        "Collection facts enriched with examples from worksheet "
                        "\u201cSKU catalog\u201d: "
                        "Wardrobe, SKU-1, price 199000."
                    ),
                    additional_headings=["[Worksheet] SKU catalog"],
                )
            )

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].relevant_headings == [
        "[Worksheet] Collections",
        "[Worksheet] SKU catalog",
    ]
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_architect_allows_natural_supporting_description_linked_to_primary_subject() -> None:
    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(
                content=_structure(
                    "[Worksheet] Collections",
                    lesson_description=(
                        "Uses values from worksheet \u201cSKU catalog\u201d to show " "collection facts."
                    ),
                    additional_headings=["[Worksheet] SKU catalog"],
                )
            )

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert "collection facts" in result.modules[0].lessons[0].description.casefold()
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_architect_allows_pronominal_enrichment_with_cited_supporting_heading() -> None:
    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(
                content=_structure(
                    "[Worksheet] Collections",
                    lesson_description=(
                        "Its wardrobe example is SKU-1 at 199000, from worksheet " "\u201cSKU catalog\u201d."
                    ),
                    additional_headings=["[Worksheet] SKU catalog"],
                )
            )

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert "wardrobe example" in result.modules[0].lessons[0].description.casefold()
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_architect_requires_supporting_heading_for_generic_catalog_details() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] Collections",
                    lesson_description=(
                        "Collection facts: this lesson covers SKUs, article numbers, " "dimensions, and prices."
                    ),
                ),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].description == "Facts stated in the source"
    assert len(llm.prompts) == 2
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]


@pytest.mark.asyncio
async def test_architect_retries_when_a_lesson_omits_the_primary_section() -> None:
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
    assert len(llm.prompts) == 2
    assert "direct_source_lesson_primary_section_missing" in llm.prompts[1]


@pytest.mark.asyncio
async def test_architect_retries_when_supporting_catalog_drives_lesson_title() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] Collections",
                    lesson_title="SKU catalog: articles, dimensions and prices",
                ),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].title == "Collection facts"
    assert len(llm.prompts) == 2
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]


@pytest.mark.asyncio
async def test_architect_retries_when_supporting_catalog_drives_lesson_description() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] Collections",
                    lesson_description=(
                        "This lesson covers worksheet \u201cSKU catalog\u201d, prices, " "and article numbers."
                    ),
                    additional_headings=["[Worksheet] SKU catalog"],
                ),
                _structure(
                    "[Worksheet] Collections",
                    lesson_description=("Examples from the source: SKUs, prices, and article numbers."),
                    additional_headings=["[Worksheet] SKU catalog"],
                ),
                _structure(
                    "[Worksheet] Collections",
                    lesson_description=(
                        "This lesson is about worksheet \u201cSKU catalog\u201d; examples "
                        "include its SKUs and prices."
                    ),
                    additional_headings=["[Worksheet] SKU catalog"],
                ),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].lessons[0].description == "Facts stated in the source"
    assert len(llm.prompts) == 4
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]
    assert "direct_source_supporting_section_promoted" in llm.prompts[2]
    assert "direct_source_supporting_section_promoted" in llm.prompts[3]


@pytest.mark.asyncio
async def test_architect_retries_when_supporting_catalog_drives_module_title() -> None:
    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] Collections",
                    module_title="SKU catalog",
                    additional_headings=["[Worksheet] SKU catalog"],
                ),
                _structure("[Worksheet] Collections"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, _corpus(), max_total_lessons=4)

    assert result.modules[0].title == "Products"
    assert len(llm.prompts) == 2
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]


@pytest.mark.asyncio
async def test_low_confidence_primary_is_advisory_but_known_supporting_stays_restricted() -> None:
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
            headings=("[Worksheet] SKU catalog",),
            text="SKU | Catalog | Price\nSKU-1 | Wardrobe | 199000",
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
            self.prompts: list[str] = []
            self.responses = [
                _structure(
                    "[Worksheet] SKU catalog",
                    lesson_title="SKU catalog",
                ),
                _structure("[Worksheet] Sheet1"),
            ]

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=self.responses.pop(0))

    llm = LLM()
    result = await run_direct_architect(llm, corpus, max_total_lessons=4)

    assert result.modules[0].lessons[0].relevant_headings == ["[Worksheet] Sheet1"]
    assert len(llm.prompts) == 2
    assert "direct_source_supporting_section_promoted" in llm.prompts[1]


@pytest.mark.asyncio
async def test_primary_heading_coverage_is_scoped_by_document_id() -> None:
    revision = "document:" + "a" * 64
    primary_chunk = DirectSourceChunk(
        chunk_id="direct:doc-primary:0",
        doc_id="doc-primary",
        doc_name="primary.xlsx",
        title="Primary source",
        headings=("[Worksheet] Shared",),
        text="Collection | Benefit\nChicago | Modular storage",
        source_revision=revision,
        chunk_index=0,
    )
    supporting_chunk = DirectSourceChunk(
        chunk_id="direct:doc-support:0",
        doc_id="doc-support",
        doc_name="support.xlsx",
        title="Supporting source",
        headings=("[Worksheet] Shared",),
        text="SKU | Catalog | Price\nSKU-1 | Wardrobe | 199000",
        source_revision=revision,
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-primary",
                title="Primary source",
                filename="primary.xlsx",
                category="general",
                source_revision=revision,
                chunks=(primary_chunk,),
            ),
            DirectSourceDocument(
                doc_id="doc-support",
                title="Supporting source",
                filename="support.xlsx",
                category="general",
                source_revision=revision,
                chunks=(supporting_chunk,),
            ),
        ),
        total_chars=len(primary_chunk.text) + len(supporting_chunk.text),
        total_chunks=2,
    )
    ambiguous = json.dumps(
        {
            "title": "Product course",
            "modules": [
                {
                    "title": "Products",
                    "lessons": [
                        {
                            "title": "Collection facts",
                            "description": "Collection facts with supporting examples.",
                            "objectives": ["Describe collection benefits"],
                            "source_doc_ids": ["doc-primary", "doc-support"],
                            "relevant_headings": ["[Worksheet] Shared"],
                        }
                    ],
                }
            ],
        }
    )

    class LLM:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def ainvoke(self, messages):
            self.prompts.append(messages[-1]["content"])
            return SimpleNamespace(content=ambiguous)

    llm = LLM()
    with pytest.raises(DirectSourceError) as exc_info:
        await run_direct_architect(
            llm,
            corpus,
            max_total_lessons=4,
            combination_goal="Use the primary source and supporting examples together.",
        )

    assert exc_info.value.code == "direct_source_heading_document_ambiguous"
    assert len(llm.prompts) == 1


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
            return SimpleNamespace(
                content=_structure(
                    "[Worksheet] Sheet2",
                    lesson_title="Product selection",
                )
            )

    llm = LLM()
    result = await run_direct_architect(llm, corpus, max_total_lessons=4)

    assert result.modules[0].lessons[0].relevant_headings == ["[Worksheet] Sheet2"]
    assert llm.calls == 1
