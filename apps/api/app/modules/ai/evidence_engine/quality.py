"""Minimum autonomous publishability contract for provider-backed V2 drafts."""

from __future__ import annotations

import re

from app.modules.ai.assessment import distractor_repeats_correct_attribute_answer
from app.modules.ai.lesson_quality import has_unprofessional_learner_language

from .models import AssessmentDraft, CourseDraft, EvidenceCourseResult, QuestionDraft
from .provider_models import GroundedBlock, PublishabilityReport

EVIDENCE_QUALITY_POLICY_VERSION = "evidence-v2-quality-v3"

_GENERIC_QUESTION_RE = re.compile(
    r"(?:о\s+ч[её]м\s+(?:этот\s+)?(?:урок|курс|раздел|модуль)|"
    r"какое\s+(?:правило|утверждение)\s+относится\s+к\s+"
    r"(?:разделу|уроку|курсу|модулю)|"
    r"что\s+(?:именно\s+)?(?:указано|разбер[её]м|рассматривается)\s+"
    r"(?:в\s+этом\s+уроке|согласно\s+(?:заголовку|материалу))|"
    r"что\s+в\s+материал(?:е|ах)\s+(?:этого\s+)?урока\s+указано\b|"
    r"что\s+верно\s+в\s+отношении\s+[«\"].+?[»\"]\s+"
    r"у\s+объект\w*\s+[«\"])",
    re.IGNORECASE,
)
_INTERNAL_GENERATION_INSTRUCTION_RE = re.compile(
    r"(?:неверн\w*\s+вариант\w*\s+должн\w*\s+быть\s+правдоподобн\w*|"
    r"вопрос\s+не\s+должен\s+содержать\s+подсказок|"
    r"incorrect\s+options?\s+(?:must|should)\s+be\s+plausible|"
    r"question\s+(?:must|should)\s+not\s+contain\s+(?:hints?|clues?))",
    re.IGNORECASE,
)
_OCR_ARTIFACT_RE = re.compile(
    r"\[UNREADABLE(?:\\?_[A-Z]+)*\]|\(\)\s*\(\)|\ufffd|(?:\?{4,})|"
    r"\bвидна\s+жительство\b|"
    r'\b\d{1,3}\.\s*[%("]\s*(?=(?:паспорт|удостоверение|вид)\b)|'
    r"(?:^|[.;:]\s+)[%*]\s+(?=(?:паспорт|удостоверение|вид)\b)",
    re.IGNORECASE,
)
_TRUNCATED_ABBREVIATION_RE = re.compile(
    r"(?:^|[.!?]\s+)др\.\s*\)\s+[А-ЯЁ]",
    re.IGNORECASE,
)
_INCOMPLETE_ANSWER_TAIL_RE = re.compile(
    r"(?:\b(?:следующим|таким)\s+образом|"
    r"\b(?:включает|содержит)\s+(?:следующее|следующие)|"
    r"\bas\s+follows|\bthe\s+following)\s*[:;,-]?\s*$",
    re.IGNORECASE,
)
MAX_ASSESSMENT_ANSWER_CHARS = 240
_TITLE_START_RE = re.compile(r"^(?:после|в\s+случае|к\s+|при\s+|из\s+)", re.IGNORECASE)
_MATERIAL_QUESTION_RE = re.compile(
    r"(?:из\s+как(?:ого\s+материала|их\s+материалов)|"
    r"как(?:ой\s+материал|ие\s+материалы)|"
    r"what\s+materials?|which\s+materials?|what\s+is\b[^?]{0,80}\bmade\s+(?:of|from))",
    re.IGNORECASE,
)
_MATERIAL_FAMILY_RE = re.compile(
    r"\b(?:лдсп|лхдф|мдф|дерев\w*|металл\w*|стал\w*|алюмин\w*|"
    r"пластик\w*|стекл\w*|фанер\w*|ткан\w*|кож\w*|хлоп\w*|"
    r"полиэстер\w*|chipboard|particleboard|mdf|hdf|wood\w*|metal\w*|"
    r"steel|alumin\w*|plastic\w*|glass|plywood|fabric\w*|leather|cotton|polyester)\b",
    re.IGNORECASE,
)


def contains_ocr_artifact(value: str) -> bool:
    if _OCR_ARTIFACT_RE.search(value):
        return True
    for match in _TRUNCATED_ABBREVIATION_RE.finditer(value):
        prefix = value[:match.start()]
        # ``и. др. )`` is noisy punctuation inside a complete parenthetical,
        # not the observed detached OCR tail ``. др. ) Ломбарда``.
        if prefix.rfind("(") <= prefix.rfind(")"):
            return True
    return False


def is_generic_question(value: str) -> bool:
    return bool(_GENERIC_QUESTION_RE.search(value))


def contains_internal_generation_instruction(value: str) -> bool:
    """Detect prompt-writing instructions that must not leak into lessons."""

    return bool(_INTERNAL_GENERATION_INSTRUCTION_RE.search(value))


def is_acceptable_title(value: str) -> bool:
    title = " ".join(value.strip().lstrip("#").split())
    words = re.findall(r"[^\W\d_]+", title, flags=re.UNICODE)
    if len(words) < 1 or len(words) > 10 or len(title) > 96:
        return False
    if contains_ocr_artifact(title) or _TITLE_START_RE.search(title):
        return False
    first = words[0].casefold().replace("ё", "е")
    if first.endswith(("ать", "ять", "ить")):
        return False
    return not any(word.casefold().endswith(("ется", "ются")) for word in words)


def question_has_ambiguous_options(question: QuestionDraft) -> bool:
    correct = " ".join(question.correct_answer.casefold().replace("ё", "е").split())
    if len(correct) >= 3 and any(
        option != question.correct_answer
        and (
            bool(
                re.search(
                    rf"(?<!\w){re.escape(correct)}(?!\w)",
                    " ".join(option.casefold().replace("ё", "е").split()),
                )
            )
            or bool(
                re.search(
                    rf"(?<!\w){re.escape(' '.join(option.casefold().replace('ё', 'е').split()))}(?!\w)",
                    correct,
                )
            )
        )
        for option in question.options
    ):
        return True
    if _MATERIAL_QUESTION_RE.search(question.prompt):
        correct_materials = {
            match.group(0).casefold()
            for match in _MATERIAL_FAMILY_RE.finditer(question.correct_answer)
        }
        if correct_materials and any(
            option != question.correct_answer
            and bool(
                correct_materials
                & {
                    match.group(0).casefold()
                    for match in _MATERIAL_FAMILY_RE.finditer(option)
                }
            )
            for option in question.options
        ):
            return True
    # The old headword heuristic equates "refuse this channel and offer a safe
    # one" with "refuse all channels". A complete blind option review supersedes
    # that approximation, not exact duplicate/containment/material checks above.
    if question.semantic_reviewed:
        return False
    return any(
        option != question.correct_answer
        and distractor_repeats_correct_attribute_answer(
            question.prompt,
            question.correct_answer,
            option,
        )
        for option in question.options
    )


def question_has_blocked_learner_language(question: QuestionDraft) -> bool:
    return any(
        has_unprofessional_learner_language(value)
        for value in (
            question.prompt,
            *question.options,
            question.explanation,
        )
    )


def question_has_incomplete_correct_answer(question: QuestionDraft) -> bool:
    """Reject an answer that promises missing steps instead of answering."""

    return _INCOMPLETE_ANSWER_TAIL_RE.search(question.correct_answer.strip()) is not None


def filter_acceptable_questions(questions: list[QuestionDraft]) -> list[QuestionDraft]:
    """Delete deterministically invalid questions without quota padding."""

    return [
        question
        for question in questions
        if not is_generic_question(question.prompt)
        and len(question.correct_answer.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
        and not question_has_incomplete_correct_answer(question)
        and not question_has_ambiguous_options(question)
        and not question_has_blocked_learner_language(question)
    ]


def evaluate_plan_preflight(result: EvidenceCourseResult) -> tuple[str, ...]:
    """Reject deterministic plan defects before any external provider call."""

    reasons: list[str] = []
    if any(not is_acceptable_title(lesson.title) for lesson in result.course.lessons):
        reasons.append("invalid_lesson_titles")
    planned = [fact_id for lesson in result.evidence_plan for fact_id in lesson.fact_ids]
    admitted = {fact.fact_id for fact in result.admitted_facts}
    if len(planned) != len(set(planned)):
        reasons.append("duplicate_planned_fact_ids")
    if set(planned) != admitted:
        reasons.append("incomplete_planned_fact_coverage")
    if (
        result.document_plan.kind == "spreadsheet"
        and result.document_plan.teachable_units > 0
        and len(result.evidence_plan) > result.document_plan.teachable_units
    ):
        reasons.append("lesson_capacity_exceeded")
    return tuple(reasons)


def evaluate_publishability(
    *,
    course: CourseDraft,
    assessment: AssessmentDraft,
    blocks: tuple[GroundedBlock, ...],
    planned_fact_ids: set[str],
    provider_fallback_count: int,
    max_lesson_words: int = 650,
) -> PublishabilityReport:
    covered = {fact_id for block in blocks for fact_id in block.fact_ids}
    coverage = len(covered & planned_fact_ids) / len(planned_fact_ids) if planned_fact_ids else 1.0
    prompts = [" ".join(question.prompt.casefold().split()) for question in assessment.questions]
    generic_count = sum(is_generic_question(question.prompt) for question in assessment.questions)
    duplicate_count = len(prompts) - len(set(prompts))
    ocr_count = sum(
        contains_ocr_artifact(value)
        for value in (
            *(lesson.title for lesson in course.lessons),
            *(lesson.content for lesson in course.lessons),
            *(question.prompt for question in assessment.questions),
            *(option for question in assessment.questions for option in question.options),
            *(question.explanation for question in assessment.questions),
        )
    )
    overlong_answers = sum(
        len(question.correct_answer.strip()) > MAX_ASSESSMENT_ANSWER_CHARS
        for question in assessment.questions
    )
    invalid_titles = sum(not is_acceptable_title(lesson.title) for lesson in course.lessons)
    overlong = sum(
        len(re.findall(r"\w+", lesson.content, flags=re.UNICODE)) > max_lesson_words
        for lesson in course.lessons
    )
    blocked_language = any(
        has_unprofessional_learner_language(value)
        for value in (
            course.title,
            course.description,
            *(lesson.title for lesson in course.lessons),
            *(lesson.objective for lesson in course.lessons),
            *(lesson.content for lesson in course.lessons),
            *(question.prompt for question in assessment.questions),
            *(option for question in assessment.questions for option in question.options),
            *(question.explanation for question in assessment.questions),
        )
    )
    ambiguous_options = any(
        question_has_ambiguous_options(question) for question in assessment.questions
    )
    reasons: list[str] = []
    if coverage < 1.0:
        reasons.append("incomplete_fact_coverage")
    # A fallback is an observability signal, not a content defect. Grounding,
    # coverage and visible quality are evaluated independently below.
    if generic_count:
        reasons.append("generic_questions")
    if duplicate_count:
        reasons.append("duplicate_questions")
    if ocr_count:
        reasons.append("visible_ocr_artifacts")
    if overlong_answers:
        reasons.append("overlong_correct_answers")
    if invalid_titles:
        reasons.append("invalid_lesson_titles")
    if overlong:
        reasons.append("overlong_lessons")
    if blocked_language:
        reasons.append("unprofessional_learner_language")
    if ambiguous_options:
        reasons.append("ambiguous_question_options")
    return PublishabilityReport(
        publishable=not reasons,
        reasons=tuple(reasons),
        fact_coverage_ratio=coverage,
        generic_question_count=generic_count,
        duplicate_question_count=duplicate_count,
        ocr_artifact_count=ocr_count,
        invalid_title_count=invalid_titles,
        overlong_lesson_count=overlong,
    )
