"""Writer Agent — deterministic 3-step pipeline for content generation.

Flow: generate queries -> retrieve + rank chunks -> generate lesson content.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, replace
from typing import Callable

from app.ml_prompts import get_renderer
from app.modules.ai.context_expansion import ContextChunk, expand_context_windows
from app.modules.ai.hybrid_retrieval import (
    RankedRetrievalItem,
    RetrievalBoundary,
    fuse_ranked_results,
)
from app.modules.ai.ingestion import VectorStore
from app.modules.ai.lexical_retrieval import retrieve_lexical_hits
from app.modules.ai.llm_client import LLMClient, create_llm
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent

logger = logging.getLogger(__name__)
MAX_CHUNK_CHARS = 24_000
MAX_WRITER_PROMPT_CHARS = 32_000


class UnsupportedLessonSourceError(ValueError):
    """Raised when a source-bound lesson cannot be grounded in selected documents."""

    def __init__(self, lesson_title: str):
        self.lesson_title = lesson_title
        super().__init__(
            f"No relevant source fragments found for lesson '{lesson_title}'. "
            "Adjust the structure or source documents instead of generating from general knowledge."
        )


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    tenant_id: str
    doc_name: str
    headings: list[str]
    text: str
    query: str
    distance: float
    contributing_queries: tuple[str, ...] = ()
    retrieval_sources: tuple[str, ...] = ()
    rrf_score: float = 0.0
    semantic_distance: float | None = None
    lexical_score: float | None = None
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_revision: str = ""
    embedding_native_dimensions: int | None = None
    embedding_storage_dimensions: int | None = None
    content_sha256: str = ""
    source_revision: str = ""
    indexed_at: str = ""
    chunk_index: int | None = None
    context_chunks: tuple[ContextChunk, ...] = ()


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
    raise ValueError("Architect did not provide valid source_doc_ids for a lesson in a multi-document course")


def _load_generation_prompt() -> str:
    """Load the static writer generation prompt from Jinja2 template."""
    return get_renderer().render("writer/system.md")


GENERATION_PROMPT = _load_generation_prompt()


def _format_source_window(chunk: RetrievedChunk) -> str:
    """Render one traceable retrieval anchor and its bounded document context."""
    if not chunk.context_chunks:
        return (
            f"[Source: {chunk.doc_name}; context: {' > '.join(chunk.headings)}]\n"
            f"{chunk.text}"
        )

    rendered_chunks = []
    for context_chunk in chunk.context_chunks:
        role = "ANCHOR" if context_chunk.is_anchor else "NEIGHBOR"
        rendered_chunks.append(
            "["
            f"Chunk: {context_chunk.chunk_id}; role: {role}; "
            f"index: {context_chunk.chunk_index}; "
            f"revision: {context_chunk.source_revision}; "
            f"context: {' > '.join(context_chunk.headings)}"
            "]\n"
            f"{context_chunk.text}"
        )
    return (
        f"[Source window: {chunk.doc_name}; anchor: {chunk.chunk_id}; "
        f"revision: {chunk.source_revision}]\n"
        + "\n\n".join(rendered_chunks)
    )


def _public_source_reference(chunk: RetrievedChunk) -> dict:
    """Project internal retrieval provenance into a learner-safe citation."""
    context_sections = [
        {
            "document": context.doc_name or chunk.doc_name,
            "headings": list(context.headings),
            "is_anchor": context.is_anchor,
        }
        for context in chunk.context_chunks
    ]
    return {
        "document": chunk.doc_name,
        "headings": list(chunk.headings),
        "context_sections": context_sections,
    }


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
    preferred_headings: list[str] | None = None,
    n_results: int = 15,
    top_n: int = 10,
    similarity_threshold: float = 0.45,
) -> list[RetrievedChunk]:
    """Multi-query retrieval + deduplication + ranking."""
    if not tenant_id:
        raise ValueError("tenant_id_required")
    where = None
    if doc_ids:
        if len(doc_ids) == 1:
            where = {"doc_id": doc_ids[0]}
        else:
            where = {"doc_id": {"$in": doc_ids}}

    # Embed each query with the exact provider identity selected by failover.
    if embeddings_provider is None:
        from app.modules.ai.ingestion import EmbeddingsProvider

        embeddings_provider = EmbeddingsProvider()

    semantic_rankings: list[list[RankedRetrievalItem]] = []
    observed_distances: list[float] = []
    for query_text in queries:
        query_embedding_batch = await embeddings_provider.embed_query_with_provenance(
            query_text
        )
        results = await store.query(
            query_embedding_batch=query_embedding_batch,
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
            tenant_id=tenant_id,
        )
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        ranking: list[RankedRetrievalItem] = []
        for doc_text, dist, meta in zip(documents, distances, metadatas):
            try:
                distance = float(dist)
            except (TypeError, ValueError):
                continue
            observed_distances.append(distance)
            metadata = meta or {}
            chunk_id = str(metadata.get("chunk_id", ""))
            doc_id = str(metadata.get("doc_id", ""))
            if (
                not doc_text
                or not chunk_id
                or not doc_id
                or (doc_ids and doc_id not in set(doc_ids))
                or distance >= similarity_threshold
            ):
                continue
            headings_raw = metadata.get("headings", "[]")
            try:
                headings = json.loads(headings_raw) if isinstance(headings_raw, str) else headings_raw
            except (json.JSONDecodeError, TypeError):
                headings = []
            if not isinstance(headings, list):
                headings = []
            ranking.append(
                RankedRetrievalItem(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    tenant_id=str(tenant_id or ""),
                    doc_name=str(metadata.get("doc_name", "")),
                    headings=tuple(str(heading) for heading in headings),
                    text=doc_text,
                    source="semantic",
                    query=query_text,
                    semantic_distance=distance,
                    embedding_provider=str(metadata.get("embedding_provider") or ""),
                    embedding_model=str(metadata.get("embedding_model") or ""),
                    embedding_revision=str(metadata.get("embedding_revision") or ""),
                    embedding_native_dimensions=metadata.get("embedding_native_dimensions"),
                    embedding_storage_dimensions=metadata.get("embedding_storage_dimensions"),
                    content_sha256=str(metadata.get("embedding_content_sha256") or ""),
                    source_revision=str(metadata.get("embedding_source_revision") or ""),
                    indexed_at=str(metadata.get("embedding_indexed_at") or ""),
                    chunk_index=metadata.get("chunk_index"),
                )
            )
        semantic_rankings.append(ranking)

    lexical_ranking: list[RankedRetrievalItem] = []
    if doc_ids and hasattr(store, "get_all_chunks"):
        lexical_hits = await retrieve_lexical_hits(
            store,
            queries,
            tenant_id=tenant_id,
            doc_ids=doc_ids,
            preferred_headings=preferred_headings,
            limit=n_results,
        )
        lexical_ranking = [
            RankedRetrievalItem(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                tenant_id=str(tenant_id or ""),
                doc_name=hit.doc_name,
                headings=hit.headings,
                text=hit.text,
                source="lexical",
                query="lexical_source_fallback",
                lexical_score=hit.score,
                embedding_provider=hit.embedding_provider,
                embedding_model=hit.embedding_model,
                embedding_revision=hit.embedding_revision,
                embedding_native_dimensions=hit.embedding_native_dimensions,
                embedding_storage_dimensions=hit.embedding_storage_dimensions,
                content_sha256=hit.content_sha256,
                source_revision=hit.source_revision,
                indexed_at=hit.indexed_at,
                chunk_index=hit.chunk_index,
            )
            for hit in lexical_hits
        ]

    fused = fuse_ranked_results(
        semantic_rankings,
        lexical_ranking,
        limit=top_n,
        boundary=RetrievalBoundary(
            tenant_id=str(tenant_id or ""),
            allowed_doc_ids=frozenset(doc_ids or ()),
        ),
    )
    if not fused:
        if observed_distances:
            logger.warning(
                "No source chunks met semantic or lexical relevance gates "
                "(best semantic distance %.3f)",
                min(observed_distances),
            )
        return []
    return [
        RetrievedChunk(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            tenant_id=hit.tenant_id,
            doc_name=hit.doc_name,
            headings=list(hit.headings),
            text=hit.text,
            query=" | ".join(hit.queries),
            distance=hit.semantic_distance if hit.semantic_distance is not None else 1.0,
            contributing_queries=hit.queries,
            retrieval_sources=hit.sources,
            rrf_score=hit.rrf_score,
            semantic_distance=hit.semantic_distance,
            lexical_score=hit.lexical_score,
            embedding_provider=hit.embedding_provider,
            embedding_model=hit.embedding_model,
            embedding_revision=hit.embedding_revision,
            embedding_native_dimensions=hit.embedding_native_dimensions,
            embedding_storage_dimensions=hit.embedding_storage_dimensions,
            content_sha256=hit.content_sha256,
            source_revision=hit.source_revision,
            indexed_at=hit.indexed_at,
            chunk_index=hit.chunk_index,
        )
        for hit in fused
    ]


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
        lesson_title,
        objectives,
        module_title,
        course_title,
        relevant_headings=relevant_headings,
    )

    # Step 2: Retrieve + rank
    formatted_chunks = await _retrieve_and_rerank(
        store,
        queries,
        lesson_title,
        doc_ids,
        tenant_id=tenant_id,
        embeddings_provider=embeddings_provider,
        preferred_headings=relevant_headings,
    )

    if not formatted_chunks:
        if require_sources or doc_ids:
            raise UnsupportedLessonSourceError(lesson_title)
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

    # Expand verified production hits only when the store exposes the exact
    # context-window contract. Lightweight legacy/test stores remain supported;
    # a context-capable store fails closed inside expand_context_windows when
    # provenance is incomplete or crosses tenant/document/revision boundaries.
    context_loader = getattr(store, "get_context_window", None)
    if isinstance(store, VectorStore) and not callable(context_loader):
        raise RuntimeError("production_context_window_api_required")
    if callable(context_loader):
        per_window_budget = max(
            512,
            (MAX_CHUNK_CHARS // max(len(formatted_chunks), 1)) - 512,
        )
        context_windows = await expand_context_windows(
            store,
            formatted_chunks,
            tenant_id=str(tenant_id or ""),
            radius=1,
            max_chars_per_window=per_window_budget,
        )
        windows_by_anchor = {
            window.anchor_chunk_id: window for window in context_windows
        }
        if len(context_windows) != len(windows_by_anchor):
            raise ValueError("duplicate_context_window_anchor")
        expected_anchors = {chunk.chunk_id for chunk in formatted_chunks}
        if set(windows_by_anchor) != expected_anchors:
            raise ValueError("context_window_anchor_set_mismatch")
        seen_context_chunks: set[tuple[str, str, str, str]] = set()
        for window in context_windows:
            if window.tenant_id != str(tenant_id or ""):
                raise ValueError("context_window_tenant_mismatch")
            for context in window.chunks:
                identity = (
                    context.tenant_id,
                    context.doc_id,
                    context.source_revision,
                    context.chunk_id,
                )
                if context.tenant_id != str(tenant_id or ""):
                    raise ValueError("context_window_tenant_mismatch")
                if identity in seen_context_chunks:
                    raise ValueError("overlapping_context_windows")
                seen_context_chunks.add(identity)
        formatted_chunks = [
            replace(
                chunk,
                context_chunks=windows_by_anchor[chunk.chunk_id].chunks,
            )
            for chunk in formatted_chunks
        ]

    # Step 3: Generate
    chunks_text = "\n\n---\n\n".join(
        _format_source_window(chunk) for chunk in formatted_chunks
    )
    objectives_text = "\n".join(f"- {o}" for o in objectives) if objectives else "- (none)"

    lang_names = {"ru": "Русский", "kk": "Қазақша", "en": "English"}
    lang_name = lang_names.get(language, language)

    sibling_block = ""
    if sibling_lessons:
        sibling_list = "\n".join(f"- {t}" for t in sibling_lessons)
        sibling_block = f"\n\nOTHER LESSONS IN COURSE (do NOT cover their topics):\n{sibling_list}"

    headings_block = ""
    if relevant_headings:
        headings_list = "\n".join(f"- {heading}" for heading in relevant_headings)
        headings_block = (
            "\n\nAUTHORITATIVE SOURCE HEADING BOUNDARIES:\n"
            f"{headings_list}\n"
            "Retrieved OCR chunks can contain text that spills across section or page "
            "boundaries. Use only material belonging to these headings."
        )

    prompt = f"""{GENERATION_PROMPT}

Lesson: {lesson_title}
Module: {module_title}
Course: {course_title}
Target Language: {language} ({lang_name})
Objectives:
{objectives_text}{headings_block}{sibling_block}

Source material:
{chunks_text}

IMPORTANT: Write the ENTIRE lesson content in {language} ({lang_name})."""

    if len(prompt) > MAX_WRITER_PROMPT_CHARS:
        raise ValueError("writer_prompt_budget_exceeded")

    response = await llm.ainvoke([{"role": "user", "content": prompt}])

    return LessonContent(
        title=lesson_title,
        objectives=objectives,
        content=response.content,
        source_chunks=[chunk.text for chunk in formatted_chunks],
        source_references=[_public_source_reference(chunk) for chunk in formatted_chunks],
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
    all_lesson_titles = [lesson.title for course_module in structure.modules for lesson in course_module.lessons]
    lesson_num = 0

    for module in structure.modules:
        lesson_contents = []
        for lesson in module.lessons:
            lesson_num += 1
            if on_progress:
                result = on_progress(f"Writing lesson {lesson_num}/{total_lessons}: {lesson.title}")
                if hasattr(result, "__await__"):
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
                sibling_lessons=[t for t in all_lesson_titles if t != lesson.title],
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
