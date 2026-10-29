"""Exact source custody for a coordinator adjacent to an answer boundary."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

_HSPACE = "[" + re.escape(SOURCE_HORIZONTAL_SPACE) + "]"
_RIGHT_BOUNDARY = re.compile(
    rf"^(?P<separator>{_HSPACE}*(?P<punct>[,;]){_HSPACE}*"
    rf"(?:либо|или|но|а|и){_HSPACE}+)\S",
    re.IGNORECASE,
)
_LEFT_BOUNDARY = re.compile(
    rf"^(?P<separator_suffix>{_HSPACE}*(?:либо|или|но|а|и){_HSPACE}+)\S",
    re.IGNORECASE,
)
_RIGHT_AT_OFFSET = re.compile(_RIGHT_BOUNDARY.pattern.removeprefix("^"), re.IGNORECASE)
_LEFT_AT_OFFSET = re.compile(_LEFT_BOUNDARY.pattern.removeprefix("^"), re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CoordinatorBoundaryReceipt:
    """Immutable byte-for-byte receipt; it carries no semantic approval."""

    source_sha256: str
    component_start: int
    component_end: int
    physical_line_end: int
    raw_tail: str
    separator_start: int
    separator_end: int
    separator_quote: str
    punctuation_offset: int
    punctuation_owner: Literal["component", "tail"]


def _physical_line_end(source_text: str, start: int) -> int:
    boundaries = [position for marker in ("\r", "\n")
                  if (position := source_text.find(marker, start)) >= 0]
    return min(boundaries, default=len(source_text))


def has_ambiguous_coordinator_boundary(source_text: str, component: str) -> bool:
    """Detect an ambiguous occurrence with a physical coordinator continuation."""
    if not component or "\r" in component or "\n" in component or component != component.strip():
        return False
    position = source_text.find(component)
    if position < 0 or source_text.find(component, position + 1) < 0:
        return False
    pattern = _LEFT_AT_OFFSET if component[-1] in ",;" else _RIGHT_AT_OFFSET
    while position >= 0:
        if pattern.match(source_text, position + len(component)):
            return True
        position = source_text.find(component, position + 1)
    return False


def prove_source_coordinator_boundary(
    source_text: str,
    component: str,
) -> CoordinatorBoundaryReceipt | None:
    """Prove one exact same-line coordinator without rewriting source text."""
    if (
        not isinstance(source_text, str)
        or not source_text
        or not isinstance(component, str)
        or not component
        or "\r" in component
        or "\n" in component
        or component != component.strip()
        or (start := source_text.find(component)) < 0
        or source_text.find(component, start + 1) >= 0
    ):
        return None
    component_start = start
    component_end = component_start + len(component)
    line_end = _physical_line_end(source_text, component_end)
    raw_tail = source_text[component_end:line_end]
    if component[-1] in ",;":
        match = _LEFT_BOUNDARY.match(raw_tail)
        if match is None:
            return None
        separator_start = component_end - 1
        separator_end = component_end + match.end("separator_suffix")
        punctuation_offset = component_end - 1
        punctuation_owner: Literal["component", "tail"] = "component"
    else:
        match = _RIGHT_BOUNDARY.match(raw_tail)
        if match is None:
            return None
        separator_start = component_end + match.start("separator")
        separator_end = component_end + match.end("separator")
        punctuation_offset = component_end + match.start("punct")
        punctuation_owner = "tail"
    return CoordinatorBoundaryReceipt(
        source_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        component_start=component_start,
        component_end=component_end,
        physical_line_end=line_end,
        raw_tail=raw_tail,
        separator_start=separator_start,
        separator_end=separator_end,
        separator_quote=source_text[separator_start:separator_end],
        punctuation_offset=punctuation_offset,
        punctuation_owner=punctuation_owner,
    )


__all__ = ["CoordinatorBoundaryReceipt", "has_ambiguous_coordinator_boundary", "prove_source_coordinator_boundary"]
