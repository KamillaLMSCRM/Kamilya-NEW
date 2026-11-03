"""Source-exact signing-event responsibility projections."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .models import SourceFact
from .operational_steps import OperationalStep, _are_exact_ordered_spans
from .quality import MAX_ASSESSMENT_ANSWER_CHARS

_MAX_REQUIRED_PROMPT_CHARS = 900

_SIGNING_RESPONSIBILITY = re.compile(
    r"^(?P<event>Подписанием\s+[^.!?]{3,260}?"
    r"(?:\s+и\s+|,\s*а\s+так\s+же\s+)"
    r"проставлением\s+[^.!?]{3,300}?),\s*(?:и\s+)?"
    r"(?P<actor>лицо,\s+согласовавшее\s+[^,.!?]{3,120}),\s+"
    r"подтверждает\s+"
    r"(?P<answer>принятие\s+на\s+себя\s+[^.!?]{3,160}?"
    r"\bответственности\s+"
    r"(?P<condition>в\s+случае\s+[^.!?]*\bнесоответств[А-Яа-яЁё-]*\b[^.!?]+))"
    r"[.!?]?$",
    flags=re.IGNORECASE,
)


def project_signing_responsibilities(
    fact: SourceFact,
    source_sentences: Sequence[str],
) -> tuple[OperationalStep, ...]:
    """Project complete joint signing/recording events into exact responsibility keys."""
    sentences = tuple(source_sentences)
    if not sentences or not _are_exact_ordered_spans(fact, sentences):
        return ()

    result: list[OperationalStep] = []
    for sentence_index, sentence in enumerate(sentences):
        match = _SIGNING_RESPONSIBILITY.fullmatch(sentence)
        if match is None:
            continue
        event = match.group("event").strip()
        actor = match.group("actor").strip()
        answer = match.group("answer").strip()
        condition = match.group("condition").strip()
        prompt = f"Что подтверждает «{actor}» событием «{event}»?"
        if (
            not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS
            or len(prompt) > _MAX_REQUIRED_PROMPT_CHARS
            or answer not in sentence
            or event not in sentence
            or actor not in sentence
            or condition not in answer
        ):
            continue
        result.append(OperationalStep(
            answer=answer,
            required_prompt=prompt,
            consumed_sentence_index=sentence_index,
            governing_sentence_index=sentence_index,
            governing_condition=condition,
        ))
    return tuple(result)
