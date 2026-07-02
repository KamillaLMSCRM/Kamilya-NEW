"""Architect Agent — interactive course design via LLM + retrieval tools."""
from __future__ import annotations

import asyncio
import json
import re
import logging
from typing import Callable

from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.llm_client import LLMClient, create_llm
from app.modules.ai.ingestion import VectorStore, Summarizer
from app.ml_prompts import get_renderer

logger = logging.getLogger(__name__)

CHAPTER_TEXT_MAX_CHARS = 8000


def _load_system_prompt() -> str:
    """Load the static architect system prompt from Jinja2 template."""
    return get_renderer().render("architect/system.md")


SYSTEM_PROMPT = _load_system_prompt()


def create_architect_tools(
    summaries_dir: str = "./summaries",
    chroma_dir: str = "./chroma_data",
    doc_ids: list[str] | None = None,
    max_chapters_per_doc: int = 5,
    embeddings_client=None,
    vector_store: VectorStore | None = None,
    tenant_id: str | None = None,
):
    """Create retrieval tools for the Architect Agent.

    tenant_id: REQUIRED for tenant isolation. When provided, every query is
    filtered by `WHERE tenant_id = :tenant_id` — this prevents leaking other
    tenants' embeddings into the LLM context. Pass None ONLY for
    system/maintenance code paths.
    """
    import collections

    store = vector_store or VectorStore(chroma_dir)
    scope = set(doc_ids) if doc_ids else None
    chapter_read_counts = collections.defaultdict(int)

    def _tenant_clause(extra_where: str = "") -> tuple[str, dict]:
        """Build WHERE clause that always includes tenant filter when known."""
        clauses = []
        params: dict = {}
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if extra_where:
            clauses.append(extra_where)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    async def list_documents() -> str:
        """List all ingested documents with IDs and names from DB (tenant-scoped)."""
        from app.core.db import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            if scope:
                placeholders = ", ".join(f":doc_{i}" for i in range(len(scope)))
                extra = f"doc_id IN ({placeholders})"
                where, params = _tenant_clause(extra)
                params.update({f"doc_{i}": did for i, did in enumerate(scope)})
                result = await session.execute(
                    text(f"SELECT DISTINCT doc_id, doc_name FROM document_embeddings {where} ORDER BY doc_name"),
                    params,
                )
            else:
                where, params = _tenant_clause()
                result = await session.execute(
                    text(f"SELECT DISTINCT doc_id, doc_name FROM document_embeddings {where} ORDER BY doc_name"),
                    params,
                )
            rows = result.fetchall()

        results = []
        for row in rows:
            results.append({"doc_id": row[0], "doc_name": row[1]})
        return json.dumps(results, ensure_ascii=False, indent=2)

    async def get_document_summary(doc_id: str) -> str:
        """Get educational profile summary of a document from DB embeddings."""
        from app.core.db import async_session_factory
        from sqlalchemy import text

        if scope and doc_id not in scope:
            return f"Document '{doc_id}' is not in the current scope."

        async with async_session_factory() as session:
            where, params = _tenant_clause("doc_id = :doc_id")
            params["doc_id"] = doc_id
            result = await session.execute(
                text(f"SELECT text, headings FROM document_embeddings {where} LIMIT 5"),
                params,
            )
            rows = result.fetchall()

        if not rows:
            return f"Document '{doc_id}' has no ingested content."

        parts = []
        for text_content, headings in rows:
            headings_str = ""
            try:
                h = json.loads(headings) if headings else []
                if h:
                    headings_str = " > ".join(h) + ": "
            except (json.JSONDecodeError, TypeError):
                pass
            preview = text_content[:500] + "..." if len(text_content) > 500 else text_content
            parts.append(f"{headings_str}{preview}")

        return "\n\n".join(parts)

    async def get_document_toc(doc_id: str) -> str:
        """Get table of contents of a document from DB."""
        from app.core.db import async_session_factory
        from sqlalchemy import text

        if scope and doc_id not in scope:
            return f"Document '{doc_id}' is not in scope."

        async with async_session_factory() as session:
            where, params = _tenant_clause("doc_id = :doc_id")
            params["doc_id"] = doc_id
            result = await session.execute(
                text(f"SELECT DISTINCT headings FROM document_embeddings {where}"),
                params,
            )
            rows = result.fetchall()

        if not rows:
            return f"Document '{doc_id}' not found."

        headings_set = set()
        for (headings_json,) in rows:
            try:
                h = json.loads(headings_json) if headings_json else []
                for heading in h:
                    headings_set.add(heading)
            except (json.JSONDecodeError, TypeError):
                pass

        if headings_set:
            return "\n".join(f"- {h}" for h in sorted(headings_set))
        return "No TOC available."

    async def get_chapter_text(doc_id: str, chapter_title: str) -> str:
        """Read text chunks matching a heading from DB."""
        from app.core.db import async_session_factory
        from sqlalchemy import text

        if scope and doc_id not in scope:
            return f"Document '{doc_id}' is not in scope."
        if chapter_read_counts[doc_id] >= max_chapters_per_doc:
            return (
                f"Limit reached: {max_chapters_per_doc} chapters from '{doc_id}'. "
                f"Use search_documents() instead."
            )
        chapter_read_counts[doc_id] += 1

        async with async_session_factory() as session:
            where, params = _tenant_clause("doc_id = :doc_id")
            params["doc_id"] = doc_id
            result = await session.execute(
                text(f"SELECT text, headings FROM document_embeddings {where}"),
                params,
            )
            rows = result.fetchall()

        if not rows:
            return f"Document '{doc_id}' not found."

        matching = []
        for text_content, headings_json in rows:
            try:
                h = json.loads(headings_json) if headings_json else []
                if any(chapter_title.lower() in heading.lower() for heading in h):
                    matching.append(text_content)
            except (json.JSONDecodeError, TypeError):
                pass

        if matching:
            full = "\n\n".join(matching)
            return full[:8000] + "..." if len(full) > 8000 else full
        return f"No content found for chapter '{chapter_title}'."

    async def search_documents(query: str, doc_id: str | None = None) -> str:
        """Semantic search across ingested documents (tenant-scoped)."""
        from app.modules.ai.ingestion import EmbeddingsProvider
        where = None
        if doc_id:
            where = {"doc_id": doc_id}
        elif scope:
            where = {"doc_id": {"$in": list(scope)}}
        tenant_filter = tenant_id

        # Generate real embeddings for the query
        provider = EmbeddingsProvider()
        query_embedding = await provider.embed_query(query)

        raw = await store.query(
            query_embeddings=[query_embedding],
            n_results=10,
            where=where,
            include=["documents", "metadatas", "distances"],
            tenant_id=tenant_id,
        )
        # Post-filter by tenant_id via SQL to avoid leaking chunks from other
        # tenants. Chroma `where` doesn't support arbitrary AND with the
        # vector query, and we don't store tenant_id in chunk metadata, so we
        # verify each result row against the source table.
        if tenant_filter is not None:
            from app.core.db import async_session_factory
            from sqlalchemy import text as _sa_text
            metas = raw.get("metadatas", [[]])[0]
            docs = raw.get("documents", [[]])[0]
            dists = raw.get("distances", [[]])[0]
            # Collect unique doc_names (these are the human-readable names; the
            # embeddings table also has a stable doc_id) — query DB to map back.
            candidate_doc_names = list({m.get("doc_name", "") for m in metas if m.get("doc_name")})
            if candidate_doc_names:
                placeholders = ", ".join(f":n_{i}" for i in range(len(candidate_doc_names)))
                async with async_session_factory() as session:
                    res = await session.execute(
                        _sa_text(
                            f"SELECT DISTINCT doc_name FROM document_embeddings "
                            f"WHERE tenant_id = :tenant_id AND doc_name IN ({placeholders})"
                        ),
                        {"tenant_id": tenant_filter, **{f"n_{i}": n for i, n in enumerate(candidate_doc_names)}},
                    )
                    allowed = {row[0] for row in res.fetchall()}
                keep_idx = [i for i, m in enumerate(metas) if m.get("doc_name", "") in allowed]
                raw["documents"] = [[docs[i] for i in keep_idx]]
                raw["metadatas"] = [[metas[i] for i in keep_idx]]
                raw["distances"] = [[dists[i] for i in keep_idx]]
            else:
                raw["documents"] = [[]]
                raw["metadatas"] = [[]]
                raw["distances"] = [[]]
        results = []
        docs = raw.get("documents", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]
        for text, meta, dist in zip(docs, metas, distances):
            entry = {
                "text": text,
                "doc_name": meta.get("doc_name", ""),
                "headings": meta.get("headings", ""),
            }
            results.append(entry)
        return json.dumps(results, ensure_ascii=False, indent=2)

    return {
        "list_documents": list_documents,
        "get_document_summary": get_document_summary,
        "get_document_toc": get_document_toc,
        "get_chapter_text": get_chapter_text,
        "search_documents": search_documents,
    }


def _build_system_prompt(
    goals: list[str] | None = None,
    course_hours: float | None = None,
    num_modules: int | None = None,
    language: str = "ru",
    guidance: str | None = None,
) -> str:
    """Build localized system prompt with goals and constraints."""
    prompt = SYSTEM_PROMPT

    if goals:
        numbered = "\n".join(f"{i}. {g}" for i, g in enumerate(goals, 1))
        prompt += (
            "\n\n## User-Defined Learning Goals\n\n"
            "You MUST prioritise these topics:\n\n"
            f"{numbered}\n\n"
            "Focus modules and lessons on content that addresses these goals.\n"
        )

    if course_hours is not None or num_modules is not None:
        lines = ["\n\n## Course Constraints\n"]
        if course_hours is not None:
            lines.append(f"- Target duration: {course_hours:g} hours")
        if num_modules is not None:
            lines.append(f"- Modules/sections: {num_modules}")
        prompt += "\n".join(lines)

    lang_names = {"ru": "Русский", "kk": "Қазақша", "en": "English"}
    lang_name = lang_names.get(language, language)

    prompt += (
        f"\n\n## Target Language\n\n"
        f"CRITICAL: Write ALL content in **{language}** ({lang_name}).\n"
        f"Zero-tolerance requirement — 100% output must be in {lang_name}.\n"
    )

    if guidance:
        prompt += (
            "\n\n## User Structure Guidance\n\n"
            f"{guidance}\n\n"
            "Adapt and improve based on document content.\n"
        )

    return prompt


def _attempt_json_repair(json_str: str) -> str | None:
    """Fix common JSON issues from LLM output using json_repair."""
    from json_repair import repair_json
    try:
        repaired = repair_json(json_str, return_objects=True)
        if isinstance(repaired, dict):
            return json.dumps(repaired, ensure_ascii=False)
    except Exception:
        pass
    return None


def _parse_course_structure(text: str) -> CourseStructure:
    """Parse JSON course structure from LLM output."""
    from json_repair import repair_json

    # Strip thinking tags
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if match:
        json_str = match.group(1).strip()
    else:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            json_str = match.group(0)
        else:
            raise ValueError(f"Could not find JSON in agent output. Last 500 chars: {text[-500:]}")

    # Sanitize JSON
    json_str = re.sub(r"//[^\n]*", "", json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
    json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
    json_str = json_str.replace('\u201c', '"').replace('\u201d', '"')
    json_str = json_str.replace('\u2018', "'").replace('\u2019', "'")

    # Try direct parse
    try:
        return CourseStructure.from_json(json_str)
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    # Fallback: json_repair
    repaired = _attempt_json_repair(json_str)
    if repaired:
        try:
            return CourseStructure.from_json(repaired)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    raise ValueError(f"Failed to parse course structure JSON")


async def run_architect(
    llm: LLMClient,
    tools: dict,
    goals: list[str] | None = None,
    course_hours: float | None = None,
    num_modules: int | None = None,
    language: str = "ru",
    guidance: str | None = None,
    on_message: Callable | None = None,
    max_iterations: int = 20,
    tenant_id: str | None = None,
) -> CourseStructure:
    """
    Run the Architect Agent — iterative LLM calls with tool execution.
    Simplified ReAct loop (no LangGraph dependency required).

    tenant_id: when provided, the pre-check is scoped to this tenant and
    the error message will not leak documents from other tenants.
    """
    system_prompt = _build_system_prompt(
        goals=goals,
        course_hours=course_hours,
        num_modules=num_modules,
        language=language,
        guidance=guidance,
    )

    messages = [{"role": "system", "content": system_prompt}]

    if goals:
        human_content = f"Explore documents and design a course focused on: {', '.join(goals)}"
    else:
        human_content = "Explore the documents and design a course structure."

    messages.append({"role": "user", "content": human_content})

    tool_descriptions = """
You have access to these tools:
- list_documents() -> str: List all ingested documents
- get_document_summary(doc_id: str) -> str: Get document summary
- get_document_toc(doc_id: str) -> str: Get document table of contents
- get_chapter_text(doc_id: str, chapter_title: str) -> str: Read chapter text
- search_documents(query: str, doc_id: str = None) -> str: Semantic search

To use a tool, respond with a JSON block:
```json
{"tool": "tool_name", "args": {"arg1": "value1"}}
```

After receiving tool results, continue your analysis.
When ready to output the final course structure, output ONLY the JSON code block.
"""

    messages[0]["content"] = messages[0]["content"] + "\n\n" + tool_descriptions

    # Pre-check: validate documents exist before starting the loop.
    # Tenant-scoped — never show documents from other tenants in error messages.
    from app.core.db import async_session_factory
    from sqlalchemy import text as sa_text
    async with async_session_factory() as session:
        if tenant_id is not None:
            all_docs = await session.execute(
                sa_text(
                    "SELECT DISTINCT doc_id, doc_name FROM document_embeddings "
                    "WHERE tenant_id = :tenant_id ORDER BY doc_name"
                ),
                {"tenant_id": tenant_id},
            )
        else:
            all_docs = await session.execute(
                sa_text("SELECT DISTINCT doc_id, doc_name FROM document_embeddings ORDER BY doc_name")
            )
        all_rows = all_docs.fetchall()
    if not all_rows:
        raise ValueError(
            "No documents with embeddings were found for your organization. "
            "Please upload documents before generating a course."
        )
    logger.info(f"Architect pre-check: {len(all_rows)} documents available (tenant={tenant_id})")

    doc_list_result = await tools["list_documents"]()
    logger.info(f"Architect scoped docs: {doc_list_result[:300]}")
    try:
        doc_list = json.loads(doc_list_result)
        if not doc_list:
            # Build a helpful, tenant-safe error message.
            available_names = [r[1] for r in all_rows]
            raise ValueError(
                "None of the selected documents have embeddings yet — their ingestion "
                "may have failed during upload. Please re-upload the documents you "
                f"want to use. Currently available for your organization: {available_names}"
            )
    except (json.JSONDecodeError, TypeError):
        pass

    # Inject document list into conversation so LLM knows what's available
    messages.append({"role": "user", "content": f"Here are the available documents:\n{doc_list_result}\n\nAnalyze these documents and design the course."})

    for iteration in range(max_iterations):
        response = await llm.ainvoke(messages)
        content = response.content

        if on_message:
            on_message(f"Iteration {iteration + 1}: {content[:200]}...")

        # Check if this is the final JSON output
        if "```json" in content and '"modules"' in content:
            try:
                return _parse_course_structure(content)
            except ValueError as e:
                # Ask LLM to fix the broken JSON
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Your JSON has a syntax error: {e}. Please output the corrected JSON ONLY. No explanation."})
                if on_message:
                    on_message(f"JSON parse error, asking for fix: {e}")
                continue

        # Check for tool call in ```json block
        tool_match = re.search(r'```json\s*\n?([\s\S]*?)\n?\s*```', content)
        if tool_match:
            raw = tool_match.group(1).strip()
            if '"tool"' in raw:
                try:
                    tool_json = json.loads(raw)
                    tool_name = tool_json.get("tool")
                    tool_args = tool_json.get("args", {})

                    if tool_name in tools:
                        result = await tools[tool_name](**tool_args)
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"Tool result: {result}"})
                        if on_message:
                            on_message(f"  -> {tool_name} returned {len(str(result))} chars")
                        continue
                    else:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"Error: Unknown tool '{tool_name}'"})
                        continue
                except (json.JSONDecodeError, AttributeError) as e:
                    pass  # Fall through to other parsing

        # Check for inline tool call
        tool_match = re.search(r'\{"tool"\s*:\s*"(\w+)"\s*,\s*"args"\s*:\s*(\{[^}]*\})\s*\}', content)

        if tool_match:
            try:
                tool_name = tool_match.group(1)
                tool_args = json.loads(tool_match.group(2))

                if tool_name in tools:
                    result = await tools[tool_name](**tool_args)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Tool result: {result}"})
                    if on_message:
                        on_message(f"  -> {tool_name} returned {len(str(result))} chars")
                else:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Error: Unknown tool '{tool_name}'"})
            except (json.JSONDecodeError, AttributeError) as e:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Error parsing tool call: {e}"})
        else:
            # No tool call and no final JSON — ask for clarification
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": "Please continue your analysis. If you have the final course structure, output it as a JSON code block."
            })

    raise ValueError(f"Architect exceeded iteration limit ({max_iterations} steps)")
