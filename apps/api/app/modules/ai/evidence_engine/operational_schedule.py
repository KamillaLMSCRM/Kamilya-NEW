"""Source-owned contracts for closed instruction-schedule projections.

The helpers in this module only describe a schedule already matched by the
assessment-axis producer.  They never infer source truth from provider wording
and the option helper can only reject a provably compatible distractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

EVENT_TIME_LITERAL = "event_time_literal"
MINIMUM_FREQUENCY_LITERAL = "minimum_frequency_literal"


@dataclass(frozen=True, slots=True)
class InstructionScheduleContract:
    kind: str
    actor: str
    activity: str
    correct_value: str
    required_prompt: str
    minimum_yearly_count: int | None


_INSTRUCTION_ACTION = re.compile(
    r"проходят\s+(?P<activity>(?:противопожарный\s+)?инструктаж"
    r"(?:\s+по\s+[^.!?;:\r\n]{2,180})?)",
    flags=re.IGNORECASE,
)
_HIRING_EVENT = re.compile(r"при\s+приеме\s+на\s+работу", flags=re.IGNORECASE)
_YEARLY_MINIMUM = re.compile(
    r"не\s+реже\s+(?P<count>\d+)\s+раз[а]?\s+в\s+год",
    flags=re.IGNORECASE,
)

_SMALL_NUMBER = {
    "один": 1,
    "одного": 1,
    "два": 2,
    "двух": 2,
    "три": 3,
    "трех": 3,
    "четыре": 4,
    "четырех": 4,
}
_NUMBER_TOKEN = r"\d+|один|одного|два|двух|три|трех|четыре|четырех"
_CALENDAR_RATE = re.compile(
    rf"(?:(?:не\s+реже)\s+)?"
    rf"(?:(?P<count>{_NUMBER_TOKEN})\s+)?(?P<occurrence>раз|раза)\s+в\s+"
    rf"(?:(?P<span>{_NUMBER_TOKEN})\s+)?"
    r"(?P<period>месяц|месяца|месяцев|квартал|квартала|кварталов|год|года|лет)"
    r"(?:\s+после\s+трудоустройства)?",
    flags=re.IGNORECASE,
)
_CALENDAR_ADVERB_RATE = {
    "ежемесячно": Fraction(12, 1),
    "ежеквартально": Fraction(4, 1),
    "ежегодно": Fraction(1, 1),
}
_PERIODS_PER_YEAR = {
    "month": Fraction(12, 1),
    "quarter": Fraction(4, 1),
    "year": Fraction(1, 1),
}
_HIRING_ENCLOSING_WINDOW = re.compile(
    r"(?:"
    r"в\s+течение\s+перв(?:ого|ой)\s+(?:рабоч(?:его|ей)\s+)?"
    r"(?:дня|недели|месяца)(?:\s+работы)?(?:\s+после\s+трудоустройства)?"
    r"|в\s+перв(?:ый|ую)\s+(?:рабоч(?:ий|ую)\s+)?"
    r"(?:день|неделю|месяц)(?:\s+работы)?(?:\s+после\s+трудоустройства)?"
    r")",
    flags=re.IGNORECASE,
)


def _normalized_closed_option(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").strip().rstrip(".").split())


def _small_integer(value: str | None, *, default: int) -> int | None:
    if value is None:
        return default
    if value.isdigit():
        number = int(value)
        return number if number > 0 else None
    return _SMALL_NUMBER.get(value)


def _calendar_period(value: str) -> str | None:
    if value.startswith("месяц"):
        return "month"
    if value.startswith("квартал"):
        return "quarter"
    if value in {"год", "года", "лет"}:
        return "year"
    return None


def _calendar_rate_per_year(option: str) -> Fraction | None:
    normalized = _normalized_closed_option(option)
    if normalized in _CALENDAR_ADVERB_RATE:
        return _CALENDAR_ADVERB_RATE[normalized]
    match = _CALENDAR_RATE.fullmatch(normalized)
    if match is None:
        return None
    count = _small_integer(match.group("count"), default=1)
    span = _small_integer(match.group("span"), default=1)
    period = _calendar_period(match.group("period"))
    if count is None or span is None or period is None:
        return None
    if match.group("count") is None and match.group("occurrence") != "раз":
        return None
    return Fraction(count, span) * _PERIODS_PER_YEAR[period]


def project_instruction_schedule(
    actor: str,
    action: str,
    timing: str,
) -> InstructionScheduleContract | None:
    """Project the two closed schedule forms owned by the existing producer."""
    if any(value != value.strip() or not value for value in (actor, action, timing)):
        return None
    if any(marker in actor + action for marker in ("\r", "\n", "«", "»")):
        return None
    action_match = _INSTRUCTION_ACTION.fullmatch(action)
    if action_match is None:
        return None
    activity = action_match.group("activity")
    if _HIRING_EVENT.fullmatch(timing):
        return InstructionScheduleContract(
            kind=EVENT_TIME_LITERAL,
            actor=actor,
            activity=activity,
            correct_value=timing,
            required_prompt=(
                f"Какой именно момент прохождения «{activity}» прямо установлен "
                f"для категории «{actor}»?"
            ),
            minimum_yearly_count=None,
        )
    minimum = _YEARLY_MINIMUM.fullmatch(timing)
    if minimum is None:
        return None
    minimum_count = int(minimum.group("count"))
    if minimum_count <= 0:
        return None
    return InstructionScheduleContract(
        kind=MINIMUM_FREQUENCY_LITERAL,
        actor=actor,
        activity=activity,
        correct_value=timing,
        required_prompt=(
            f"Какая минимальная периодичность прохождения «{activity}» прямо "
            f"установлена для категории «{actor}»?"
        ),
        minimum_yearly_count=minimum_count,
    )


def instruction_schedule_option_rejection(
    contract: InstructionScheduleContract,
    option: str,
) -> str | None:
    """Reject a provably compatible wrong option; never accept an option."""
    normalized = _normalized_closed_option(option)
    if not normalized:
        return None
    if contract.kind == EVENT_TIME_LITERAL:
        if _HIRING_ENCLOSING_WINDOW.fullmatch(normalized):
            return "instruction_schedule_event_window_includes_required_event"
        if _calendar_rate_per_year(normalized) is not None:
            return "instruction_schedule_recurring_timing_does_not_replace_event"
        return None
    if (
        contract.kind == MINIMUM_FREQUENCY_LITERAL
        and contract.minimum_yearly_count is not None
        and contract.minimum_yearly_count > 0
    ):
        candidate_rate = _calendar_rate_per_year(normalized)
        if (
            candidate_rate is not None
            and candidate_rate >= contract.minimum_yearly_count
        ):
            return "instruction_schedule_frequency_still_meets_minimum"
    return None


__all__ = [
    "EVENT_TIME_LITERAL",
    "MINIMUM_FREQUENCY_LITERAL",
    "InstructionScheduleContract",
    "instruction_schedule_option_rejection",
    "project_instruction_schedule",
]
