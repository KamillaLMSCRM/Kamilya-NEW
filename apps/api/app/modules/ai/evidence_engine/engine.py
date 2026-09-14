"""A parallel evidence-first engine; it is intentionally not wired to production."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from .adapters import XlsxEvidenceAdapter
from .models import (
    AssessmentDraft,
    CourseDraft,
    CourseIntent,
    DocumentPlan,
    EvaluationReport,
    EvidenceCourseResult,
    LessonDraft,
    LessonEvidence,
    QuestionDraft,
    SourceDocument,
    SourceFact,
    SourceSection,
    StageTiming,
)

_BUCKETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Назначение и позиционирование",
        re.compile(r"что это|назначен|идея|стиль|комнат|аудитор|применен", re.IGNORECASE),
    ),
    (
        "Материалы и исполнение",
        re.compile(
            r"материал|фасад|корпус|цвет|ручк|отделк|фурнитур|направляющ",
            re.IGNORECASE,
        ),
    ),
    (
        "Ассортимент и отличия",
        re.compile(
            r"размер|вес|комплект|состав|модул|гарант|характерист|особенност|"
            r"преимуществ|отличается",
            re.IGNORECASE,
        ),
    ),
    (
        "Работа с покупателем",
        re.compile(r"кому|покупател|рекоменд|что сказать", re.IGNORECASE),
    ),
)


def _norm(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _fact_key(fact: SourceFact) -> tuple[str, str, str]:
    return (_norm(fact.subject), _norm(fact.attribute), _norm(fact.value))


def _stable_id(prefix: str, *parts: str) -> str:
    body = "\x1f".join(_norm(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"


def _deduplicate_facts(facts: list[SourceFact]) -> tuple[list[SourceFact], int]:
    grouped: dict[tuple[str, str, str], SourceFact] = {}
    duplicate_count = 0
    for fact in facts:
        key = _fact_key(fact)
        if key in grouped:
            duplicate_count += 1
            continue
        grouped[key] = fact
    unique: list[SourceFact] = []
    for key, winner in grouped.items():
        unique.append(replace(winner, fact_id=_stable_id("fact", *key)))
    return unique, duplicate_count


def _bucket_name(attribute: str) -> str:
    for title, pattern in _BUCKETS:
        if pattern.search(attribute):
            return title
    return "Ключевые сведения"


def _partition_subject_facts(facts: list[SourceFact]) -> list[tuple[str, list[SourceFact]]]:
    if len(facts) <= 7:
        return [("", facts)]
    grouped: dict[str, list[SourceFact]] = defaultdict(list)
    for fact in facts:
        grouped[_bucket_name(fact.attribute)].append(fact)
    substantial = [(name, values) for name, values in grouped.items() if len(values) >= 2]
    remainder = [fact for name, values in grouped.items() if len(values) < 2 for fact in values]
    if not substantial:
        size = 6
        return [("", facts[index : index + size]) for index in range(0, len(facts), size)]
    for fact in remainder:
        target_index = min(range(len(substantial)), key=lambda index: len(substantial[index][1]))
        substantial[target_index][1].append(fact)
    order = {name: index for index, (name, _) in enumerate(_BUCKETS)}
    order["Ключевые сведения"] = len(order)
    return sorted(substantial, key=lambda item: order.get(item[0], len(order) + 1))


def _partition_narrative_facts(facts: list[SourceFact]) -> list[tuple[str, list[SourceFact]]]:
    if not facts:
        return []
    partitions: list[list[SourceFact]] = []
    current: list[SourceFact] = []
    current_words = 0
    for fact in facts:
        fact_words = len(fact.value.split())
        if current and (current_words + fact_words > 550 or len(current) >= 14):
            partitions.append(current)
            current = []
            current_words = 0
        current.append(fact)
        current_words += fact_words
    if current:
        partitions.append(current)
    if len(partitions) > 1 and len(partitions[-1]) <= 2:
        partitions[-2].extend(partitions.pop())
    return [("", partition) for partition in partitions]


def _narrative_lesson_title(module: str, facts: list[SourceFact], *, split: bool) -> str:
    module_title = re.sub(r"^(?:\d+|[Зз])\.\s*", "", module).strip()
    if not split:
        return module_title.capitalize()
    first = re.sub(r"^(?:\d+|[Зз])\s*[).,]\s*", "", facts[0].value).strip()
    first = first.split(".", 1)[0].split(";", 1)[0].strip()
    words = first.split()
    summary = " ".join(words[:11]).strip(" ,:-")
    if len(summary) < 12:
        summary = module_title
    while len(summary) > 96 and " " in summary:
        summary = summary.rsplit(" ", 1)[0]
    return summary.rstrip(" ,:-").capitalize()


_DURATION_VALUE_RE = re.compile(
    r"(?:в\s+течение|не\s+позднее|срок(?:ом)?(?:\s+до)?|до)\s+"
    r"(?P<answer>(?:\d+(?:[.,]\d+)?|[а-яё-]+)(?:\s*\([^)]{1,50}\))?\s+"
    r"(?:(?:рабочих|календарных)\s+)?(?:дн(?:я|ей)|месяц(?:а|ев)|час(?:а|ов)))",
    re.IGNORECASE,
)
_PERCENT_VALUE_RE = re.compile(r"(?P<answer>\d+(?:[.,]\d+)?\s*%)")


def _extract_assessable_value(fact: SourceFact) -> str | None:
    if fact.confidence < 0.8 or fact.uncertainty not in {"", "local_ocr"}:
        return None
    if "Условие" in fact.value and "Описание" in fact.value:
        return None
    patterns = (_DURATION_VALUE_RE, _PERCENT_VALUE_RE)
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(" ".join(match.group("answer").split()) for match in pattern.finditer(fact.value))
    distinct = list(dict.fromkeys(_norm(value) for value in matches))
    if len(distinct) != 1:
        return None
    answer = matches[0]
    if re.match(r"^[Зз]\s*\(", answer):
        return None
    return answer


def _masked_fact_prompt(value: str, answer: str) -> str:
    masked = value.replace(answer, "_____", 1)
    masked = re.sub(r"^(?:\d+|[Зз])\s*[).,]\s*", "", masked).strip()
    if len(masked) <= 220:
        return masked
    blank_index = masked.find("_____")
    start = max(0, blank_index - 95)
    end = min(len(masked), blank_index + 120)
    excerpt = masked[start:end].strip(" ,;:-")
    if start:
        excerpt = f"…{excerpt}"
    if end < len(masked):
        excerpt = f"{excerpt}…"
    return excerpt


_RUSSIAN_NUMBER_MARKERS: tuple[tuple[str, str], ...] = (
    ("триста шестьдесят шесть", "366"),
    ("триста шестьдесят пять", "365"),
    ("сто семьдесят девять", "179"),
    ("девяност", "90"),
    ("сорока пяти", "45"),
    ("тридцат", "30"),
    ("пятнадцат", "15"),
    ("четырнадцат", "14"),
    ("десят", "10"),
    ("сем", "7"),
    ("пят", "5"),
    ("трех", "3"),
    ("трёх", "3"),
    ("три", "3"),
)


def _answer_semantic_key(value: str) -> str:
    normalized = _norm(value)
    digit = re.search(r"\d+(?:[.,]\d+)?", normalized)
    number = digit.group(0).replace(",", ".") if digit else ""
    if not number:
        for marker, resolved in _RUSSIAN_NUMBER_MARKERS:
            if marker in normalized:
                number = resolved
                break
    if "рабоч" in normalized:
        unit = "working_day"
    elif "календар" in normalized:
        unit = "calendar_day"
    elif "дн" in normalized:
        unit = "day"
    elif "месяц" in normalized:
        unit = "month"
    elif "час" in normalized:
        unit = "hour"
    elif "%" in normalized:
        unit = "percent"
    else:
        unit = normalized
    return f"{number}:{unit}"


def _entity_tokens(value: str) -> set[str]:
    ignored = {"коллекция", "система", "collection", "и", "and"}
    return {
        token
        for token in re.findall(r"[^\W\d_]{3,}", _norm(value), flags=re.UNICODE)
        if token not in ignored
    }


def _supporting_example_facts(
    *,
    subject: str,
    bucket: str,
    supporting: list[SourceFact],
) -> tuple[SourceFact, ...]:
    if bucket not in {"", "Ассортимент и отличия"}:
        return ()
    required = _entity_tokens(subject)
    if not required:
        return ()
    by_item: dict[str, list[SourceFact]] = defaultdict(list)
    for fact in supporting:
        if required <= _entity_tokens(fact.subject):
            by_item[fact.subject].append(fact)
    preferred_attributes = (
        "артикул",
        "функциональная группа",
        "размеры (ш×г×в), мм",
        "вес",
    )
    for item in sorted(by_item, key=_norm):
        item_facts = by_item[item]
        selected = [
            fact
            for attribute in preferred_attributes
            for fact in item_facts
            if _norm(fact.attribute) == _norm(attribute)
        ]
        if len(selected) >= 2:
            return tuple(selected[:3])
    return ()


class EvidenceCourseEngine:
    """Deep public seam for the local V2 experiment.

    It accepts an immutable source and returns a fully traceable draft.  No DB,
    queue, provider route, existing pipeline function, or production setting is
    touched.
    """

    def __init__(self) -> None:
        self._xlsx = XlsxEvidenceAdapter()

    def generate(
        self,
        source_path: Path,
        *,
        intent: CourseIntent | None = None,
        simulation_seed: int = 0,
    ) -> EvidenceCourseResult:
        suffix = source_path.suffix.casefold()
        if suffix != ".xlsx":
            raise ValueError(f"Unsupported local source type: {suffix}")
        started = perf_counter()
        document = self._xlsx.read(source_path)
        adapter_seconds = perf_counter() - started
        result = self.generate_from_document(
            document,
            intent=intent,
            simulation_seed=simulation_seed,
        )
        return replace(
            result,
            timings=(StageTiming(stage="source_adapter", seconds=adapter_seconds), *result.timings),
        )

    def generate_from_document(
        self,
        document: SourceDocument,
        *,
        intent: CourseIntent | None = None,
        simulation_seed: int = 0,
    ) -> EvidenceCourseResult:
        del simulation_seed  # Fact allocation is deliberately seed-independent.
        resolved_intent = intent or CourseIntent()
        timings: list[StageTiming] = []

        started = perf_counter()
        primary_sections = [section for section in document.sections if section.role == "primary"]
        supporting_sections = [section for section in document.sections if section.role == "supporting"]
        admitted, duplicate_count = _deduplicate_facts(
            [fact for section in primary_sections for fact in section.facts]
        )
        supporting, supporting_duplicates = _deduplicate_facts(
            [fact for section in supporting_sections for fact in section.facts]
        )
        timings.append(StageTiming(stage="document_plan", seconds=perf_counter() - started))

        started = perf_counter()
        evidence = self._build_evidence_plan(
            document.kind,
            primary_sections,
            admitted,
            supporting,
        )
        timings.append(StageTiming(stage="evidence_plan", seconds=perf_counter() - started))

        started = perf_counter()
        course = self._render_course(
            document,
            evidence,
            admitted,
            supporting,
            resolved_intent,
        )
        timings.append(StageTiming(stage="course_draft", seconds=perf_counter() - started))

        started = perf_counter()
        assessment = self._build_assessment(document.kind, evidence, admitted)
        timings.append(StageTiming(stage="assessment_draft", seconds=perf_counter() - started))

        started = perf_counter()
        evaluation = self._evaluate(
            admitted,
            evidence,
            assessment,
            duplicate_fact_count=duplicate_count + supporting_duplicates,
        )
        timings.append(StageTiming(stage="evaluation", seconds=perf_counter() - started))

        document_plan = DocumentPlan(
            source_id=document.source_id,
            source_sha256=document.source_sha256,
            kind=document.kind,
            primary_sections=tuple(section.title for section in primary_sections),
            supporting_sections=tuple(section.title for section in supporting_sections),
            admitted_fact_count=len(admitted),
            supporting_fact_count=len(supporting),
            duplicate_fact_count=duplicate_count + supporting_duplicates,
        )
        fingerprint = self._fingerprint(evidence, assessment)
        return EvidenceCourseResult(
            document_plan=document_plan,
            admitted_facts=tuple(admitted),
            supporting_facts=tuple(supporting),
            evidence_plan=tuple(evidence),
            course=course,
            assessment=assessment,
            evaluation=evaluation,
            semantic_fingerprint=fingerprint,
            timings=tuple(timings),
        )

    @staticmethod
    def _build_evidence_plan(
        kind: str,
        sections: list[SourceSection],
        admitted: list[SourceFact],
        supporting: list[SourceFact],
    ) -> list[LessonEvidence]:
        section_by_fact = {
            _fact_key(fact): section.title
            for section in sections
            for fact in section.facts
        }
        by_module_subject: dict[tuple[str, str], list[SourceFact]] = defaultdict(list)
        for fact in admitted:
            module = section_by_fact.get(_fact_key(fact), "Основной материал")
            by_module_subject[(module, fact.subject)].append(fact)

        evidence: list[LessonEvidence] = []
        for (module, subject), facts in by_module_subject.items():
            if kind == "narrative":
                partitions = _partition_narrative_facts(facts)
            else:
                ordered = sorted(
                    facts,
                    key=lambda item: (_bucket_name(item.attribute), _norm(item.attribute)),
                )
                partitions = _partition_subject_facts(ordered)
            for index, (bucket, selected) in enumerate(partitions, start=1):
                if kind == "narrative":
                    title = _narrative_lesson_title(
                        module,
                        selected,
                        split=len(partitions) > 1,
                    )
                else:
                    title = subject if len(partitions) == 1 else f"{subject}: {bucket or f'часть {index}'}"
                lesson_id = _stable_id("lesson", module, subject, bucket, str(index))
                attributes = ", ".join(dict.fromkeys(fact.attribute for fact in selected))
                if kind == "narrative":
                    objective = f"Применять подтверждённые положения раздела «{module}»."
                else:
                    objective = f"Различать подтверждённые сведения: {attributes}."
                supporting_examples = (
                    _supporting_example_facts(
                        subject=subject,
                        bucket=bucket,
                        supporting=supporting,
                    )
                    if kind == "spreadsheet"
                    else ()
                )
                evidence.append(
                    LessonEvidence(
                        lesson_id=lesson_id,
                        module_title=module,
                        title=title,
                        objective=objective,
                        fact_ids=tuple(fact.fact_id for fact in selected),
                        supporting_fact_ids=tuple(fact.fact_id for fact in supporting_examples),
                        source_locators=tuple(
                            fact.source_locator for fact in [*selected, *supporting_examples]
                        ),
                    )
                )
        return evidence

    @staticmethod
    def _render_course(
        document: SourceDocument,
        evidence: list[LessonEvidence],
        facts: list[SourceFact],
        supporting: list[SourceFact],
        intent: CourseIntent,
    ) -> CourseDraft:
        by_id = {fact.fact_id: fact for fact in [*facts, *supporting]}
        lessons: list[LessonDraft] = []
        for plan in evidence:
            lesson_facts = [by_id[fact_id] for fact_id in plan.fact_ids]
            lines = ["### Подтверждённые сведения"]
            for fact in lesson_facts:
                lines.append(f"- **{fact.attribute}.** {fact.value}")
            supporting_facts = [by_id[fact_id] for fact_id in plan.supporting_fact_ids]
            if supporting_facts:
                lines.extend(["", "### Пример из вспомогательного листа"])
                for fact in supporting_facts:
                    lines.append(f"- **{fact.subject} — {fact.attribute}.** {fact.value}")
            lines.extend(
                [
                    "",
                    "### Источники",
                    *[
                        f"- `{fact.source_locator}`"
                        for fact in [*lesson_facts, *supporting_facts]
                    ],
                ]
            )
            word_count = len(re.findall(r"\w+", " ".join(fact.value for fact in lesson_facts)))
            lessons.append(
                LessonDraft(
                    lesson_id=plan.lesson_id,
                    module_title=plan.module_title,
                    title=plan.title,
                    objective=plan.objective,
                    content="\n".join(lines),
                    fact_ids=plan.fact_ids,
                    supporting_fact_ids=plan.supporting_fact_ids,
                    duration_minutes=max(2, math.ceil(word_count / 130)),
                )
            )
        intent_suffix = ""
        if intent.purpose:
            intent_suffix = f" Цель методиста: {intent.purpose.strip()}"
        return CourseDraft(
            title=f"{document.title}: доказательный учебный черновик",
            description=(
                "Курс построен только по подтверждённым фактам источника; объём адаптирован "
                f"к фактическому материалу.{intent_suffix}"
            ),
            lessons=tuple(lessons),
        )

    @staticmethod
    def _build_assessment(
        kind: str,
        evidence: list[LessonEvidence],
        facts: list[SourceFact],
    ) -> AssessmentDraft:
        if kind == "narrative":
            return EvidenceCourseEngine._build_narrative_assessment(evidence, facts)
        by_id = {fact.fact_id: fact for fact in facts}
        peers: dict[str, list[SourceFact]] = defaultdict(list)
        for fact in facts:
            peers[_norm(fact.attribute)].append(fact)
        questions: list[QuestionDraft] = []
        tested: set[tuple[str, str, str]] = set()
        for lesson in evidence:
            candidates = [by_id[fact_id] for fact_id in lesson.fact_ids]
            candidates.sort(
                key=lambda fact: (
                    0 if re.search(r"\d", fact.value) else 1,
                    len(fact.value),
                    _norm(fact.attribute),
                )
            )
            target_questions = min(3, max(1, math.ceil(len(candidates) / 3)))
            for fact in candidates:
                if len([q for q in questions if q.lesson_id == lesson.lesson_id]) >= target_questions:
                    break
                key = _fact_key(fact)
                if key in tested:
                    continue
                tested.add(key)
                compatible = [
                    peer
                    for peer in peers[_norm(fact.attribute)]
                    if peer.fact_id != fact.fact_id and _norm(peer.value) != _norm(fact.value)
                ]
                unique_peers: dict[str, SourceFact] = {}
                for peer in compatible:
                    unique_peers.setdefault(_norm(peer.value), peer)
                distractors = list(unique_peers.values())[:3]
                if len(distractors) >= 2:
                    option_pairs = [(fact.value, fact.fact_id), *[(d.value, d.fact_id) for d in distractors]]
                    option_pairs.sort(key=lambda item: _norm(item[0]))
                    questions.append(
                        QuestionDraft(
                            question_id=_stable_id("question", fact.fact_id),
                            lesson_id=lesson.lesson_id,
                            kind="single_choice",
                            prompt=f"Что указано для «{fact.subject}» в поле «{fact.attribute}»?",
                            options=tuple(value for value, _ in option_pairs),
                            correct_answer=fact.value,
                            explanation=f"Подтверждено источником: {fact.value}",
                            fact_id=fact.fact_id,
                            distractor_fact_ids=tuple(source_id for _, source_id in option_pairs if source_id != fact.fact_id),
                        )
                    )
        return AssessmentDraft(questions=tuple(questions))

    @staticmethod
    def _build_narrative_assessment(
        evidence: list[LessonEvidence], facts: list[SourceFact]
    ) -> AssessmentDraft:
        by_id = {fact.fact_id: fact for fact in facts}
        answer_by_fact = {
            fact.fact_id: extracted
            for fact in facts
            if (extracted := _extract_assessable_value(fact)) is not None
        }
        peers: dict[str, list[tuple[SourceFact, str]]] = defaultdict(list)
        for fact in facts:
            answer = answer_by_fact.get(fact.fact_id)
            if answer:
                peers[_norm(fact.attribute)].append((fact, answer))

        questions: list[QuestionDraft] = []
        seen_prompts: set[str] = set()
        for lesson in evidence:
            for fact_id in lesson.fact_ids:
                if len([q for q in questions if q.lesson_id == lesson.lesson_id]) >= 3:
                    break
                fact = by_id[fact_id]
                answer = answer_by_fact.get(fact_id)
                if not answer:
                    continue
                unique_answers: dict[str, tuple[SourceFact, str]] = {}
                for peer, peer_answer in peers[_norm(fact.attribute)]:
                    if (
                        peer.fact_id == fact.fact_id
                        or _answer_semantic_key(peer_answer) == _answer_semantic_key(answer)
                    ):
                        continue
                    unique_answers.setdefault(
                        _answer_semantic_key(peer_answer),
                        (peer, peer_answer),
                    )
                distractors = list(unique_answers.values())[:3]
                if len(distractors) < 2:
                    continue
                masked = _masked_fact_prompt(fact.value, answer)
                prompt = f"Какое значение пропущено в положении: «{masked}»?"
                prompt_key = _norm(prompt)
                if prompt_key in seen_prompts:
                    continue
                seen_prompts.add(prompt_key)
                option_pairs = [(answer, fact.fact_id), *[(value, peer.fact_id) for peer, value in distractors]]
                option_pairs.sort(key=lambda item: _norm(item[0]))
                questions.append(
                    QuestionDraft(
                        question_id=_stable_id("question", fact.fact_id, answer),
                        lesson_id=lesson.lesson_id,
                        kind="single_choice",
                        prompt=prompt,
                        options=tuple(value for value, _ in option_pairs),
                        correct_answer=answer,
                        explanation=f"Точное значение подтверждено фрагментом {fact.source_locator}.",
                        fact_id=fact.fact_id,
                        distractor_fact_ids=tuple(
                            source_id for _, source_id in option_pairs if source_id != fact.fact_id
                        ),
                    )
                )
        return AssessmentDraft(questions=tuple(questions))

    @staticmethod
    def _evaluate(
        facts: list[SourceFact],
        evidence: list[LessonEvidence],
        assessment: AssessmentDraft,
        *,
        duplicate_fact_count: int,
    ) -> EvaluationReport:
        lesson_by_fact = {
            fact_id: lesson.lesson_id for lesson in evidence for fact_id in lesson.fact_ids
        }
        used = set(lesson_by_fact)
        prompts = [_norm(question.prompt) for question in assessment.questions]
        duplicate_questions = len(prompts) - len(set(prompts))
        cross_lesson = sum(
            1
            for question in assessment.questions
            if lesson_by_fact.get(question.fact_id) != question.lesson_id
        )
        unsupported = sum(1 for question in assessment.questions if question.fact_id not in used)
        warnings: list[str] = []
        true_false_count = sum(q.kind == "true_false" for q in assessment.questions)
        if assessment.questions and true_false_count / len(assessment.questions) > 0.5:
            warnings.append("assessment_true_false_dominance")
        if not assessment.questions:
            warnings.append("assessment_empty_no_safe_questions")
        uncertain_fact_count = sum(fact.confidence < 0.8 for fact in facts)
        if uncertain_fact_count:
            warnings.append("uncertain_source_facts_require_review")
        return EvaluationReport(
            admitted_fact_count=len(facts),
            used_fact_count=len(used),
            coverage_ratio=(len(used) / len(facts)) if facts else 0.0,
            duplicate_fact_count=duplicate_fact_count,
            duplicate_question_count=duplicate_questions,
            unsupported_claim_count=unsupported,
            cross_lesson_question_count=cross_lesson,
            quota_padding_count=0,
            uncertain_fact_count=uncertain_fact_count,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _fingerprint(
        evidence: list[LessonEvidence], assessment: AssessmentDraft
    ) -> str:
        payload = {
            "lessons": sorted(
                (lesson.title, sorted(lesson.fact_ids)) for lesson in evidence
            ),
            "questions": sorted(
                (question.fact_id, question.lesson_id, question.kind)
                for question in assessment.questions
            ),
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
