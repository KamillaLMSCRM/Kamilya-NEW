"""Source-exact typed steps for one bounded rejection follow-up chain."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .models import SourceFact
from .quality import MAX_ASSESSMENT_ANSWER_CHARS

_MAX_REQUIRED_PROMPT_CHARS = 900

_REJECTION_TRIGGER = re.compile(
    r"^(?:\d+(?:\.\d+)*[.)]?\s+)?"
    r"(?P<condition>(?:Если|В\s+случае\s+если)\b[^.!?]+?\bне\s+"
    r"[А-Яа-яЁё-]+(?:ет|ит|ют|ут|ат|ят)(?:ся|сь)?\b[^.!?]*?),\s*"
    r"то\s+[^.!?]*(?:отметк|запис)[^.!?]*[.!?]?$",
    flags=re.IGNORECASE,
)
_DEPENDENT_ACT = re.compile(
    r"^В\s+этом\s+случае\s+"
    r"(?P<answer>(?:составляется|оформляется)\s+"
    r"(?P<document>Акт\s+[^.!?]{3,140}?)\s+"
    r"с\s+расчетом\s+[^.!?]{3,180}?)[.!?]?$",
    flags=re.IGNORECASE,
)
_ACTOR_DOCUMENTS = re.compile(
    r"^(?P<answer>С\s+(?P<actor>[^.!?]{3,140}?),\s+"
    r"берется\s+(?P<first>[^,.!?]{3,100})\s+и\s+"
    r"(?P<second>[^,.!?]{3,100}))[.!?]?$",
    flags=re.IGNORECASE,
)
_RECIPIENT_AND_BASIS = re.compile(
    r"^(?P<first>(?P<documents>[^,.!?]{3,120}?)\s+"
    r"предоставля(?:ется|ются)\s+(?P<recipient>[^,.!?]{3,140}?)),\s+"
    r"на\s+основании\s+которых\s+"
    r"(?P<second>(?P<affected>[^,.!?]{3,140}?)\s+"
    r"(?P<predicate>внос(?:ится|ятся)\s+"
    r"(?P<destination>[^,.!?]{3,120}?)))[.!?]?$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class OperationalStep:
    """One exact source action with its bounded source-owned condition."""

    answer: str
    required_prompt: str
    consumed_sentence_index: int
    governing_sentence_index: int
    governing_condition: str


@dataclass(frozen=True, slots=True)
class ExactSentenceSpan:
    """One exact sentence-relative source span claimed by a projection."""

    sentence_index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class OperationalProjection:
    """Assessment step with only its explicitly consumed source spans."""

    step: OperationalStep
    consumed_spans: tuple[ExactSentenceSpan, ...]


def _are_exact_ordered_spans(fact: SourceFact, sentences: Sequence[str]) -> bool:
    cursor = 0
    for sentence in sentences:
        if not sentence or sentence != sentence.strip():
            return False
        position = fact.value.find(sentence, cursor)
        if position < 0 or fact.value[cursor:position].strip():
            return False
        cursor = position + len(sentence)
    return not fact.value[cursor:].strip()


def _normalized_act_title(value: str) -> str:
    normalized = " ".join(value.casefold().split())
    return re.sub(r"^акты\b", "акт", normalized, count=1)


def _step(
    *,
    answer: str,
    prompt: str,
    sentence: str,
    sentence_index: int,
    governing_sentence_index: int,
    condition: str,
) -> OperationalStep | None:
    if (
        not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS
        or len(prompt) > _MAX_REQUIRED_PROMPT_CHARS
        or answer not in sentence
    ):
        return None
    return OperationalStep(
        answer=answer,
        required_prompt=prompt,
        consumed_sentence_index=sentence_index,
        governing_sentence_index=governing_sentence_index,
        governing_condition=condition,
    )


def project_rejection_followups(
    fact: SourceFact,
    source_sentences: Sequence[str],
) -> tuple[OperationalStep, ...]:
    """Project only consecutive exact follow-ups governed by a rejection condition.

    The caller owns sentence segmentation. A mismatched, reordered, unrelated,
    newly conditioned, or numbered sentence terminates the current chain; no
    context is carried across that boundary.
    """
    sentences = tuple(source_sentences)
    if not sentences or not _are_exact_ordered_spans(fact, sentences):
        return ()

    result: list[OperationalStep] = []
    for trigger_index, trigger_sentence in enumerate(sentences):
        trigger = _REJECTION_TRIGGER.fullmatch(trigger_sentence)
        if trigger is None or trigger_index + 1 >= len(sentences):
            continue
        condition = trigger.group("condition").strip()

        act_index = trigger_index + 1
        act_sentence = sentences[act_index]
        act = _DEPENDENT_ACT.fullmatch(act_sentence)
        if act is None:
            continue
        act_answer = act.group("answer").strip()
        act_step = _step(
            answer=act_answer,
            prompt=(
                "Какой документ оформляется и что он должен содержать при условии "
                f"«{condition}»?"
            ),
            sentence=act_sentence,
            sentence_index=act_index,
            governing_sentence_index=trigger_index,
            condition=condition,
        )
        if act_step is None:
            continue
        chain = [act_step]

        documents_index = act_index + 1
        if documents_index >= len(sentences):
            result.extend(chain)
            continue
        documents_sentence = sentences[documents_index]
        documents = _ACTOR_DOCUMENTS.fullmatch(documents_sentence)
        if documents is None:
            result.extend(chain)
            continue
        documents_answer = documents.group("answer").strip()
        documents_step = _step(
            answer=documents_answer,
            prompt=(
                f"Что необходимо получить с «{documents.group('actor').strip()}» "
                f"при условии «{condition}»?"
            ),
            sentence=documents_sentence,
            sentence_index=documents_index,
            governing_sentence_index=trigger_index,
            condition=condition,
        )
        if documents_step is None:
            result.extend(chain)
            continue
        chain.append(documents_step)

        basis_index = documents_index + 1
        if basis_index >= len(sentences):
            result.extend(chain)
            continue
        basis_sentence = sentences[basis_index]
        basis = _RECIPIENT_AND_BASIS.fullmatch(basis_sentence)
        if basis is None:
            result.extend(chain)
            continue
        if _normalized_act_title(basis.group("documents")) != _normalized_act_title(
            act.group("document")
        ):
            result.extend(chain)
            continue
        first_answer = basis.group("recipient").strip()
        second_answer = basis.group("predicate").strip()
        first_step = _step(
            answer=first_answer,
            prompt=(
                f"Куда предоставляются «{basis.group('documents').strip()}» "
                f"при условии «{condition}»?"
            ),
            sentence=basis_sentence,
            sentence_index=basis_index,
            governing_sentence_index=trigger_index,
            condition=condition,
        )
        second_step = _step(
            answer=second_answer,
            prompt=(
                f"Какое действие выполняется с «{basis.group('affected').strip()}» "
                f"на основании «{basis.group('documents').strip()}» при условии "
                f"«{condition}»?"
            ),
            sentence=basis_sentence,
            sentence_index=basis_index,
            governing_sentence_index=trigger_index,
            condition=condition,
        )
        if first_step is not None and second_step is not None:
            chain.extend((first_step, second_step))
        result.extend(chain)

    return tuple(result)
