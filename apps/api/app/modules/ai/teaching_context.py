"""Exact source custody for audited, non-assessable teaching context.

This module accounts for exact instructional spans only.  It never creates a
target, obligation, evidence level, source exclusion, or assessment credit.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from app.modules.ai.assessment_preservation import (
    source_contains_unambiguous_positive_prescriptive_action,
)

TEACHING_CONTEXT_POLICY = "teaching-context-v1"
MAX_CONTEXT_ROWS = 64
MAX_CONTEXT_ALIAS_CHARS = 80
MAX_CONTEXT_REF_CHARS = 160
MAX_CONTEXT_QUOTE_CHARS = 2_000
MAX_CONTEXT_SOURCE_CHARS = 60_000

_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}")
_CONTEXT_ID = re.compile(r"teaching-context:[0-9a-f]{64}")
_AUDIT_ERRORS = frozenset(
    {
        "contains_assessable_action",
        "contains_permission_or_prohibition",
        "contains_decision_or_consequence",
        "contains_trigger_condition_or_exception",
        "contains_deadline_or_routing",
        "contains_mandatory_responsibility",
        "not_useful_teaching_context",
        "source_scope_uncertain",
    }
)


@dataclass(frozen=True, slots=True)
class TeachingContextProtectedSpan:
    """A caller-owned assessment/material span that context may not overlap."""

    source_ref: str
    quote_start: int
    quote_end: int


@dataclass(frozen=True, slots=True)
class TeachingContext:
    """One exact source span with a server-derived, source-bound identity."""

    context_id: str
    author_alias: str
    source_ref: str
    source_id: str
    quote: str
    quote_start: int
    quote_end: int
    source_sha256: str
    binding_sha256: str


@dataclass(frozen=True, slots=True)
class TeachingContextIssue:
    """Finite negative diagnostic; an issue is never positive evidence."""

    stage: Literal["author", "audit"]
    code: str
    row_index: int
    identity: str = ""
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TeachingContextCompilation:
    contexts: tuple[TeachingContext, ...]
    issues: tuple[TeachingContextIssue, ...]


@dataclass(frozen=True, slots=True)
class TeachingContextInventory:
    compiled: tuple[TeachingContext, ...]
    admitted: tuple[TeachingContext, ...]
    issues: tuple[TeachingContextIssue, ...]


@dataclass(frozen=True, slots=True)
class _SourceRecord:
    source_ref: str
    source_id: str
    text: str
    source_sha256: str


def _canonical_digest(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _bounded_text(value: object, maximum: int) -> str | None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(unicategory < " " and unicategory not in "\t\n" for unicategory in value)
    ):
        return None
    return value


def _source_record(sources: Mapping[str, tuple[str, str]], source_ref: str) -> _SourceRecord | None:
    value = sources.get(source_ref)
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    source_id = _bounded_text(value[0], MAX_CONTEXT_REF_CHARS)
    text = _bounded_text(value[1], MAX_CONTEXT_SOURCE_CHARS)
    if source_id is None or text is None:
        return None
    return _SourceRecord(source_ref, source_id, text, sha256(text.encode("utf-8")).hexdigest())


def _occurrences(text: str, quote: str) -> tuple[int, ...]:
    result: list[int] = []
    start = 0
    while (found := text.find(quote, start)) >= 0:
        result.append(found)
        if len(result) > 1:
            break
        start = found + 1
    return tuple(result)


def _overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _protected_inventory(
    sources: Mapping[str, tuple[str, str]],
    protected_spans: Sequence[TeachingContextProtectedSpan],
) -> tuple[tuple[str, str, int, int], ...] | None:
    if not isinstance(protected_spans, tuple | list) or len(protected_spans) > 512:
        return None
    result = []
    for span in protected_spans:
        if not isinstance(span, TeachingContextProtectedSpan):
            return None
        source = _source_record(sources, span.source_ref)
        if (
            source is None
            or type(span.quote_start) is not int
            or type(span.quote_end) is not int
            or not 0 <= span.quote_start < span.quote_end <= len(source.text)
        ):
            return None
        result.append((source.source_id, source.source_sha256, span.quote_start, span.quote_end))
    return tuple(result)


def _context(
    *, alias: str, source: _SourceRecord, quote: str, quote_start: int,
) -> TeachingContext:
    quote_end = quote_start + len(quote)
    binding = {
        "policy": TEACHING_CONTEXT_POLICY,
        "author_alias": alias,
        "source_ref": source.source_ref,
        "source_id": source.source_id,
        "quote": quote,
        "quote_start": quote_start,
        "quote_end": quote_end,
        "source_sha256": source.source_sha256,
    }
    digest = _canonical_digest(binding)
    return TeachingContext(
        context_id="teaching-context:" + digest,
        author_alias=alias,
        source_ref=source.source_ref,
        source_id=source.source_id,
        quote=quote,
        quote_start=quote_start,
        quote_end=quote_end,
        source_sha256=source.source_sha256,
        binding_sha256=digest,
    )


def compile_teaching_contexts(
    author_rows: object,
    sources: Mapping[str, tuple[str, str]],
    *,
    protected_spans: Sequence[TeachingContextProtectedSpan] = (),
) -> TeachingContextCompilation:
    """Compile exact author spans while retaining row-local negative issues."""
    if not isinstance(sources, Mapping):
        return TeachingContextCompilation((), (
            TeachingContextIssue("author", "source_inventory_invalid", -1),
        ))
    protected = _protected_inventory(sources, protected_spans)
    if protected is None:
        return TeachingContextCompilation((), (
            TeachingContextIssue("author", "protected_span_inventory_invalid", -1),
        ))
    if not isinstance(author_rows, list):
        return TeachingContextCompilation((), (
            TeachingContextIssue("author", "author_rows_invalid", -1),
        ))
    if len(author_rows) > MAX_CONTEXT_ROWS:
        return TeachingContextCompilation((), (
            TeachingContextIssue("author", "author_row_limit", -1),
        ))

    aliases = [
        row.get("id")
        for row in author_rows
        if isinstance(row, Mapping)
        and type(row.get("id")) is str
        and _ALIAS.fullmatch(row["id"]) is not None
    ]
    duplicate_aliases = {alias for alias, count in Counter(aliases).items() if count > 1}
    issues: list[TeachingContextIssue] = []
    candidates: list[tuple[int, TeachingContext]] = []
    for index, row in enumerate(author_rows):
        identity = row.get("id", "") if isinstance(row, Mapping) and type(row.get("id")) is str else ""
        if not isinstance(row, Mapping) or set(row) != {"id", "ref", "quote"}:
            issues.append(TeachingContextIssue("author", "author_row_malformed", index, identity))
            continue
        alias = row["id"]
        source_ref = _bounded_text(row["ref"], MAX_CONTEXT_REF_CHARS)
        quote = _bounded_text(row["quote"], MAX_CONTEXT_QUOTE_CHARS)
        if type(alias) is not str or _ALIAS.fullmatch(alias) is None or source_ref is None or quote is None:
            issues.append(TeachingContextIssue("author", "author_row_malformed", index, identity))
            continue
        if alias in duplicate_aliases:
            issues.append(TeachingContextIssue("author", "duplicate_author_alias", index, alias))
            continue
        source = _source_record(sources, source_ref)
        if source is None:
            code = "unknown_source_ref" if source_ref not in sources else "source_record_invalid"
            issues.append(TeachingContextIssue("author", code, index, alias))
            continue
        occurrences = _occurrences(source.text, quote)
        if len(occurrences) != 1:
            issues.append(TeachingContextIssue("author", "quote_not_unique", index, alias))
            continue
        if source_contains_unambiguous_positive_prescriptive_action(quote):
            issues.append(TeachingContextIssue("author", "prescriptive_action_detected", index, alias))
            continue
        context = _context(alias=alias, source=source, quote=quote, quote_start=occurrences[0])
        if any(
            owner == (context.source_id, context.source_sha256)
            and _overlaps(context.quote_start, context.quote_end, start, end)
            for source_id, source_sha256, start, end in protected
            for owner in ((source_id, source_sha256),)
        ):
            issues.append(TeachingContextIssue("author", "protected_span_overlap", index, alias))
            continue
        candidates.append((index, context))

    overlapping: set[int] = set()
    for position, (left_index, left) in enumerate(candidates):
        for right_index, right in candidates[position + 1 :]:
            if (
                (left.source_id, left.source_sha256) == (right.source_id, right.source_sha256)
                and _overlaps(left.quote_start, left.quote_end, right.quote_start, right.quote_end)
            ):
                overlapping.update((left_index, right_index))
    contexts = []
    for index, context in candidates:
        if index in overlapping:
            issues.append(TeachingContextIssue("author", "context_span_overlap", index, context.author_alias))
        else:
            contexts.append(context)
    return TeachingContextCompilation(
        tuple(contexts),
        tuple(sorted(issues, key=lambda row: (row.row_index, row.stage, row.code, row.identity))),
    )


def _audit_row(row: object) -> tuple[str, bool, tuple[str, ...]] | None:
    if not isinstance(row, Mapping) or set(row) != {"context_id", "admit", "errors"}:
        return None
    context_id, admit, errors = row["context_id"], row["admit"], row["errors"]
    if (
        type(context_id) is not str
        or _CONTEXT_ID.fullmatch(context_id) is None
        or type(admit) is not bool
        or not isinstance(errors, list)
        or len(errors) > 8
        or any(type(error) is not str or error not in _AUDIT_ERRORS for error in errors)
        or len(set(errors)) != len(errors)
        or (admit and errors)
        or (not admit and not errors)
    ):
        return None
    return context_id, admit, tuple(errors)


def admit_teaching_contexts(
    compilation: TeachingContextCompilation,
    audit_rows: object,
) -> TeachingContextInventory:
    """Admit only one complete positive audit row per compiled context."""
    if not isinstance(compilation, TeachingContextCompilation):
        raise ValueError("teaching_context_invalid_compilation")
    issues = list(compilation.issues)
    contexts = {row.context_id: row for row in compilation.contexts}
    parsed: dict[str, list[tuple[int, bool, tuple[str, ...]]]] = {}
    if not isinstance(audit_rows, list) or len(audit_rows) > MAX_CONTEXT_ROWS:
        issues.append(TeachingContextIssue("audit", "audit_rows_invalid", -1))
        audit_rows = []
    for index, raw in enumerate(audit_rows):
        identity = raw.get("context_id", "") if isinstance(raw, Mapping) and type(raw.get("context_id")) is str else ""
        row = _audit_row(raw)
        if row is None:
            issues.append(TeachingContextIssue("audit", "audit_row_malformed", index, identity))
            continue
        context_id, admit, errors = row
        if context_id not in contexts:
            issues.append(TeachingContextIssue("audit", "audit_context_unknown", index, context_id))
            continue
        parsed.setdefault(context_id, []).append((index, admit, errors))

    admitted = []
    for context in compilation.contexts:
        rows = parsed.get(context.context_id, [])
        if not rows:
            issues.append(TeachingContextIssue("audit", "audit_positive_missing", -1, context.context_id))
            continue
        if len(rows) != 1:
            issues.extend(
                TeachingContextIssue("audit", "audit_context_duplicate", index, context.context_id)
                for index, _, _ in rows
            )
            continue
        index, admit, errors = rows[0]
        if not admit:
            issues.append(TeachingContextIssue("audit", "audit_context_rejected", index, context.context_id, errors))
            continue
        admitted.append(context)
    return TeachingContextInventory(
        compiled=compilation.contexts,
        admitted=tuple(admitted),
        issues=tuple(sorted(issues, key=lambda row: (row.stage, row.row_index, row.code, row.identity))),
    )


def complete_teaching_context_source_refs(
    contexts: Sequence[TeachingContext], sources: Mapping[str, tuple[str, str]],
) -> frozenset[str]:
    """Rederive full literal coverage, not semantic admission or source exclusion.

    Callers supply only independently admitted contexts. No target, obligation,
    or coverage credit follows from accounting for non-assessable source text.
    Partial context never accounts for another clause in the same source unit.
    """
    if not isinstance(contexts, tuple | list) or len(contexts) > MAX_CONTEXT_ROWS:
        raise ValueError("teaching_context_invalid_complete_inventory")
    if not contexts:
        return frozenset()
    for context in contexts:
        if not isinstance(context, TeachingContext):
            raise ValueError("teaching_context_invalid_complete_inventory")
        rebuilt = compile_teaching_contexts([{"id": context.author_alias, "ref": context.source_ref,
            "quote": context.quote}], sources)
        if rebuilt.issues or rebuilt.contexts != (context,):
            raise ValueError("teaching_context_invalid_complete_binding")
    full = set()
    for ref, (_, text) in sources.items():
        covered = [False] * len(text)
        for context in contexts:
            if context.source_ref == ref:
                covered[context.quote_start:context.quote_end] = [True] * len(context.quote)
        if covered and all(covered[index] for index, character in enumerate(text)
                           if character.isalnum() or character in "_><=≥≤≠+−%‰°²³/"):
            full.add(ref)
    return frozenset(full)


def teaching_context_inventory_valid(
    inventory: TeachingContextInventory,
    *,
    author_rows: object,
    audit_rows: object,
    sources: Mapping[str, tuple[str, str]],
    protected_spans: Sequence[TeachingContextProtectedSpan] = (),
) -> bool:
    """Strictly rederive current source bindings and audit admission, zero calls."""
    if not isinstance(inventory, TeachingContextInventory):
        return False
    try:
        rebuilt = admit_teaching_contexts(
            compile_teaching_contexts(author_rows, sources, protected_spans=protected_spans),
            audit_rows,
        )
    except (TypeError, ValueError):
        return False
    return rebuilt == inventory
