"""Value objects for provider-backed V2 simulations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import AssessmentDraft, CourseDraft, EvidenceCourseResult, StageTiming


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    model: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    payload: dict[str, Any]
    model: str
    duration_seconds: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalMeasurement:
    lesson_id: str
    recall_at_k: float
    k: int
    top_fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderBackedResult:
    evidence_result: EvidenceCourseResult
    realized_course: CourseDraft
    realized_assessment: AssessmentDraft
    embedding_model: str
    embedding_dimension: int
    chat_model: str
    retrieval: tuple[RetrievalMeasurement, ...]
    provider_fallback_count: int
    validation_errors: tuple[str, ...]
    chat_attempt_count: int
    prompt_tokens: int
    completion_tokens: int
    timings: tuple[StageTiming, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
