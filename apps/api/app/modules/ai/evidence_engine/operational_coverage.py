"""Pure exact-span coverage accounting for operational projections."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .operational_steps import ExactSentenceSpan, OperationalProjection

_ORDINAL_ONLY = re.compile(r"\s*\d+(?:\.\d+)*[.)]?\s*")


@dataclass(frozen=True, slots=True)
class OperationalCoverageAudit:
    """Material source spans not owned by admitted exact projections."""

    uncovered_spans: tuple[ExactSentenceSpan, ...]
    uncovered_sentence_indices: tuple[int, ...]


def _normalized_pair(answer: str, prompt: str) -> tuple[str, str]:
    return (
        " ".join(answer.casefold().split()),
        " ".join(prompt.casefold().split()),
    )


def _is_source_separator(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")


def _valid_projection(
    projection: OperationalProjection,
    sentences: tuple[str, ...],
) -> bool:
    step = projection.step
    indexes = (step.consumed_sentence_index, step.governing_sentence_index)
    if any(
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < len(sentences)
        for index in indexes
    ):
        return False
    if not projection.consumed_spans:
        return False
    for span in projection.consumed_spans:
        if (
            isinstance(span.sentence_index, bool)
            or not isinstance(span.sentence_index, int)
            or not 0 <= span.sentence_index < len(sentences)
            or isinstance(span.start, bool)
            or not isinstance(span.start, int)
            or isinstance(span.end, bool)
            or not isinstance(span.end, int)
        ):
            return False
        sentence = sentences[span.sentence_index]
        if not 0 <= span.start < span.end <= len(sentence):
            return False
        if sentence[span.start:span.end] != span.text:
            return False
    return True


def _uncovered_segments(
    sentence: str,
    sentence_index: int,
    covered: list[bool],
) -> tuple[ExactSentenceSpan, ...]:
    if _ORDINAL_ONLY.fullmatch(sentence):
        return ()
    result: list[ExactSentenceSpan] = []
    cursor = 0
    while cursor < len(sentence):
        if covered[cursor]:
            cursor += 1
            continue
        start = cursor
        while cursor < len(sentence) and not covered[cursor]:
            cursor += 1
        end = cursor
        material_start = start
        while material_start < end and _is_source_separator(sentence[material_start]):
            material_start += 1
        material_end = end
        while material_end > material_start and _is_source_separator(sentence[material_end - 1]):
            material_end -= 1
        if material_start == material_end:
            continue
        material = "".join(
            character
            for character in sentence[material_start:material_end]
            if not _is_source_separator(character)
        ).casefold()
        bounded_by_claims = start > 0 and end < len(sentence)
        if material == "и" and bounded_by_claims:
            continue
        result.append(ExactSentenceSpan(
            sentence_index=sentence_index,
            start=material_start,
            end=material_end,
            text=sentence[material_start:material_end],
        ))
    return tuple(result)


def audit_operational_coverage(
    source_sentences: Sequence[str],
    actual_targets: Iterable[tuple[str, str]],
    projections: Iterable[OperationalProjection],
) -> OperationalCoverageAudit:
    """Return material source spans not claimed by actual exact target pairs."""
    sentences = tuple(source_sentences)
    remaining_targets = Counter(
        _normalized_pair(answer, prompt) for answer, prompt in actual_targets
    )
    covered = [[False] * len(sentence) for sentence in sentences]

    for projection in projections:
        target = _normalized_pair(
            projection.step.answer,
            projection.step.required_prompt,
        )
        if not remaining_targets[target] or not _valid_projection(projection, sentences):
            continue
        remaining_targets[target] -= 1
        for span in projection.consumed_spans:
            covered[span.sentence_index][span.start:span.end] = [True] * (
                span.end - span.start
            )

    uncovered = tuple(
        span
        for sentence_index, sentence in enumerate(sentences)
        for span in _uncovered_segments(sentence, sentence_index, covered[sentence_index])
    )
    return OperationalCoverageAudit(
        uncovered_spans=uncovered,
        uncovered_sentence_indices=tuple(dict.fromkeys(
            span.sentence_index for span in uncovered
        )),
    )
