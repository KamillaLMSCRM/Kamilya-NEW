"""Writer Agent — deterministic 3-step pipeline for content generation.

Flow: generate queries -> retrieve + rank chunks -> generate lesson content.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Callable

from app.modules.ai.llm_client import LLMClient, create_llm
from app.modules.ai.ingestion import VectorStore
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.ml_prompts import get_renderer

logger = logging.getLogger(__name__)
MAX_CHUNK_CHARS = 24_000


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    doc_name: str
    headings: list[str]
    text: str
    query: str
    distance: float


def resolve_lesson_doc_ids(
    lesson_doc_ids: list[str],
    selected_doc_ids: list[str],
) -> list[str]:
    """Validate Architect output against the selected source boundary."""
    selected = set(selected_doc_ids)
    resolved = list(dict.fromkeys(doc_id for doc_id in lesson_doc_ids if doc_id in selected))
    if resolved:
        return resolved
    if len(selected_doc_ids) == 1:
        return list(selected_doc_ids)
    raise ValueError(
        "Architect did not provide valid source_doc_ids for a lesson in a multi-document course"
    )


def _load_generation_prompt() -> str:
    """Load the static writer generation prompt from Jinja2 template."""
    return get_renderer().render("writer/system.md")


GENERATION_PROMPT = _load_generation_prompt()


def _generate_queries(
    lesson_title: str,
    objectives: list[str],
    module_title: str,
    course_title: str,
    relevant_headings: list[str] | None = None,
) -> list[str]:
    """Generate search queries deterministically from title, objectives, and headings."""
    queries = [lesson_title]
    for obj in objectives:
        queries.append(obj)
    if relevant_headings:
        for h in relevant_headings:
            queries.append(f"{lesson_title} {h}")
    return queries


async def _retrieve_and_rerank(
    store: VectorStore,
    queries: list[str],
    lesson_title: str,
    doc_ids: list[str] | None = None,
    tenant_id: str | None = None,
    embeddings_provider=None,
    n_results: int = 15,
    top_n: int = 10,
    similarity_threshold: float = 0.45,
) -> list[RetrievedChunk]:
    """Multi-query retrieval + deduplication + ranking."""
    where = None
    if doc_ids:
        if len(doc_ids) == 1:
            where = {"doc_id": doc_ids[0]}
        else:
            where = {"doc_id": {"$in": doc_ids}}

    # Get real embeddings (Qwen → hash fallback)
    if embeddings_provider is not None:
        query_embeddings = await embeddings_provider.embed(queries)
    else:
        from app.modules.ai.ingestion import EmbeddingsProvider
        provider = EmbeddingsProvider()
        query_embeddings = await provider.embed(queries)

    best_chunks: dict[str, RetrievedChunk] = {}

    for qe, query_text in zip(query_embeddings, queries):
        results = await store.query(
            query_embeddings=[qe],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
            tenant_id=tenant_id,
        )
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for doc_text, dist, meta in zip(documents, distances, metadatas):
            if doc_text and (doc_text not in best_chunks or dist < best_chunks[doc_text].distance):
                headings_raw = (meta or {}).get("headings", "[]")
                try:
                    headings = json.loads(headings_raw)
                except (json.JSONDecodeError, TypeError):
                    headings = []
                best_chunks[doc_text] = RetrievedChunk(
                    chunk_id=str((meta or {}).get("chunk_id", "")),
                    doc_id=str((meta or {}).get("doc_id", "")),
                    doc_name=str((meta or {}).get("doc_name", "")),
                    headings=headings,
                    text=doc_text,
                    query=query_text,
                    distance=float(dist),
                )

    if not best_chunks:
        return []

    ranked = sorted(best_chunks.values(), key=lambda chunk: chunk.distance)
    pre_filter_ranked = ranked
    ranked = [chunk for chunk in ranked if chunk.distance < similarity_threshold]
    if not ranked and pre_filter_ranked:
        logger.warning(
            "No source chunks met the relevance threshold for lesson %s (best distance %.3f)",
            lesson_title,
            pre_filter_ranked[0].distance,
        )
        return []
    return ranked[:top_n]


async def write_lesson(
    llm: LLMClient,
    store: VectorStore,
    lesson_title: str,
    objectives: list[str],
    module_title: str,
    course_title: str,
    doc_ids: list[str] | None = None,
    tenant_id: str | None = None,
    relevant_headings: list[str] | None = None,
    language: str = "ru",
    sibling_lessons: list[str] | None = None,
    embeddings_provider=None,
    require_sources: bool = False,
) -> LessonContent:
    """Generate grounded content for a single lesson (3-step pipeline)."""
    # Step 1: Deterministic query generation
    queries = _generate_queries(
        lesson_title, objectives, module_title, course_title,
        relevant_headings=relevant_headings,
    )

    # Step 2: Retrieve + rank
    formatted_chunks = await _retrieve_and_rerank(
        store, queries, lesson_title, doc_ids,
        tenant_id=tenant_id,
        embeddings_provider=embeddings_provider,
    )

    if not formatted_chunks:
        if require_sources:
            raise ValueError(
                f"No relevant source fragments found for lesson '{lesson_title}'. "
                "Adjust the structure or source documents instead of generating from general knowledge."
            )
        # No chunks found — still generate content from LLM using general knowledge
        objectives_text = "\n".join(f"- {o}" for o in objectives) if objectives else "- (none)"
        lang_names = {"ru": "Русский", "kk": "Қазақша", "en": "English"}
        lang_name = lang_names.get(language, language)

        prompt = f"""Write a comprehensive educational lesson on the topic below. 
Use your general knowledge. Write detailed, well-structured content with examples.

Lesson: {lesson_title}
Module: {module_title}
Course: {course_title}
Target Language: {language} ({lang_name})
Objectives:
{objectives_text}

IMPORTANT: Write the ENTIRE lesson content in {language} ({lang_name}).
Format as Markdown with ## headers for sections.
Include practical examples and key concepts.
Length: 1500-2500 words."""

        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        content = response.content or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        return LessonContent(
            title=lesson_title,
            objectives=objectives,
            content=content,
            source_chunks=[],
        )

    # Step 3: Generate
    chunks_text = "\n\n---\n\n".join(
        f"[Source: {chunk.doc_name}; context: {' > '.join(chunk.headings)}]\n{chunk.text}"
        for chunk in formatted_chunks
    )
    objectives_text = "\n".join(f"- {o}" for o in objectives) if objectives else "- (none)"

    lang_names = {"ru": "Русский", "kk": "Қазақша", "en": "English"}
    lang_name = lang_names.get(language, language)

    sibling_block = ""
    if sibling_lessons:
        sibling_list = "\n".join(f"- {t}" for t in sibling_lessons)
        sibling_block = f"\n\nOTHER LESSONS IN MODULE (do NOT cover their topics):\n{sibling_list}"

    prompt = f"""{GENERATION_PROMPT}

Lesson: {lesson_title}
Module: {module_title}
Course: {course_title}
Target Language: {language} ({lang_name})
Objectives:
{objectives_text}{sibling_block}

Source material:
{chunks_text}

IMPORTANT: Write the ENTIRE lesson content in {language} ({lang_name})."""

    response = await llm.ainvoke([{"role": "user", "content": prompt}])

    return LessonContent(
        title=lesson_title,
        objectives=objectives,
        content=response.content,
        source_chunks=[chunk.text for chunk in formatted_chunks],
        source_references=[asdict(chunk) for chunk in formatted_chunks],
    )


async def write_course(
    llm: LLMClient,
    store: VectorStore,
    structure,
    doc_ids: list[str] | None = None,
    language: str = "ru",
    on_progress: Callable | None = None,
    embeddings_provider=None,
    tenant_id: str | None = None,
) -> CourseContent:
    """Generate content for all lessons sequentially."""
    modules = []
    total_lessons = sum(len(m.lessons) for m in structure.modules)
    lesson_num = 0

    for module in structure.modules:
        lesson_contents = []
        sibling_titles = [l.title for l in module.lessons]

        for lesson in module.lessons:
            lesson_num += 1
            if on_progress:
                result = on_progress(f"Writing lesson {lesson_num}/{total_lessons}: {lesson.title}")
                if hasattr(result, '__await__'):
                    await result

            # Check for cancellation
            import asyncio
            if asyncio.current_task() and asyncio.current_task().cancelled():
                raise asyncio.CancelledError()

            objectives = [obj.text for obj in lesson.objectives]
            lesson_headings = lesson.relevant_headings if lesson.relevant_headings else None

            lesson_doc_ids = resolve_lesson_doc_ids(lesson.source_doc_ids, doc_ids or [])
            content = await write_lesson(
                llm=llm,
                store=store,
                lesson_title=lesson.title,
                objectives=objectives,
                module_title=module.title,
                course_title=structure.title,
                doc_ids=lesson_doc_ids,
                tenant_id=tenant_id,
                relevant_headings=lesson_headings,
                language=language,
                sibling_lessons=[t for t in sibling_titles if t != lesson.title],
                embeddings_provider=embeddings_provider,
                require_sources=bool(doc_ids),
            )
            lesson_contents.append(content)

        modules.append(ModuleContent(title=module.title, lessons=lesson_contents))

    return CourseContent(
        title=structure.title,
        description=structure.description,
        modules=modules,
    )
