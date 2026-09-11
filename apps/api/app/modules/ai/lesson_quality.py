"""Deterministic admission policy for generated lesson drafts.

The policy does not attempt semantic grading.  It rejects only observable
failure modes that should never reach a methodologist: source-free filler,
verbatim sentence repetition, and an implausibly thin response for a
substantive source excerpt.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
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
_UNSUPPORTED_RELATIONSHIP_PATTERNS = (
    re.compile(r"\b(?:прямо|напрямую)\s+связан\w*\b"),
    re.compile(r"\bоснов\w*\s+для\b"),
    re.compile(r"\bпоэтому\b.{0,100}\b(?:важно|нужно|следует|необходимо)\b"),
    re.compile(
        r"\bзначит\b.{0,140}\b(?:рабоч\w*\s+шаг\w*|важно|нужно|следует|необходимо)\b"
    ),
    re.compile(
        r"\b(?:преимуществ\w*|материал\w*|размер\w*|каталог\w*)\b.{0,120}"
        r"\b(?:определя\w*|обусловлива\w*|привод\w*|требу\w*)\b"
    ),
    re.compile(r"\b(?:directly linked|directly related|basis for)\b"),
    re.compile(r"\btherefore\b.{0,100}\b(?:must|should|need)\b"),
)
_RELATIONSHIP_OPERATOR_ROOTS = (
    "определ",
    "обуслов",
    "привод",
    "требу",
    "связан",
    "поэтому",
    "значит",
    "важно",
    "нужно",
    "следует",
    "необходимо",
    "direct",
    "link",
    "relat",
    "basis",
    "therefore",
    "must",
    "should",
    "need",
)
LESSON_QUALITY_POLICY_VERSION = "lesson-quality-v5"
_LESSON_QUALITY_EVENTS: ContextVar[
    list[tuple[str, str, tuple[str, ...], LessonQualityResult]] | None
] = ContextVar("lesson_quality_events", default=None)


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


def _relationship_claim_supported(
    pattern: re.Pattern[str],
    *,
    content: str,
    source: str,
) -> bool:
    """Require the same relationship and its local anchors in one source fragment."""
    content_fragments = tuple(
        fragment.strip()
        for fragment in re.split(r"[.!?\n]+", content)
        if pattern.search(fragment)
    )
    source_fragments = tuple(
        fragment.strip()
        for fragment in re.split(r"[.!?\n]+", source)
        if pattern.search(fragment)
    )
    for claim in content_fragments:
        claim_tokens = set(_content_tokens(claim))
        anchor_tokens = {
            token
            for token in claim_tokens
            if not any(token.startswith(root) for root in _RELATIONSHIP_OPERATOR_ROOTS)
        }
        if not any(
            anchor_tokens
            and anchor_tokens.issubset(set(_content_tokens(source_fragment)))
            for source_fragment in source_fragments
        ):
            return False
    return bool(content_fragments)


@dataclass(frozen=True, slots=True)
class LessonQualityResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    source_anchor_matches: int
    required_source_anchor_matches: int
    generic_sentence_share: float
    repeated_sentence_count: int


@contextmanager
def capture_lesson_quality_evaluations() -> Iterator[
    list[tuple[str, str, tuple[str, ...], LessonQualityResult]]
]:
    """Capture exact validator inputs only inside an explicit task context."""
    events: list[tuple[str, str, tuple[str, ...], LessonQualityResult]] = []
    token = _LESSON_QUALITY_EVENTS.set(events)
    try:
        yield events
    finally:
        _LESSON_QUALITY_EVENTS.reset(token)


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
    normalized_source_text = "\n".join(
        " ".join(line.casefold().replace("ё", "е").split())
        for chunk in source_chunks
        for line in chunk.splitlines()
    )
    normalized_content_text = "\n".join(
        " ".join(line.casefold().replace("ё", "е").split())
        for line in content.splitlines()
    )
    unsupported_relationship = any(
        pattern.search(normalized_content_text)
        and not _relationship_claim_supported(
            pattern,
            content=normalized_content_text,
            source=normalized_source_text,
        )
        for pattern in _UNSUPPORTED_RELATIONSHIP_PATTERNS
    )

    reasons: list[str] = []
    if not content.strip() or anchor_matches < required_matches:
        reasons.append("insufficient_source_anchors")
    if generic_count >= 2 and generic_share >= 0.50:
        reasons.append("generic_filler_dominates")
    if repeated_count:
        reasons.append("repeated_lesson_sentence")
    if len(source_tokens) >= 20 and len(_content_tokens(content)) < 25:
        reasons.append("lesson_too_thin_for_source")
    if unsupported_relationship:
        reasons.append("unsupported_relationship_claim")

    result = LessonQualityResult(
        accepted=not reasons,
        reason_codes=tuple(reasons),
        source_anchor_matches=anchor_matches,
        required_source_anchor_matches=required_matches,
        generic_sentence_share=round(generic_share, 4),
        repeated_sentence_count=repeated_count,
    )
    events = _LESSON_QUALITY_EVENTS.get()
    if events is not None:
        events.append((title, content, tuple(source_chunks), result))
    return result


__all__ = [
    "LESSON_QUALITY_POLICY_VERSION",
    "LessonQualityResult",
    "capture_lesson_quality_evaluations",
    "evaluate_lesson_quality",
]
