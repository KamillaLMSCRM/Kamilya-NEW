"""Source-exact typed projections for bounded approval and reference rules."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .models import SourceFact
from .operational_steps import (
    ExactSentenceSpan,
    OperationalProjection,
    OperationalStep,
    _are_exact_ordered_spans,
)
from .quality import MAX_ASSESSMENT_ANSWER_CHARS

_MAX_REQUIRED_PROMPT_CHARS = 900

_PHONE_PREAPPROVAL = re.compile(
    r"^(?P<answer>(?P<phone>(?P<subject>Решение\s+о\s+[^,.!?]{3,190}?\s+"
    r"по\s+данной\s+категории)\s+требует\s+предварительного\s+"
    r"согласования\s+по\s+телефону),\s*а\s+в\s+дальнейшем\s+"
    r"(?P<reference>в\s+соответствии\s+с\s+п\.\s*\d+(?:\.\d+)*\.))$",
    flags=re.IGNORECASE,
)
_GENERAL_APPROVAL = re.compile(
    r"^(?P<answer>(?P<subject>[^:!?]{3,140}?)\s+требуют\s+обязательного\s+"
    r"согласования\s+(?P<event>\([^()]{3,130}?\s+и\s+[^()]{3,130}?\))\s+"
    r"с\s+(?P<actor>[^:,.!?]{3,100}?)):\s*\d+[.)]\s+[^.!?]+[.!?]?$",
    flags=re.IGNORECASE,
)
_REFUSAL = re.compile(
    r"^(?:(?P<branch>\d+[.)]\s*(?P<locality>при\s+[^.!?]{3,220}?)\s+"
    r"[-–—]\s+))?"
    r"(?P<condition>В\s+случае\s+несогласования)\s*[-–—]\s*"
    r"(?P<answer>(?P<actor>[^,.!?]{3,100}?)\s+отказывает\s+"
    r"[^.!?]{3,180}?)[.!?]?$",
    flags=re.IGNORECASE,
)
_REMOTE_PHONE_APPROVAL = re.compile(
    r"^(?P<scope>(?P<subject>[^.!?]{3,140}?\b(?:категори[ия]|класса)\b)\s+"
    r"(?P<locality>при\s+[^.!?]{3,240}?\bвне\b[^.!?]{3,160}?))\s+"
    r"(?P<answer>предварительно\s+согласовываются\s+"
    r"(?P<actor>[^,.!?]{3,100}?)\s+(?P<method>по\s+телефону))[.!?]?$",
    flags=re.IGNORECASE,
)
_REMOTE_COMPLEX_REVIEW = re.compile(
    r"^(?P<actor>[^,.!?]{3,120}?)\s+"
    r"(?P<answer>проводят\s+согласование\s+[^.!?]{3,160}?\s+"
    r"во\s+время\s+проведения\s+комплексной\s+проверки\s+"
    r"(?P<locality>[^.!?]{3,220}?\bвне\b[^.!?]{3,140}?))[.!?]?$",
    flags=re.IGNORECASE,
)
_REMOTE_ANALOGY = re.compile(
    r"^(?P<scope>\d+[.)]\s*(?P<locality>при\s+[^.!?]{3,240}?\bвне\b"
    r"[^.!?]{3,160}?))\s+[-–—]\s+"
    r"(?P<relation>алгоритм\s+действий\s+аналогичен\s+"
    r"(?P<answer>процедуре\s+согласования\s+[^.!?]{3,160}?\b"
    r"(?:категории|класса)))[.!?]?$",
    flags=re.IGNORECASE,
)
_HANDOVER_ANALOGY = re.compile(
    r"^(?P<actor>[^,.!?]{3,120}?)\s+"
    r"(?P<condition>в\s+случае\s+наличия\s+[^,.!?]{3,160}?\b"
    r"(?:категории|класса),\s+во\s+время\s+приема-передачи\s+"
    r"[^,.!?]{3,140}?\s+и\s+наличия\s+подозрений(?:\s+\([^)]{2,80}\))?\s+"
    r"в\s+отношении\s+качественных\s+и/или\s+количественных\s+"
    r"характеристик\s+[^.!?]{3,120}?)\s+"
    r"(?P<relation>должен\s+действовать\s+также\s+как\s+"
    r"(?P<answer>при\s+приеме-передаче\s+[^.!?]{3,160}?\b"
    r"(?:категории|класса)))[.!?]?$",
    flags=re.IGNORECASE,
)
_NUMBERED_MARKER = re.compile(r"(?:^|:\s*)\d+[.)]\s*")
_NUMBERED_LOCAL_BRANCH = re.compile(
    r"(?:^|:\s*)(?P<branch>\d+[.)]\s*"
    r"(?P<locality>при\s+[^.!?]{3,240}?))\s+[-–—]",
    flags=re.IGNORECASE,
)
_APPROVAL_CONTINUATION = re.compile(
    r"^Если\s+[^.!?]{3,180}?\s+согласовывает\s+[^.!?]{3,160}?,\s+"
    r"то\s+[^.!?]+[.!?]?$",
    flags=re.IGNORECASE,
)


def _span(
    sentence: str,
    sentence_index: int,
    match: re.Match[str],
    group: str,
) -> ExactSentenceSpan:
    start, end = match.span(group)
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
    prompt: str,
    condition: str,
    consumed_groups: tuple[str, ...],
    minimum_answer_chars: int = 12,
) -> OperationalProjection | None:
    answer = match.group(answer_group).strip()
    if (
        not minimum_answer_chars <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS
        or len(prompt) > _MAX_REQUIRED_PROMPT_CHARS
    ):
        return None
    answer_start, answer_end = match.span(answer_group)
    if sentence[answer_start:answer_end].strip() != answer:
        return None
    return OperationalProjection(
        step=OperationalStep(
            answer=answer,
            required_prompt=prompt,
            consumed_sentence_index=sentence_index,
            governing_sentence_index=sentence_index,
            governing_condition=condition,
        ),
        consumed_spans=tuple(
            _span(sentence, sentence_index, match, group)
            for group in consumed_groups
            if match.start(group) >= 0
        ),
    )


def _phone_preapproval(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalProjection, ...]:
    match = _PHONE_PREAPPROVAL.fullmatch(sentence)
    if match is None:
        return ()
    subject = match.group("subject").strip()
    reference = match.group("reference").strip()
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="phone",
        prompt=f"Какое предварительное согласование требуется для «{subject}»?",
        condition=subject,
        consumed_groups=("phone",),
    )
    if projection is None:
        return ()
    if not reference.casefold().startswith("в соответствии с п."):
        return ()
    return (projection,)


def _general_approval(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalProjection, ...]:
    match = _GENERAL_APPROVAL.fullmatch(sentence)
    if match is None:
        return ()
    event = match.group("event").strip()
    actor = match.group("actor").strip()
    subject = match.group("subject").strip()
    if " или " in event.casefold() or " и/или " in event.casefold():
        return ()
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="answer",
        prompt=(
            f"Какое обязательное согласование с «{actor}» требуется для "
            f"«{subject}»?"
        ),
        condition=subject,
        consumed_groups=("answer",),
    )
    return (projection,) if projection is not None else ()


def _refusal(
    sentence: str,
    sentence_index: int,
    inherited_branch: tuple[str, ExactSentenceSpan, int] | None = None,
) -> tuple[OperationalProjection, ...]:
    match = _REFUSAL.fullmatch(sentence)
    if match is None:
        return ()
    condition = match.group("condition").strip()
    actor = match.group("actor").strip()
    locality = match.group("locality")
    inherited_locality = inherited_branch[0] if inherited_branch is not None else None
    locality_text = locality.strip() if locality is not None else inherited_locality
    locality_prompt = (
        f" при условии «{locality_text}»" if locality_text is not None else ""
    )
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="answer",
        prompt=(
            f"Какое действие выполняет «{actor}» {condition.casefold()}"
            f"{locality_prompt}?"
        ),
        condition=condition,
        consumed_groups=("branch", "condition", "answer"),
    )
    if projection is None:
        return ()
    if locality is None and inherited_branch is not None:
        projection = OperationalProjection(
            step=projection.step,
            consumed_spans=(inherited_branch[1], *projection.consumed_spans),
        )
    return (projection,)


def _remote_phone_approval(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalProjection, ...]:
    match = _REMOTE_PHONE_APPROVAL.fullmatch(sentence)
    if match is None:
        return ()
    scope = match.group("scope").strip()
    actor = match.group("actor").strip()
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="method",
        prompt=f"Каким способом предварительно согласовываются «{scope}»?",
        condition=scope,
        consumed_groups=("scope", "method"),
        minimum_answer_chars=5,
    )
    if projection is None or actor.casefold() in {"оно", "это", "лицо"}:
        return ()
    participant = _projection(
        sentence=sentence, sentence_index=sentence_index, match=match,
        answer_group="actor",
        prompt=f"Кто указан как участник предварительного согласования по телефону для «{scope}»?",
        condition=scope, consumed_groups=("scope", "answer"), minimum_answer_chars=5,
    )
    return (projection, participant) if participant is not None else (projection,)


def _remote_complex_review(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalProjection, ...]:
    match = _REMOTE_COMPLEX_REVIEW.fullmatch(sentence)
    if match is None:
        return ()
    actor = match.group("actor").strip()
    locality = match.group("locality").strip()
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="answer",
        prompt=f"Какое согласование проводят «{actor}» для «{locality}»?",
        condition=locality,
        consumed_groups=("actor", "answer"),
    )
    return (projection,) if projection is not None else ()


def _remote_analogy(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalProjection, ...]:
    match = _REMOTE_ANALOGY.fullmatch(sentence)
    if match is None:
        return ()
    locality = match.group("locality").strip()
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="answer",
        prompt=(
            "Какой точно названной процедуре алгоритм действий аналогичен "
            f"при условии «{locality}»?"
        ),
        condition=locality,
        consumed_groups=("scope", "relation"),
    )
    return (projection,) if projection is not None else ()


def _handover_analogy(
    sentence: str,
    sentence_index: int,
) -> tuple[OperationalProjection, ...]:
    match = _HANDOVER_ANALOGY.fullmatch(sentence)
    if match is None:
        return ()
    actor = match.group("actor").strip()
    condition = match.group("condition").strip()
    projection = _projection(
        sentence=sentence,
        sentence_index=sentence_index,
        match=match,
        answer_group="answer",
        prompt=(
            f"На какой точно названный порядок должен ориентироваться «{actor}» "
            f"при условии «{condition}»?"
        ),
        condition=condition,
        consumed_groups=("actor", "condition", "relation"),
    )
    return (projection,) if projection is not None else ()


def is_unresolved_procedure_reference(sentence: str) -> bool:
    """A named analogy supplies no executable steps or independent answer key."""
    return bool(_REMOTE_ANALOGY.fullmatch(sentence) or _HANDOVER_ANALOGY.fullmatch(sentence))


def project_operational_approvals(
    fact: SourceFact,
    source_sentences: Sequence[str],
) -> tuple[OperationalProjection, ...]:
    """Project only complete source-owned approval and explicit-reference rules."""
    sentences = tuple(source_sentences)
    if not sentences or not _are_exact_ordered_spans(fact, sentences):
        return ()

    projectors = (
        _phone_preapproval,
        _general_approval,
        _remote_phone_approval,
        _remote_complex_review,
    )
    result: list[OperationalProjection] = []
    active_branch: tuple[str, ExactSentenceSpan, int] | None = None
    for sentence_index, sentence in enumerate(sentences):
        if _NUMBERED_MARKER.search(sentence):
            active_branch = None
            branch_match = _NUMBERED_LOCAL_BRANCH.search(sentence)
            if branch_match is not None:
                active_branch = (
                    branch_match.group("locality").strip(),
                    _span(sentence, sentence_index, branch_match, "branch"),
                    sentence_index,
                )
        inherited_branch = active_branch
        if inherited_branch is not None:
            branch_index = inherited_branch[2]
            direct = sentence_index == branch_index + 1
            approval_then_refusal = (
                sentence_index == branch_index + 2
                and _APPROVAL_CONTINUATION.fullmatch(sentences[sentence_index - 1])
                is not None
            )
            if not direct and not approval_then_refusal and sentence_index != branch_index:
                inherited_branch = None
        refusal = _refusal(sentence, sentence_index, inherited_branch)
        if refusal:
            result.extend(refusal)
            continue
        for projector in projectors:
            projections = projector(sentence, sentence_index)
            if projections:
                result.extend(projections)
                break
    return tuple(result)
