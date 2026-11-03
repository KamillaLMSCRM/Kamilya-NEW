"""Lossless, bounded parsing of office-document list layout markers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SOURCE_HORIZONTAL_SPACE = " \t\u00a0\u202f"
_HSPACE = SOURCE_HORIZONTAL_SPACE
_HSPACE_RE = re.compile(f"[{re.escape(_HSPACE)}]+")
_LETTER_MARKERS = frozenset(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    "әғқңөұүһі"
    "abcdefghijklmnopqrstuvwxyz"
)
_SPACED_ONLY_BULLETS = frozenset("·●○■□▫◆◇")
_BULLETS = frozenset("-*—–•‣◦▪∙→") | _SPACED_ONLY_BULLETS
_OPENING_PUNCTUATION = frozenset("«\"'“„([{<")
_MAX_MARKER_DIGITS = 9
_MAX_MARKER_SEGMENTS = 12
_COMPACT_DOTTED_DATE_RE = re.compile(r"([0-9]{1,4})\.([0-9]{1,2})\.([0-9]{1,4})")
_DASH_MARKERS = frozenset("-—–")
_DOCLING_TRANSPARENT_METADATA_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:<!-- footnote -->|"
    r"<!-- page-number page=\d+ item_id=#/texts/\d+ text=\d+ -->|"
    r"<!-- native-layout-unknown reason=top_edge_overlapping_ocr_hypotheses_unresolved "
    r"item_ids=#/texts/\d+(?:,#/texts/\d+){2,5} -->)[ \t]*(?:\r?\n|$)"
)


def verified_docling_semantic_view(text: str) -> str:
    """Hide finite converter annotations in a view; callers prove Docling ownership.

    Never replace raw source/chunks or interpret formula, image, or uncertain
    key-value relationships as transparent. No source words or values change.
    """
    return _DOCLING_TRANSPARENT_METADATA_LINE_RE.sub("", text)


@dataclass(frozen=True, slots=True)
class SourceMarker:
    """A source-layout marker; all factual source text remains outside it."""

    family: str
    numeric_path: tuple[int, ...]
    letter: str
    content_start: int
    decoration: bool
    raw_start: int
    raw_marker: str


def _body_start(text: str, index: int, *, whitespace_required: bool) -> int | None:
    if whitespace_required:
        if index >= len(text) or text[index] not in _HSPACE:
            return None
        index = len(_HSPACE_RE.match(text, index).group(0)) + index  # type: ignore[union-attr]
    while index < len(text) and text[index] in _HSPACE:
        index += 1
    if index >= len(text) or text[index] in "\r\n":
        return None
    return index


def _punctuated_body_start(text: str, index: int, *, hierarchical: bool = False) -> int | None:
    """One delimiter family for flat/nested office lists; never repair a value."""
    start = index
    while index < len(text) and text[index] in ".,…":
        index += 1
    if index == start:
        return None
    body = _body_start(text, index, whitespace_required=True)
    punctuation = text[start:index]
    if body is None:
        return None
    if ((len(punctuation) > 1 or "…" in punctuation)
            and re.match(r"[+\-−]?[ \t\u00a0\u202f]*(?:\d|[.,]\d)", text[body:])):
        return None
    if hierarchical and punctuation == ",":
        return None  # Two-segment decimals followed by comma/unit remain literal.
    return body


def _starts_compact_civil_date(text: str, index: int) -> bool:
    """Recognize a complete dotted date at a flat marker's body boundary."""
    match = _COMPACT_DOTTED_DATE_RE.match(text, index)
    if match is None:
        return False
    first, month_text, third = match.groups()
    if len(first) == 4 and len(third) <= 2:
        year, month, day = int(first), int(month_text), int(third)
    elif len(third) == 4 and len(first) <= 2:
        year, month, day = int(third), int(month_text), int(first)
    else:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    end = match.end()
    if end >= len(text) or text[end] in _HSPACE or text[end] in "\r\n":
        return True
    return text[end] in ".," and (
        end + 1 >= len(text) or text[end + 1] in _HSPACE or text[end + 1] in "\r\n"
    )


def _make_marker(
    text: str,
    *,
    family: str,
    numeric_path: tuple[int, ...] = (),
    letter: str = "",
    raw_start: int,
    content_start: int,
    decoration: bool,
) -> SourceMarker:
    return SourceMarker(
        family=family,
        numeric_path=numeric_path,
        letter=letter,
        content_start=content_start,
        decoration=decoration,
        raw_start=raw_start,
        raw_marker=text[raw_start:content_start],
    )


def _dash_cluster_body_start(text: str, start: int) -> tuple[bool, int | None]:
    """Recognize 2–3 layout dashes, never repair a numeric or mathematical body."""
    cursor = start
    count = 0
    last_dash_end = start
    inner_space = False
    while cursor < len(text) and text[cursor] in _DASH_MARKERS:
        count += 1
        if count > 3:
            return True, None
        cursor += 1
        last_dash_end = cursor
        while cursor < len(text) and text[cursor] in _HSPACE:
            cursor += 1
        if (count == 1 and cursor > last_dash_end
                and re.match(r"-{2,}(?=[^\W\d_])", text[cursor:], re.UNICODE)):
            # An outer bullet can introduce a literal compact command flag.
            # Keep its '--' bytes in the body, not in the layout marker.
            return False, None
        if cursor > last_dash_end and cursor < len(text) and text[cursor] in _DASH_MARKERS:
            inner_space = True
    if count < 2:
        return False, None
    if (cursor == last_dash_end and not inner_space) or cursor >= len(text):
        return True, None  # Require layout spacing, never compact CLI flags.
    probe = cursor
    while probe < len(text) and text[probe] in _OPENING_PUNCTUATION:
        probe += 1
    if probe >= len(text) or not text[probe].isalpha():
        return True, None
    if re.match(r"[^\W\d_]{1,2}\s*[=<>+*/]", text[probe:], re.UNICODE):
        return True, None
    return True, cursor


def parse_source_marker(text: str) -> SourceMarker | None:
    """Parse one marker at the start of a line without rewriting ``text``.

    The returned offsets refer to the supplied string. Punctuation that could
    be part of a decimal, date, range, or quantity is intentionally rejected.
    """

    if not isinstance(text, str) or not text:
        return None
    index = 0
    while index < len(text) and text[index] in _HSPACE:
        index += 1
    raw_start = index
    decoration = False
    dash_cluster, cluster_body = _dash_cluster_body_start(text, index)
    if dash_cluster:
        if cluster_body is None:
            return None
        decoration = True
        index = cluster_body
    elif index < len(text) and text[index] in _BULLETS:
        bullet = text[index]
        following = index + 1
        if bullet in _SPACED_ONLY_BULLETS and (following >= len(text) or text[following] not in _HSPACE):
            # Circle/square/diamond glyphs and middle dots are only structural
            # when separated from their body; never repair compact math/text.
            return None
        if bullet in "-*—–" and (following >= len(text) or text[following] not in _HSPACE):
            body_probe = following
            while body_probe < len(text) and text[body_probe] in _OPENING_PUNCTUATION:
                body_probe += 1
            if body_probe >= len(text) or not text[body_probe].isalpha():
                return None
        decoration = True
        index = following
        while index < len(text) and text[index] in _HSPACE:
            index += 1
        if index >= len(text):
            return None
    decorated_body_start = index

    if index < len(text) and text[index] == "(":
        close = text.find(")", index + 1)
        enclosed_digits = text[index + 1 : close] if close > index + 1 else ""
        if enclosed_digits.isascii() and enclosed_digits.isdigit() and len(enclosed_digits) <= _MAX_MARKER_DIGITS:
            body = _body_start(text, close + 1, whitespace_required=True)
            if body is not None:
                return _make_marker(text, family="numeric", numeric_path=(int(enclosed_digits),), raw_start=raw_start, content_start=body, decoration=decoration)
        elif len(enclosed_digits) == 1 and enclosed_digits.casefold() in _LETTER_MARKERS:
            body = _body_start(text, close + 1, whitespace_required=True)
            if body is not None:
                return _make_marker(text, family="letter", letter=enclosed_digits, raw_start=raw_start, content_start=body, decoration=decoration)

    digits = re.match(r"[0-9]+", text[index:])
    if digits is not None:
        first_digits = digits.group(0)
        if len(first_digits) > _MAX_MARKER_DIGITS:
            return _bullet_fallback(text, raw_start, decorated_body_start, decoration)
        index += len(first_digits)
        path = [int(first_digits)]
        while True:
            separator = index
            while separator < len(text) and text[separator] in _HSPACE:
                separator += 1
            if separator >= len(text) or text[separator] != ".":
                break
            digits_start = separator + 1
            while digits_start < len(text) and text[digits_start] in _HSPACE:
                digits_start += 1
            next_digits = re.match(r"[0-9]+", text[digits_start:])
            if next_digits is None:
                break
            digits_end = digits_start + len(next_digits.group(0))
            space_before_dot = separator > index
            space_after_dot = digits_start > separator + 1
            termination = digits_end
            while termination < len(text) and text[termination] in _HSPACE:
                termination += 1
            structurally_terminated = (
                termination < len(text) and text[termination] in ".)…"
            )
            if (
                len(path) == 1
                and space_after_dot
                and not space_before_dot
                and _starts_compact_civil_date(text, digits_start)
            ):
                # A compact flat marker may introduce a literal civil date.
                # Do not absorb the date components into the marker path.
                break
            if space_after_dot and not space_before_dot and not structurally_terminated:
                # ``2. 2,5 дня`` is an ordinary marker with numeric-leading
                # content. A spaced hierarchy is admitted only when the next
                # segment has its own unambiguous marker terminator.
                break
            if len(path) >= _MAX_MARKER_SEGMENTS or len(next_digits.group(0)) > _MAX_MARKER_DIGITS:
                return _bullet_fallback(text, raw_start, decorated_body_start, decoration)
            path.append(int(next_digits.group(0)))
            index = digits_end
        hierarchical = len(path) > 1
        delimiter_index = index
        while delimiter_index < len(text) and text[delimiter_index] in _HSPACE:
            delimiter_index += 1
        if (
            delimiter_index > index
            and (delimiter_index >= len(text) or text[delimiter_index] not in ".,…")
        ):
            delimiter_index = index
        if hierarchical:
            # A trailing sentence dot does not turn a complete civil date
            # into a clause hierarchy. Ambiguous date-shaped values remain
            # ordinary source text; the original bytes are never repaired.
            if len(path) == 3 and (1000 <= path[0] <= 9999 or 1000 <= path[2] <= 9999):
                year, month, day = path if path[0] >= 1000 else list(reversed(path))
                try:
                    date(year, month, day)
                except ValueError:
                    pass
                else:
                    return _bullet_fallback(text, raw_start, decorated_body_start, decoration)
            if text[delimiter_index : delimiter_index + 2] == ".)":
                body = _body_start(text, delimiter_index + 2, whitespace_required=True)
            elif delimiter_index < len(text) and text[delimiter_index] == ")":
                body = _body_start(text, delimiter_index + 1, whitespace_required=True)
            else:
                body = _punctuated_body_start(text, delimiter_index, hierarchical=len(path) == 2)
        elif text[delimiter_index : delimiter_index + 2] == ".)":
            body = _body_start(text, delimiter_index + 2, whitespace_required=True)
        elif delimiter_index < len(text) and text[delimiter_index] in ".,…":
            body = _punctuated_body_start(text, delimiter_index)
        elif delimiter_index < len(text) and text[delimiter_index] == ")":
            body = _body_start(text, delimiter_index + 1, whitespace_required=False)
        else:
            return _bullet_fallback(text, raw_start, decorated_body_start, decoration)
        if body is None:
            return _bullet_fallback(text, raw_start, decorated_body_start, decoration)
        return _make_marker(text, family="numeric", numeric_path=tuple(path), raw_start=raw_start, content_start=body, decoration=decoration)

    # A letter plus dot is indistinguishable here from an ordinary abbreviation
    # (city, paragraph, page, unit). Keep it literal without sibling evidence.
    if index < len(text) and text[index].casefold() in _LETTER_MARKERS and index + 1 < len(text) and text[index + 1] == ")":
        body = _body_start(text, index + 2, whitespace_required=True)
        if body is not None:
            return _make_marker(text, family="letter", letter=text[index], raw_start=raw_start, content_start=body, decoration=decoration)
    return _bullet_fallback(text, raw_start, decorated_body_start, decoration)


def _bullet_fallback(text: str, raw_start: int, content_start: int, decoration: bool) -> SourceMarker | None:
    if not decoration:
        return None
    leading_digits = re.match(r"[0-9]+", text[content_start:])
    if leading_digits is not None and len(leading_digits.group(0)) > _MAX_MARKER_DIGITS:
        return None
    numeric_like = re.match(r"[0-9]+([.)])", text[content_start:])
    decimal_like = re.match(r"[0-9]+\.[0-9]", text[content_start:])
    if numeric_like is not None and decimal_like is None:
        after = content_start + numeric_like.end()
        if after >= len(text) or text[after] in "\r\n" or text[after] not in _HSPACE:
            return None
    body = _body_start(text, content_start, whitespace_required=False)
    if body is None:
        return None
    return _make_marker(text, family="bullet", raw_start=raw_start, content_start=body, decoration=True)


def split_marker_paragraphs(text: str) -> list[str]:
    """Split only at recognized line-start markers, preserving every character."""

    if not text:
        return []
    starts: list[int] = []
    position = 0
    for line in text.splitlines(keepends=True):
        if parse_source_marker(line) is not None:
            starts.append(position)
        position += len(line)
    if not starts:
        return [text]
    pieces: list[str] = []
    if starts[0] > 0:
        pieces.append(text[: starts[0]])
    pieces.extend(text[start:end] for start, end in zip(starts, starts[1:] + [len(text)], strict=False))
    return pieces
