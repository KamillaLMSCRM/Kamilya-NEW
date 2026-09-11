"""Deterministic admission policy for generated lesson drafts.

The policy does not attempt semantic grading.  It rejects only observable
failure modes that should never reach a methodologist: source-free filler,
verbatim sentence repetition, and an implausibly thin response for a
substantive source excerpt.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?:\n+|(?<=[.!?])\s+)")
_STOP_WORDS = frozenset(
    {
        "для", "или", "как", "это", "этот", "эта", "эти", "того", "при",
        "что", "чтобы", "который", "которая", "которые", "также", "есть",
        "уже", "можно", "нужно", "будет", "быть", "его", "она", "они",
        "and", "the", "this", "that", "with", "from", "into", "your",
        "мен", "бұл", "және", "немесе", "керек", "болып",
        "урок", "уроке", "курса", "курс", "раздел", "модуль", "материал",
    }
)
_GENERIC_MARKERS = (
    "в этом уроке мы разберем",
    "в данном уроке мы разберем",
    "в этом уроке вы узнаете",
    "давайте разберем",
    "материал поможет лучше понять",
    "подведем итоги",
    "теперь вы знаете",
    "in this lesson we will",
    "this lesson will help you",
    "let us explore",
    "to summarize",
)
LESSON_QUALITY_POLICY_VERSION = "lesson-quality-v1"


def _normalize(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold().replace("ё", "е")))


def _content_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _normalize(value).split() if token not in _STOP_WORDS)


def _sentences(value: str) -> tuple[str, ...]:
    cleaned = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    return tuple(
        normalized
        for raw in _SENTENCE_RE.split(cleaned)
        for normalized in [_normalize(raw)]
        if normalized
    )


@dataclass(frozen=True, slots=True)
class LessonQualityResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    source_anchor_matches: int
    required_source_anchor_matches: int
    generic_sentence_share: float
    repeated_sentence_count: int


def evaluate_lesson_quality(
    *,
    title: str,
    content: str,
    source_chunks: Sequence[str],
) -> LessonQualityResult:
    """Evaluate one lesson against the exact excerpts supplied to its writer."""

    source_tokens = set(_content_tokens("\n".join(source_chunks)))
    # The title comes from the architect and must not make an otherwise generic
    # lesson look grounded. Source anchors must occur in the lesson body.
    content_tokens = set(_content_tokens(content))
    anchor_matches = len(source_tokens & content_tokens)
    if len(source_tokens) <= 3:
        required_matches = 1
    elif len(source_tokens) <= 8:
        required_matches = 2
    else:
        required_matches = min(5, max(3, math.ceil(len(source_tokens) * 0.08)))

    sentences = _sentences(content)
    generic_count = sum(
        any(marker in sentence for marker in _GENERIC_MARKERS)
        for sentence in sentences
    )
    generic_share = generic_count / len(sentences) if sentences else 1.0
    counts: dict[str, int] = {}
    for sentence in sentences:
        if len(sentence.split()) >= 7:
            counts[sentence] = counts.get(sentence, 0) + 1
    repeated_count = sum(count - 1 for count in counts.values() if count > 1)

    reasons: list[str] = []
    if not content.strip() or anchor_matches < required_matches:
        reasons.append("insufficient_source_anchors")
    if generic_count >= 2 and generic_share >= 0.50:
        reasons.append("generic_filler_dominates")
    if repeated_count:
        reasons.append("repeated_lesson_sentence")
    if len(source_tokens) >= 20 and len(_content_tokens(content)) < 25:
        reasons.append("lesson_too_thin_for_source")

    return LessonQualityResult(
        accepted=not reasons,
        reason_codes=tuple(reasons),
        source_anchor_matches=anchor_matches,
        required_source_anchor_matches=required_matches,
        generic_sentence_share=round(generic_share, 4),
        repeated_sentence_count=repeated_count,
    )


__all__ = [
    "LESSON_QUALITY_POLICY_VERSION",
    "LessonQualityResult",
    "evaluate_lesson_quality",
]
