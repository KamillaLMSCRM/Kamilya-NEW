"""Lossless, source-oriented blocks for narrative evidence extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.modules.ai.ingestion import is_sentence_like_ordinal_heading
from app.modules.ai.source_layout import parse_source_marker, split_marker_paragraphs

_CONTINUATION_RE = re.compile(
    r"^(?:"
    r"исключение\b|при\s+этом|однако|вместе\s+с\s+тем|"
    r"если|в\s+случае|при\s+условии|при\s+этом|"
    r"except(?:ion)?|however|if|unless|provided\s+that|in\s+case\s+of"
    r")\b",
    re.IGNORECASE,
)
_DOCLING_IMAGE_MARKER_RE = re.compile(r"^\s*<!--\s*image\s*-->\s*$", re.IGNORECASE)
_DOCLING_SPECK_METADATA_RE = re.compile(r"^\s*<!-- source-speck U\+[0-9A-F]{4,6}(?: U\+[0-9A-F]{4,6}){0,2} -->\s*$")
_DOCLING_BACKTICK_SPECK_RE = re.compile(r"^`+$")
_NAVIGATION_HEADING_RE = re.compile(
    r"^\s*(?:contents|table\s+of\s+contents|содержание)\s*:?\s*$",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_LINE_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+[^\r\n]*(?:\r?\n|$)")
_UPPERCASE_WRAP_CONNECTORS = frozenset(
    {"без", "в", "для", "до", "из", "к", "на", "от", "по", "при", "с"}
)
_SOFT_COLON_CHILD_RE = re.compile(
    r"^(?:"
    r"по\b|на\b|пут[её]м\b|посредством\b|через\b|с\s*использованием\b|"
    r"(?:[^\W\d_]+\s+){1,5}(?:бойынша|арқылы|көмегімен)\b"
    r")",
    re.IGNORECASE | re.UNICODE,
)
_PRESCRIPTIVE_MODAL_RE = re.compile(
    r"\b(?:"
    r"обязан(?:а|о|ы)?|должен|должна|должно|должны|необходимо|следует|"
    r"міндетті|тиіс"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_LITERAL_FLAT_LIST_MAX_SOURCE_CHARS = 8_192
_LITERAL_FLAT_LIST_MAX_QUOTE_CHARS = 2_000
_LITERAL_FLAT_LIST_MAX_LINES = 96


class _ListFamily(Enum):
    """Established list grammar that may survive a blank source paragraph."""

    NUMERIC_CHILD = "numeric_child"
    OPERATIVE_NUMERIC_LIST = "operative_numeric_list"
    LETTER_CHILD = "letter_child"
    BULLET = "bullet"


@dataclass(slots=True)
class _ListState:
    family: _ListFamily
    last_ordinal: int | None = None


@dataclass(slots=True)
class _OwnerScope:
    value: str
    family: _ListFamily | None = None
    last_ordinal: int | None = None
    exportable: bool = True
    soft_children_open: bool = False


@dataclass(frozen=True, slots=True)
class NarrativeSourceBlock:
    """One exact source clause with any proved literal list governors."""

    clause: str
    owner_context: tuple[str, ...] = ()

    @property
    def evidence_text(self) -> str:
        """Return the self-contained literal text used by evidence consumers."""

        return "\n".join((*self.owner_context, self.clause))


def _normalize_block(value: str) -> str:
    return " ".join(value.split())


def is_navigation_heading(value: str) -> bool:
    """Return whether a heading is explicit document navigation, not source evidence."""

    return bool(_NAVIGATION_HEADING_RE.fullmatch(value))


def _terminal_colon_layout_view(value: str) -> str:
    """Recognize one isolated unmatched OCR closer, without changing source bytes."""
    match = re.search(r":\s+([)\]}])$", value)
    if match:
        prefix = value[:match.start(1)]
        opening, closing = "([{", { ")": "(", "]": "[", "}": "{" }
        stack = []
        for character in prefix:
            if character in opening:
                stack.append(character)
            elif character in closing:
                if not stack or stack.pop() != closing[character]:
                    return value
        if not stack:
            return value[:match.start(1)].rstrip()
    return value


def _has_terminal_colon(value: str) -> bool:
    if value.endswith(":"):
        return True
    view = _terminal_colon_layout_view(value)
    return view != value and _is_operative_colon_governor(view)


def _is_operative_colon_governor(value: str) -> bool:
    """Recognize a bounded action clause, never a colon-only nominal heading."""

    value = _terminal_colon_layout_view(value)
    if not value.endswith(":"):
        return False
    body = value[:-1].strip()
    if is_sentence_like_ordinal_heading(f"1. {body}"):
        return True

    words = re.findall(r"[^\W\d_]+", body.casefold().replace("ё", "е"), re.UNICODE)
    if len(words) >= 2 and body[-1:].isalpha() and words[-1] in {
        "обязан", "обязана", "обязаны", "обязано",
        "должен", "должна", "должны", "должно", "необходимо", "следует",
    }:
        return True
    if len(words) >= 3 and words[-1].endswith(("ады", "еді", "йды", "йді")):
        return True

    # Converted English context clauses commonly put the actor and base-form
    # action after a comma. Reuse the shared action heuristic for the predicate;
    # arbitrary two-word nominal headings do not establish list ownership.
    tail = body.rsplit(",", 1)[-1].strip()
    tail_words = re.findall(r"[^\W\d_]+", tail.casefold(), re.UNICODE)
    return bool(
        "," in body
        and len(tail_words) >= 2
        and is_sentence_like_ordinal_heading(f"1. {tail_words[-1]}")
    )


def _structured_marker(value: str) -> tuple[_ListFamily, int | None] | None:
    marker = parse_source_marker(value)
    if marker is None:
        return None
    if marker.family == "bullet":
        return (_ListFamily.BULLET, None)
    if marker.family == "letter":
        return (_ListFamily.LETTER_CHILD, None)
    if marker.family != "numeric" or len(marker.numeric_path) != 1:
        return None
    raw_marker = marker.raw_marker.rstrip()
    family = (
        _ListFamily.NUMERIC_CHILD
        if raw_marker.endswith((")", ","))
        else _ListFamily.OPERATIVE_NUMERIC_LIST
    )
    return (family, marker.numeric_path[0])


def literal_flat_list_parts(
    source: str,
) -> tuple[str, tuple[str, ...]] | None:
    """Return one exact operative header and its proved flat sibling lines."""

    if (
        not isinstance(source, str)
        or not source
        or len(source) > _LITERAL_FLAT_LIST_MAX_SOURCE_CHARS
        or "\x00" in source
    ):
        return None
    lines = source.splitlines()
    if not 3 <= len(lines) <= _LITERAL_FLAT_LIST_MAX_LINES:
        return None
    nonblank_indexes = [index for index, line in enumerate(lines) if line.strip()]
    if len(nonblank_indexes) < 3:
        return None
    first, last = nonblank_indexes[0], nonblank_indexes[-1]
    literal_lines = lines[first : last + 1]
    if any(not line.strip() for line in literal_lines):
        return None

    header, *leaf_lines = literal_lines
    if not _is_operative_colon_governor(header):
        return None
    family: _ListFamily | None = None
    marker_indent: str | None = None
    for leaf_line in leaf_lines:
        marker = parse_source_marker(leaf_line)
        structured = _structured_marker(leaf_line)
        if marker is None or structured is None:
            return None
        indent = leaf_line[:marker.raw_start]
        if marker_indent is None:
            marker_indent = indent
        elif indent != marker_indent:
            return None
        leaf_body = leaf_line[marker.content_start :]
        if leaf_body.rstrip().endswith(":"):
            return None
        if family is None:
            family = structured[0]
        elif structured[0] is not family:
            return None
    return header, tuple(leaf_lines)


def literal_flat_list_governor(source: str, quote: str) -> str | None:
    """Return an exact flat-list governor for one unique literal leaf quote."""

    if (
        not isinstance(quote, str)
        or not quote.strip()
        or len(quote) > _LITERAL_FLAT_LIST_MAX_QUOTE_CHARS
        or any(character in "\r\n\v\f\x85\u2028\u2029" for character in quote)
    ):
        return None
    parts = literal_flat_list_parts(source)
    if parts is None:
        return None
    header, leaf_lines = parts
    matches = 0
    for leaf_line in leaf_lines:
        marker = parse_source_marker(leaf_line)
        if marker is None:
            return None
        if quote == leaf_line or quote == leaf_line[marker.content_start :]:
            matches += 1
    return header if matches == 1 else None


def _scope_accepts(scope: _OwnerScope, family: _ListFamily, ordinal: int | None) -> bool:
    if scope.soft_children_open:
        return False
    if scope.family is not None and scope.family is not family:
        return False
    if family is _ListFamily.NUMERIC_CHILD:
        return not (
            ordinal == 1
            and scope.last_ordinal is not None
        )
    return not (
        ordinal is not None
        and scope.last_ordinal is not None
        and ordinal <= scope.last_ordinal
    )


def _consume_scope_marker(scope: _OwnerScope, family: _ListFamily, ordinal: int | None) -> None:
    if scope.family is None:
        scope.family = family
    if ordinal is not None:
        scope.last_ordinal = (
            max(scope.last_ordinal, ordinal)
            if family is _ListFamily.NUMERIC_CHILD and scope.last_ordinal is not None
            else ordinal
        )


def _exact_lower_resume_index(
    owners: list[_OwnerScope],
    family: _ListFamily,
    ordinal: int | None,
) -> int | None:
    if ordinal is None:
        return None
    for index in range(len(owners) - 2, -1, -1):
        scope = owners[index]
        if _is_exact_next(scope, family, ordinal):
            return index
    return None


def _is_exact_next(scope: _OwnerScope, family: _ListFamily, ordinal: int | None) -> bool:
    return bool(
        ordinal is not None
        and scope.family is family
        and scope.last_ordinal is not None
        and ordinal == scope.last_ordinal + 1
    )


def _exportable_owner_context(owners: list[_OwnerScope]) -> tuple[str, ...]:
    if any(not owner.exportable for owner in owners):
        return ()
    return tuple(owner.value for owner in owners)


def _matching_owner_context(
    owners: list[_OwnerScope],
    family: _ListFamily,
    ordinal: int | None,
) -> tuple[str, ...]:
    resume_index = _exact_lower_resume_index(owners, family, ordinal)
    if resume_index is not None:
        del owners[resume_index + 1 :]
        context = _exportable_owner_context(owners)
        _consume_scope_marker(owners[-1], family, ordinal)
        return context
    while owners and not _scope_accepts(owners[-1], family, ordinal):
        owners.pop()
    if not owners:
        return ()
    context = _exportable_owner_context(owners)
    _consume_scope_marker(owners[-1], family, ordinal)
    return context


def _prospective_owner_index(
    owners: list[_OwnerScope],
    family: _ListFamily,
    ordinal: int | None,
) -> int | None:
    resume_index = _exact_lower_resume_index(owners, family, ordinal)
    if resume_index is not None:
        return resume_index
    return next(
        (
            index
            for index in range(len(owners) - 1, -1, -1)
            if _scope_accepts(owners[index], family, ordinal)
        ),
        None,
    )


def _split_orphaned_incompatible_tail(
    clause: str,
    owners: list[_OwnerScope],
    marker_details: tuple[_ListFamily, int | None] | None,
    operative: bool,
) -> tuple[str, str | None, str | None]:
    """Detach an ungoverned nested marker without closing its proved outer scope."""

    lines = clause.splitlines()
    if (
        marker_details is None
        or not owners
        or operative
        or lines[0].endswith(":")
        or len(lines) < 2
    ):
        return clause, None, None

    family, ordinal = marker_details
    owner_index = _prospective_owner_index(owners, family, ordinal)
    if owner_index is None:
        return clause, None, None

    projected_last = owners[owner_index].last_ordinal
    if ordinal is not None:
        projected_last = (
            max(projected_last, ordinal)
            if family is _ListFamily.NUMERIC_CHILD and projected_last is not None
            else ordinal
        )

    incompatible_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        details = _structured_marker(line)
        if details is None:
            continue
        nested_family, nested_ordinal = details
        if nested_family is not family:
            incompatible_index = index
            break
        if nested_ordinal is not None:
            projected_last = (
                max(projected_last, nested_ordinal)
                if family is _ListFamily.NUMERIC_CHILD and projected_last is not None
                else nested_ordinal
            )
    if incompatible_index is None:
        return clause, None, None

    resume_index: int | None = None
    if projected_last is not None:
        for index, line in enumerate(lines[incompatible_index + 1 :], start=incompatible_index + 1):
            details = _structured_marker(line)
            if details == (family, projected_last + 1):
                resume_index = index
                break

    orphan_end = resume_index if resume_index is not None else len(lines)
    leading = "\n".join(lines[:incompatible_index])
    orphan = "\n".join(lines[incompatible_index:orphan_end])
    resume = "\n".join(lines[resume_index:]) if resume_index is not None else None
    return leading, orphan, resume


def _is_bounded_uppercase_wrap(value: str, previous_clause: str) -> bool:
    if "\n" in value or parse_source_marker(value) is not None or value.endswith(":"):
        return False
    first_letter = next((character for character in value if character.isalpha()), "")
    if not first_letter.isupper() or not value.endswith((".", ";", "!", "?")):
        return False
    previous_line = previous_clause.rsplit("\n", 1)[-1]
    if parse_source_marker(previous_line) is None or previous_line.endswith((".", ";", "!", "?", ":")):
        return False
    words = re.findall(r"[^\W\d_]+", previous_line.casefold().replace("ё", "е"), re.UNICODE)
    return bool(words and words[-1] in _UPPERCASE_WRAP_CONNECTORS)


def _is_soft_colon_child(value: str, owner: _OwnerScope) -> bool:
    """Keep a bounded unmarked list phrase under its literal colon governor."""

    if (
        not owner.exportable
        or owner.family is not None
        or not owner.value.endswith(":")
        or "\n" in value
        or value.endswith(":")
        or parse_source_marker(value) is not None
    ):
        return False
    first_letter = next((character for character in value if character.isalpha()), "")
    if not first_letter.islower() or not _SOFT_COLON_CHILD_RE.match(value):
        return False

    # A preposition may also introduce a new actor and predicate. Explicit duty
    # modality and the shared bounded action morphology therefore close this
    # literal owner instead of being treated as proof of list-child ownership.
    action_probe = value.rstrip().removesuffix(";").rstrip()
    morphology_probe = re.sub(
        r"^с\s+использованием\b\s*",
        "",
        action_probe,
        count=1,
        flags=re.IGNORECASE,
    )
    return not (
        _PRESCRIPTIVE_MODAL_RE.search(action_probe)
        or is_sentence_like_ordinal_heading(f"1. {morphology_probe}")
    )


def _heading_segments(text: str) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    cursor = 0
    for match in _MARKDOWN_HEADING_LINE_RE.finditer(text):
        if match.start() > cursor:
            segments.append((text[cursor : match.start()], False))
        segments.append(("", True))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return segments


def _split_internal_numeric_restarts(value: str) -> list[str]:
    lines = value.splitlines()
    if len(lines) < 2:
        return [value]
    pieces: list[str] = []
    start = 0
    last_ordinal: dict[_ListFamily, int] = {}
    for index, line in enumerate(lines):
        details = _structured_marker(line)
        if details is None or details[1] is None:
            continue
        family, ordinal = details
        assert ordinal is not None
        previous = last_ordinal.get(family)
        is_restart = bool(
            previous is not None
            and (
                ordinal == 1
                if family is _ListFamily.NUMERIC_CHILD
                else ordinal <= previous
            )
        )
        if index > start and is_restart:
            pieces.append("\n".join(lines[start:index]))
            start = index
            last_ordinal.clear()
        last_ordinal[family] = (
            max(previous, ordinal)
            if family is _ListFamily.NUMERIC_CHILD and previous is not None
            else ordinal
        )
    pieces.append("\n".join(lines[start:]))
    return pieces


def split_narrative_blocks(text: str) -> list[str]:
    """Return normalized, coherent source blocks without sentence-level splitting.

    Blank lines and explicit numbered paragraphs establish candidate boundaries.
    A list introduction remains with its following bullets, and an explicit
    exception or condition remains with the preceding rule.  No content is
    discarded or shortened; a single long paragraph is one complete block.
    """

    blocks: list[str] = []
    persistent_list: _ListState | None = None
    for source_paragraph in re.split(r"\n\s*\n", text):
        local_list_active = False
        substantive_parts = 0
        for numbered_part in split_marker_paragraphs(source_paragraph):
            paragraph = _normalize_block(numbered_part)
            if (
                not paragraph
                or _DOCLING_IMAGE_MARKER_RE.fullmatch(paragraph)
                or _DOCLING_SPECK_METADATA_RE.fullmatch(paragraph)
                or _DOCLING_BACKTICK_SPECK_RE.fullmatch(paragraph)
            ):
                continue
            same_source_paragraph = substantive_parts > 0
            substantive_parts += 1
            marker = parse_source_marker(paragraph)
            hierarchical_item = bool(marker and marker.family == "numeric" and len(marker.numeric_path) > 1)
            if hierarchical_item:
                # Docling often prepends a visual bullet to a real clause
                # number such as 1.4. That is a new source rule, not another
                # child of the preceding list introduction.
                if marker and marker.decoration:
                    paragraph = paragraph[1:].lstrip()
                    marker = parse_source_marker(paragraph)
            numbered_item = bool(marker and marker.family == "numeric" and len(marker.numeric_path) == 1)
            numbered_child = bool(numbered_item and marker and marker.raw_marker.rstrip().endswith(")"))
            numbered_comma = bool(numbered_item and marker and marker.raw_marker.rstrip().endswith(","))
            numbered_dot_parent = bool(
                numbered_item and marker and marker.raw_marker.rstrip().endswith((".", "…"))
            )
            operative_numeric_item = numbered_dot_parent or numbered_comma
            letter_child = bool(marker and marker.family == "letter")
            is_marker = bool(marker and marker.family in {"numeric", "letter"} and not hierarchical_item)
            # OCR may enumerate a visual dash list starting at an arbitrary
            # number after a page/paragraph boundary. Keep the existing explicit
            # list introduction; never treat a bare new numbered rule this way.
            ocr_list_continuation = bool(
                blocks and numbered_item and marker and paragraph[marker.content_start:].startswith(("—", "–", "-"))
                and blocks[-1].endswith((";", ","))
                and re.search(r":\s+(?:[-*•‣]\s+|\d+[.)]\s+)", blocks[-1])
            )
            persistent_child = bool(
                persistent_list
                and (
                    (
                        persistent_list.family is _ListFamily.NUMERIC_CHILD
                        and (numbered_child or numbered_comma)
                    )
                    or (
                        persistent_list.family is _ListFamily.OPERATIVE_NUMERIC_LIST
                        and operative_numeric_item
                        and marker is not None
                        and persistent_list.last_ordinal is not None
                        and marker.numeric_path[0] > persistent_list.last_ordinal
                    )
                    or (
                        persistent_list.family is _ListFamily.LETTER_CHILD
                        and letter_child
                    )
                )
            )
            closes_persistent_list = bool(
                hierarchical_item
                or (
                    operative_numeric_item
                    and persistent_list is not None
                    and not (
                        persistent_list.family is _ListFamily.NUMERIC_CHILD and numbered_comma
                    )
                    and (persistent_list.family is not _ListFamily.OPERATIVE_NUMERIC_LIST or not persistent_child)
                )
            )
            introduced_in_same_paragraph = bool(
                same_source_paragraph and blocks and _has_terminal_colon(blocks[-1])
            )
            explicit_child_after_colon = bool(
                not same_source_paragraph
                and blocks
                and _has_terminal_colon(blocks[-1])
                and (numbered_child or letter_child)
            )
            operative_numeric_after_colon = bool(
                blocks
                and operative_numeric_item
                and _is_operative_colon_governor(blocks[-1])
            )
            is_list_item = is_marker and not closes_persistent_list and (
                local_list_active
                or ocr_list_continuation
                or introduced_in_same_paragraph
                or explicit_child_after_colon
                or operative_numeric_after_colon
                or persistent_child
            )
            is_bullet = not hierarchical_item and (bool(marker and marker.family == "bullet") or is_list_item)
            is_continuation = bool(_CONTINUATION_RE.match(paragraph))
            first_letter = next((character for character in paragraph if character.isalpha()), "")
            is_list_continuation = bool(
                persistent_list
                and blocks
                and blocks[-1].rstrip()[-1:].isalnum()
                and not is_marker
                and not hierarchical_item
                and first_letter.islower()
            )
            if blocks and (is_bullet or is_continuation or is_list_continuation):
                separator = "\n" if is_bullet else " "
                blocks[-1] = f"{blocks[-1]}{separator}{paragraph}"
            else:
                blocks.append(paragraph)
            local_list_active = is_list_item
            if numbered_child and is_list_item:
                persistent_list = _ListState(_ListFamily.NUMERIC_CHILD)
            elif letter_child and is_list_item:
                persistent_list = _ListState(_ListFamily.LETTER_CHILD)
            elif (numbered_comma and persistent_child
                  and persistent_list is not None and persistent_list.family is _ListFamily.NUMERIC_CHILD):
                # OCR punctuation may vary inside one already established
                # numeric child chain. The number itself is never inferred.
                persistent_list = _ListState(_ListFamily.NUMERIC_CHILD)
            elif operative_numeric_item and is_list_item and (
                operative_numeric_after_colon
                or persistent_list is not None
                and persistent_list.family is _ListFamily.OPERATIVE_NUMERIC_LIST
            ):
                assert marker is not None
                persistent_list = _ListState(_ListFamily.OPERATIVE_NUMERIC_LIST, marker.numeric_path[0])
            elif closes_persistent_list:
                persistent_list = None
            elif not (is_bullet or is_continuation or is_list_continuation):
                persistent_list = None
    return blocks


def split_narrative_source_blocks(text: str) -> list[NarrativeSourceBlock]:
    """Return grouped source clauses with only literal, proved owner context."""

    result: list[NarrativeSourceBlock] = []
    owners: list[_OwnerScope] = []
    recovered_group_open = False

    for segment, is_heading in _heading_segments(text):
        if is_heading:
            owners.clear()
            recovered_group_open = False
            continue

        clauses = [
            part
            for legacy_block in split_narrative_blocks(segment)
            for part in _split_internal_numeric_restarts(legacy_block)
        ]
        clause_index = 0
        while clause_index < len(clauses):
            clause = clauses[clause_index]
            clause_index += 1
            lines = clause.splitlines()
            first_line = lines[0]
            first_marker = parse_source_marker(first_line)
            marker_details = _structured_marker(first_line)
            operative = _is_operative_colon_governor(first_line)
            clause, orphaned_tail, resume_tail = _split_orphaned_incompatible_tail(
                clause,
                owners,
                marker_details,
                operative,
            )
            if resume_tail is not None:
                clauses.insert(clause_index, resume_tail)
            lines = clause.splitlines()

            if (
                first_marker is None
                and owners
                and len(lines) > 1
                and first_line.rstrip().endswith(":")
            ):
                resume_line = next(
                    (
                        index
                        for index, line in enumerate(lines[1:], start=1)
                        if (
                            (details := _structured_marker(line)) is not None
                            and _is_exact_next(owners[-1], *details)
                        )
                    ),
                    None,
                )
                if resume_line is not None:
                    clauses.insert(clause_index, "\n".join(lines[resume_line:]))
                    clause = "\n".join(lines[:resume_line])
                    lines = lines[:resume_line]

            if (
                owners
                and result
                and _is_bounded_uppercase_wrap(clause, result[-1].clause)
            ):
                previous = result[-1]
                result[-1] = NarrativeSourceBlock(
                    clause=f"{previous.clause} {clause}",
                    owner_context=previous.owner_context,
                )
                recovered_group_open = True
                continue

            owner_context: tuple[str, ...] = ()
            attached_to_owner = False
            close_soft_owner = False
            if operative and first_marker is None:
                if owners:
                    owner_context = _exportable_owner_context(owners)
                    attached_to_owner = bool(owner_context)
                else:
                    owners.clear()
                owners.append(_OwnerScope(first_line))
            elif operative and (
                marker_details is None
                or marker_details[0] is _ListFamily.OPERATIVE_NUMERIC_LIST
            ):
                owners.clear()
                owners.append(_OwnerScope(first_line))
            elif marker_details is not None:
                family, ordinal = marker_details
                owner_context = _matching_owner_context(owners, family, ordinal)
                attached_to_owner = bool(owner_context)
                matched_owner = bool(owners)
                if operative and matched_owner:
                    owners.append(_OwnerScope(first_line))
                elif not operative and matched_owner and first_line.endswith(":"):
                    owners.append(_OwnerScope(first_line, exportable=False))
            elif first_marker is not None:
                owners.clear()
            elif owners:
                if _is_soft_colon_child(clause, owners[-1]):
                    owner_context = _exportable_owner_context(owners)
                    attached_to_owner = bool(owner_context)
                    owners[-1].soft_children_open = True
                    close_soft_owner = clause.endswith((".", "!", "?"))
                elif owners[-1].family is None:
                    owners.pop()

            if attached_to_owner and recovered_group_open and result:
                previous = result[-1]
                result[-1] = NarrativeSourceBlock(
                    clause=f"{previous.clause}\n{clause}",
                    owner_context=previous.owner_context,
                )
            else:
                result.append(NarrativeSourceBlock(clause=clause, owner_context=owner_context))
            recovered_group_open = attached_to_owner and recovered_group_open
            if close_soft_owner:
                owners.pop()

            if orphaned_tail is not None:
                result.append(NarrativeSourceBlock(clause=orphaned_tail))
                recovered_group_open = False

            for line in lines[1:]:
                details = _structured_marker(line)
                if details is None:
                    if parse_source_marker(line) is not None:
                        owners.clear()
                    continue
                family, ordinal = details
                _matching_owner_context(owners, family, ordinal)
                matched_owner = bool(owners)
                if _is_operative_colon_governor(line) and matched_owner:
                    owners.append(_OwnerScope(line))
                elif line.endswith(":") and matched_owner:
                    owners.append(_OwnerScope(line, exportable=False))

    return result
