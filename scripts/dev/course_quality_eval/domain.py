from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

JsonObject = dict[str, Any]
Decision = Literal["pass", "review", "reject"]


class PrivacyViolation(ValueError):
    """Raised before an external evaluator sees content with obvious PII."""


@dataclass(frozen=True)
class ArtifactIdentity:
    path: str
    sha256: str
    source_sha256: str | None
    course_title: str


@dataclass(frozen=True)
class LessonArtifact:
    id: str
    title: str
    objectives: tuple[str, ...]
    content: str
    source: str


@dataclass(frozen=True)
class QuestionArtifact:
    id: str
    lesson_id: str
    lesson_title: str
    text: str
    options: tuple[str, ...]
    correct_indexes: tuple[int, ...]
    explanation: str
    source: str


@dataclass(frozen=True)
class CourseArtifact:
    identity: ArtifactIdentity
    lessons: tuple[LessonArtifact, ...]
    questions: tuple[QuestionArtifact, ...]
    raw_path: Path = field(repr=False, compare=False)


@dataclass(frozen=True)
class EvaluationRequest:
    model: str
    state: JsonObject
    questions: dict[str, JsonObject]


@dataclass(frozen=True)
class AdapterResult:
    model: str
    answers: dict[str, JsonObject]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cached: bool = False


class Evaluator(Protocol):
    def evaluate(self, request: EvaluationRequest) -> AdapterResult: ...


@dataclass(frozen=True)
class Rubric:
    version: str
    model: str
    enforcement: Literal["report_only", "calibrated"]
    lesson_questions: dict[str, JsonObject]
    question_questions: dict[str, JsonObject]


@dataclass(frozen=True)
class EvaluationFinding:
    target_id: str
    title: str
    decision: Decision
    reasons: tuple[str, ...]
    signals: dict[str, float]
    model: str
    latency_ms: int


@dataclass(frozen=True)
class UsageSummary:
    input_tokens: int
    output_tokens: int
    calls: int
    live_calls: int
    cache_hits: int
    provider_latency_ms: int
    evaluation_wall_ms: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class EvaluationReport:
    schema_version: int
    generated_at: str
    rubric_version: str
    requested_model: str
    resolved_models: tuple[str, ...]
    enforcement: str
    decision: Decision
    artifact: ArtifactIdentity
    lessons: tuple[EvaluationFinding, ...]
    questions: tuple[EvaluationFinding, ...]
    usage: UsageSummary
