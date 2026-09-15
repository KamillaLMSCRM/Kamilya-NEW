"""Production-shaped application seam for the evidence-first generation engine."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, Protocol
from urllib.parse import quote, unquote

from app.modules.ai.architect_schema import CourseStructure, LearningObjective
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import (
    CourseAssessment,
    LessonAssessment,
    MCQOption,
    MCQQuestion,
)
from app.modules.ai.direct_source import (
    DirectSourceCorpus,
    merged_direct_source_worksheet_tables,
)
from app.modules.ai.document_passport import SectionRole, build_document_passport
from app.modules.ai.lesson_quality import neutralize_unprofessional_source_language
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent

from .engine import EvidenceCourseEngine
from .models import (
    AssessmentDraft,
    CourseDraft,
    CourseIntent,
    LessonDraft,
    QuestionDraft,
    SourceDocument,
    SourceFact,
    SourceSection,
    StageTiming,
)
from .provider_engine import ProviderBackedEvidenceEngine, _normalize
from .provider_models import GroundedBlock, ProviderBackedResult, RetrievalMeasurement
from .providers import EVIDENCE_REALIZER_SYSTEM_PROMPT
from .quality import (
    EVIDENCE_QUALITY_POLICY_VERSION,
    evaluate_publishability,
    filter_acceptable_questions,
)

ProgressCallback = Callable[[str, int, int, str | None, int | None], Awaitable[None] | None]
CancellationCallback = Callable[[], Awaitable[None] | None]


class GenerationClient(Protocol):
    async def ainvoke_validated(
        self,
        messages: str | list[dict[str, Any]],
        parser: Callable[[str], Any],
        config: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Any: ...


class EmbeddingClient(Protocol):
    async def embed_documents_with_provenance(
        self, texts: list[str], *, on_progress: Callable[..., Awaitable[None]] | None = None
    ) -> Any: ...
    async def embed_queries_with_provenance(
        self, texts: list[str], *, on_progress: Callable[..., Awaitable[None]] | None = None
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class EvidenceSourceBundle:
    document: SourceDocument

    @property
    def all_facts(self) -> tuple[SourceFact, ...]:
        return tuple(fact for section in self.document.sections for fact in section.facts)


@dataclass(frozen=True, slots=True)
class EvidenceGenerationOutput:
    result: ProviderBackedResult
    corpus: DirectSourceCorpus


@dataclass(frozen=True, slots=True)
class GenerationArtifacts:
    structure: CourseStructure
    content: CourseContent
    assessment: CourseAssessment
    diagnostics: dict[str, Any]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-")
    return normalized[:80] or "item"


def _stable_id(prefix: str, *parts: str) -> str:
    body = "\x1f".join(" ".join(part.casefold().split()) for part in parts)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"


def _locator(**values: str | int) -> str:
    return ";".join(f"{key}={quote(str(value), safe=':-_.')}" for key, value in values.items())


def _locator_values(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in value.split(";"):
        key, separator, raw = item.partition("=")
        if separator and key:
            parsed[key] = unquote(raw)
    return parsed


def _section_role(value: SectionRole) -> str:
    return "primary" if value is SectionRole.PRIMARY else "supporting"


def _narrative_section_role(
    *,
    document_id: str,
    section_name: str,
    role_by_section: dict[tuple[str, str], SectionRole],
) -> SectionRole:
    exact = role_by_section.get((document_id, section_name.casefold().strip()))
    if exact is not None:
        return exact
    normalized = section_name.casefold().strip()
    if normalized.startswith(("содержание", "приложение", "contents", "appendix")):
        return SectionRole.SUPPORTING
    document_roles = [
        role for (doc_id, _name), role in role_by_section.items() if doc_id == document_id
    ]
    if SectionRole.PRIMARY in document_roles:
        return SectionRole.PRIMARY
    return SectionRole.SUPPORTING


def _narrative_attribute(value: str) -> str:
    normalized = value.casefold().replace("ё", "е")
    if re.search(r"\b(?:дн|дня|дней|месяц|месяца|месяцев|час|часов|срок)\w*\b", normalized):
        return "срок"
    if re.search(r"\b(?:процент|ставк|вознагражден|тенге|сумм)\w*\b", normalized):
        return "финансовое условие"
    if re.search(r"\b(?:вправе|право)\w*\b", normalized):
        return "право"
    if re.search(r"\b(?:обязан|должен|необходимо)\w*\b", normalized):
        return "обязанность"
    if re.search(r"\b(?:запрещен|не допускается|не вправе)\w*\b", normalized):
        return "запрет"
    return "положение"


def _split_narrative_chunk(text: str) -> list[str]:
    cleaned = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)
    parts = re.split(
        r"\n{2,}|(?=^\s*(?:\d+(?:\.\d+)*|[а-яё])\s*[.)]\s+)",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    return [" ".join(part.split()) for part in parts if len(" ".join(part.split())) >= 25]


def build_evidence_source(corpus: DirectSourceCorpus) -> EvidenceSourceBundle:
    """Convert verified direct-source chunks without reopening an ambient file."""

    passport = build_document_passport(corpus)
    role_by_section = {
        (section.document_id, section.name.casefold().strip()): section.role
        for section in passport.sections
    }
    document_by_id = {document.doc_id: document for document in corpus.documents}
    sections: list[SourceSection] = []
    tables = merged_direct_source_worksheet_tables(corpus)
    table_keys: set[tuple[str, str]] = set()
    for doc_id, normalized_heading, heading, headers, rows in tables:
        table_keys.add((doc_id, normalized_heading))
        role = role_by_section.get((doc_id, normalized_heading), SectionRole.UNKNOWN)
        title = heading.removeprefix("[Worksheet] ").strip()
        document = document_by_id[doc_id]
        sheet_facts: list[SourceFact] = []
        matrix = bool(headers and headers[0].casefold().strip() in {
            "поле", "характеристика", "параметр", "свойство", "field", "attribute", "parameter", "property",
        })
        for row_index, (cells, _raw) in enumerate(rows, start=2):
            if matrix:
                attribute = cells[0].strip()
                for column_index, entity in enumerate(headers[1:], start=2):
                    value = cells[column_index - 1].strip() if column_index - 1 < len(cells) else ""
                    if not attribute or not entity.strip() or not value:
                        continue
                    sheet_facts.append(SourceFact(
                        fact_id=_stable_id("source-fact", doc_id, title, attribute, entity, value),
                        subject=entity.strip(),
                        attribute=attribute,
                        value=value,
                        source_locator=_locator(
                            doc_id=doc_id,
                            source_revision=document.source_revision,
                            section=title,
                            row=row_index,
                            column=column_index,
                        ),
                    ))
            else:
                subject = cells[0].strip() if cells else ""
                if not subject:
                    continue
                for column_index, header in enumerate(headers[1:], start=2):
                    value = cells[column_index - 1].strip() if column_index - 1 < len(cells) else ""
                    if not header.strip() or not value:
                        continue
                    sheet_facts.append(SourceFact(
                        fact_id=_stable_id("source-fact", doc_id, title, subject, header, value),
                        subject=subject,
                        attribute=header.strip(),
                        value=value,
                        source_locator=_locator(
                            doc_id=doc_id,
                            source_revision=document.source_revision,
                            section=title,
                            row=row_index,
                            column=column_index,
                        ),
                    ))
        if sheet_facts:
            sections.append(SourceSection(
                section_id=f"{doc_id}:sheet:{_slug(title)}",
                title=title,
                role=_section_role(role),  # type: ignore[arg-type]
                facts=tuple(sheet_facts),
            ))

    for document in corpus.documents:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for chunk in sorted(document.chunks, key=lambda item: item.chunk_index):
            section_name = next(
                (
                    heading.removeprefix("[Worksheet] ").strip()
                    for heading in reversed(chunk.headings)
                ),
                document.title,
            )
            normalized = section_name.casefold().strip()
            if (document.doc_id, normalized) in table_keys:
                continue
            grouped[section_name].append(chunk)
        for section_name, chunks in grouped.items():
            role = _narrative_section_role(
                document_id=document.doc_id,
                section_name=section_name,
                role_by_section=role_by_section,
            )
            narrative_facts: list[SourceFact] = []
            for chunk in chunks:
                for part_index, value in enumerate(_split_narrative_chunk(chunk.text), start=1):
                    narrative_facts.append(SourceFact(
                        fact_id=_stable_id(
                            "source-fact",
                            document.doc_id,
                            chunk.chunk_id,
                            str(part_index),
                            value,
                        ),
                        subject=section_name,
                        attribute=_narrative_attribute(value),
                        value=value,
                        source_locator=_locator(
                            doc_id=document.doc_id,
                            source_revision=document.source_revision,
                            chunk_id=chunk.chunk_id,
                            section=section_name,
                            part=part_index,
                        ),
                    ))
            if narrative_facts:
                sections.append(SourceSection(
                    section_id=f"{document.doc_id}:section:{_slug(section_name)}",
                    title=section_name,
                    role=_section_role(role),  # type: ignore[arg-type]
                    facts=tuple(narrative_facts),
                ))

    revisions = sorted(document.source_revision for document in corpus.documents)
    digest = hashlib.sha256("\x1f".join(revisions).encode("utf-8")).hexdigest()
    titles = list(dict.fromkeys(document.title for document in corpus.documents))
    kind: Literal["spreadsheet", "narrative"] = "spreadsheet" if tables else "narrative"
    return EvidenceSourceBundle(
        document=SourceDocument(
            source_id=f"direct:{digest}",
            title=" + ".join(titles),
            kind=kind,
            sections=tuple(sections),
            source_sha256=digest,
        )
    )


async def _checkpoint(callback: CancellationCallback | None) -> None:
    if callback is None:
        return
    value = callback()
    if inspect.isawaitable(value):
        await value


async def _progress(
    callback: ProgressCallback | None,
    stage: str,
    completed: int,
    total: int,
    provider: str | None = None,
    attempt: int | None = None,
) -> None:
    if callback is None:
        return
    value = callback(stage, completed, total, provider, attempt)
    if inspect.isawaitable(value):
        await value


def _json_object(value: str) -> dict[str, Any]:
    content = value.strip()
    if content.startswith("```"):
        content = content.removeprefix("```json").removeprefix("```")
        content = content.removesuffix("```").strip()
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("evidence_realizer_response_not_object")
    return payload


def _deduplicate_questions(questions: list[QuestionDraft]) -> list[QuestionDraft]:
    accepted: list[QuestionDraft] = []
    seen: set[str] = set()
    for question in questions:
        key = " ".join(question.prompt.casefold().replace("ё", "е").split())
        if key in seen:
            continue
        seen.add(key)
        accepted.append(question)
    return accepted


def _escape_markdown_text(value: str) -> str:
    """Neutralize source markup while preserving source-visible text."""

    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
    for marker in ("`", "*", "_", "#", "|", "!", "~", "[", "]", "(", ")"):
        escaped = escaped.replace(marker, f"\\{marker}")
    escaped = re.sub(r"(?m)^(\s*)([-+>])", r"\1\\\2", escaped)
    escaped = re.sub(r"(?m)^(\s*)(\d+)\.", r"\1\2\\.", escaped)
    return escaped


def _grounded_fallback(
    *,
    base_lesson: LessonDraft,
    plan_fact_ids: tuple[str, ...],
    facts_by_id: dict[str, SourceFact],
    seeds: list[QuestionDraft],
) -> tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]]:
    """Return a readable source-only lesson when every model attempt is unusable."""

    blocks: list[GroundedBlock] = []
    rendered: list[str] = []
    for fact_id in plan_fact_ids:
        fact = facts_by_id[fact_id]
        heading = neutralize_unprofessional_source_language(
            " ".join(fact.attribute.strip().rstrip(".:").split())
        ) or "Подтверждённые сведения"
        text = neutralize_unprofessional_source_language(fact.value.strip())
        blocks.append(
            GroundedBlock(
                lesson_id=base_lesson.lesson_id,
                heading=heading,
                text=text,
                fact_ids=(fact_id,),
            )
        )
        rendered.extend((f"### {_escape_markdown_text(heading)}", "", _escape_markdown_text(text), ""))
    word_count = len(re.findall(r"\w+", " ".join(rendered), flags=re.UNICODE))
    return (
        LessonDraft(
            lesson_id=base_lesson.lesson_id,
            module_title=base_lesson.module_title,
            title=neutralize_unprofessional_source_language(base_lesson.title),
            objective=neutralize_unprofessional_source_language(base_lesson.objective),
            content="\n".join(rendered).strip(),
            fact_ids=base_lesson.fact_ids,
            supporting_fact_ids=base_lesson.supporting_fact_ids,
            duration_minutes=max(2, math.ceil(word_count / 130)),
        ),
        list(seeds),
        blocks,
    )


async def generate_evidence_course(
    corpus: DirectSourceCorpus,
    *,
    intent: CourseIntent,
    generation_client: GenerationClient,
    embedding_client: EmbeddingClient,
    progress_callback: ProgressCallback | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> EvidenceGenerationOutput:
    """Generate a complete validated draft or raise before database persistence."""

    started = perf_counter()
    await _checkpoint(cancellation_callback)
    bundle = build_evidence_source(corpus)
    evidence_result = EvidenceCourseEngine().generate_from_document(bundle.document, intent=intent)
    if not evidence_result.evidence_plan:
        raise ValueError("evidence_plan_empty")
    evidence_seconds = perf_counter() - started
    await _progress(progress_callback, "evidence_plan", 1, 1)

    facts = list(evidence_result.admitted_facts)
    facts_by_id = {fact.fact_id: fact for fact in facts}
    lesson_by_id = {lesson.lesson_id: lesson for lesson in evidence_result.course.lessons}
    seeds_by_lesson: dict[str, list[QuestionDraft]] = defaultdict(list)
    for question in evidence_result.assessment.questions:
        seeds_by_lesson[question.lesson_id].append(question)

    embedding_started = perf_counter()
    embedding_model = ""
    embedding_dimension = 0
    embedding_degraded = False
    embedding_error = ""
    retrieval: list[RetrievalMeasurement] = []
    embedding_total = len(facts) + len(evidence_result.evidence_plan)

    async def document_progress(
        completed: int,
        _total: int,
        provider: str,
        attempt: int = 1,
    ) -> None:
        await _progress(
            progress_callback,
            "embeddings",
            completed,
            embedding_total,
            provider,
            attempt,
        )

    async def query_progress(
        completed: int,
        _total: int,
        provider: str,
        attempt: int = 1,
    ) -> None:
        await _progress(
            progress_callback,
            "embeddings",
            len(facts) + completed,
            embedding_total,
            provider,
            attempt,
        )

    try:
        await _checkpoint(cancellation_callback)
        document_batch = await embedding_client.embed_documents_with_provenance(
            [fact.value for fact in facts],
            on_progress=document_progress,
        )
        document_vectors = tuple(_normalize(tuple(vector)) for vector in document_batch.vectors)
        if len(document_vectors) != len(facts):
            raise ValueError("document_embedding_count_mismatch")
        queries: list[str] = []
        for plan in evidence_result.evidence_plan:
            await _checkpoint(cancellation_callback)
            # The resilient client owns the Qwen instruction prefix and applies
            # it only to query embeddings. Passing plain text avoids double prefixing.
            queries.append(" ".join((
                plan.title,
                plan.objective,
                *sorted({facts_by_id[fact_id].attribute for fact_id in plan.fact_ids}),
            )))
        query_batch = await embedding_client.embed_queries_with_provenance(
            queries,
            on_progress=query_progress,
        )
        if len(query_batch.vectors) != len(queries):
            raise ValueError("query_embedding_count_mismatch")
        if query_batch.space != document_batch.space:
            # Provider failover is allowed, but vectors from unrelated model
            # families must never be compared. Retrieval is a quality metric,
            # so degrade it without blocking grounded course realization.
            embedding_degraded = True
            embedding_error = "IncompatibleEmbeddingSpace"
        else:
            query_vectors = tuple(
                _normalize(tuple(vector)) for vector in query_batch.vectors
            )
            retrieval = ProviderBackedEvidenceEngine._measure_retrieval(
                facts=facts,
                document_vectors=document_vectors,
                query_vectors=query_vectors,
                plans=evidence_result.evidence_plan,
            )
        embedding_model = str(document_batch.model)
        embedding_dimension = len(document_vectors[0]) if document_vectors else 0
    except AllProvidersFailedError as exc:
        embedding_degraded = True
        embedding_error = type(exc).__name__
    embedding_seconds = perf_counter() - embedding_started
    if embedding_degraded:
        await _progress(progress_callback, "embeddings", embedding_total, embedding_total)

    realization_started = perf_counter()
    realized_lessons: list[LessonDraft] = []
    realized_questions: list[QuestionDraft] = []
    grounded_blocks: list[GroundedBlock] = []
    validation_errors: list[str] = []
    provider_fallback_count = 0
    deterministic_fallback_count = 0
    deterministic_fallback_lesson_ids: list[str] = []
    chat_attempt_count = 0
    chat_model = ""
    total = len(evidence_result.evidence_plan)
    for index, plan in enumerate(evidence_result.evidence_plan, start=1):
        await _checkpoint(cancellation_callback)
        base_lesson = lesson_by_id[plan.lesson_id]
        seeds = seeds_by_lesson.get(plan.lesson_id, [])
        request = ProviderBackedEvidenceEngine._realizer_request(
            plan,
            facts_by_id,
            seeds,
            intent,
        )

        def parser(
            raw: str,
            *,
            _base_lesson: LessonDraft = base_lesson,
            _plan_fact_ids: frozenset[str] = frozenset(plan.fact_ids),
            _seeds: tuple[QuestionDraft, ...] = tuple(seeds),
        ) -> tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]]:
            payload = _json_object(raw)
            return ProviderBackedEvidenceEngine._validate_and_render(
                payload,
                base_lesson=_base_lesson,
                plan_fact_ids=set(_plan_fact_ids),
                facts_by_id=facts_by_id,
                seeds=list(_seeds),
            )

        validated = None
        lesson_failure_reasons: list[ValidatedCallFailureReason] = []
        for attempt in range(2):
            try:
                validated = await generation_client.ainvoke_validated(
                    [
                        {"role": "system", "content": EVIDENCE_REALIZER_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                request,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    parser=parser,
                    response_format={"type": "json_object"},
                )
                chat_attempt_count += validated.attempt_count
                lesson_failure_reasons.extend(validated.failure_reasons)
                provider_fallback_count += max(0, validated.attempt_count - 1)
                break
            except AllProvidersFailedError as exc:
                reasons = list(exc.reasons) or [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE]
                lesson_failure_reasons.extend(reasons)
                chat_attempt_count += len(reasons)
                provider_fallback_count += len(reasons)
                if attempt == 1:
                    validated = None
                    break
                request["validation_feedback"] = (
                    "The previous provider chain did not satisfy the strict evidence "
                    "contract. Return complete JSON, cover every supplied fact_id, and "
                    "introduce no facts or numbers outside the supplied evidence."
                )
        validation_errors.extend(reason.value for reason in lesson_failure_reasons)
        if validated is None:
            deterministic_fallback_count += 1
            deterministic_fallback_lesson_ids.append(plan.lesson_id)
            lesson, questions, blocks = _grounded_fallback(
                base_lesson=base_lesson,
                plan_fact_ids=plan.fact_ids,
                facts_by_id=facts_by_id,
                seeds=seeds,
            )
            chat_model = "deterministic-grounded-fallback"
        else:
            lesson, questions, blocks = validated.value
            chat_model = str(validated.model_id)
        realized_lessons.append(lesson)
        realized_questions.extend(questions)
        grounded_blocks.extend(blocks)
        await _progress(progress_callback, "realization", index, total)

    realized_questions = filter_acceptable_questions(
        _deduplicate_questions(realized_questions)
    )
    realized_course = CourseDraft(
        title=bundle.document.title,
        description=evidence_result.course.description,
        lessons=tuple(realized_lessons),
    )
    realized_assessment = AssessmentDraft(questions=tuple(realized_questions))
    publishability = evaluate_publishability(
        course=realized_course,
        assessment=realized_assessment,
        blocks=tuple(grounded_blocks),
        planned_fact_ids={fact.fact_id for fact in evidence_result.admitted_facts},
        provider_fallback_count=provider_fallback_count,
    )
    if not publishability.publishable:
        raise ValueError("evidence_publishability_failed:" + ",".join(publishability.reasons))
    await _checkpoint(cancellation_callback)
    await _progress(progress_callback, "quality", 1, 1)
    result = ProviderBackedResult(
        evidence_result=evidence_result,
        realized_course=realized_course,
        realized_assessment=realized_assessment,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        embedding_degraded=embedding_degraded,
        embedding_error=embedding_error,
        chat_model=chat_model,
        retrieval=tuple(retrieval),
        grounded_blocks=tuple(grounded_blocks),
        publishability=publishability,
        provider_fallback_count=provider_fallback_count,
        deterministic_fallback_count=deterministic_fallback_count,
        deterministic_fallback_lesson_ids=tuple(deterministic_fallback_lesson_ids),
        validation_errors=tuple(validation_errors),
        chat_attempt_count=chat_attempt_count,
        prompt_tokens=0,
        completion_tokens=0,
        timings=(
            StageTiming(stage="evidence_plan", seconds=evidence_seconds),
            StageTiming(stage="embeddings", seconds=embedding_seconds),
            StageTiming(stage="realization", seconds=perf_counter() - realization_started),
        ),
    )
    return EvidenceGenerationOutput(result=result, corpus=corpus)


def _fact_reference(fact: SourceFact, corpus: DirectSourceCorpus) -> dict[str, Any]:
    values = _locator_values(fact.source_locator)
    doc_id = values.get("doc_id", "")
    document = next((item for item in corpus.documents if item.doc_id == doc_id), None)
    doc_name = document.filename if document is not None else doc_id
    section = values.get("section", "")
    headings = [section] if section else []
    return {
        "document": doc_name,
        "doc_id": doc_id,
        "doc_name": doc_name,
        "headings": headings,
        "context_sections": [
            {"document": doc_name, "headings": headings, "is_anchor": True}
        ],
        "source_locator": fact.source_locator,
        "fact_id": fact.fact_id,
    }


def to_generation_artifacts(output: EvidenceGenerationOutput) -> GenerationArtifacts:
    """Map the validated V2 result onto the existing single persistence contract."""

    result = output.result
    facts_by_id = {
        fact.fact_id: fact
        for fact in (
            *result.evidence_result.admitted_facts,
            *result.evidence_result.supporting_facts,
        )
    }
    questions_by_lesson: dict[str, list[QuestionDraft]] = defaultdict(list)
    for question in result.realized_assessment.questions:
        questions_by_lesson[question.lesson_id].append(question)
    grouped: dict[str, list[LessonDraft]] = defaultdict(list)
    for lesson in result.realized_course.lessons:
        grouped[lesson.module_title].append(lesson)
    fallback_lesson_ids = set(result.deterministic_fallback_lesson_ids)

    structure_modules: list[StructureModule] = []
    content_modules: list[ModuleContent] = []
    assessments: list[LessonAssessment] = []
    for module_title, lessons in grouped.items():
        structure_lessons: list[StructureLesson] = []
        content_lessons: list[LessonContent] = []
        for lesson in lessons:
            fact_ids = tuple(dict.fromkeys((*lesson.fact_ids, *lesson.supporting_fact_ids)))
            lesson_facts = [facts_by_id[fact_id] for fact_id in fact_ids]
            references = [_fact_reference(fact, output.corpus) for fact in lesson_facts]
            doc_ids = list(dict.fromkeys(ref["doc_id"] for ref in references if ref["doc_id"]))
            headings = list(dict.fromkeys(
                heading for ref in references for heading in ref.get("headings", []) if heading
            ))
            structure_lessons.append(StructureLesson(
                title=lesson.title,
                objectives=[LearningObjective(text=lesson.objective)],
                description=lesson.objective,
                source_doc_ids=doc_ids,
                relevant_headings=headings,
            ))
            content_lessons.append(LessonContent(
                title=lesson.title,
                objectives=[lesson.objective],
                content=lesson.content,
                source_chunks=[fact.value for fact in lesson_facts],
                source_references=references,
                quality_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
                source_validation_status=(
                    "needs_review" if lesson.lesson_id in fallback_lesson_ids else "verified"
                ),
            ))
            lesson_questions = questions_by_lesson.get(lesson.lesson_id, [])
            assessments.append(LessonAssessment(
                lesson_title=lesson.title,
                mcq=[
                    MCQQuestion(
                        question=question.prompt,
                        options=[
                            MCQOption(text=option, is_correct=option == question.correct_answer)
                            for option in question.options
                        ],
                        explanation=question.explanation,
                        source_quote=facts_by_id[question.fact_id].value,
                        quality_score=5.0,
                    )
                    for question in lesson_questions
                ],
                quality_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
                omission_reason=("no_safe_source_grounded_questions" if not lesson_questions else ""),
            ))
        structure_modules.append(StructureModule(
            title=module_title,
            description="",
            lessons=structure_lessons,
        ))
        content_modules.append(ModuleContent(title=module_title, lessons=content_lessons))

    degraded = result.embedding_degraded or result.deterministic_fallback_count > 0
    degraded_notice = (
        "Часть материала сохранена только по подтверждённым сведениям источника "
        "из-за недоступности или некорректного ответа модели. Черновик требует "
        "проверки методистом перед публикацией."
    )
    course_description = result.realized_course.description
    if degraded and degraded_notice not in course_description:
        course_description = "\n\n".join(filter(None, (course_description, degraded_notice)))

    diagnostics = {
        "engine": "evidence_v2",
        "quality_policy_version": EVIDENCE_QUALITY_POLICY_VERSION,
        "semantic_fingerprint": result.evidence_result.semantic_fingerprint,
        "publishable": result.publishability.publishable,
        "fact_coverage_ratio": result.publishability.fact_coverage_ratio,
        "admitted_fact_count": result.evidence_result.document_plan.admitted_fact_count,
        "supporting_fact_count": result.evidence_result.document_plan.supporting_fact_count,
        "lesson_count": len(result.realized_course.lessons),
        "question_count": len(result.realized_assessment.questions),
        "embedding_model": result.embedding_model,
        "embedding_dimension": result.embedding_dimension,
        "embedding_degraded": result.embedding_degraded,
        "chat_model": result.chat_model,
        "quality_status": "degraded_needs_review" if degraded else "validated_draft",
        "provider_fallback_count": result.provider_fallback_count,
        "deterministic_fallback_count": result.deterministic_fallback_count,
        "validation_errors": list(dict.fromkeys(result.validation_errors))[:50],
        "chat_attempt_count": result.chat_attempt_count,
        "timings": {timing.stage: round(timing.seconds, 3) for timing in result.timings},
    }
    return GenerationArtifacts(
        structure=CourseStructure(
            title=result.realized_course.title,
            description=course_description,
            modules=structure_modules,
        ),
        content=CourseContent(
            title=result.realized_course.title,
            description=course_description,
            modules=content_modules,
            source_warnings=[degraded_notice] if degraded else [],
        ),
        assessment=CourseAssessment(assessments=assessments),
        diagnostics=diagnostics,
    )
