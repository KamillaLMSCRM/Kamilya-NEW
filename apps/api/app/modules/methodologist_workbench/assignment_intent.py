"""Deterministic parser for the bounded assignment instruction contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MAX_INSTRUCTION_LENGTH = 4000
_COMMAND_RE = re.compile(
    r'^Назначь курс (?:("(?P<title_straight>[^"\r\n]+)")|(«(?P<title_guillemet>[^»\r\n]+)»)) '
    r'отделу (?:("(?P<department_straight>[^"\r\n]+)")|(«(?P<department_guillemet>[^»\r\n]+)»)) '
    r"до (?P<deadline>\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAssignment:
    """The only executable data produced by the local assignment parser."""

    course_query: str
    department_query: str
    due_at: datetime
    timezone_name: str


def _parse_deadline(value: str) -> date:
    try:
        if "." in value:
            return datetime.strptime(value, "%d.%m.%Y").date()
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("deadline_invalid") from exc


def parse_assignment_instruction(instruction: str, timezone_name: str, now: datetime) -> ParsedAssignment:
    """Parse one exact assignment command and return its future local deadline.

    This deliberately does not trim, normalize, infer, or interpret natural
    language. Any deviation from the bounded command shape is unsupported.
    """

    if not isinstance(instruction, str) or not instruction or len(instruction) > _MAX_INSTRUCTION_LENGTH:
        raise ValueError("instruction_unsupported")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("timezone_invalid")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("context_invalid")
    try:
        zone = ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("timezone_invalid") from exc

    match = _COMMAND_RE.fullmatch(instruction)
    if match is None:
        raise ValueError("instruction_unsupported")

    course_query = match.group("title_straight") or match.group("title_guillemet")
    department_query = match.group("department_straight") or match.group("department_guillemet")
    if course_query is None or not course_query.strip() or department_query is None or not department_query.strip():
        raise ValueError("instruction_unsupported")

    deadline = _parse_deadline(match.group("deadline"))
    due_at = datetime.combine(deadline, time(23, 59, 59), tzinfo=zone)
    if due_at <= now:
        raise ValueError("deadline_passed")
    return ParsedAssignment(course_query, department_query, due_at, timezone_name)
