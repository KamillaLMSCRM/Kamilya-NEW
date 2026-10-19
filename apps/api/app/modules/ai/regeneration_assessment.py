"""Adapt a source-verified lesson snapshot to the reviewed assessment pipeline.

This is lesson-snapshot provenance, not a claim to reopen/reverify the original
files. The caller's grounded rewrite owns original-document verification. No
storage, retrieval, settings, persistence or provider selection occurs here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine import semantic_assessment
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import LessonDraft
from app.modules.ai.ingestion import DocumentChunker


async def prepare_lesson_assessment(*, lesson: Any, client: Any) -> list[dict[str, Any]]:
    """Return fully reviewed adaptive questions or fail before replacing a quiz."""
    if lesson.source_validation_status != "verified" or not lesson.source_document_ids:
        raise ValueError("Сначала проверьте источники урока перед обновлением теста.")
    content = (lesson.content or "").strip()
    if not content or len(content) > 120_000:
        raise ValueError("Разделите материал урока перед обновлением теста.")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_id = f"lesson-snapshot:{lesson.id}"
    revision = f"sha256:{digest}"
    rows = DocumentChunker().chunk_markdown(content, source_id, "lesson.md")
    chunks = tuple(DirectSourceChunk(
        chunk_id=f"{source_id}:{index}", doc_id=source_id, doc_name="lesson.md",
        title=lesson.title, headings=tuple(json.loads(row["metadata"]["headings"])),
        text=row["text"], source_revision=revision, chunk_index=index,
        table_fragment=row["metadata"].get("worksheet_table_fragment"),
    ) for index, row in enumerate(rows))
    corpus = DirectSourceCorpus(str(lesson.tenant_id), (DirectSourceDocument(
        source_id, lesson.title, "lesson.md", "training_material", revision, chunks,
    ),), len(content), len(chunks))
    source = build_evidence_source(corpus)
    planned = EvidenceCourseEngine().generate_from_document(source.document)
    facts = {fact.fact_id: fact for fact in planned.admitted_facts}
    if not facts:
        raise ValueError("Не удалось покрыть содержание урока проверяемыми вопросами.")
    owned_lesson = LessonDraft(str(lesson.id), "Материал урока", lesson.title,
                               "Применять правила урока", content, tuple(facts), (), 1)
    result = await semantic_assessment.generate_block_assessment([owned_lesson], facts, client)
    coverage = result.audit.get("coverage", {})
    contract = result.audit.get("contract_coverage", {})
    if (
        not result.questions
        or result.audit.get("terminal_status") != "completed"
        or coverage.get("audit_incomplete", True)
        or coverage.get("requires_review", True)
        or contract.get("audit_incomplete", True)
        or any(contract.get(key, 1) != 0 for key in (
            "omitted_contract_count", "uncovered_contract_count", "unassessable_source_count",
        ))
    ):
        raise ValueError("Тест не покрывает важные правила урока; прежний тест сохранён. "
                         "Проверьте или разделите материал перед повторной генерацией.")
    if any(len(option) > 500 for question in result.questions for option in question.options):
        raise ValueError("Варианты ответа слишком длинные; прежний тест сохранён.")
    return [{"text": question.prompt, "choices": list(question.options),
             "correct_index": question.options.index(question.correct_answer),
             "explanation": question.explanation} for question in result.questions]
