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

    def list_documents() -> str:
        """List all ingested documents with IDs and names."""
        from pathlib import Path
        results = []
        summaries_path = Path(summaries_dir)
        if summaries_path.exists():
            for fp in sorted(summaries_path.glob("*.json")):
                with open(fp) as f:
                    data = json.load(f)
                if scope and data.get("doc_id") not in scope:
                    continue
                results.append({"doc_id": data.get("doc_id"), "doc_name": data.get("doc_name")})
        return json.dumps(results, ensure_ascii=False, indent=2)

    def get_document_summary(doc_id: str) -> str:
        """Get educational profile summary of a document."""
        from pathlib import Path
        if scope and doc_id not in scope:
            return f"Document '{doc_id}' is not in the current scope."
        summaries_path = Path(summaries_dir)
        for fp in summaries_path.glob("*.json"):
            with open(fp) as f:
                data = json.load(f)
            if data.get("doc_id") == doc_id:
                edu = data.get("educational_summary", {})
                if edu:
                    parts = []
                    if edu.get("target_audience"):
                        parts.append(f"Target Audience: {edu['target_audience']}")
                    if edu.get("global_description"):
                        parts.append(f"Description: {edu['global_description']}")
                    if edu.get("core_topics"):
                        parts.append(f"Core Topics: {', '.join(edu['core_topics'])}")
                    if edu.get("extractable_skills"):
                        parts.append(f"Extractable Skills: {', '.join(edu['extractable_skills'])}")
                    return "\n".join(parts) if parts else "No educational profile available."
                return data.get("summary", "No summary available.")
        return f"Document '{doc_id}' not found."

    def get_document_toc(doc_id: str) -> str:
        """Get table of contents of a document."""
        from pathlib import Path
        if scope and doc_id not in scope:
            return f"Document '{doc_id}' is not in scope."
        summaries_path = Path(summaries_dir)
        for fp in summaries_path.glob("*.json"):
            with open(fp) as f:
                data = json.load(f)
            if data.get("doc_id") == doc_id:
                toc = data.get("toc", "")
                if toc:
                    return toc
                chapters = data.get("chapters", {})
                if chapters:
                    return "\n".join(f"- {t}" for t in chapters.keys())
                return "No TOC available."
        return f"Document '{doc_id}' not found."

    def get_chapter_text(doc_id: str, chapter_title: str) -> str:
        """Read full text of a specific chapter (capped at 8000 chars)."""
        from pathlib import Path
        if scope and doc_id not in scope:
            return f"Document '{doc_id}' is not in scope."
        if chapter_read_counts[doc_id] >= max_chapters_per_doc:
            return (
                f"Limit reached: {max_chapters_per_doc} chapters from '{doc_id}'. "
                f"Use search_documents() instead."
            )
        chapter_read_counts[doc_id] += 1
        summaries_path = Path(summaries_dir)
        for fp in summaries_path.glob("*.json"):
            with open(fp) as f:
                data = json.load(f)
            if data.get("doc_id") != doc_id:
                continue
            chapters = data.get("chapters", {})
            if not chapters:
                return f"No chapters for '{doc_id}'."
            rel_path = None
            for title, path in chapters.items():
                if title.lower() == chapter_title.lower():
                    rel_path = path
                    break
            if not rel_path:
                chapter_lower = chapter_title.lower()
                for title, path in chapters.items():
                    if chapter_lower in title.lower() or title.lower() in chapter_lower:
                        rel_path = path
                        break
            if not rel_path:
                available = ", ".join(f'"{t}"' for t in chapters.keys())
                return f"Chapter '{chapter_title}' not found. Available: {available}"
            chapter_path = summaries_path / rel_path
            if not chapter_path.exists():
                return f"Chapter file not found at {rel_path}."
            content = chapter_path.read_text(encoding="utf-8")
            if len(content) > CHAPTER_TEXT_MAX_CHARS:
                content = content[:CHAPTER_TEXT_MAX_CHARS] + "\n\n... [truncated]"
            return content
        return f"Document '{doc_id}' not found."

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
    """Attempt to fix broken JSON by rebuilding structure."""
    import json
    try:
        # Try to extract key parts with regex
        title_match = re.search(r'"title"\s*:\s*"([^"]*)"', json_str)
        desc_match = re.search(r'"description"\s*:\s*"([^"]*)"', json_str)

        modules = []
        # Find module blocks
        mod_pattern = re.finditer(r'"title"\s*:\s*"([^"]*)"', json_str)
        lessons = []
        for m in mod_pattern:
            title = m.group(1)
            if len(title) > 5 and "module" in title.lower() or "модуль" in title.lower():
                continue
            lessons.append(title)

        if title_match:
            result = {
                "title": title_match.group(1),
                "description": desc_match.group(1) if desc_match else "",
                "modules": [{"title": "Module 1", "lessons": [{"title": t, "objectives": [{"text": "Learn about " + t}]} for t in lessons[:5]]}] if lessons else []
            }
            return json.dumps(result, ensure_ascii=False)
    except Exception:
        pass
    return None


def _attempt_json_repair(json_str: str) -> str | None:
    """Fix common JSON issues from LLM output."""
    return None


def _parse_course_structure(text: str) -> CourseStructure:
    """Parse JSON course structure from LLM output."""
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
    # Fix missing commas after string values before next key
    json_str = re.sub(r'"\s*\n(\s*")', r'",\n\1', json_str)
    # Fix missing commas after boolean/null/number before next key
    json_str = re.sub(r'(false|true|null|\d+\.?\d*)\s*\n(\s*")', r'\1,\n\2', json_str)
    # Fix smart quotes
    json_str = json_str.replace('\u2018', "'").replace('\u2019', "'")

    try:
        return CourseStructure.from_json(json_str)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Last resort: use LLM to fix the JSON
        logger.warning(f"JSON parse failed, attempting repair: {e}")
        repaired = _attempt_json_repair(json_str)
        if repaired:
            try:
                return CourseStructure.from_json(repaired)
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        raise ValueError(f"Failed to parse course structure JSON: {e}") from e


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

        # Check for tool call
        tool_match = re.search(r'```json\s*\{[^}]*"tool"[^}]*\}\s*```', content, re.DOTALL)
        if not tool_match:
            tool_match = re.search(r'\{"tool"\s*:\s*"(\w+)"\s*,\s*"args"\s*:\s*(\{[^}]*\})\s*\}', content)

        if tool_match:
            try:
                tool_json = json.loads(tool_match.group(0).strip().strip("`").strip())
                tool_name = tool_json.get("tool")
                tool_args = tool_json.get("args", {})

                if tool_name in tools:
                    result = tools[tool_name](**tool_args) if not asyncio.iscoroutinefunction(tools[tool_name]) else await tools[tool_name](**tool_args)
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
