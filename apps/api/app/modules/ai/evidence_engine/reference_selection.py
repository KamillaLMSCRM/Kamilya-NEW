"""Exact, selection-only projections for source-named procedure references.

These projections identify which named procedure a source selects in a fully
specified situation. They deliberately do not claim or expand the referenced
procedure's missing operational steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .models import SourceFact
from .operational_steps import ExactSentenceSpan

ReferenceKind = Literal["remote_analogy", "handover_analogy"]

_NAMED_CATEGORY_RE = re.compile(
    r"\b(?:[IVXLCDM]+|\d+)\s+(?:категори[ия]|класс(?:а|у|ом|е)?)\b",
    re.IGNORECASE,
)
_REMOTE_RELATION_RE = re.compile(
    r"^алгоритм\s+действий\s+аналогичен\s+"
    r"(?P<answer>процедуре\s+согласования\s+[^.!?]{3,160}?\b"
    r"(?:категории|класса)\b)$",
    re.IGNORECASE,
)
_HANDOVER_PREFIX_RE = re.compile(
    r"^(?P<actor>[^,.!?]{3,120}?)\s+"
    r"(?P<trigger>в\s+случае\s+наличия\s+[^.!?]{3,720}?)$",
    re.IGNORECASE,
)
_HANDOVER_RELATION_RE = re.compile(
    r"^при\s+приеме-передаче\s+[^.!?]{3,160}?\b(?:[IVXLCDM]+|\d+)\s+"
    r"(?:категории|класса)\b$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReferenceSelection:
    """One source-exact procedure/category selection, never an execution step."""

    kind: Literal["selection"]
    reference_kind: ReferenceKind
    answer: str
    required_prompt: str
    scope: str
    sentence_index: int
    consumed_spans: tuple[ExactSentenceSpan, ...]
    unresolved_procedure_content: bool = True


def _exact_ordered_spans(fact: SourceFact, sentences: tuple[str, ...]) -> bool:
    """Require the caller's sentence sequence to cover the fact byte-for-byte."""

    cursor = 0
    for sentence in sentences:
        if not sentence or sentence != sentence.strip():
            return False
        position = fact.value.find(sentence, cursor)
        if position < 0 or fact.value[cursor:position].strip():
            return False
        cursor = position + len(sentence)
    return not fact.value[cursor:].strip()


def _span(sentence: str, sentence_index: int, match: re.Match[str], group: str) -> ExactSentenceSpan:
    start, end = match.span(group)
    return ExactSentenceSpan(
        sentence_index=sentence_index,
        start=start,
        end=end,
        text=sentence[start:end],
    )


def _category_is_explicit(value: str) -> bool:
    return _NAMED_CATEGORY_RE.search(value) is not None


def _actor_is_explicit(value: str) -> bool:
    return value.casefold().strip(" .,:;") not in {"он", "оно", "это", "лицо"}


def _remote_selection(
    fact: SourceFact, sentence: str, sentence_index: int,
) -> ReferenceSelection | None:
    marker = re.search(r"\s+[-–—]\s+", sentence)
    if marker is None:
        return None
    scope_end = marker.start()
    scope = sentence[:scope_end].strip()
    relation_start = marker.end()
    relation = sentence[relation_start:].strip().rstrip(".!?").strip()
    relation_match = _REMOTE_RELATION_RE.fullmatch(relation)
    if relation_match is None:
        return None
    answer = relation_match.group("answer").strip()
    if not re.search(r"\bпри\s+[^.!?]{3,240}\bвне\b", scope, re.IGNORECASE):
        return None
    # The operating category must be present in the scope or in the explicit
    # SourceFact subject; the referenced answer category is not enough.
    if not _category_is_explicit(scope) and not _category_is_explicit(fact.subject):
        return None
    return ReferenceSelection(
        kind="selection",
        reference_kind="remote_analogy",
        answer=answer,
        required_prompt=(
            f"Какую точно названную процедуру следует выбрать для «{fact.subject.strip()}» "
            f"при условии «{scope}»?"
        ),
        scope=scope,
        sentence_index=sentence_index,
        consumed_spans=(
            ExactSentenceSpan(sentence_index, 0, scope_end, sentence[:scope_end]),
            ExactSentenceSpan(
                sentence_index, relation_start, relation_start + len(relation),
                sentence[relation_start:relation_start + len(relation)],
            ),
        ),
    )


def _handover_selection(
    sentence: str, sentence_index: int,
) -> ReferenceSelection | None:
    marker = re.search(r"\s+должен\s+действовать\s+также\s+как\s+", sentence, re.IGNORECASE)
    if marker is None:
        return None
    prefix = sentence[:marker.start()].strip()
    relation_start = marker.end()
    relation = sentence[relation_start:].strip().rstrip(".!?").strip()
    prefix_match = _HANDOVER_PREFIX_RE.fullmatch(prefix)
    if prefix_match is None or _HANDOVER_RELATION_RE.fullmatch(relation) is None:
        return None
    actor = prefix_match.group("actor").strip()
    trigger = prefix_match.group("trigger").strip()
    answer = relation
    if (
        not _actor_is_explicit(actor)
        or not re.search(r"\bво\s+время\s+приема-передачи\b", trigger, re.IGNORECASE)
        or not re.search(r"\bподозр", trigger, re.IGNORECASE)
        or not _category_is_explicit(trigger)
    ):
        return None
    return ReferenceSelection(
        kind="selection",
        reference_kind="handover_analogy",
        answer=answer,
        required_prompt=(
            f"Какую точно названную процедуру выбрать сотруднику «{actor}» "
            f"при условии «{trigger}»?"
        ),
        scope=trigger,
        sentence_index=sentence_index,
        consumed_spans=(
            ExactSentenceSpan(sentence_index, 0, prefix_match.end("actor"), actor),
            ExactSentenceSpan(
                sentence_index, prefix_match.start("trigger"), prefix_match.end("trigger"),
                trigger,
            ),
            ExactSentenceSpan(sentence_index, marker.start(), marker.end(), sentence[marker.start():marker.end()]),
            ExactSentenceSpan(
                sentence_index, relation_start, relation_start + len(relation),
                sentence[relation_start:relation_start + len(relation)],
            ),
        ),
    )


def project_reference_selections(
    fact: SourceFact, source_sentences: tuple[str, ...] | list[str],
) -> tuple[ReferenceSelection, ...]:
    """Project complete named-procedure selections without claiming its steps."""

    sentences = tuple(source_sentences)
    if not sentences or not _exact_ordered_spans(fact, sentences):
        return ()
    selections: list[ReferenceSelection] = []
    for index, sentence in enumerate(sentences):
        selection = _remote_selection(fact, sentence, index)
        if selection is None:
            selection = _handover_selection(sentence, index)
        if selection is not None:
            selections.append(selection)
    return tuple(selections)
