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
_RELATIONSHIP_TOKEN_RE = re.compile(r"[\w./-]+", re.UNICODE)
_RELATIONSHIP_FRAGMENT_SPLIT_RE = re.compile(
    r"(?:[!?]+|\n+|\.(?!\w)|(?<!\w)\.)"
)
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
    re.compile(
        r"\b(?:связан\w*\s+с(?:о)?|links?\s+(?:to|with)|"
        r"(?:is\s+)?linked\s+(?:to|with)|(?:is\s+)?related\s+to|"
        r"relates?\s+to)\b"
    ),
    re.compile(r"\bоснов\w*\s+для\b"),
    re.compile(
        r"\b[\w./-]+\b.{0,80}\b(?:определя\w*|обусловлива\w*|"
        r"привод\w*|требу\w*|determines?|causes?|requires?)\b"
    ),
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
    re.compile(r"\b(?:если\s+клиент\w*|if\s+(?:the\s+)?customer\w*)\b"),
    re.compile(
        r"\b(?:начн\w*\s+с|диалог\w*.{0,80}\bначина\w*|"
        r"start\w*\s+with|conversation\w*.{0,80}\bbegin\w*)\b"
    ),
    re.compile(
        r"\b(?:используйте|можно\s+использовать|использовать.{0,40}\bкак|"
        r"построй\w*|подавай\w*|соотнес\w*|use|can\s+be\s+used)\b"
    ),
    re.compile(r"\b(?:ориентир\w*|serves?\s+as\s+(?:a\s+)?guide\w*)\b"),
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
    "если",
    "клиент",
    "начн",
    "диалог",
    "использ",
    "постро",
    "подава",
    "соотнес",
    "ориентир",
    "customer",
    "start",
    "conversation",
    "use",
    "guide",
)
_RELATIONSHIP_OPERATOR_RE = re.compile(
    r"\b(?:(?:прямо|напрямую)\s+связан\w*|основ\w*\s+для|"
    r"связан\w*\s+с(?:о)?|links?\s+(?:to|with)|"
    r"(?:is\s+)?linked\s+(?:to|with)|(?:is\s+)?related\s+to|"
    r"relates?\s+to|"
    r"определя\w*|обусловлива\w*|привод\w*|требу\w*|поэтому|значит|"
    r"directly\s+(?:linked|related)|basis\s+for|therefore|"
    r"determines?|causes?|requires?|must|should|need|"
    r"если\s+клиент\w*|if\s+(?:the\s+)?customer\w*|"
    r"начн\w*\s+с|диалог\w*.{0,80}\bначина\w*|"
    r"start\w*\s+with|conversation\w*.{0,80}\bbegin\w*|"
    r"используйте|можно\s+использовать|использовать.{0,40}\bкак|построй\w*|подавай\w*|"
    r"соотнес\w*|use\w*|can\s+be\s+used|"
    r"ориентир\w*|serves?\s+as\s+(?:a\s+)?guide\w*)\b"
)
_RELATIONSHIP_SHORT_STOP_WORDS = frozenset(
    {
        "в", "во", "на", "по", "к", "ко", "с", "со", "о", "об", "от",
        "до", "из", "за", "у", "и", "а", "но", "не", "то", "же", "бы",
        "ли", "of", "to", "is", "as", "at", "by", "in", "on", "or", "an",
        "be", "if",
    }
)
LESSON_QUALITY_POLICY_VERSION = "lesson-quality-v10"


def _normalize(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold().replace("ё", "е")))


def _content_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _normalize(value).split() if token not in _STOP_WORDS)


def _relationship_tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    raw_tokens = _RELATIONSHIP_TOKEN_RE.findall(value.replace("ё", "е"))
    for raw_token in raw_tokens:
        token = raw_token.casefold().strip("._-/")
        if (
            not token
            or token in _STOP_WORDS
            or token in _RELATIONSHIP_SHORT_STOP_WORDS
        ):
            continue
        if any(character.isdigit() for character in token) or len(token) >= 2:
            tokens.append(token)
    return tuple(tokens)


def _sentences(value: str) -> tuple[str, ...]:
    cleaned = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    return tuple(
        normalized
        for raw in _SENTENCE_RE.split(cleaned)
        for normalized in [_normalize(raw)]
        if normalized
    )


def _relationship_operator(value: str) -> str:
    normalized = value.casefold().replace("ё", "е")
    if re.search(r"(?:прямо|напрямую)\s+связан|directly\s+linked", normalized):
        return "direct_link"
    if re.search(
        r"связан\w*\s+с(?:о)?|links?\s+(?:to|with)|"
        r"(?:is\s+)?linked\s+(?:to|with)",
        normalized,
    ):
        return "link"
    if re.search(r"(?:is\s+)?related\s+to|relates?\s+to", normalized):
        return "relation"
    if "directly related" in normalized:
        return "direct_relation"
    if re.search(r"основ\w*\s+для|basis\s+for", normalized):
        return "basis"
    if re.search(r"определя\w*|determines?", normalized):
        return "determine"
    if re.search(r"обусловлива\w*", normalized):
        return "condition"
    if re.search(r"привод\w*|causes?", normalized):
        return "cause"
    if re.search(r"требу\w*|requires?", normalized):
        return "require"
    if re.search(r"поэтому|therefore", normalized):
        return "therefore"
    if "значит" in normalized:
        return "imply"
    if re.search(r"\bmust\b", normalized):
        return "must"
    if re.search(r"\bshould\b", normalized):
        return "should"
    if re.search(r"\bneed\b", normalized):
        return "need"
    if re.search(r"если\s+клиент\w*|if\s+(?:the\s+)?customer\w*", normalized):
        return "customer_condition"
    if re.search(
        r"начн\w*\s+с|диалог\w*.{0,80}\bначина\w*|"
        r"start\w*\s+with|conversation\w*.{0,80}\bbegin\w*",
        normalized,
    ):
        return "start_instruction"
    if re.search(
        r"используйте|можно\s+использовать|использовать.{0,40}\bкак|"
        r"\buse\b|can\s+be\s+used",
        normalized,
    ):
        return "use_instruction"
    if re.search(r"построй\w*|подавай\w*|соотнес\w*", normalized):
        return "sales_instruction"
    if re.search(r"ориентир\w*|serves?\s+as\s+(?:a\s+)?guide\w*", normalized):
        return "guidance_claim"
    return ""


def _ordered_relationship_anchors(
    value: str,
) -> tuple[str, set[str], set[str]]:
    operator = _RELATIONSHIP_OPERATOR_RE.search(value)
    if operator is None:
        return "", set(_relationship_tokens(value)), set()

    def anchors(fragment: str) -> set[str]:
        return {
            token
            for token in _relationship_tokens(fragment)
            if not any(
                token.startswith(root) for root in _RELATIONSHIP_OPERATOR_ROOTS
            )
        }

    return (
        _relationship_operator(operator.group(0)),
        anchors(value[: operator.start()]),
        anchors(value[operator.end() :]),
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
        for fragment in _RELATIONSHIP_FRAGMENT_SPLIT_RE.split(content)
        if pattern.search(fragment)
    )
    source_fragments = tuple(
        fragment.strip()
        for fragment in _RELATIONSHIP_FRAGMENT_SPLIT_RE.split(source)
        if pattern.search(fragment)
    )
    for claim in content_fragments:
        claim_operator, claim_subject, claim_endpoint = (
            _ordered_relationship_anchors(claim)
        )
        supported = False
        for source_fragment in source_fragments:
            source_operator, source_subject, source_endpoint = (
                _ordered_relationship_anchors(source_fragment)
            )
            if not claim_operator or claim_operator != source_operator:
                continue
            if claim_subject and claim_endpoint:
                supported = claim_subject.issubset(
                    source_subject
                ) and claim_endpoint.issubset(source_endpoint)
            else:
                claim_anchors = claim_subject | claim_endpoint
                supported = bool(claim_anchors) and claim_anchors.issubset(
                    set(_relationship_tokens(source_fragment))
                )
            if supported:
                break
        if not supported:
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


@dataclass(frozen=True, slots=True)
class LessonQualityEvaluation:
    lesson_identity: tuple[int, int] | None
    title: str
    content: str
    source_chunks: tuple[str, ...]
    result: LessonQualityResult


_LESSON_QUALITY_EVENTS: ContextVar[list[LessonQualityEvaluation] | None] = (
    ContextVar("lesson_quality_events", default=None)
)


@contextmanager
def capture_lesson_quality_evaluations() -> Iterator[
    list[LessonQualityEvaluation]
]:
    """Capture exact validator inputs only inside an explicit task context."""
    events: list[LessonQualityEvaluation] = []
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
    lesson_identity: tuple[int, int] | None = None,
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
        events.append(
            LessonQualityEvaluation(
                lesson_identity=lesson_identity,
                title=title,
                content=content,
                source_chunks=tuple(source_chunks),
                result=result,
            )
        )
    return result


__all__ = [
    "LESSON_QUALITY_POLICY_VERSION",
    "LessonQualityResult",
    "LessonQualityEvaluation",
    "capture_lesson_quality_evaluations",
    "evaluate_lesson_quality",
]
