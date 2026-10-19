"""Adapt a source-verified lesson snapshot to the reviewed assessment pipeline.

This is lesson-snapshot provenance, not a claim to reopen/reverify the original
files. The caller's grounded rewrite owns original-document verification. No
storage, retrieval, settings, persistence or provider selection occurs here.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine import semantic_assessment
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import LessonDraft
from app.modules.ai.ingestion import DocumentChunker

logger = logging.getLogger(__name__)


def _coverage_diagnostic(audit: dict[str, Any], digest: str) -> dict[str, Any]:
    """Closed, bounded operational metadata: never source/model prose or keys."""
    allowed_states = {"retained", "omitted", "uncovered", "unassessable"}
    allowed_reasons = {
        "educational", "question_supported", "explanation_supported", "options_distinct",
        "local_quality_filter_rejected", "partial_unatomized_source_contract",
        "unatomizable_source_contract", "assessment_density_limit",
        "semantic_rejection", "assessment_not_completed",
    }
    counts = {state: 0 for state in sorted(allowed_states)}
    reasons: dict[str, int] = {}
    raw_outcomes = audit.get("axis_outcomes")
    outcomes = raw_outcomes if isinstance(raw_outcomes, list) else []
    for row in outcomes[:200]:
        if not isinstance(row, dict):
            continue
        state = row.get("state")
        if isinstance(state, str) and state in counts:
            counts[state] += 1
        if state != "retained":
            reason = str(row.get("reason", "")).split(";", 1)[0]
            code = reason if reason in allowed_reasons else "other"
            reasons[code] = reasons.get(code, 0) + 1
    terminal = audit.get("terminal_status")
    if not isinstance(terminal, str) or terminal not in {
        "completed", "completed_with_warnings", "review_required",
    }:
        terminal = "unknown"
    return {"policy": "regeneration-coverage-diagnostic-v1", "snapshot_sha256": digest,
            "terminal": terminal,
            "outcomes_known": isinstance(raw_outcomes, list), "states": counts, "reasons": reasons}


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
        logger.warning("Regeneration assessment rejected audit=%s",
                       json.dumps(_coverage_diagnostic(result.audit, digest), sort_keys=True))
        raise ValueError("Тест не покрывает важные правила урока; прежний тест сохранён. "
                         "Проверьте или разделите материал перед повторной генерацией.")
    if any(len(option) > 500 for question in result.questions for option in question.options):
        raise ValueError("Варианты ответа слишком длинные; прежний тест сохранён.")
    return [{"text": question.prompt, "choices": list(question.options),
             "correct_index": question.options.index(question.correct_answer),
             "explanation": question.explanation} for question in result.questions]
