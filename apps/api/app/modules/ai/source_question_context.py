"""Literal original-source context binding, not semantic or display-label proof."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

MAX_CONTEXT_CHARS = 300
MAX_SOURCE_CHARS = 65_536
MAX_CONTEXT_PARTS = 12
MAX_SOURCES = 256
NEUTRAL_RULE_STEM = "Какой вариант полностью соответствует правилу?"


class OriginalContextBinding(TypedDict):
    source_id: str
    quote: str
    start: int
    end: int


def _fail(code: str) -> None:
    raise ValueError("source_question_context_" + code)


def _validate_source(source_id: Any, original_text: Any) -> None:
    if (not isinstance(source_id, str) or not source_id or len(source_id) > 192
            or any(character.isspace() for character in source_id)):
        _fail("owner")
    if not isinstance(original_text, str) or not original_text or len(original_text) > MAX_SOURCE_CHARS:
        _fail("source_bound")


def bind_original_context(source_id: str, original_text: str, quote: str) -> OriginalContextBinding:
    """Bind exact source bytes; do not normalize a heading, repair or choose an occurrence."""
    _validate_source(source_id, original_text)
    if (not isinstance(quote, str) or not quote or quote != quote.strip()
            or len(quote) > MAX_CONTEXT_CHARS):
        _fail("quote_bound")
    start = original_text.find(quote)
    if start < 0 or original_text.find(quote, start + 1) >= 0:
        _fail("not_unique_literal")
    return {"source_id": source_id, "quote": quote, "start": start, "end": start + len(quote)}


def validate_context_binding(
    binding: Any, *, source_id: str, original_text: str,
) -> OriginalContextBinding:
    """Recompute literal identity and reject, never repair, stored offsets or owner."""
    if not isinstance(binding, Mapping) or set(binding) != {"source_id", "quote", "start", "end"}:
        _fail("schema")
    if binding["source_id"] != source_id:
        _fail("owner")
    canonical = bind_original_context(source_id, original_text, binding["quote"])
    if (type(binding["start"]) is not int or binding["start"] != canonical["start"]
            or type(binding["end"]) is not int or binding["end"] != canonical["end"]):
        _fail("offset")
    return canonical


def render_neutral_rule_stem(bindings: Any, original_sources: Mapping[str, str]) -> str:
    """Render only revalidated original quotes; metadata is not an implicit premise."""
    if (not isinstance(bindings, Sequence) or isinstance(bindings, str | bytes)
            or len(bindings) > MAX_CONTEXT_PARTS or not isinstance(original_sources, Mapping)
            or len(original_sources) > MAX_SOURCES):
        _fail("render_schema")
    for owner, original in original_sources.items():
        _validate_source(owner, original)
    if sum(len(value) for value in original_sources.values()) > MAX_SOURCE_CHARS:
        _fail("source_bound")
    quotes = []
    seen = set()
    for binding in bindings:
        if not isinstance(binding, Mapping) or not isinstance(binding.get("source_id"), str):
            _fail("schema")
        owner = binding["source_id"]
        if owner not in original_sources:
            _fail("owner")
        validated = validate_context_binding(binding, source_id=owner, original_text=original_sources[owner])
        signature = (owner, validated["start"], validated["end"])
        if signature in seen:
            _fail("duplicate")
        seen.add(signature)
        quotes.append(validated["quote"])
    if sum(len(quote) for quote in quotes) > MAX_CONTEXT_CHARS:
        _fail("combined_bound")
    stem = ("Условие: " + "\n".join(quotes) + "\n" if quotes else "") + NEUTRAL_RULE_STEM
    if len(stem) > 500:
        _fail("render_bound")
    return stem
