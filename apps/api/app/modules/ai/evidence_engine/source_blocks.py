"""Lossless, source-oriented blocks for narrative evidence extraction."""

from __future__ import annotations

import re

_LIST_OR_NUMBERED_PARAGRAPH_BOUNDARY_RE = re.compile(
    r"(?=^\s*(?:\d+(?:\.\d+)*|[а-яёa-z])[.)]\s+\S)", re.MULTILINE | re.IGNORECASE
)
_BULLET_RE = re.compile(r"^(?:[-*•‣])\s+")
_NUMBERED_BULLET_RE = re.compile(r"^\d+[.)]\s+")
_LETTERED_BULLET_RE = re.compile(r"^[а-яёa-z][.)]\s+", re.IGNORECASE)
_CONTINUATION_RE = re.compile(
    r"^(?:"
    r"исключение\b|при\s+этом|однако|вместе\s+с\s+тем|"
    r"если|в\s+случае|при\s+условии|при\s+этом|"
    r"except(?:ion)?|however|if|unless|provided\s+that|in\s+case\s+of"
    r")\b",
    re.IGNORECASE,
)
_DOCLING_IMAGE_MARKER_RE = re.compile(r"^\s*<!--\s*image\s*-->\s*$", re.IGNORECASE)
_NAVIGATION_HEADING_RE = re.compile(
    r"^\s*(?:contents|table\s+of\s+contents|содержание)\s*:?\s*$",
    re.IGNORECASE,
)
_NUMBERED_ITEM_RE = re.compile(r"^(?P<number>\d+)[.)]\s+")


def _normalize_block(value: str) -> str:
    return " ".join(value.split())


def is_navigation_heading(value: str) -> bool:
    """Return whether a heading is explicit document navigation, not source evidence."""

    return bool(_NAVIGATION_HEADING_RE.fullmatch(value))


def split_narrative_blocks(text: str) -> list[str]:
    """Return normalized, coherent source blocks without sentence-level splitting.

    Blank lines and explicit numbered paragraphs establish candidate boundaries.
    A list introduction remains with its following bullets, and an explicit
    exception or condition remains with the preceding rule.  No content is
    discarded or shortened; a single long paragraph is one complete block.
    """

    blocks: list[str] = []
    next_numbered_list_item: int | None = None
    for source_paragraph in re.split(r"\n\s*\n", text):
        list_active = False
        for numbered_part in _LIST_OR_NUMBERED_PARAGRAPH_BOUNDARY_RE.split(source_paragraph):
            paragraph = _normalize_block(numbered_part)
            if not paragraph or _DOCLING_IMAGE_MARKER_RE.fullmatch(paragraph):
                continue
            is_marker = bool(
                _NUMBERED_BULLET_RE.match(paragraph) or _LETTERED_BULLET_RE.match(paragraph)
            )
            numbered_item = _NUMBERED_ITEM_RE.match(paragraph)
            is_list_item = is_marker and (
                list_active
                or (blocks and blocks[-1].endswith(":"))
                or (
                    numbered_item is not None
                    and next_numbered_list_item == int(numbered_item.group("number"))
                )
            )
            is_bullet = bool(_BULLET_RE.match(paragraph)) or is_list_item
            is_continuation = bool(_CONTINUATION_RE.match(paragraph))
            if blocks and (is_bullet or is_continuation):
                blocks[-1] = f"{blocks[-1]} {paragraph}"
            else:
                blocks.append(paragraph)
            list_active = is_list_item
            next_numbered_list_item = (
                int(numbered_item.group("number")) + 1
                if numbered_item is not None and is_list_item
                else None
            )
    return blocks
