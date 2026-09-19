"""A parallel evidence-first engine; it is intentionally not wired to production."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
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
from .quality import is_acceptable_title

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

# Narrative sizing is content-derived: a lesson should contain enough material
# for a coherent learning unit, rather than mirror the parser's internal fact
# partitions.  These densities intentionally remain softer than the hard
# per-prompt partition limits used to protect provider requests.
_NARRATIVE_WORDS_PER_LESSON = 550
_NARRATIVE_UNIT_WORDS = 300
_NARRATIVE_UNIT_FACTS = 10
_NARRATIVE_MAX_FACTS_PER_LESSON = 20
_LOW_VALUE_SPREADSHEET_ASSESSMENT_RE = re.compile(
    r"^(?:коллекция|тип|вид|категория|наименование|название|код|артикул|sku|"
    r"ширина|высота|глубина|размер(?:ы)?|габарит(?:ы)?|вес)$",
    re.IGNORECASE,
)


def _norm(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _trim_narrative_title(value: str, *, max_words: int = 10) -> str:
    words = value.split()
    trimmed = words[:max_words]
    connectors = {"и", "или", "а", "по", "на", "в", "к", "о", "об", "для", "их"}
    while len(trimmed) > 1 and trimmed[-1].casefold().strip(".,:;—–") in connectors:
        trimmed.pop()
    return " ".join(trimmed).rstrip(" .,:;—–")


def _concise_narrative_title(value: str) -> str:
    """Turn verbose regulatory headings into stable learner-facing topics."""

    title = re.sub(r"^\s*\d+[.)]?\s*", "", value).strip(" .,:;—–")
    normalized = _norm(title)
    patterns: tuple[tuple[tuple[str, ...], str], ...] = (
        (("общие положения",), "Общие положения"),
        (("подачи заявления", "рассмотрения"), "Подача и рассмотрение заявления"),
        (("заключения договора",), "Заключение договора о микрокредите"),
        (("предельные величины", "ставок"), "Предельные ставки вознаграждения"),
        (("выплаты вознаграждения",), "Выплата вознаграждения"),
        (("требования", "обеспечению"), "Требования к обеспечению"),
        (("годовой эффективной ставки",), "Расчёт годовой эффективной ставки"),
        (("методы погашения",), "Методы погашения микрокредита"),
        (("рассмотрения обращений",), "Рассмотрение обращений клиентов"),
        (("права и обязанности", "ответственность"), "Права, обязанности и ответственность сторон"),
        (("конфиденциальность",), "Конфиденциальность"),
        (("заключительные положения",), "Заключительные положения"),
    )
    for markers, concise in patterns:
        if all(marker in normalized for marker in markers):
            return concise
    return _trim_narrative_title(title, max_words=8)


def _is_major_narrative_section(title: str, *, fact_count: int, word_count: int) -> bool:
    letters = "".join(character for character in title if character.isalpha())
    return bool(letters and letters.isupper()) or fact_count > 10 or word_count >= 250


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
        if current and (
            current_words + fact_words > _NARRATIVE_UNIT_WORDS
            or len(current) >= _NARRATIVE_UNIT_FACTS
        ):
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


def _bounded_spreadsheet_plan(
    evidence: list[LessonEvidence],
    *,
    teachable_units: int,
) -> list[LessonEvidence]:
    """Merge source-owned units without dropping facts when the passport sets a ceiling."""

    if teachable_units <= 0 or len(evidence) <= teachable_units:
        return evidence
    by_subject: dict[tuple[str, str], list[LessonEvidence]] = defaultdict(list)
    for lesson in evidence:
        subject = lesson.title.split(":", 1)[0].strip()
        by_subject[(lesson.module_title, subject)].append(lesson)

    subject_units: list[LessonEvidence] = []
    for (module, subject), lessons in by_subject.items():
        if len(lessons) == 1:
            subject_units.append(lessons[0])
            continue
        fact_ids = tuple(dict.fromkeys(fact_id for item in lessons for fact_id in item.fact_ids))
        subject_units.append(
            LessonEvidence(
                lesson_id=_stable_id("lesson", module, subject, *fact_ids),
                module_title=module,
                title=subject,
                objective=f"Применять подтверждённые сведения о теме «{subject}».",
                fact_ids=fact_ids,
                supporting_fact_ids=tuple(
                    dict.fromkeys(
                        fact_id
                        for item in lessons
                        for fact_id in item.supporting_fact_ids
                    )
                ),
                source_locators=tuple(
                    dict.fromkeys(
                        locator for item in lessons for locator in item.source_locators
                    )
                ),
            )
        )

    target = min(teachable_units, len(subject_units))
    by_module: dict[str, list[LessonEvidence]] = defaultdict(list)
    for lesson in subject_units:
        by_module[lesson.module_title].append(lesson)

    grouped_units: list[tuple[str, int, int, list[LessonEvidence]]] = []
    if target >= len(by_module):
        quotas = {module: 1 for module in by_module}
        remaining = target - len(quotas)
        module_order = {module: index for index, module in enumerate(by_module)}
        while remaining > 0:
            candidates = [
                module
                for module, lessons in by_module.items()
                if quotas[module] < len(lessons)
            ]
            if not candidates:
                break
            module = max(
                candidates,
                key=lambda item: (
                    len(by_module[item]) / quotas[item],
                    -module_order[item],
                ),
            )
            quotas[module] += 1
            remaining -= 1
        for module, lessons in by_module.items():
            quota = quotas[module]
            for part_index in range(quota):
                start = math.floor(part_index * len(lessons) / quota)
                end = math.floor((part_index + 1) * len(lessons) / quota)
                grouped_units.append((module, part_index, quota, lessons[start:end]))
    else:
        for part_index in range(target):
            start = math.floor(part_index * len(subject_units) / target)
            end = math.floor((part_index + 1) * len(subject_units) / target)
            group = subject_units[start:end]
            modules = list(dict.fromkeys(item.module_title for item in group))
            grouped_units.append((" и ".join(modules), part_index, target, group))

    bounded: list[LessonEvidence] = []
    for module, part_index, quota, group in grouped_units:
        fact_ids = tuple(dict.fromkeys(fact_id for item in group for fact_id in item.fact_ids))
        supporting_fact_ids = tuple(
            dict.fromkeys(
                fact_id
                for item in group
                for fact_id in item.supporting_fact_ids
            )
        )
        source_locators = tuple(
            dict.fromkeys(locator for item in group for locator in item.source_locators)
        )
        subjects = list(dict.fromkeys(item.title.split(":", 1)[0].strip() for item in group))
        if len(subjects) == 1:
            title = subjects[0]
        elif (
            len(subjects) == 2
            and len(" и ".join(subjects)) <= 96
            and len(" и ".join(subjects).split()) <= 10
        ):
            title = " и ".join(subjects)
        else:
            title = (
                f"{module}: часть {part_index + 1}"
                if quota > 1
                else f"{module}: основные сведения"
            )
        objective_subjects = ", ".join(subjects[:6])
        objective = f"Применять подтверждённые сведения: {objective_subjects}."
        bounded.append(
            LessonEvidence(
                lesson_id=_stable_id("lesson", module, str(part_index + 1), *fact_ids),
                module_title=module,
                title=title,
                objective=objective,
                fact_ids=fact_ids,
                supporting_fact_ids=supporting_fact_ids,
                source_locators=source_locators,
            )
        )
    return bounded


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
    r"(?:(?:рабочих|календарных)\s+)?"
    r"(?:минут(?:а|ы)?|день|дня|дней|месяц(?:а|ев)?|час(?:а|ов)?))",
    re.IGNORECASE,
)
_DURATION_ANY_RE = re.compile(
    r"(?P<answer>\d+(?:[.,]\d+)?\s+"
    r"(?:(?:рабочих|календарных)\s+)?"
    r"(?:минут(?:а|ы)?|день|дня|дней|месяц(?:а|ев)?|час(?:а|ов)?))",
    re.IGNORECASE,
)
_PERCENT_VALUE_RE = re.compile(r"(?P<answer>\d+(?:[.,]\d+)?\s*%)")


def _extract_assessable_value(fact: SourceFact) -> str | None:
    if fact.confidence < 0.8 or fact.uncertainty not in {"", "local_ocr"}:
        return None
    if "Условие" in fact.value and "Описание" in fact.value:
        return None
    patterns = (_DURATION_VALUE_RE, _DURATION_ANY_RE, _PERCENT_VALUE_RE)
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
    elif "минут" in normalized:
        unit = "minute"
    elif "%" in normalized:
        unit = "percent"
    else:
        unit = normalized
    return f"{number}:{unit}"


def _answer_unit_family(value: str) -> str:
    normalized = _norm(value)
    if re.search(r"\b(?:минут|час)", normalized):
        return "short-duration"
    if re.search(r"\b(?:ден|дн|месяц)", normalized):
        return "calendar-duration"
    if "%" in normalized or "процент" in normalized:
        return "percent"
    return "other"


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


def _spreadsheet_question_prompt(fact: SourceFact) -> str:
    attribute = _norm(fact.attribute)
    subject = fact.subject.strip()
    if "комнат" in attribute or "помещен" in attribute:
        return f"Для каких помещений подходит «{subject}»?"
    if "материал корпуса" in attribute:
        return f"Из какого материала выполнен корпус «{subject}»?"
    if "материал фасада" in attribute:
        return f"Из какого материала выполнен фасад «{subject}»?"
    if "цвет" in attribute or "отделк" in attribute:
        return f"Какие цвета или варианты отделки доступны для «{subject}»?"
    if "стиль" in attribute:
        return f"Какой стиль характерен для «{subject}»?"
    if "основн" in attribute and "иде" in attribute:
        return f"Какова основная идея коллекции «{subject}»?"
    if "что это" in attribute or "описан" in attribute:
        return f"Какое описание точнее всего характеризует «{subject}»?"
    if "что сказать" in attribute or "покупател" in attribute:
        return f"Как лучше представить покупателю коллекцию «{subject}»?"
    if "отлич" in attribute:
        return f"Чем «{subject}» отличается от сопоставимых коллекций?"
    if "особенност" in attribute:
        detail = re.sub(
            r"^\s*особенности?\s*",
            "",
            fact.attribute,
            flags=re.IGNORECASE,
        ).strip()
        if detail:
            return f"Какие особенности {detail} характерны для «{subject}»?"
        return f"Какая особенность лучше всего характеризует «{subject}»?"
    if "преимуществ" in attribute:
        return f"Какое главное преимущество лучше всего характеризует «{subject}»?"
    if "направляющ" in attribute:
        return f"Какие направляющие используются в коллекции «{subject}»?"
    if "ширин" in attribute:
        return f"Какова ширина «{subject}»?"
    if "высот" in attribute:
        return f"Какова высота «{subject}»?"
    if "глубин" in attribute:
        return f"Какова глубина «{subject}»?"
    if "размер" in attribute or "габарит" in attribute:
        return f"Какие размеры указаны для «{subject}»?"
    if "где использ" in attribute or "применение" in attribute:
        return f"Где используется «{subject}»?"
    if "решен" in attribute:
        return f"Какое решение следует применить в ситуации «{subject}»?"
    if "почему" in attribute or "обоснован" in attribute:
        return f"Почему для ситуации «{subject}» рекомендуется указанное решение?"
    if "код" in attribute or "артикул" in attribute:
        return f"Какой код или артикул указан для «{subject}»?"
    if "количеств" in attribute:
        return f"Какое количество указано для «{subject}»?"
    clean_attribute = fact.attribute.strip()
    return f"Какое значение параметра «{clean_attribute}» установлено для «{subject}»?"


def _answer_is_exposed_by_subject(fact: SourceFact) -> bool:
    """Reject recall questions whose identifier already contains the answer."""

    answer = _norm(fact.value).strip(" .,:;()[]{}«»\"'")
    subject = _norm(fact.subject)
    if len(answer) < 2 or len(answer.split()) > 5:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(answer)}(?!\w)", subject))


def _is_low_value_spreadsheet_assessment_fact(fact: SourceFact) -> bool:
    """Keep catalog identifiers/specifications as lesson facts, not quiz filler."""

    attribute = _norm(fact.attribute).strip(" .,:;()[]{}«»\"'")
    return bool(_LOW_VALUE_SPREADSHEET_ASSESSMENT_RE.fullmatch(attribute))


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
            [
                fact
                for section in primary_sections
                for fact in section.facts
                if fact.confidence >= 0.8 and fact.uncertainty in {"", "local_ocr"}
            ]
        )
        supporting, supporting_duplicates = _deduplicate_facts(
            [
                fact
                for section in supporting_sections
                for fact in section.facts
                if fact.confidence >= 0.8 and fact.uncertainty in {"", "local_ocr"}
            ]
        )
        timings.append(StageTiming(stage="document_plan", seconds=perf_counter() - started))

        started = perf_counter()
        evidence = self._build_evidence_plan(
            document.kind,
            primary_sections,
            admitted,
            supporting,
        )
        if document.kind == "spreadsheet":
            evidence = _bounded_spreadsheet_plan(
                evidence,
                teachable_units=document.teachable_units,
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
        lesson_count = len(evidence)
        evaluation = replace(
            evaluation,
            quota_padding_count=(
                max(0, lesson_count - document.teachable_units)
                if document.kind == "spreadsheet" and document.teachable_units > 0
                else 0
            ),
            supporting_lesson_share=(
                sum(bool(lesson.supporting_fact_ids) for lesson in evidence) / lesson_count
                if lesson_count
                else 0.0
            ),
            capacity_ratio=(
                lesson_count / document.teachable_units
                if document.kind == "spreadsheet" and document.teachable_units > 0
                else 0.0
            ),
            generated_duration_minutes=sum(lesson.duration_minutes for lesson in course.lessons),
            invalid_title_count=sum(
                not is_acceptable_title(lesson.title) for lesson in course.lessons
            ),
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
            teachable_units=document.teachable_units,
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
        if kind == "narrative":
            return EvidenceCourseEngine._build_narrative_evidence_plan(sections, admitted)
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
            ordered = sorted(
                facts,
                key=lambda item: (_bucket_name(item.attribute), _norm(item.attribute)),
            )
            partitions = _partition_subject_facts(ordered)
            for index, (bucket, selected) in enumerate(partitions, start=1):
                title = subject if len(partitions) == 1 else f"{subject}: {bucket or f'часть {index}'}"
                lesson_id = _stable_id("lesson", module, subject, bucket, str(index))
                attributes = ", ".join(dict.fromkeys(fact.attribute for fact in selected))
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
    def _build_narrative_evidence_plan(
        sections: list[SourceSection], admitted: list[SourceFact]
    ) -> list[LessonEvidence]:
        admitted_by_key = {_fact_key(fact): fact for fact in admitted}
        section_units: list[tuple[str, list[list[SourceFact]]]] = []
        seen_fact_ids: set[str] = set()
        for section in sections:
            facts: list[SourceFact] = []
            for fact in section.facts:
                admitted_fact = admitted_by_key.get(_fact_key(fact))
                if admitted_fact is None or admitted_fact.fact_id in seen_fact_ids:
                    continue
                seen_fact_ids.add(admitted_fact.fact_id)
                facts.append(admitted_fact)
            partitions = [partition for _bucket, partition in _partition_narrative_facts(facts)]
            if partitions:
                section_units.append((section.title, partitions))
        if not section_units:
            return []

        groups: list[list[tuple[str, list[SourceFact], int]]] = []
        group_is_major: list[bool] = []
        for section_title, partitions in section_units:
            total_words = sum(
                len(fact.value.split()) for partition in partitions for fact in partition
            )
            total_facts = sum(len(partition) for partition in partitions)
            is_major = _is_major_narrative_section(
                section_title,
                fact_count=total_facts,
                word_count=total_words,
            )
            group: list[tuple[str, list[SourceFact], int]] = []
            group_words = 0
            group_facts = 0
            for partition_index, partition in enumerate(partitions, start=1):
                unit_words = sum(len(fact.value.split()) for fact in partition)
                unit_facts = len(partition)
                if group and (
                    group_words + unit_words > _NARRATIVE_WORDS_PER_LESSON
                    or group_facts + unit_facts > _NARRATIVE_MAX_FACTS_PER_LESSON
                ):
                    groups.append(group)
                    group_is_major.append(is_major)
                    group = []
                    group_words = 0
                    group_facts = 0
                group.append((section_title, partition, partition_index))
                group_words += unit_words
                group_facts += unit_facts
            if group:
                groups.append(group)
                group_is_major.append(is_major)

        # A one-clause cover page is context, not a standalone learning topic.
        # Merge only that leading fragment with the first substantive section;
        # all numbered legal sections retain their own lesson boundary.
        if len(groups) >= 2:
            first_title = _norm(groups[0][0][0])
            first_facts = sum(len(item[1]) for item in groups[0])
            merged_facts = first_facts + sum(len(item[1]) for item in groups[1])
            merged_words = sum(
                len(fact.value.split())
                for item in [*groups[0], *groups[1]]
                for fact in item[1]
            )
            if (
                first_title in {"вводная часть", "введение"}
                and first_facts <= 2
                and merged_facts <= _NARRATIVE_MAX_FACTS_PER_LESSON
                and merged_words <= _NARRATIVE_WORDS_PER_LESSON
            ):
                groups[0] = [*groups[0], *groups.pop(1)]
                group_is_major.pop(1)

        base_titles: list[str] = []
        cleaned_group_titles: list[list[str]] = []
        for group in groups:
            section_titles = list(dict.fromkeys(title for title, _, _ in group))
            cleaned_titles = [_concise_narrative_title(title) for title in section_titles]
            cleaned_group_titles.append(cleaned_titles)
            if len(cleaned_titles) == 1:
                base_title = cleaned_titles[0]
            elif len(cleaned_titles) == 2:
                base_title = f"{cleaned_titles[0]} и {cleaned_titles[1]}"
            else:
                base_title = f"{cleaned_titles[0]} — {cleaned_titles[-1]}"
            base_titles.append(_trim_narrative_title(base_title, max_words=10))
        base_title_counts = Counter(base_titles)
        base_title_occurrences: Counter[str] = Counter()

        evidence: list[LessonEvidence] = []
        for group_index, (group, cleaned_titles, base_title) in enumerate(
            zip(groups, cleaned_group_titles, base_titles, strict=True), start=1
        ):
            selected = [fact for _, facts, _ in group for fact in facts]
            section_titles = list(dict.fromkeys(title for title, _, _ in group))
            base_title_occurrences[base_title] += 1
            if base_title_counts[base_title] > 1:
                title = (
                    f"{_trim_narrative_title(base_title, max_words=7)}: "
                    f"часть {base_title_occurrences[base_title]}"
                )
            else:
                title = base_title
            covered = ", ".join(f"«{item}»" for item in cleaned_titles)
            lesson_id = _stable_id("lesson", *section_titles, str(group_index))
            evidence.append(
                LessonEvidence(
                    lesson_id=lesson_id,
                    module_title="Основной материал",
                    title=f"{title[:1].upper()}{title[1:]}",
                    objective=f"Применять правила разделов {covered}.",
                    fact_ids=tuple(fact.fact_id for fact in selected),
                    supporting_fact_ids=(),
                    source_locators=tuple(fact.source_locator for fact in selected),
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
        tested_attribute_answers: set[tuple[str, str]] = set()
        for lesson in evidence:
            candidates = [
                by_id[fact_id]
                for fact_id in lesson.fact_ids
                if not _answer_is_exposed_by_subject(by_id[fact_id])
                and not _is_low_value_spreadsheet_assessment_fact(by_id[fact_id])
            ]
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
                attribute_answer = (_norm(fact.attribute), _norm(fact.value))
                if attribute_answer in tested_attribute_answers:
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
                            prompt=_spreadsheet_question_prompt(fact),
                            options=tuple(value for value, _ in option_pairs),
                            correct_answer=fact.value,
                            explanation=f"Подтверждено источником: {fact.value}",
                            fact_id=fact.fact_id,
                            distractor_fact_ids=tuple(source_id for _, source_id in option_pairs if source_id != fact.fact_id),
                        )
                    )
                    tested_attribute_answers.add(attribute_answer)
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
        peers: dict[tuple[str, str], list[tuple[SourceFact, str]]] = defaultdict(list)
        for fact in facts:
            answer = answer_by_fact.get(fact.fact_id)
            if answer:
                peers[(_norm(fact.attribute), _answer_unit_family(answer))].append(
                    (fact, answer)
                )

        questions: list[QuestionDraft] = []
        seen_prompts: set[str] = set()
        tested_answer_keys: set[tuple[str, str]] = set()
        for lesson in evidence:
            for fact_id in lesson.fact_ids:
                if len([q for q in questions if q.lesson_id == lesson.lesson_id]) >= 3:
                    break
                fact = by_id[fact_id]
                answer = answer_by_fact.get(fact_id)
                if not answer:
                    continue
                tested_answer_key = (_norm(fact.attribute), _answer_semantic_key(answer))
                if tested_answer_key in tested_answer_keys:
                    continue
                unique_answers: dict[str, tuple[SourceFact, str]] = {}
                peer_key = (_norm(fact.attribute), _answer_unit_family(answer))
                for peer, peer_answer in peers[peer_key]:
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
                tested_answer_keys.add(tested_answer_key)

            # Do not pad a lesson with a generic section-membership question.
            # Narrative questions are emitted only when the source exposes one
            # exact assessable value and at least two distinct sourced peers.
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
