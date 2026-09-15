"""Provider-backed realization layered over the immutable V2 evidence plan."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

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
)
from .provider_models import GroundedBlock, ProviderBackedResult, RetrievalMeasurement
from .providers import QWEN_QUERY_PREFIX, ChatJsonProvider, EmbeddingProvider, ProviderCallError
from .quality import (
    contains_ocr_artifact,
    evaluate_publishability,
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
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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
                realized_lessons.append(base_lesson)
                realized_questions.extend(seeds)
                grounded_blocks.append(
                    GroundedBlock(
                        lesson_id=base_lesson.lesson_id,
                        heading="Детерминированный черновик",
                        text=base_lesson.content,
                        fact_ids=base_lesson.fact_ids,
                    )
                )
            else:
                lesson, questions, lesson_blocks = accepted
                realized_lessons.append(lesson)
                realized_questions.extend(questions)
                grounded_blocks.extend(lesson_blocks)
        realization_seconds = perf_counter() - realization_started

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
                    "value": facts_by_id[fact_id].value,
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
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("block must be an object")
            heading = _clean_output_text(str(block.get("heading") or ""))
            text = _clean_output_text(str(block.get("text") or ""))
            fact_ids = {str(value) for value in block.get("fact_ids") or []}
            if not heading or not text or not fact_ids:
                raise ValueError("block heading, text and fact_ids are required")
            if not fact_ids <= plan_fact_ids:
                raise ValueError("block cites a fact outside the lesson plan")
            if contains_ocr_artifact(heading) or contains_ocr_artifact(text):
                raise ValueError("block exposes unresolved OCR artifacts")
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
            prompt = _clean_output_text(str(raw.get("prompt") or ""))
            explanation = _clean_output_text(str(raw.get("explanation") or ""))
            if not prompt or not explanation:
                continue
            if is_generic_question(prompt):
                continue
            if contains_ocr_artifact(prompt) or contains_ocr_artifact(explanation):
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
                prompt=prompt,
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
        title = _clean_output_text(str(payload.get("title") or base_lesson.title)).lstrip("# ")
        if not is_acceptable_title(title):
            raise ValueError("lesson title is not a concise complete nominal phrase")
        lesson = LessonDraft(
            lesson_id=base_lesson.lesson_id,
            module_title=base_lesson.module_title,
            title=title,
            objective=_clean_output_text(str(payload.get("objective") or base_lesson.objective)),
            content="\n".join(rendered).strip(),
            fact_ids=base_lesson.fact_ids,
            supporting_fact_ids=base_lesson.supporting_fact_ids,
            duration_minutes=max(2, math.ceil(word_count / 130)),
        )
        return lesson, questions, grounded_blocks
