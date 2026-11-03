"""Lossless source spans for planning rule extraction, not semantic approval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_TABLE_SEPARATOR = re.compile(r"^\s*\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_DISPLAY_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SECTION_START = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+|\*\*\s*\d+(?:\.\d+)*[.)][^\r\n]*\*\*|\d+(?:\.\d+)*[.)][ \t]+)")
_MARKDOWN_NUMBERED_SECTION = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+\d+(?:\.\d+)*[.)][ \t]+[^\r\n]*")
_NUMBERED_PARENT = re.compile(r"^\s*\d+(?:\.\d+)*\.[ \t]+")
_NUMBERED_CHILD = re.compile(r"^\s*\d+\)[ \t]+")


@dataclass(frozen=True, slots=True)
class SourceUnit:
    start: int
    end: int
    text: str
    kind: Literal["prose", "table_header", "table_row"]
    context: str = ""
    container_id: str = ""


def source_table_topic(unit: SourceUnit) -> str:
    """Return the literal label of one unambiguously labelled table row.

    A label is structural navigation, not proof that a row is independent.
    Unlabelled and multi-row spans deliberately remain unsplit.
    """
    if unit.kind != "table_row" or not unit.container_id:
        return ""
    lines = [line.strip() for line in unit.text.splitlines() if line.lstrip().startswith("|")]
    separators = [i for i, line in enumerate(lines) if _TABLE_SEPARATOR.fullmatch(line)]
    rows = lines[separators[-1] + 1:] if separators else lines
    candidates: list[list[str]] = []
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if cells and not all(re.fullmatch(r"\*\*.+?\*\*", cell) for cell in cells):
            candidates.append(cells)
    if len(candidates) != 1:
        return ""
    label = candidates[0][0].strip().strip("*").strip()
    if not label or len(label) > 120 or _DISPLAY_BREAK.search(label):
        return ""
    return label


def plan_source_units(text: str) -> tuple[SourceUnit, ...]:
    """Partition exact source spans; table rows carry their literal header.

    This is a structural inventory, not proof that rows are semantically
    independent or that a cell, a cross-reference, or the associated condition
    can safely be extracted in isolation. Never split a long row to fit a limit.
    """
    if not text:
        return ()
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    units: list[SourceUnit] = []

    def append_prose(start: int, end: int) -> None:
        section_starts = [start + match.start() for match in _SECTION_START.finditer(text[start:end])]
        if section_starts:
            boundaries = [start, *(value for value in section_starts if value > start), end]
            for left, right in zip(boundaries, boundaries[1:], strict=False):
                units.append(SourceUnit(left, right, text[left:right], "prose"))
            return
        position = start
        for separator in re.finditer(r"\r?\n[ \t]*\r?\n", text[start:end]):
            boundary = start + separator.end()
            units.append(SourceUnit(position, boundary, text[position:boundary], "prose"))
            position = boundary
        if position < end:
            units.append(SourceUnit(position, end, text[position:end], "prose"))

    prose_start = 0
    index = 0
    while index + 1 < len(lines):
        if not (lines[index].lstrip().startswith("|") and _TABLE_SEPARATOR.fullmatch(lines[index + 1].strip())):
            index += 1
            continue
        if prose_start < offsets[index]:
            append_prose(prose_start, offsets[index])
        header_start = offsets[index]
        header_end = offsets[index + 2]
        header = text[header_start:header_end]
        container_id = f"table:{header_start}:{header_end}"
        units.append(SourceUnit(header_start, header_end, header, "table_header", container_id=container_id))
        index += 2
        row_context = header
        header_cells = lines[index - 2].strip().strip("|").split("|")
        if index < len(lines) and all(not cell.strip() for cell in header_cells):
            first_cells = lines[index].strip().strip("|").split("|")
            if first_cells and all(re.fullmatch(r"\s*\*\*.+?\*\*\s*", cell) for cell in first_cells):
                row_context += lines[index]
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            start, end = offsets[index], offsets[index + 1]
            units.append(SourceUnit(start, end, text[start:end], "table_row", row_context, container_id))
            index += 1
        prose_start = offsets[index]
    if prose_start < len(text):
        append_prose(prose_start, len(text))
    return tuple(units)


def coalesce_table_headers(units: tuple[SourceUnit, ...], source: str) -> tuple[SourceUnit, ...]:
    """Pair table headings and any adjacent section title with first data row."""
    result: list[SourceUnit] = []
    index = 0
    while index < len(units):
        unit = units[index]
        if (unit.kind == "table_header" and index + 1 < len(units)
                and units[index + 1].kind == "table_row"
                and units[index + 1].container_id == unit.container_id
                and unit.end == units[index + 1].start):
            row = units[index + 1]
            consumed = 2
            header_cells = unit.text.splitlines()[0].strip().strip("|").split("|")
            row_cells = row.text.strip().strip("|").split("|")
            if (all(not cell.strip() for cell in header_cells) and row_cells
                    and all(re.fullmatch(r"\s*\*\*.+?\*\*\s*", cell) for cell in row_cells)
                    and index + 2 < len(units) and units[index + 2].kind == "table_row"
                    and units[index + 2].container_id == unit.container_id
                    and row.end == units[index + 2].start):
                row = units[index + 2]
                consumed = 3
            start = unit.start
            if result and result[-1].kind == "prose" and result[-1].end == start:
                lines = [line for line in result[-1].text.splitlines() if line.strip()]
                if len(lines) == 1 and _SECTION_START.match(lines[0]):
                    start = result.pop().start
            result.append(SourceUnit(start, row.end, source[start:row.end], "table_row",
                                     container_id=unit.container_id))
            index += consumed
            continue
        result.append(unit)
        index += 1
    return tuple(result)


def coalesce_leading_context(units: tuple[SourceUnit, ...], source: str) -> tuple[SourceUnit, ...]:
    """Keep material before the first explicit section with that section."""
    if len(units) < 2:
        return units
    first, second = units[:2]
    if (first.kind != "prose" or second.kind != "prose" or first.end != second.start
            or _SECTION_START.match(first.text) or not _SECTION_START.match(second.text)):
        return units
    return (SourceUnit(first.start, second.end, source[first.start:second.end], "prose"), *units[2:])


def coalesce_structural_prose(units: tuple[SourceUnit, ...], source: str, *,
                              allow_single_section: bool = False) -> tuple[SourceUnit, ...]:
    """Group explicit sections and their nested lists without arbitrary size cuts.

    This is enabled only when the source has multiple numbered Markdown section
    headings. It does not infer semantic independence or source completeness.
    """
    if len(list(_MARKDOWN_NUMBERED_SECTION.finditer(source))) < 2:
        return units
    major = [i for i, unit in enumerate(units)
             if unit.kind == "prose" and _MARKDOWN_NUMBERED_SECTION.match(unit.text)]
    # A caller that already bounded an original major-section window may opt in
    # without fabricating another heading outside that contiguous source window.
    if len(major) < (1 if allow_single_section else 2):
        return units
    first = major[0]
    work = list(units)
    if first and all(unit.kind == "prose" for unit in units[:first]):
        work = [SourceUnit(work[0].start, work[first].end, source[work[0].start:work[first].end], "prose"),
                *work[first + 1:]]

    result: list[SourceUnit] = []
    buffer: list[SourceUnit] = []
    buffer_has_body = False

    def flush() -> None:
        nonlocal buffer, buffer_has_body
        if buffer:
            result.append(SourceUnit(buffer[0].start, buffer[-1].end,
                                     source[buffer[0].start:buffer[-1].end], "prose"))
        buffer, buffer_has_body = [], False

    index = 0
    while index < len(work):
        unit = work[index]
        if unit.kind != "prose":
            flush()
            result.append(unit)
            index += 1
            continue
        is_major = bool(_MARKDOWN_NUMBERED_SECTION.match(unit.text))
        is_heading = bool(re.match(r"\s*#{1,6}[ \t]+", unit.text))
        if is_major or (is_heading and buffer_has_body):
            flush()
        has_children = (bool(_NUMBERED_PARENT.match(unit.text)) and index + 1 < len(work)
                        and work[index + 1].kind == "prose" and bool(_NUMBERED_CHILD.match(work[index + 1].text)))
        if has_children:
            if buffer_has_body:
                flush()
            buffer.append(unit)
            index += 1
            while index < len(work) and work[index].kind == "prose" and _NUMBERED_CHILD.match(work[index].text):
                buffer.append(work[index])
                index += 1
            flush()
            continue
        buffer.append(unit)
        if not is_heading and not is_major and _NUMBERED_PARENT.match(unit.text):
            buffer_has_body = True
        index += 1
    flush()
    return tuple(result)


def source_section_label(source: str, unit: SourceUnit) -> str:
    """Return a stable source heading identity, or empty when none is present.

    Heading identity is structural navigation, not proof of semantic completeness.
    """
    markdown_sections = list(_MARKDOWN_NUMBERED_SECTION.finditer(source))
    matches = ([match for match in markdown_sections if match.start() < unit.end]
               if len(markdown_sections) >= 2 else list(_SECTION_START.finditer(source, 0, unit.end)))
    if not matches:
        return ""
    match = matches[-1]
    line = source[match.start():].splitlines()[0].strip().lstrip("#").strip().strip("*").strip()
    numbered = re.match(r"(\d+(?:\.\d+)*)[.)](?:\s|$)", line)
    if numbered:
        return f"Раздел {numbered.group(1)}"
    return line.lstrip("#").strip()


def _rendered_projection(text: str) -> tuple[str, list[int]]:
    """Project a narrow set of display markers with reversible source offsets.

    This is candidate retrieval only. Removing Markdown markers can be ambiguous
    (for example in formulas), so it must never by itself certify a quotation.
    """
    chars: list[str] = []
    offsets: list[int] = []
    position = 0
    pending_space: int | None = None
    while position < len(text):
        marker = _DISPLAY_BREAK.match(text, position)
        if marker:
            if chars and pending_space is None:
                pending_space = position
            position = marker.end()
            continue
        if text.startswith("**", position):
            position += 2
            continue
        char = text[position]
        if char.isspace() or char == "|":
            if chars and pending_space is None:
                pending_space = position
        else:
            if pending_space is not None:
                chars.append(" ")
                offsets.append(pending_space)
                pending_space = None
            for lowered in char.lower():
                chars.append(lowered)
                offsets.append(position)
        position += 1
    return "".join(chars), offsets


def find_rendered_quote_spans(source: str, quote: str) -> list[tuple[int, int]]:
    """Return possible source-coordinate matches; the caller must review them."""
    haystack, offsets = _rendered_projection(source)
    needle, _ = _rendered_projection(quote)
    if not needle:
        return []
    result: list[tuple[int, int]] = []
    start = 0
    while (index := haystack.find(needle, start)) >= 0:
        result.append((offsets[index], offsets[index + len(needle) - 1] + 1))
        start = index + 1
    return result


def rendered_candidate_preserves_table_boundaries(source_slice: str, quote: str) -> bool:
    """Reject projected candidates that remove or relocate a table delimiter."""
    source_parts, quote_parts = source_slice.split("|"), quote.split("|")
    return len(source_parts) == len(quote_parts) and all(
        _rendered_projection(left)[0] == _rendered_projection(right)[0]
        for left, right in zip(source_parts, quote_parts, strict=True)
    )
