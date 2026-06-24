"""Writer Agent — deterministic 3-step pipeline for content generation.

Flow: generate queries -> retrieve + rank chunks -> generate lesson content.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from app.modules.ai.llm_client import LLMClient, create_llm
from app.modules.ai.ingestion import VectorStore
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent

logger = logging.getLogger(__name__)
MAX_CHUNK_CHARS = 24_000

GENERATION_PROMPT = """\
You are a Course Content Writer. Write a comprehensive, well-structured lesson \
based EXCLUSIVELY on the provided source chunks.

Rules:
- Write in Markdown format starting with a level-1 heading
- Write in the TARGET LANGUAGE specified (translate/adapt from source if needed)
- Base content ONLY on the provided chunks — do NOT invent facts
- Cover all learning objectives
- Do NOT cite or reference source numbers in the output

CRITICAL — language rule:
- Your ENTIRE output MUST be in the TARGET LANGUAGE specified below.
- TRANSLATE everything if source material is in a different language.

CRITICAL — anti-repetition rules:
- Write ONLY about the specific topic indicated by the lesson title and objectives
- Do NOT include general introductions or background material UNLESS it is the SPECIFIC topic
- Do NOT define concepts covered by other lessons in the module
- Start directly with the lesson-specific material.
"""


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
    embeddings_provider=None,
    n_results: int = 15,
    top_n: int = 10,
    similarity_threshold: float = 0.45,
) -> list[tuple[str, str]]:
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

    best_chunks: dict[str, tuple[float, list[str], str]] = {}

    for qe, query_text in zip(query_embeddings, queries):
        results = await store.query(
            query_embeddings=[qe],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for doc_text, dist, meta in zip(documents, distances, metadatas):
            if doc_text and (doc_text not in best_chunks or dist < best_chunks[doc_text][0]):
                headings_raw = (meta or {}).get("headings", "[]")
                try:
                    headings = json.loads(headings_raw)
                except (json.JSONDecodeError, TypeError):
                    headings = []
                best_chunks[doc_text] = (dist, headings, query_text)

    if not best_chunks:
        return []

    ranked = sorted(best_chunks.items(), key=lambda x: x[1][0])
    pre_filter_ranked = ranked
    ranked = [
        (t, (d, h, q))
        for t, (d, h, q) in ranked
        if d < similarity_threshold
    ]
    if not ranked and pre_filter_ranked:
        ranked = pre_filter_ranked

    formatted = []
    for text, (_dist, headings, query) in ranked[:top_n]:
        if headings:
            heading_ctx = " > ".join(headings)
            formatted.append((f"[Context: {heading_ctx}]\n{text}", query))
        else:
            formatted.append((text, query))
    return formatted


async def write_lesson(
    llm: LLMClient,
    store: VectorStore,
    lesson_title: str,
    objectives: list[str],
    module_title: str,
    course_title: str,
    doc_ids: list[str] | None = None,
    relevant_headings: list[str] | None = None,
    language: str = "ru",
    sibling_lessons: list[str] | None = None,
    embeddings_provider=None,
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
        embeddings_provider=embeddings_provider,
    )

    if not formatted_chunks:
        return LessonContent(
            title=lesson_title,
            objectives=objectives,
            content=f"# {lesson_title}\n\n*No relevant content found.*\n",
            source_chunks=[],
        )

    # Step 3: Generate
    chunks_text = "\n\n---\n\n".join(text for text, _query in formatted_chunks)
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
        source_chunks=[text for text, _query in formatted_chunks],
    )


async def write_course(
    llm: LLMClient,
    store: VectorStore,
    structure,
    doc_ids: list[str] | None = None,
    language: str = "ru",
    on_progress: Callable | None = None,
    embeddings_provider=None,
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

            content = await write_lesson(
                llm=llm,
                store=store,
                lesson_title=lesson.title,
                objectives=objectives,
                module_title=module.title,
                course_title=structure.title,
                doc_ids=doc_ids,
                relevant_headings=lesson_headings,
                language=language,
                sibling_lessons=[t for t in sibling_titles if t != lesson.title],
                embeddings_provider=embeddings_provider,
            )
            lesson_contents.append(content)

        modules.append(ModuleContent(title=module.title, lessons=lesson_contents))

    return CourseContent(
        title=structure.title,
        description=structure.description,
        modules=modules,
    )
