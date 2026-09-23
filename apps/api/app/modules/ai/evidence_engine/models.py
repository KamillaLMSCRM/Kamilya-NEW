"""Value objects for the isolated evidence-first course-generation experiment."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

SectionRole = Literal["primary", "supporting"]
SourceKind = Literal["spreadsheet", "narrative"]


def is_tabular_locator(locator: str) -> bool:
    """Recognize worksheet provenance in either supported source adapter."""
    fields = {
        key for item in locator.split(";")
        for key, separator, _value in (item.partition("="),)
        if separator
    }
    return "sheet" in fields or {"row", "column"} <= fields


QuestionKind = Literal["single_choice", "true_false"]
AssessmentAxisKind = Literal["attribute", "numeric_value", "rule_value"]
DistractorSourceRelation = Literal[
    "same_axis",
    "same_attribute_other_subject",
    "other_function_or_attribute",
]


@dataclass(frozen=True, slots=True)
class CourseIntent:
    purpose: str = ""
    audience: str = ""
    emphasis: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceFact:
    fact_id: str
    subject: str
    attribute: str
    value: str
    source_locator: str
    confidence: float = 1.0
    uncertainty: str = ""


@dataclass(frozen=True, slots=True)
class SourceSection:
    section_id: str
    title: str
    role: SectionRole
    facts: tuple[SourceFact, ...]


@dataclass(frozen=True, slots=True)
class SourceDocument:
    source_id: str
    title: str
    kind: SourceKind
    sections: tuple[SourceSection, ...]
    source_sha256: str = ""
    teachable_units: int = 0


@dataclass(frozen=True, slots=True)
class DocumentPlan:
    source_id: str
    source_sha256: str
    kind: SourceKind
    primary_sections: tuple[str, ...]
    supporting_sections: tuple[str, ...]
    admitted_fact_count: int
    supporting_fact_count: int
    duplicate_fact_count: int
    teachable_units: int = 0


@dataclass(frozen=True, slots=True)
class LessonEvidence:
    lesson_id: str
    module_title: str
    title: str
    objective: str
    fact_ids: tuple[str, ...]
    supporting_fact_ids: tuple[str, ...]
    source_locators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LessonDraft:
    lesson_id: str
    module_title: str
    title: str
    objective: str
    content: str
    fact_ids: tuple[str, ...]
    supporting_fact_ids: tuple[str, ...]
    duration_minutes: int


@dataclass(frozen=True, slots=True)
class CourseDraft:
    title: str
    description: str
    lessons: tuple[LessonDraft, ...]


@dataclass(frozen=True, slots=True)
class QuestionDraft:
    question_id: str
    lesson_id: str
    kind: QuestionKind
    prompt: str
    options: tuple[str, ...]
    correct_answer: str
    explanation: str
    fact_id: str
    distractor_fact_ids: tuple[str, ...] = ()
    evidence_fact_ids: tuple[str, ...] = ()
    source_quote: str = ""
    semantic_block_id: str = ""
    semantic_reviewed: bool = False
    repaired_prompt: str = ""


@dataclass(frozen=True, slots=True)
class AssessmentAxis:
    """Immutable source-owned knowledge target for one assessment question."""

    axis_id: str
    lesson_id: str
    semantic_block_id: str
    primary_fact_id: str
    evidence_fact_ids: tuple[str, ...]
    subject: str
    attribute: str
    required_prompt: str
    correct_value: str
    normalized_correct_value: str
    eligible_distractor_fact_ids: tuple[str, ...]
    axis_kind: AssessmentAxisKind
    distractor_constraints: tuple[DistractorConstraint, ...] = ()


@dataclass(frozen=True, slots=True)
class DistractorConstraint:
    """Source-owned classification for a source value proposed as a distractor."""

    fact_id: str
    subject: str
    attribute: str
    value: str
    relation: DistractorSourceRelation
    attribute_anchors: tuple[str, ...] = ()
    value_anchors: tuple[str, ...] = ()
    distinctive_anchors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoredAssessment:
    """Provider-owned wording only; it has no authority over answer truth."""

    axis_id: str
    prompt: str
    distractors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssessmentDraft:
    questions: tuple[QuestionDraft, ...]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    admitted_fact_count: int
    used_fact_count: int
    coverage_ratio: float
    duplicate_fact_count: int
    duplicate_question_count: int
    unsupported_claim_count: int
    cross_lesson_question_count: int
    quota_padding_count: int
    uncertain_fact_count: int = 0
    warnings: tuple[str, ...] = ()
    supporting_lesson_share: float = 0.0
    capacity_ratio: float = 0.0
    generated_duration_minutes: int = 0
    invalid_title_count: int = 0


@dataclass(frozen=True, slots=True)
class StageTiming:
    stage: str
    seconds: float


@dataclass(frozen=True, slots=True)
class EvidenceCourseResult:
    document_plan: DocumentPlan
    admitted_facts: tuple[SourceFact, ...]
    supporting_facts: tuple[SourceFact, ...]
    evidence_plan: tuple[LessonEvidence, ...]
    course: CourseDraft
    assessment: AssessmentDraft
    evaluation: EvaluationReport
    semantic_fingerprint: str
    timings: tuple[StageTiming, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
