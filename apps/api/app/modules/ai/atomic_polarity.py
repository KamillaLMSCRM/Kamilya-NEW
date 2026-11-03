"""Compile one exact source-owned atomic predicate and its literal polarity.

The module proves only a bounded syntactic layout. It never establishes which
option is true, educational, grammatical in context, or admissible.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.ai.assessment_preservation import (
    _word_info,
    source_predicate_supports_literal_negation,
    starts_with_known_infinitive_clause,
)
from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

_WORD_RE = re.compile(r"(?<!\w)[А-Яа-яЁё]+(?!\w)")
_NEGATION_RE = re.compile(r"(?<!\w)(?:не|ни)(?!\w)", re.IGNORECASE)
_COORDINATION_RE = re.compile(r"(?<!\w)(?:и|или|либо|а|но)(?!\w)", re.IGNORECASE)
_CLAUSE_PUNCTUATION_RE = re.compile(r"[,;:.!?()\[\]{}\r\n\v\f]")
_MAX_COMPONENT_CHARS = 240
_MAX_SOURCE_CHARS = 65_536
_HSPACE = frozenset(SOURCE_HORIZONTAL_SPACE)
_EMPHATIC_NEGATIVE_PROHIBITION_RE = re.compile(
    r"(?<!\w)(?:категорически|строго|строжайше) (?P<negation>не )"
    r"(?:запрещается|запрещено|запрещен|запрещена|запрещены|воспрещается|воспрещено)(?!\w)",
)


def has_visible_prohibition_wording(text: str) -> bool:
    """Detect a presentation cue, never infer whether a prohibition applies."""
    words = [match.group().casefold() for match in _WORD_RE.finditer(text)]
    previous = ""
    for word in words:
        lemmas = _word_info(word).lemmas
        if word == "нельзя" or lemmas & {"запрет", "запретить", "запрещать", "воспретить", "воспрещать"}:
            return True
        if previous == "не" and lemmas & {
            "допускаться", "допускать", "допустить", "допуститься",
            "разрешаться", "разрешать", "разрешить", "разрешиться",
            "позволять", "позволить", "позволяться", "дозволять", "дозволить", "дозволяться",
        }:
            return True
        previous = word
    return False


def has_marked_emphatic_polarity_pair(options: Sequence[str]) -> bool:
    """Negative presentation guard, not a prohibition truth/answer inference.

    Only an exact emphatic-prohibition pair differing by one inserted negation
    is marked. Ordinary negation and emphatic recommendations are not this cue.
    """
    visible = {" ".join(option.casefold().split()) for option in options}
    for option in visible:
        for match in _EMPHATIC_NEGATIVE_PROHIBITION_RE.finditer(option):
            positive = option[:match.start("negation")] + option[match.end("negation"):]
            if positive in visible:
                return True
    return False


def has_bounded_literal_occurrence(value: object, source: object) -> bool:
    """Exact clause ownership; Unicode marks never become invisible boundaries."""
    if not isinstance(value, str) or not value or not isinstance(source, str):
        return False
    start = source.find(value)
    while start >= 0:
        end = start + len(value)
        boundaries = (source[start - 1] if start else "", source[end] if end < len(source) else "")
        if not any(char and (char == "_" or unicodedata.category(char)[0] in {"L", "N", "M"})
                   for char in boundaries):
            return True
        start = source.find(value, start + 1)
    return False


@dataclass(frozen=True, slots=True)
class AtomicPolaritySpec:
    base: str
    opposite: str
    focus: str
    source: str


def literal_polarity_opposite(base: object, focus: object) -> str | None:
    """Toggle exactly one owned predicate focus and preserve every other byte."""
    if (not isinstance(base, str) or not isinstance(focus, str) or not base or not focus
            or len(base) > _MAX_COMPONENT_CHARS or base != base.strip() or focus != focus.strip()
            or base.count(focus) != 1):
        return None
    start = base.index(focus)
    negative = re.match(r"^не(?P<gap>[" + re.escape(SOURCE_HORIZONTAL_SPACE) + r"]+)(?P<word>[А-Яа-яЁё]+)$",
                        focus, re.IGNORECASE)
    if negative is not None:
        predicate = negative.group("word")
        replacement = predicate
    else:
        if _WORD_RE.fullmatch(focus) is None:
            return None
        predicate = focus
        replacement = "не " + focus
    if not source_predicate_supports_literal_negation(predicate, allow_short_participle=True):
        return None
    return base[:start] + replacement + base[start + len(focus):]


def is_literal_polarity_opposite(base: object, focus: object, candidate: object) -> bool:
    """Recognize the same exact toggle while retaining horizontal-space legacy."""
    if not isinstance(base, str) or not isinstance(focus, str) or not isinstance(candidate, str):
        return False
    canonical = literal_polarity_opposite(base, focus)
    if canonical is None:
        return False
    if candidate == canonical:
        return True
    if re.match(r"^не[" + re.escape(SOURCE_HORIZONTAL_SPACE) + r"]+", focus, re.IGNORECASE):
        return False  # Removal has one exact result; no whitespace is inserted.
    if base.count(focus) != 1:
        return False
    start = base.index(focus)
    prefix, suffix = base[:start], base[start + len(focus):]
    if not candidate.startswith(prefix + "не") or not candidate.endswith(focus + suffix):
        return False
    gap_start = len(prefix) + 2
    gap_end = len(candidate) - len(focus + suffix)
    gap = candidate[gap_start:gap_end]
    return bool(gap) and all(character in _HSPACE for character in gap)


def source_owned_atomic_polarity(base: object, source: object) -> AtomicPolaritySpec | None:
    """Return a conservative exact-polarity layout, never a truth or key proof."""
    if (not isinstance(base, str) or not isinstance(source, str) or not base or not source
            or base != base.strip() or len(base) > _MAX_COMPONENT_CHARS
            or len(source) > _MAX_SOURCE_CHARS or source.count(base) != 1
            or _CLAUSE_PUNCTUATION_RE.search(base) or _COORDINATION_RE.search(base)):
        return None
    if not has_bounded_literal_occurrence(base, source):
        return None  # A unique stem inside a longer token is not an exact owned clause.
    words = list(_WORD_RE.finditer(base))
    if len(words) < 2:
        return None
    predicates = [match for match in words if source_predicate_supports_literal_negation(
        match.group(), allow_short_participle=True,
    )]
    # One finite/modal predicate may govern one following infinitive. Anything
    # broader is not an atomic polarity decision and stays with AUTHOR.
    if not 1 <= len(predicates) <= 2:
        return None
    if len(predicates) == 2 and not starts_with_known_infinitive_clause(base[predicates[1].start():]):
        return None
    predicate = predicates[0]
    negations = list(_NEGATION_RE.finditer(base))
    if negations:
        if len(negations) != 1 or negations[0].group().casefold() != "не":
            return None
        negation = negations[0]
        gap = base[negation.end():predicate.start()]
        if not gap or any(character not in _HSPACE for character in gap):
            return None
        focus = base[negation.start():predicate.end()]
    else:
        focus = predicate.group()
    opposite = literal_polarity_opposite(base, focus)
    if opposite is None or opposite == base:
        return None
    return AtomicPolaritySpec(base, opposite, focus, source)
