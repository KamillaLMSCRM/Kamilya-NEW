"""Conservative negative guard for overlapping deadline answer options.

This module proves only that two displayed alternatives are not exclusive.  It
does not establish source truth, select a key, repair wording, or replace either
semantic critic.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

EARLIER_ACTION_SATISFIES_DEADLINE = (
    "earlier_action_satisfies_deadline: immediate action also satisfies a maximum deadline; "
    "do not grade it false. Test an explicit late-action scenario or an exact numeric maximum "
    "with same-unit point options, preserving the source's start event and day type"
)

_IMMEDIATE = re.compile(
    r"\b(?:незамедлительно|немедленно|сразу(?:\s+же)?|без\s+промедления)\b",
    re.IGNORECASE,
)
_UPPER_BOUND = re.compile(
    r"\b(?:"
    r"в\s+течени[еи]|"
    r"не\s+позднее(?:\s+чем)?(?:\s+через)?|"
    r"не\s+позже(?:\s+чем)?(?:\s+через)?|"
    r"максимум\s+через|"
    r"в\s+срок\s+до"
    r")\s+(?P<value>\d{1,4})\s+"
    r"(?:(?:рабоч|календарн)\w*\s+)?д(?:ень|ня|ней)\b",
    re.IGNORECASE,
)
_KNOWN_NEGATIVE_SCOPE = re.compile(
    r"\b(?:нельзя|запрещ\w*|недопустим\w*|никогда|ошибочн\w*|наруша\w*)\b|"
    r"\bне\s+(?:допуска\w*|разреш\w*|долж(?:ен|на|но|ны)|следует)\b|"
    r"\bне\s+[а-яё-]{2,}(?:ть|ться)\b",
    re.IGNORECASE,
)
_UNKNOWN_NEGATIVE_MARKER = re.compile(
    r"\b(?:не|ни|нет|без)\b|\bне(?!замедлительно|медленно)[а-яё-]{3,}\b",
    re.IGNORECASE,
)
_SPACE = re.compile(r"\s+")
_EDGE_PUNCTUATION = re.compile(r"^[\s,;:.!?()\[\]{}\-–—]+|[\s,;:.!?()\[\]{}\-–—]+$")


@dataclass(frozen=True)
class _OptionShape:
    timing: Literal["immediate", "upper_bound"]
    action: str


def _normalize(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = _EDGE_PUNCTUATION.sub("", value)
    return _SPACE.sub(" ", value).strip()


def _without_span(value: str, start: int, end: int) -> str:
    return value[:start] + " " + value[end:]


def deadline_negative_scope(value: str) -> Literal["negative", "unmarked", "unknown"]:
    """Classify finite negative syntax without treating absence as approval.

    Supported timing operators are masked before inspection, so ``не позднее``
    is not confused with action negation and ``без промедления`` remains an
    immediate marker.  Any other negative-looking token is ``unknown`` and must
    stay with the mandatory source-aware critics.
    """
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    masked = list(value)
    spans = [match.span() for pattern in (_IMMEDIATE, _UPPER_BOUND) for match in pattern.finditer(value)]
    for start, end in spans:
        masked[start:end] = " " * (end - start)
    remainder = "".join(masked)
    if _KNOWN_NEGATIVE_SCOPE.search(remainder):
        return "negative"
    if _UNKNOWN_NEGATIVE_MARKER.search(remainder):
        return "unknown"
    return "unmarked"


def _action_shape(value: str, match: re.Match[str]) -> str:
    remainder = _without_span(value, match.start(), match.end())
    # Every other displayed token remains part of the option identity.  In
    # particular, never erase a start event, condition, purpose, or plan step:
    # only literally matching residuals can prove overlap without source truth.
    return _normalize(remainder)


def _shape(value: str) -> _OptionShape | None:
    immediate = list(_IMMEDIATE.finditer(value))
    upper = list(_UPPER_BOUND.finditer(value))
    # Multiple or mixed timing predicates need source semantics, not a lexical
    # veto.  The positive upper bound is deliberately finite and non-zero.
    if len(immediate) == 1 and not upper:
        return _OptionShape("immediate", _action_shape(value, immediate[0]))
    if len(upper) == 1 and not immediate:
        amount = int(upper[0].group("value"))
        if 1 <= amount <= 3660:
            return _OptionShape("upper_bound", _action_shape(value, upper[0]))
    return None


def _shared_action_with_extra_purpose(stem: str, immediate: str, bound: str) -> bool:
    """Hold a broad timing answer that may include an immediate purposeful act.

    A full-plan question can legitimately require the stated purpose, so this
    narrow overlap proof is unavailable there. No action, condition or source
    truth is inferred from a missing phrase.
    """
    if re.search(r"\b(?:план\w*|порядок|полн\w*|вс[её]\b|всех\b|кажд\w*)", stem, re.I):
        return False
    if not re.fullmatch(r"[а-яе]{3,}(?:ть|ти|чь)", bound):
        return False
    prefix = bound + " для "
    if not immediate.startswith(prefix):
        return False
    purpose = immediate[len(prefix):]
    return bool(purpose.strip()) and not re.search(
        r"\b(?:если|когда|после|до|перед|кроме|только|при|без|не)\b", purpose, re.I
    )


def deadline_option_scope_issue(stem: str, options: Sequence[str], key: int) -> str | None:
    """Return a negative-only issue for a proven immediate/deadline overlap.

    The key may be either side of the pair.  Options must express exactly one
    supported timing shape and the same remaining action (or both be timing-only
    under the shared stem).  Unknown forms fail open to the mandatory critics.
    """
    if (
        not isinstance(stem, str)
        or not isinstance(options, Sequence)
        or isinstance(options, str | bytes)
        or type(key) is not int
        or not 0 <= key < len(options)
        or len(options) < 2
        or any(not isinstance(option, str) or not option.strip() for option in options)
    ):
        return None
    # ``unmarked`` is only permission to continue this negative proof.  It is
    # not a positive semantic verdict. Known and unknown negative scope both
    # fail open to the source-aware critics.
    if deadline_negative_scope(stem) != "unmarked":
        return None
    keyed = _shape(options[key])
    if keyed is None or deadline_negative_scope(options[key]) != "unmarked":
        return None
    opposite = "upper_bound" if keyed.timing == "immediate" else "immediate"
    for index, option in enumerate(options):
        if index == key:
            continue
        candidate = _shape(option)
        if candidate is not None and candidate.timing == opposite and deadline_negative_scope(option) == "unmarked":
            immediate, bound = ((keyed.action, candidate.action) if keyed.timing == "immediate"
                                else (candidate.action, keyed.action))
            if candidate.action == keyed.action or _shared_action_with_extra_purpose(stem, immediate, bound):
                return EARLIER_ACTION_SATISFIES_DEADLINE
    return None
