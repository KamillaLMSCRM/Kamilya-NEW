"""Versioned question source evidence; consistency is not source approval."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupportSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_fact_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)
    source_revision: str = Field(min_length=1, max_length=256)
    source_locator: str = Field(min_length=1, max_length=2048)
    quote: str = Field(min_length=1, max_length=4000)
    quote_start: int = Field(ge=0)
    quote_end: int = Field(gt=0)
    role: Literal["condition", "exception", "timing", "scope"]

    @model_validator(mode="after")
    def valid_span(self) -> SupportSourceEvidence:
        if self.quote_end - self.quote_start != len(self.quote):
            raise ValueError("question_evidence_invalid_span")
        return self


class QuestionSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    policy: Literal["question-support-evidence-v1"]
    question_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supporting: list[SupportSourceEvidence] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_support(self) -> QuestionSourceEvidence:
        identities = [(item.source_fact_id, item.source_id, item.source_revision,
                       item.source_locator, item.quote_start, item.quote_end, item.role)
                      for item in self.supporting]
        if len(set(identities)) != len(identities):
            raise ValueError("question_evidence_duplicate_support")
        return self


def question_content_sha256(
    *, text: str, question_type: str, explanation: str | None, choices: list[dict[str, Any]]
) -> str:
    """Bind exact learner text, explanations, ordered options and key."""
    payload = {
        "text": text,
        "type": question_type,
        "explanation": explanation,
        "choices": [{"text": row["text"], "is_correct": row["is_correct"]} for row in choices],
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
