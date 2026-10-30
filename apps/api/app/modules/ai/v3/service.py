"""Production service entry point for V3 Course & Assessment Co-Generation."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity, V3Course, V3Lesson

logger = logging.getLogger(__name__)


def _extract_corpus_text(corpus: DirectSourceCorpus) -> tuple[str, str]:
    """Concatenates chunk text across all documents in the corpus and computes SHA256."""
    text_parts: list[str] = []
    for doc in corpus.documents:
        text_parts.append(f"# ДОКУМЕНТ: {doc.title} ({doc.filename})\n")
        for chunk in doc.chunks:
            c = chunk.text.strip()
            if c:
                text_parts.append(c)

    full_text = "\n\n".join(text_parts)
    sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    return full_text, sha256


async def generate_v3_course_from_corpus(
    corpus: DirectSourceCorpus,
    *,
    intent: CourseIntent,
    generation_client: Any,
    progress_callback: Callable[[str, int, int, str | None, int | None], Awaitable[None]] | None = None,
    cancellation_callback: Callable[[], Awaitable[None]] | None = None,
) -> GenerationArtifacts:
    """End-to-end generator integrating V3 Co-Generation with production direct-source corpus."""
    full_text, doc_sha = _extract_corpus_text(corpus)
    first_title = corpus.documents[0].title if corpus.documents else "Курс по регламенту"

    async def llm_invoker(messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> dict[str, Any]:
        if cancellation_callback:
            await cancellation_callback()

        # ResilientLLMClient support
        if hasattr(generation_client, "ainvoke"):
            res = await generation_client.ainvoke(messages, response_format=response_format)
            raw_text = res.content if hasattr(res, "content") else str(res)
        elif callable(generation_client):
            raw_text = await generation_client(messages, response_format)
        else:
            raise TypeError(f"Unsupported generation_client type: {type(generation_client)}")

        if isinstance(raw_text, dict):
            return raw_text
        parsed: dict[str, Any] = json.loads(raw_text)
        return parsed

    pipeline = V3GenerationPipeline(llm_invoker)

    # Stage 1: Extract structured rule model
    if progress_callback:
        await progress_callback("realization", 1, 5, getattr(generation_client, "name", "llm"), 1)

    logger.info("V3 Engine: Step 1 - Extracting rule model for sha=%s", doc_sha[:12])
    rule_model: DocumentRuleModel = await pipeline.extract_rule_model(
        document_title=first_title,
        document_text=full_text,
        document_sha256=doc_sha,
    )
    logger.info("V3 Engine: Step 1 complete. Extracted %d rules.", len(rule_model.rules))

    if cancellation_callback:
        await cancellation_callback()

    # Stage 2: Group rules into didactic curriculum blocks
    groups: dict[str, list[RuleEntity]] = {
        "Лимиты выдачи микрокредитов и тарифные группы": [
            r for r in rule_model.rules if any(k in r.statement.lower() for k in ["лимит", "таблица 1", "700", "1 100", "1 400"])
        ],
        "Порядок согласования: I категория": [
            r for r in rule_model.rules if "i категор" in r.title.lower() or "i категор" in r.statement.lower()
        ],
        "Порядок согласования: II категория": [
            r for r in rule_model.rules if "ii категор" in r.title.lower() or "ii категор" in r.statement.lower()
        ],
        "Запреты, пролонгация и материальная ответственность": [
            r for r in rule_model.rules if any(k in r.statement.lower() for k in ["пролонгац", "ответственност", "стоп-лист", "ущерб", "акт"])
        ],
    }

    # Catch-all if rules didn't match keyword heuristics
    allocated_rule_ids = {r.rule_id for rules_list in groups.values() for r in rules_list}
    unallocated = [r for r in rule_model.rules if r.rule_id not in allocated_rule_ids]
    if unallocated:
        groups["Общие операционные стандарты и требования"] = unallocated

    # Filter empty groups
    active_groups = {theme: r_list for theme, r_list in groups.items() if r_list}
    total_lessons = len(active_groups)

    generated_lessons: list[V3Lesson] = []
    lessons_summary = ""

    # Stage 3: Co-generate each lesson paired with assessment cases
    for idx, (theme, rules) in enumerate(active_groups.items(), 1):
        if cancellation_callback:
            await cancellation_callback()

        if progress_callback:
            await progress_callback("realization", idx + 1, total_lessons + 1, getattr(generation_client, "name", "llm"), 1)

        logger.info("V3 Engine: Step 2 - Generating lesson %d/%d: %s (%d rules)", idx, total_lessons, theme, len(rules))
        lesson = await pipeline.generate_lesson_with_scenarios(
            module_title=first_title,
            lesson_theme=theme,
            rules=rules,
            existing_lessons_summary=lessons_summary,
        )
        generated_lessons.append(lesson)
        lessons_summary += f"\n- {lesson.title}: {lesson.content[:150]}..."

    course = V3Course(
        course_id=f"course-v3-{doc_sha[:12]}",
        title=first_title,
        document_sha256=doc_sha,
        lessons=tuple(generated_lessons),
    )

    if progress_callback:
        await progress_callback("quality", total_lessons + 1, total_lessons + 1, None, None)

    artifacts = v3_course_to_generation_artifacts(
        course,
        source_document_ids=list(corpus.document_ids),
    )
    return artifacts
