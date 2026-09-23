"""Provider-backed realization layered over the immutable V2 evidence plan."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

from app.modules.ai.lesson_quality import (
    has_unprofessional_learner_language,
    neutralize_unprofessional_source_language,
)

from .adapters import XlsxEvidenceAdapter
from .engine import EvidenceCourseEngine
from .models import (
    AssessmentDraft,
    CourseDraft,
    CourseIntent,
    LessonDraft,
    LessonEvidence,
    QuestionDraft,
    SourceDocument,
    SourceFact,
    StageTiming,
    is_tabular_locator,
)
from .provider_models import GroundedBlock, ProviderBackedResult, RetrievalMeasurement
from .providers import QWEN_QUERY_PREFIX, ChatJsonProvider, EmbeddingProvider, ProviderCallError
from .quality import (
    contains_internal_generation_instruction,
    contains_ocr_artifact,
    evaluate_publishability,
    filter_acceptable_questions,
    is_acceptable_title,
    is_generic_question,
)


def _normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ProviderCallError("embedding vector has invalid norm")
    normalized = tuple(value / norm for value in vector)
    if any(not math.isfinite(value) for value in normalized):
        raise ProviderCallError("embedding vector contains non-finite values")
    return normalized


_SPOKEN_NUMBER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ноль\s+цел\w*\s+три\s+десят\w*", re.IGNORECASE), "0.3"),
    (re.compile(r"ноль\s+цел\w*\s+пять\s+десят\w*", re.IGNORECASE), "0.5"),
    (re.compile(r"ноль\s+цел\w*\s+три\s+сот\w*", re.IGNORECASE), "0.03"),
    (re.compile(r"\b(?:три|трех|трёх)\b", re.IGNORECASE), "3"),
    (re.compile(r"\b(?:пять|пяти)\b", re.IGNORECASE), "5"),
    (re.compile(r"\b(?:семь|семи)\b", re.IGNORECASE), "7"),
    (re.compile(r"\b(?:десять|десяти)\b", re.IGNORECASE), "10"),
    (re.compile(r"\b(?:пятнадцать|пятнадцати)\b", re.IGNORECASE), "15"),
    (re.compile(r"\b(?:тридцать|тридцати)\b", re.IGNORECASE), "30"),
    (re.compile(r"\b(?:сорок\s+пять|сорока\s+пяти)\b", re.IGNORECASE), "45"),
    (re.compile(r"\b(?:девяносто|девяноста)\b", re.IGNORECASE), "90"),
)


def _numbers(value: str) -> set[str]:
    numbers = {
        item.replace(",", ".")
        for item in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", value)
    }
    for pattern, normalized in _SPOKEN_NUMBER_PATTERNS:
        if pattern.search(value):
            numbers.add(normalized)
    return numbers


def _clean_output_text(value: str) -> str:
    cleaned = re.sub(r"\bтаюке\b", "также", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bвидна\s+жительство\b", "вид на жительство", cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(r"\bзаконодательством\s+PK\b", "законодательством РК", cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(
        r'\b\d{1,3}\.\s*[%("]\s*(?=(?:паспорт|удостоверение|вид\s+на\s+жительство)\b)',
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(^|[.;:])\s*[%*]\s+(?=(?:паспорт|удостоверение|вид\s+на\s+жительство)\b)",
        r"\1 ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\bи\.\s*др\.", "и др.", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bдр\.\s+\)", "др.)", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([.!?])\s+,", r"\1,", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


_GROUNDING_STOPWORDS = {
    "без", "более", "бы", "был", "была", "быть", "в", "во", "для", "до",
    "его", "если", "и", "из", "или", "к", "как", "на", "не", "но", "о",
    "по", "при", "с", "со", "также", "то", "только", "у", "что", "это",
    "a", "an", "and", "as", "at", "for", "from", "if", "in", "is", "not",
    "of", "on", "only", "or", "the", "this", "to", "when", "with",
}


def _grounding_tokens(value: str) -> set[str]:
    return {
        token[:7]
        for token in re.findall(r"[^\W\d_]{3,}", value.casefold().replace("ё", "е"), re.UNICODE)
        if token not in _GROUNDING_STOPWORDS
    }


_REDUNDANCY_GENERIC_TOKENS = {"колл", "лине", "сери", "coll", "rang"}


def _redundancy_tokens(value: str) -> set[str]:
    return {token[:4] for token in _grounding_tokens(value)} - _REDUNDANCY_GENERIC_TOKENS


def _is_covered_sentence(value: str, previous: list[set[str]]) -> bool:
    """Return true when a later short sentence adds no new source meaning."""
    tokens = _redundancy_tokens(value)
    if len(tokens) < 3:
        return False
    return any(
        len(tokens) <= len(available)
        and len(tokens & available) / len(tokens) >= 0.85
        for available in previous
    )


def _grounded_teaching_text(text: str, facts: list[SourceFact]) -> str:
    """Keep supported prose and restore every omitted sentence of cited facts."""
    sources = [
        " ".join((fact.subject, fact.attribute, _clean_output_text(fact.value)))
        for fact in facts
    ]
    normalized_sources = [" ".join(source.casefold().replace("ё", "е").split())
                          for source in sources]
    source_tokens = [_grounding_tokens(source) for source in sources]
    sentences = [match.group(0).strip() for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text)
                 if match.group(0).strip()]
    grounded: list[str] = []
    for sentence in sentences:
        normalized = " ".join(sentence.casefold().replace("ё", "е").split())
        tokens = _grounding_tokens(sentence)
        exact = any(normalized in source or source in normalized for source in normalized_sources)
        lexical = max(
            ((len(tokens & available) / len(tokens)) if tokens else 0.0)
            for available in source_tokens
        )
        if exact or lexical >= 0.65:
            grounded.append(sentence)
    if grounded:
        deduplicated: list[str] = []
        seen_sentences: set[str] = set()
        seen_token_sets: list[set[str]] = []
        for sentence in grounded:
            normalized = " ".join(sentence.casefold().replace("ё", "е").split())
            if normalized in seen_sentences or _is_covered_sentence(sentence, seen_token_sets):
                continue
            seen_sentences.add(normalized)
            seen_token_sets.append(_redundancy_tokens(sentence))
            deduplicated.append(sentence)
        grounded = deduplicated
        # Citing one fact id is not enough when the provider kept only one
        # sentence of a multi-sentence rule. Preserve supported paraphrases,
        # then append only source sentences whose meaning is still absent.
        # OCR-tainted facts remain excluded from this restoration path.
        if not any(contains_ocr_artifact(_clean_output_text(fact.value)) for fact in facts):
            grounded_normalized = [
                " ".join(sentence.casefold().replace("ё", "е").split())
                for sentence in grounded
            ]
            grounded_tokens = [_grounding_tokens(sentence) for sentence in grounded]
            combined_grounded_tokens = set().union(*grounded_tokens) if grounded_tokens else set()
            grounded_redundancy_tokens = [
                _redundancy_tokens(sentence) for sentence in grounded
            ]
            for fact in facts:
                source_sentences = [
                    match.group(0).strip()
                    for match in re.finditer(
                        r"[^.!?]+(?:[.!?]+|$)", _clean_output_text(fact.value)
                    )
                    if match.group(0).strip()
                    and any(character.isalpha() for character in match.group(0))
                ]
                for source_sentence in source_sentences:
                    normalized = " ".join(
                        source_sentence.casefold().replace("ё", "е").split()
                    )
                    tokens = _grounding_tokens(source_sentence)
                    semantic_threshold = 0.65 if len(source_sentences) == 1 else 0.9
                    covered = any(
                        normalized in candidate or candidate in normalized
                        for candidate in grounded_normalized
                    ) or any(
                        tokens and len(tokens & available) / len(tokens) >= semantic_threshold
                        for available in grounded_tokens
                    ) or any(
                        tokens
                        and available
                        and len(tokens & available) / min(len(tokens), len(available)) >= 0.85
                        and len(available) / len(tokens) >= 0.45
                        for available in grounded_tokens
                    ) or (
                        tokens
                        and len(tokens & combined_grounded_tokens) / len(tokens) >= 0.65
                    ) or _is_covered_sentence(
                        source_sentence, grounded_redundancy_tokens
                    )
                    if covered:
                        continue
                    restored = _clean_output_text(
                        neutralize_unprofessional_source_language(source_sentence)
                    )
                    grounded.append(restored)
                    grounded_normalized.append(normalized)
                    grounded_tokens.append(tokens)
                    grounded_redundancy_tokens.append(
                        _redundancy_tokens(source_sentence)
                    )
        return " ".join(grounded)
    if any(contains_ocr_artifact(_clean_output_text(fact.value)) for fact in facts):
        # A validated clean omission notice is safer than re-exposing unreadable
        # source glyphs or guessing the missing value.
        return text
    # Do not splice several bare table-cell values into an unsupported model
    # block. The caller can render uncovered facts separately with their labels.
    return ""


class ProviderBackedEvidenceEngine:
    """Use Qwen retrieval and DeepSeek prose without surrendering fact ownership."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingProvider,
        chat: ChatJsonProvider,
        max_realizer_attempts: int = 2,
    ) -> None:
        if max_realizer_attempts < 1:
            raise ValueError("max_realizer_attempts must be positive")
        self._embeddings = embeddings
        self._chat = chat
        self._max_realizer_attempts = max_realizer_attempts
        self._evidence = EvidenceCourseEngine()
        self._xlsx = XlsxEvidenceAdapter()

    def generate(
        self,
        source_path: Path,
        *,
        intent: CourseIntent | None = None,
        simulation_seed: int = 0,
    ) -> ProviderBackedResult:
        if source_path.suffix.casefold() != ".xlsx":
            raise ValueError(f"Unsupported local source type: {source_path.suffix}")
        return self.generate_from_document(
            self._xlsx.read(source_path),
            intent=intent,
            simulation_seed=simulation_seed,
        )

    def generate_from_document(
        self,
        document: SourceDocument,
        *,
        intent: CourseIntent | None = None,
        simulation_seed: int = 0,
    ) -> ProviderBackedResult:
        started = perf_counter()
        evidence_result = self._evidence.generate_from_document(
            document,
            intent=intent,
            simulation_seed=simulation_seed,
        )
        evidence_seconds = perf_counter() - started
        facts = list(evidence_result.admitted_facts)
        facts_by_id = {fact.fact_id: fact for fact in facts}
        lesson_by_id = {lesson.lesson_id: lesson for lesson in evidence_result.course.lessons}
        questions_by_lesson: dict[str, list[QuestionDraft]] = defaultdict(list)
        for question in evidence_result.assessment.questions:
            questions_by_lesson[question.lesson_id].append(question)

        embedding_started = perf_counter()
        embedding_model = ""
        embedding_dimension = 0
        embedding_degraded = False
        embedding_error = ""
        retrieval: list[RetrievalMeasurement] = []
        try:
            document_batch = self._embeddings.embed([fact.value for fact in facts])
            document_vectors = tuple(_normalize(vector) for vector in document_batch.vectors)
            if len(document_vectors) != len(facts):
                raise ProviderCallError("document embedding count does not match admitted facts")
            query_texts = [
                QWEN_QUERY_PREFIX
                + " ".join(
                    [
                        plan.title,
                        plan.objective,
                        *sorted({facts_by_id[fact_id].attribute for fact_id in plan.fact_ids}),
                    ]
                )
                for plan in evidence_result.evidence_plan
            ]
            query_batch = self._embeddings.embed(query_texts)
            query_vectors = tuple(_normalize(vector) for vector in query_batch.vectors)
            if len(query_vectors) != len(evidence_result.evidence_plan):
                raise ProviderCallError("query embedding count does not match lesson plan")
            retrieval = self._measure_retrieval(
                facts=facts,
                document_vectors=document_vectors,
                query_vectors=query_vectors,
                plans=evidence_result.evidence_plan,
            )
            embedding_model = document_batch.model
            embedding_dimension = len(document_vectors[0]) if document_vectors else 0
        except ProviderCallError as exc:
            embedding_degraded = True
            embedding_error = type(exc).__name__
        embedding_seconds = perf_counter() - embedding_started

        realized_lessons: list[LessonDraft] = []
        realized_questions: list[QuestionDraft] = []
        grounded_blocks: list[GroundedBlock] = []
        validation_errors: list[str] = []
        fallback_count = 0
        deterministic_fallback_lesson_ids: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        chat_attempt_count = 0
        chat_model = ""
        realization_started = perf_counter()
        for plan in evidence_result.evidence_plan:
            base_lesson = lesson_by_id[plan.lesson_id]
            seeds = questions_by_lesson.get(plan.lesson_id, [])
            request = self._realizer_request(plan, facts_by_id, seeds, intent or CourseIntent())
            accepted: tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]] | None = None
            last_error = ""
            for _ in range(self._max_realizer_attempts):
                try:
                    chat_attempt_count += 1
                    completion = self._chat.complete_json(request)
                    chat_model = completion.model
                    prompt_tokens += completion.prompt_tokens
                    completion_tokens += completion.completion_tokens
                    accepted = self._validate_and_render(
                        completion.payload,
                        base_lesson=base_lesson,
                        plan_fact_ids=set(plan.fact_ids),
                        facts_by_id=facts_by_id,
                        seeds=seeds,
                    )
                    break
                except (ProviderCallError, ValueError, KeyError, TypeError) as exc:
                    last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                    request["validation_feedback"] = last_error
            if accepted is None:
                fallback_count += 1
                deterministic_fallback_lesson_ids.append(plan.lesson_id)
                validation_errors.append(f"{plan.lesson_id}: {last_error or 'provider unavailable'}")
                fallback_lesson = LessonDraft(
                    lesson_id=base_lesson.lesson_id,
                    module_title=base_lesson.module_title,
                    title=neutralize_unprofessional_source_language(base_lesson.title),
                    objective=neutralize_unprofessional_source_language(base_lesson.objective),
                    content=neutralize_unprofessional_source_language(base_lesson.content),
                    fact_ids=base_lesson.fact_ids,
                    supporting_fact_ids=base_lesson.supporting_fact_ids,
                    duration_minutes=base_lesson.duration_minutes,
                )
                realized_lessons.append(fallback_lesson)
                realized_questions.extend(seeds)
                grounded_blocks.append(
                    GroundedBlock(
                        lesson_id=fallback_lesson.lesson_id,
                        heading="Детерминированный черновик",
                        text=fallback_lesson.content,
                        fact_ids=fallback_lesson.fact_ids,
                    )
                )
            else:
                lesson, questions, lesson_blocks = accepted
                realized_lessons.append(lesson)
                realized_questions.extend(questions)
                grounded_blocks.extend(lesson_blocks)
        realization_seconds = perf_counter() - realization_started

        realized_questions = filter_acceptable_questions(realized_questions)
        realized_course = CourseDraft(
            title=evidence_result.course.title,
            description=evidence_result.course.description,
            lessons=tuple(realized_lessons),
        )
        realized_assessment = AssessmentDraft(questions=tuple(realized_questions))
        publishability = evaluate_publishability(
            course=realized_course,
            assessment=realized_assessment,
            blocks=tuple(grounded_blocks),
            planned_fact_ids={fact.fact_id for fact in evidence_result.admitted_facts},
            provider_fallback_count=fallback_count,
        )

        return ProviderBackedResult(
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
            provider_fallback_count=fallback_count,
            deterministic_fallback_count=fallback_count,
            deterministic_fallback_lesson_ids=tuple(deterministic_fallback_lesson_ids),
            validation_errors=tuple(validation_errors),
            chat_attempt_count=chat_attempt_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            timings=(
                StageTiming(stage="evidence_plan", seconds=evidence_seconds),
                StageTiming(stage="qwen_embeddings", seconds=embedding_seconds),
                StageTiming(stage="deepseek_realization", seconds=realization_seconds),
            ),
        )

    @staticmethod
    def _measure_retrieval(
        *,
        facts: list[SourceFact],
        document_vectors: tuple[tuple[float, ...], ...],
        query_vectors: tuple[tuple[float, ...], ...],
        plans: tuple[LessonEvidence, ...],
    ) -> list[RetrievalMeasurement]:
        measurements: list[RetrievalMeasurement] = []
        for plan, query in zip(plans, query_vectors, strict=True):
            ranked = sorted(
                zip(facts, document_vectors, strict=True),
                key=lambda item: sum(left * right for left, right in zip(query, item[1], strict=True)),
                reverse=True,
            )
            k = min(len(ranked), max(8, len(plan.fact_ids) * 2))
            top_ids = tuple(fact.fact_id for fact, _ in ranked[:k])
            expected = set(plan.fact_ids)
            recall = len(expected.intersection(top_ids)) / len(expected) if expected else 1.0
            measurements.append(
                RetrievalMeasurement(
                    lesson_id=plan.lesson_id,
                    recall_at_k=recall,
                    k=k,
                    top_fact_ids=top_ids,
                )
            )
        return measurements

    @staticmethod
    def _realizer_request(
        plan: LessonEvidence,
        facts_by_id: dict[str, SourceFact],
        seeds: list[QuestionDraft],
        intent: CourseIntent,
    ) -> dict[str, Any]:
        return {
            "lesson_title": plan.title,
            "objective": plan.objective,
            "course_intent": {
                "purpose": intent.purpose,
                "audience": intent.audience,
                "emphasis": list(intent.emphasis),
            },
            "facts": [
                {
                    "fact_id": fact_id,
                    "subject": facts_by_id[fact_id].subject,
                    "attribute": facts_by_id[fact_id].attribute,
                    "value": _clean_output_text(facts_by_id[fact_id].value),
                    "source_locator": facts_by_id[fact_id].source_locator,
                }
                for fact_id in plan.fact_ids
            ],
            "question_seeds": [
                {
                    "fact_id": seed.fact_id,
                    "prompt": seed.prompt,
                    "options": list(seed.options),
                    "correct_answer": seed.correct_answer,
                }
                for seed in seeds
            ],
        }

    @staticmethod
    def _validate_and_render(
        payload: dict[str, Any],
        *,
        base_lesson: LessonDraft,
        plan_fact_ids: set[str],
        facts_by_id: dict[str, SourceFact],
        seeds: list[QuestionDraft],
    ) -> tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]]:
        blocks = payload.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("blocks must be a non-empty list")
        rendered: list[str] = []
        grounded_blocks: list[GroundedBlock] = []
        covered: set[str] = set()
        seen_blocks: set[tuple[str, tuple[str, ...]]] = set()
        seen_lesson_sentences: set[str] = set()
        seen_lesson_token_sets: list[set[str]] = []
        prior_sentences_by_fact: dict[str, list[str]] = defaultdict(list)
        prior_tokens_by_fact: dict[str, set[str]] = defaultdict(set)
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("block must be an object")
            heading = neutralize_unprofessional_source_language(
                _clean_output_text(str(block.get("heading") or ""))
            )
            text = neutralize_unprofessional_source_language(
                _clean_output_text(str(block.get("text") or ""))
            )
            fact_ids = {str(value) for value in block.get("fact_ids") or []}
            if not heading or not text or not fact_ids:
                raise ValueError("block heading, text and fact_ids are required")
            if not fact_ids <= plan_fact_ids:
                raise ValueError("block cites a fact outside the lesson plan")
            if contains_ocr_artifact(heading) or contains_ocr_artifact(text):
                raise ValueError("block exposes unresolved OCR artifacts")
            if has_unprofessional_learner_language(heading) or has_unprofessional_learner_language(text):
                raise ValueError("block contains blocked learner-visible language")
            cited_source = " ".join(facts_by_id[fact_id].value for fact_id in fact_ids)
            if (
                contains_internal_generation_instruction(text)
                and not contains_internal_generation_instruction(cited_source)
            ):
                raise ValueError("block exposes internal generation instructions")
            allowed_numbers = set().union(
                *(
                    _numbers(
                        " ".join(
                            (
                                facts_by_id[fact_id].subject,
                                facts_by_id[fact_id].attribute,
                                facts_by_id[fact_id].value,
                                facts_by_id[fact_id].source_locator,
                            )
                        )
                    )
                    for fact_id in fact_ids
                )
            )
            unexpected_numbers = _numbers(text) - allowed_numbers
            if unexpected_numbers:
                raise ValueError(
                    "block introduces a number absent from cited facts: "
                    f"{sorted(unexpected_numbers)}"
                )
            text = _grounded_teaching_text(
                text,
                [facts_by_id[fact_id] for fact_id in sorted(fact_ids)],
            )
            if not text:
                # Unsupported model prose contributes no coverage. Facts still
                # absent after all blocks are rendered below with attribution.
                continue
            fresh_sentences: list[str] = []
            for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text):
                sentence = match.group(0).strip()
                if not sentence:
                    continue
                normalized_sentence = " ".join(
                    sentence.casefold().replace("ё", "е").split()
                )
                if (
                    normalized_sentence in seen_lesson_sentences
                    or _is_covered_sentence(sentence, seen_lesson_token_sets)
                ):
                    continue
                tail = " ".join(
                    re.sub(
                        r"[ .;:]+$", "",
                        sentence.rsplit(",", 1)[-1].casefold().replace("ё", "е"),
                    ).split()
                )
                sentence_tokens = _redundancy_tokens(sentence)
                if (
                    "," in sentence
                    and len(_redundancy_tokens(tail)) >= 2
                    and any(
                        sentence_tokens <= prior_tokens_by_fact[fact_id]
                        and any(
                            tail in earlier for earlier in prior_sentences_by_fact[fact_id]
                        )
                        for fact_id in fact_ids
                    )
                ):
                    # The clause after the condition was already taught in
                    # full, and this restatement adds no source vocabulary.
                    continue
                seen_lesson_sentences.add(normalized_sentence)
                seen_lesson_token_sets.append(sentence_tokens)
                for fact_id in fact_ids:
                    prior_sentences_by_fact[fact_id].append(normalized_sentence)
                    prior_tokens_by_fact[fact_id].update(sentence_tokens)
                fresh_sentences.append(sentence)
            text = _clean_output_text(" ".join(fresh_sentences))
            if not text:
                # The same grounded sentence was already rendered by an
                # earlier block; only this duplicate can claim coverage.
                covered.update(fact_ids)
                continue
            block_key = (
                " ".join(text.casefold().replace("ё", "е").split()),
                tuple(sorted(fact_ids)),
            )
            if block_key in seen_blocks:
                covered.update(fact_ids)
                continue
            seen_blocks.add(block_key)
            covered.update(fact_ids)
            rendered.extend([f"### {heading}", "", text, ""])
            grounded_blocks.append(
                GroundedBlock(
                    lesson_id=base_lesson.lesson_id,
                    heading=heading,
                    text=text,
                    fact_ids=tuple(sorted(fact_ids)),
                )
            )
        # Keep valid provider-authored teaching blocks, but do not discard an
        # entire lesson merely because the model omitted one of many atomic
        # source facts. Missing facts are rendered verbatim and remain cited,
        # so the server still guarantees complete, source-only coverage.
        for fact_id in base_lesson.fact_ids:
            if fact_id not in plan_fact_ids or fact_id in covered:
                continue
            fact = facts_by_id[fact_id]
            text = _clean_output_text(
                neutralize_unprofessional_source_language(fact.value.strip())
            )
            if contains_ocr_artifact(text):
                raise ValueError("fallback fact exposes unresolved OCR artifacts")
            if is_tabular_locator(fact.source_locator) and not re.search(r"[.!?]$", text):
                # A workbook cell alone is not a teachable statement. Preserve
                # its exact subject, column label and value without inventing
                # a grammatical relationship absent from the source.
                subject = _clean_output_text(fact.subject)
                attribute = _clean_output_text(fact.attribute)
                text = f"{subject} — {attribute}: {text}."
            heading = neutralize_unprofessional_source_language(
                " ".join(fact.attribute.strip().rstrip(".:").split())
            ) or "Подтверждённые сведения"
            if heading.casefold() == "положение":
                # Conversion labels like "положение" are not useful headings.
                # A short exact source prefix distinguishes adjacent rules.
                heading = " ".join(text.split()[:5]).rstrip(".,;:") or fact.subject
            rendered.extend([f"### {heading}", "", text, ""])
            grounded_blocks.append(
                GroundedBlock(
                    lesson_id=base_lesson.lesson_id,
                    heading=heading,
                    text=text,
                    fact_ids=(fact_id,),
                )
            )
            covered.add(fact_id)
        if covered != plan_fact_ids:
            raise ValueError("realizer did not cover every planned fact")

        seed_by_fact = {seed.fact_id: seed for seed in seeds}
        raw_questions = payload.get("questions")
        if not isinstance(raw_questions, list):
            raw_questions = []
        rewritten_by_fact: dict[str, QuestionDraft] = {}
        seen_fact_ids: set[str] = set()
        for raw in raw_questions:
            if not isinstance(raw, dict):
                continue
            cited = tuple(str(value) for value in raw.get("fact_ids") or [])
            if len(cited) != 1 or cited[0] not in seed_by_fact or cited[0] in seen_fact_ids:
                continue
            seed = seed_by_fact[cited[0]]
            options = seed.options
            correct_answer = seed.correct_answer
            prompt = neutralize_unprofessional_source_language(
                _clean_output_text(str(raw.get("prompt") or ""))
            )
            explanation = neutralize_unprofessional_source_language(
                _clean_output_text(str(raw.get("explanation") or ""))
            )
            if not prompt or not explanation:
                continue
            if is_generic_question(prompt):
                continue
            if contains_ocr_artifact(prompt) or contains_ocr_artifact(explanation):
                continue
            if has_unprofessional_learner_language(prompt) or has_unprofessional_learner_language(explanation):
                continue
            fact = facts_by_id[seed.fact_id]
            allowed_numbers = set().union(
                *(
                    _numbers(value)
                    for value in (
                        *seed.options,
                        seed.prompt,
                        fact.subject,
                        fact.attribute,
                        fact.value,
                        fact.source_locator,
                    )
                )
            )
            unexpected_numbers = (_numbers(prompt) | _numbers(explanation)) - allowed_numbers
            if unexpected_numbers:
                continue
            rewritten_by_fact[seed.fact_id] = QuestionDraft(
                question_id=seed.question_id,
                lesson_id=seed.lesson_id,
                kind=seed.kind,
                # A specific deterministic seed already names the tested
                # attribute and is safer than an unconstrained paraphrase.
                # Only generic source-membership seeds require model rewriting.
                prompt=(prompt if is_generic_question(seed.prompt) else seed.prompt),
                options=options,
                correct_answer=correct_answer,
                explanation=explanation,
                fact_id=seed.fact_id,
                distractor_fact_ids=seed.distractor_fact_ids,
            )
            seen_fact_ids.add(seed.fact_id)
        questions = [rewritten_by_fact.get(seed.fact_id, seed) for seed in seeds]
        word_count = len(re.findall(r"\w+", " ".join(rendered)))
        if word_count > 650:
            raise ValueError("lesson exceeds the 650-word publishability ceiling")
        title = neutralize_unprofessional_source_language(
            _clean_output_text(str(payload.get("title") or base_lesson.title)).lstrip("# ")
        )
        objective = neutralize_unprofessional_source_language(
            _clean_output_text(str(payload.get("objective") or base_lesson.objective))
        )
        if plan_fact_ids and all(
            is_tabular_locator(facts_by_id[fact_id].source_locator)
            for fact_id in plan_fact_ids
        ):
            # The plan owns the row subject. A model must not turn a collection
            # into one item mentioned only in a supporting catalog sheet; both
            # fields feed the later assessment author as factual context.
            title = base_lesson.title
            objective = base_lesson.objective
        if not is_acceptable_title(title):
            raise ValueError("lesson title is not a concise complete nominal phrase")
        if has_unprofessional_learner_language(title) or has_unprofessional_learner_language(objective):
            raise ValueError("lesson metadata contains blocked learner-visible language")
        lesson = LessonDraft(
            lesson_id=base_lesson.lesson_id,
            module_title=base_lesson.module_title,
            title=title,
            objective=objective,
            content="\n".join(rendered).strip(),
            fact_ids=base_lesson.fact_ids,
            supporting_fact_ids=base_lesson.supporting_fact_ids,
            duration_minutes=max(2, math.ceil(word_count / 130)),
        )
        return lesson, questions, grounded_blocks
