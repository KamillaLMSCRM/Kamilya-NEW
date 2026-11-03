"""Source-bound ordered-list review contract. No semantic approval is minted here.

A caller must inject a trusted verifier for the complete semantic receipt. Exact
spans, hashes, IDs and option inventory alone do not establish list semantics.
"""
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Row:
    row_id: str
    ordinal: int
    span: Span


@dataclass(frozen=True)
class OptionBinding:
    index: int
    row_id: str
    option_text: str


@dataclass(frozen=True)
class ListRelation:
    source_id: str
    source_sha256: str
    target_id: str
    governor: Span
    rows: tuple[Row, ...]
    semantics: Literal['ordered', 'conditional', 'unknown']


@dataclass(frozen=True)
class Selector:
    kind: Literal['ordinal', 'none', 'unknown']
    span: Span | None
    row_id: str | None


@dataclass(frozen=True)
class ReviewInput:
    relation: ListRelation
    stem: str
    options: tuple[str, ...]
    key: int
    option_bindings: tuple[OptionBinding, ...]
    selector: Selector


Verifier = Callable[[ReviewInput], bool]


def _span(text: str, value: Span | None) -> bool:
    return (isinstance(value, Span) and type(value.start) is int and type(value.end) is int
            and 0 <= value.start < value.end <= len(text) and text[value.start:value.end] == value.text)


def assess_list_scope(*, source_id: str, source_text: str, target_id: str,
                      target_source_ids: tuple[str, ...], target_components: tuple[str, ...],
                      request: ReviewInput, verifier: Verifier | None) -> str:
    """Return HOLD/UNKNOWN or REVIEW_REQUIRED; never select a key or approve.

    The trusted verifier must review order semantics, complete sibling coverage,
    option equivalence and selector meaning, including conditional scopes.
    """
    try:
        rel = request.relation
        if (not isinstance(rel, ListRelation) or not isinstance(source_text, str)
                or rel.source_id != source_id or rel.target_id != target_id or source_id not in target_source_ids
                or sha256(source_text.encode('utf-8')).hexdigest() != rel.source_sha256
                or not _span(source_text, rel.governor) or rel.governor.text not in request.stem
                or rel.semantics not in ('ordered', 'conditional', 'unknown')
                or type(request.key) is not int or not 0 <= request.key < len(request.options)
                or len(rel.rows) < 2 or any(not isinstance(r, Row) or not _span(source_text, r.span) for r in rel.rows)
                or len({r.row_id for r in rel.rows}) != len(rel.rows)
                or len({r.ordinal for r in rel.rows}) != len(rel.rows)
                or any(type(r.ordinal) is not int or r.ordinal < 1 for r in rel.rows)
                or any(a.span.end > b.span.start for a, b in zip(rel.rows, rel.rows[1:], strict=False))
                or rel.governor.end > rel.rows[0].span.start
                or any(not isinstance(b, OptionBinding) or not 0 <= b.index < len(request.options)
                       or b.option_text != request.options[b.index] for b in request.option_bindings)
                or len(request.option_bindings) != len(request.options)
                or len({b.index for b in request.option_bindings}) != len(request.option_bindings)
                or any(b.row_id not in {r.row_id for r in rel.rows} for b in request.option_bindings)
                or not any(b.index == request.key and any(r.row_id == b.row_id and r.span.text in target_components
                       for r in rel.rows) for b in request.option_bindings)):
            return 'UNKNOWN'
        selector = request.selector
        if not isinstance(selector, Selector) or selector.kind not in ('ordinal', 'none', 'unknown'):
            return 'UNKNOWN'
        if selector.kind == 'ordinal':
            if not _span(request.stem, selector.span) or selector.row_id not in {r.row_id for r in rel.rows}:
                return 'UNKNOWN'
        elif selector.span is not None or selector.row_id is not None:
            return 'UNKNOWN'
        if rel.semantics == 'unknown' or selector.kind == 'unknown' or not callable(verifier):
            return 'UNKNOWN'
        try:
            verified = verifier(request)
        except Exception:
            return 'UNKNOWN'
        if verified is not True:
            return 'UNKNOWN'
        if rel.semantics != 'ordered':
            return 'REVIEW_REQUIRED'
        if selector.kind == 'none' and len({b.row_id for b in request.option_bindings}) >= 2:
            return 'HOLD_MULTIPLE_SOURCE_MEMBERS'
        if selector.kind == 'ordinal' and not any(b.index == request.key and b.row_id == selector.row_id
                                                   for b in request.option_bindings):
            return 'HOLD_SELECTOR_KEY_MISMATCH'
        return 'REVIEW_REQUIRED'
    except (AttributeError, TypeError, ValueError):
        return 'UNKNOWN'
