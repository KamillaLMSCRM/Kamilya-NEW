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

logger = logging.getLogger(__name__)

CHAPTER_TEXT_MAX_CHARS = 8000

SYSTEM_PROMPT = """\
You are a Course Architect. Your job is to explore a collection of ingested \
documents and design a structured course based on their content.

## Workflow

1. Call `list_documents()` to see all available documents.
2. For EACH document, call `get_document_summary(doc_id)` and \
`get_document_toc(doc_id)` to understand its content and structure.
3. Use `get_chapter_text(doc_id, chapter_title)` to read chapters that are \
important for course design.
4. Use `search_documents(query)` to find specific information across documents.
5. Based on your analysis, design a course structure with:
   - A descriptive course **title**
   - A brief course **description**
   - Logical **modules** (topic groups)
   - **Lessons** within each module
   - **Learning objectives** for each lesson

## Rules

- Structure the course logically — from fundamental to advanced topics.
- Each lesson should cover a focused, self-contained topic.
- Learning objectives must be specific and measurable.
- Write ALL text in the TARGET LANGUAGE specified by the user.
- If source documents are in a different language, TRANSLATE and ADAPT.
- Aim for 3-8 lessons per module.
- Base everything on the actual document content — do not invent topics.

## Output

After your analysis, output the course structure as a JSON code block:

```json
{
  "title": "Course Title",
  "description": "Brief course description",
  "modules": [
    {
      "title": "Module 1 Title",
      "lessons": [
        {
          "title": "Lesson Title",
          "description": "Brief lesson description",
          "objectives": [
            {"text": "Learner will be able to ..."}
          ],
          "source_doc_ids": ["doc-stem-1"],
          "relevant_headings": ["Chapter 3: Topic Name"]
        }
      ]
    }
  ]
}
```

Output ONLY the JSON block as your final answer.
"""


def create_architect_tools(
    summaries_dir: str = "./summaries",
    chroma_dir: str = "./chroma_data",
    doc_ids: list[str] | None = None,
    max_chapters_per_doc: int = 5,
    embeddings_client=None,
    vector_store: VectorStore | None = None,
):
    """Create retrieval tools for the Architect Agent."""
    import collections

    store = vector_store or VectorStore(chroma_dir)
    scope = set(doc_ids) if doc_ids else None
    chapter_read_counts = collections.defaultdict(int)

    async def list_documents() -> str:
        """List all ingested documents with IDs and names from DB."""
        from app.core.db import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT DISTINCT doc_id, doc_name FROM document_embeddings ORDER BY doc_name")
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
            result = await session.execute(
                text("SELECT text, headings FROM document_embeddings WHERE doc_id = :doc_id LIMIT 5"),
                {"doc_id": doc_id},
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
            result = await session.execute(
                text("SELECT DISTINCT headings FROM document_embeddings WHERE doc_id = :doc_id"),
                {"doc_id": doc_id},
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
            result = await session.execute(
                text("SELECT text, headings FROM document_embeddings WHERE doc_id = :doc_id"),
                {"doc_id": doc_id},
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
        """Semantic search across ingested documents."""
        where = None
        if doc_id:
            where = {"doc_id": doc_id}
        elif scope:
            where = {"doc_id": {"$in": list(scope)}}

        # Use placeholder embeddings when real embeddings not available
        query_embedding = [0.0] * 4096

        raw = await store.query(
            query_embeddings=[query_embedding],
            n_results=10,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
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
) -> CourseStructure:
    """
    Run the Architect Agent — iterative LLM calls with tool execution.
    Simplified ReAct loop (no LangGraph dependency required).
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
