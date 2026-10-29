"""Fail-closed source-layout proof for one governed checklist leaf.

This module proves only physical source custody.  It does not classify the owner
line as an actor, establish the governor's meaning, or admit the leaf as true.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE, parse_source_marker

_HSPACE = "[" + re.escape(SOURCE_HORIZONTAL_SPACE) + "]"
_WORD = r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)?"
_VALUE = r"[0-9]+(?:[,.][0-9]+)?(?:[А-Яа-яЁёA-Za-z]+)?"
_TOKEN = r"(?:" + _WORD + r"|" + _VALUE + r"|[A-Za-z]+)"
# Physical custody only, never meaning: quantities and abbreviations may occur
# inside a Cyrillic-leading comma-separated nominal checklist body.
_LEAF_BODY = _WORD + r"(?:,?" + _HSPACE + r"+" + _TOKEN + r")*"
_COMPONENT = re.compile(_LEAF_BODY + r"[,;.]?")
_NEWLINE = re.compile(r"\r\n|\r|\n")
_MAX_SOURCE_CHARS = 65_536
_MAX_ANCHOR_CHARS = 1_024


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class ChecklistLeafLayoutProof:
    owner: SourceSpan
    governor: SourceSpan
    leaf: SourceSpan
    source_sha256: str


@dataclass(frozen=True)
class _PhysicalLine:
    start: int
    content_end: int
    end: int
    text: str


def _physical_lines(source_text: str) -> tuple[_PhysicalLine, ...]:
    lines: list[_PhysicalLine] = []
    start = 0
    while start < len(source_text):
        boundary = _NEWLINE.search(source_text, start)
        if boundary is None:
            content_end = len(source_text)
            end = content_end
        else:
            content_end = boundary.start()
            end = boundary.end()
        lines.append(_PhysicalLine(start, content_end, end, source_text[start:content_end]))
        start = end
    return tuple(lines)


def _same_level_leaf(line: str, indent: str, marker: str) -> bool:
    return re.fullmatch(
        re.escape(indent + marker) + _HSPACE + r"+" + _LEAF_BODY + r"[,;.]?" + _HSPACE + r"*",
        line,
    ) is not None


def prove_checklist_leaf_layout(
    source_text: object,
    component: object,
) -> ChecklistLeafLayoutProof | None:
    """Return exact spans only for an unambiguous physical checklist layout.

    Semantic owner identity, role, truth, and target admission deliberately stay
    outside this helper. ``leaf`` is the selected component's exact source span;
    punctuation omitted by the caller remains outside that span even though the
    surrounding physical leaf is proven complete. Unsupported or ambiguous source
    shapes return ``None``.
    """
    if (
        not isinstance(source_text, str)
        or not source_text
        or len(source_text) > _MAX_SOURCE_CHARS
        or not isinstance(component, str)
        or not component
        or len(component) > 240
        or source_text.count(component) != 1
    ):
        return None

    component_start = source_text.find(component)
    lines = _physical_lines(source_text)
    leaf_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.start <= component_start < line.content_end
        ),
        None,
    )
    if leaf_index is None:
        return None

    leaf_line = lines[leaf_index]
    if _COMPONENT.fullmatch(component) is not None:
        punctuation = "" if component[-1] in ",;." else r"[,;.]?"
        leaf_match = re.fullmatch(
            r"(?P<indent>" + _HSPACE + r"*)(?P<marker>[-–—•])" + _HSPACE + r"+"
            r"(?P<component>" + re.escape(component) + r")"
            + punctuation
            + _HSPACE + r"*",
            leaf_line.text,
        )
        component_group = "component"
    else:
        # A marked answer must own the complete physical leaf after indentation;
        # unlike the body form, it cannot omit punctuation or any body bytes.
        leaf_match = re.fullmatch(
            r"(?P<indent>" + _HSPACE + r"*)(?P<component>"
            r"(?P<marker>[-–—•])" + _HSPACE + r"+" + _LEAF_BODY + r"[,;.]?)"
            + _HSPACE + r"*",
            leaf_line.text,
        )
        component_group = "component"
        if leaf_match is not None and leaf_match.group(component_group) != component:
            return None
    if leaf_match is None:
        return None
    exact_component_start = leaf_line.start + leaf_match.start(component_group)
    if exact_component_start != component_start:
        return None

    indent = leaf_match.group("indent")
    marker = leaf_match.group("marker")
    block_start = leaf_index
    while block_start > 0 and _same_level_leaf(lines[block_start - 1].text, indent, marker):
        block_start -= 1

    governor_index = block_start - 1
    owner_index = governor_index - 1
    if owner_index < 0:
        return None
    governor_line = lines[governor_index]
    owner_line = lines[owner_index]

    governor_indent = governor_line.text[:len(governor_line.text) - len(governor_line.text.lstrip(SOURCE_HORIZONTAL_SPACE))]
    governor_marker = parse_source_marker(governor_line.text)
    if governor_marker is not None and governor_marker.decoration:
        return None
    quote_offset = governor_marker.content_start if governor_marker is not None else len(governor_indent)
    governor_quote = governor_line.text[quote_offset:].rstrip(SOURCE_HORIZONTAL_SPACE)
    if (
        not governor_quote.endswith(":")
        or not governor_quote[0].isalpha()
        or not governor_quote[:-1].strip()
        or not indent.startswith(governor_indent)
        or len(governor_quote) > _MAX_ANCHOR_CHARS
    ):
        return None

    owner_quote = owner_line.text.rstrip(SOURCE_HORIZONTAL_SPACE)
    if (
        not owner_quote.strip()
        or len(owner_quote) > _MAX_ANCHOR_CHARS
        or re.match(_HSPACE + r"*[-–—•]" + _HSPACE + r"+", owner_quote) is not None
    ):
        return None

    # Each returned quote must identify one source span, never a nearby duplicate.
    if source_text.count(owner_quote) != 1 or source_text.count(governor_quote) != 1:
        return None

    if leaf_index + 1 < len(lines):
        following_index = leaf_index + 1
        following = lines[following_index].text
        same_level_prefix = re.escape(indent + marker) + _HSPACE + r"+"
        next_marker = parse_source_marker(following)
        if (
            following.strip()
            and re.match(same_level_prefix, following) is None
            and not (next_marker is not None and not next_marker.decoration
                     and next_marker.family == "numeric" and next_marker.raw_start == 0)
        ):
            return None
        if not following.strip():
            while following_index < len(lines) and not lines[following_index].text.strip():
                following_index += 1
            if (
                following_index < len(lines)
                and re.match(_HSPACE + r"+", lines[following_index].text) is not None
            ):
                return None

    owner_start = owner_line.start
    owner_end = owner_line.start + len(owner_quote)
    governor_start = governor_line.start + quote_offset
    governor_end = governor_start + len(governor_quote)
    component_end = component_start + len(component)
    return ChecklistLeafLayoutProof(
        owner=SourceSpan(owner_start, owner_end, owner_quote),
        governor=SourceSpan(governor_start, governor_end, governor_quote),
        leaf=SourceSpan(component_start, component_end, component),
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
    )
