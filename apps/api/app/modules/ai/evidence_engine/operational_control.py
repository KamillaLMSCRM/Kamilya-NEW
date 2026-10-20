"""Source-exact projections for closed actor/control responsibility rules."""

from __future__ import annotations

import re

_MAX_KEY_CHARS = 240
_MAX_REQUIRED_PROMPT_CHARS = 900

_CONTROL_RESPONSIBILITY = re.compile(
    r"^(?P<actor>(?-i:[А-ЯЁ][^.!?]{2,400}?)\S)(?:,)?\s+"
    r"(?P<action>(?:контролирует|контролируют)\s+"
    r"соблюдение\s+(?P<rules>правил|"
    r"(?-i:Правил(?:\s+[а-яё-]{3,40}){1,48}\s+безопасности))\s+"
    r"(?:подчин[её]нными\s+им\s+работниками|всем\s+персоналом\s+организации))"
    r"\.$",
    flags=re.IGNORECASE,
)
_UNSAFE_CONTEXT = re.compile(
    r"\b(?:не|ни|если|когда|ежедневно|ежемесячно|ежегодно|периодически|"
    r"при|после|до)\b|\b(?:в\s+случае|во\s+время|в\s+течение|"
    r"кажд(?:ый|ую)\s+(?:день|смену)|по\s+окончании)\b",
    flags=re.IGNORECASE,
)
_AMBIGUOUS_ACTOR = re.compile(r"\b(?:или|либо|и/или)\b", flags=re.IGNORECASE)
_NON_NOMINAL_RULE_SCOPE = re.compile(
    r"\b(?:должен|должна|должны|обязан|обязана|обязаны|необходимо|следует|"
    r"запрещ[а-яё-]*|разреш[а-яё-]*|выполн[а-яё-]*|соблюд[а-яё-]*|"
    r"контролир[а-яё-]*|обеспеч[а-яё-]*|провер[а-яё-]*)\b",
    flags=re.IGNORECASE,
)
_UNRESOLVED_ACTORS = {"он", "она", "оно", "они", "это", "лицо", "работник"}


def project_control_responsibility(value: str) -> tuple[str, str] | None:
    """Return an exact actor key and a prompt containing the complete control action."""

    match = _CONTROL_RESPONSIBILITY.fullmatch(value)
    if match is None:
        return None
    actor = match.group("actor")
    action = match.group("action")
    rules = match.group("rules")
    prompt = (
        "Какой полный перечень лиц прямо указан в источнике для действия "
        f"«{action}»?"
    )
    if (
        len(actor) > _MAX_KEY_CHARS
        or len(prompt) > _MAX_REQUIRED_PROMPT_CHARS
        or _UNSAFE_CONTEXT.search(value)
        or _AMBIGUOUS_ACTOR.search(actor)
        or _NON_NOMINAL_RULE_SCOPE.search(rules)
        or actor.casefold() in _UNRESOLVED_ACTORS
    ):
        return None
    return actor, prompt
