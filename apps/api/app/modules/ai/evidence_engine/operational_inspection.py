"""Source-exact typed projections for bounded inspections and checklists."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .models import SourceFact
from .operational_steps import (
    ExactSentenceSpan,
    OperationalStep,
    _are_exact_ordered_spans,
)
from .operational_steps import (
    OperationalProjection as OperationalInspectionProjection,
)
from .quality import MAX_ASSESSMENT_ANSWER_CHARS

_MAX_REQUIRED_PROMPT_CHARS = 900

_CHECKLIST = re.compile(
    r"^(?P<scope_context>"
    r"(?P<timing>Во\s+время\s+[^.!?]{3,160}?)\s+"
    r"(?P<actor>(?-i:[А-ЯЁA-Z][А-Яа-яЁёA-Za-z.-]*"
    r"(?:\s+[А-Яа-яЁёA-Za-z.-]+){0,3}?))\s+1\.)\s+"
    r"(?P<visit>должен\s+посетить\s+[^.!?]{3,200}?)\s+и\s+"
    r"(?P<check>проверить\s+[^.!?]{3,500}?\s+на\s+соответствие:\s*"
    r"-\s*[^.!?]{3,500})[.!?]?$",
    flags=re.IGNORECASE,
)
_LOCAL_BRANCH = re.compile(
    r"(?P<scope_context>"
    r"\d+[.)]\s*(?P<locality>при\s+[^.!?]{3,240}?)\s+[-–—]\s+"
    r"(?P<actor>(?-i:[А-ЯЁA-Z][А-Яа-яЁёA-Za-z.-]*"
    r"(?:\s+[А-Яа-яЁёA-Za-z.-]+){0,3}?)))\s+"
    r"(?P<inspection>проводит\s+осмотр,\s+проверку\s+[^,.!?]{3,180}?\s+"
    r"совместно\s+с\s+(?P<coactor>[^,.!?]{3,100}?)),\s+"
    r"(?P<determination>определяет\s+[^.!?]{3,240}?\s+"
    r"в\s+соответствии\s+с\s+(?P<qualification>[^.!?]{3,180}))[.!?]?$",
    flags=re.IGNORECASE,
)


def _span(
    sentence: str,
    sentence_index: int,
    start: int,
    end: int,
) -> ExactSentenceSpan:
    return ExactSentenceSpan(
        sentence_index=sentence_index,
        start=start,
        end=end,
        text=sentence[start:end],
    )


def _projection(
    *,
    sentence: str,
    sentence_index: int,
    match: re.Match[str],
    answer_group: str,
    scope_group: str,
    prompt: str,
    condition: str,
) -> OperationalInspectionProjection | None:
    answer = match.group(answer_group).strip()
    if (
        not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS
        or len(prompt) > _MAX_REQUIRED_PROMPT_CHARS
    ):
        return None
    answer_start, answer_end = match.span(answer_group)
    scope_start, scope_end = match.span(scope_group)
    if sentence[answer_start:answer_end].strip() != answer:
        return None
    return OperationalInspectionProjection(
        step=OperationalStep(
            answer=answer,
            required_prompt=prompt,
            consumed_sentence_index=sentence_index,
            governing_sentence_index=sentence_index,
            governing_condition=condition,
        ),
        consumed_spans=(
            _span(sentence, sentence_index, scope_start, scope_end),
            _span(sentence, sentence_index, answer_start, answer_end),
        ),
    )


def _checklist_projections(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalInspectionProjection, ...]:
    match = _CHECKLIST.fullmatch(sentence)
    if match is None:
        return ()
    timing = match.group("timing").strip()
    actor = match.group("actor").strip()
    check = match.group("check").strip()
    if (
        " или " in actor.casefold()
        or " и " in actor.casefold()
        or check.count("- ") < 2
        or re.search(r"-\s*(?:[.,;]|$)", check)
    ):
        return ()
    visit = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="visit",
        scope_group="scope_context",
        prompt=f"Какое действие должен выполнить «{actor}» «{timing}»?",
        condition=timing,
    )
    verification = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="check",
        scope_group="scope_context",
        prompt=(
            f"Что и по каким полным критериям должен проверить «{actor}» "
            f"«{timing}»?"
        ),
        condition=timing,
    )
    if visit is None or verification is None:
        return ()
    return visit, verification


def _local_branch_projections(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalInspectionProjection, ...]:
    match = _LOCAL_BRANCH.search(sentence)
    if match is None:
        return ()
    locality = match.group("locality").strip()
    actor = match.group("actor").strip()
    coactor = match.group("coactor").strip()
    determination = match.group("determination").strip()
    object_match = re.fullmatch(r"определяет\s+(.+?)\s+в\s+соответствии\s+с\s+.+",
                               determination, flags=re.IGNORECASE)
    if object_match is None:
        return ()
    if any(
        token in value.casefold()
        for value in (actor, coactor)
        for token in (" или ", " и ")
    ):
        return ()
    inspection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="inspection",
        scope_group="scope_context",
        prompt=(
            f"Какое действие выполняет «{actor}» совместно с «{coactor}» "
            f"при условии «{locality}»?"
        ),
        condition=locality,
    )
    determination = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="determination",
        scope_group="scope_context",
        prompt=(
            f"Как «{actor}» определяет {object_match.group(1)} "
            f"при условии «{locality}»?"
        ),
        condition=locality,
    )
    if inspection is None or determination is None:
        return ()
    return inspection, determination


def project_operational_inspections(
    fact: SourceFact,
    source_sentences: Sequence[str],
) -> tuple[OperationalInspectionProjection, ...]:
    """Project only complete, exact inspection/checklist source shapes."""
    sentences = tuple(source_sentences)
    if not sentences or not _are_exact_ordered_spans(fact, sentences):
        return ()

    result: list[OperationalInspectionProjection] = []
    for sentence_index, sentence in enumerate(sentences):
        checklist = _checklist_projections(sentence, sentence_index)
        if checklist:
            result.extend(checklist)
            continue
        result.extend(_local_branch_projections(sentence, sentence_index))
    return tuple(result)
