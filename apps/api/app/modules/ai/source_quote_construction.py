"""Construct literal quoted-source recall slots, without a truth or key verdict."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NoReturn, TypedDict

from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE, parse_source_marker
from app.modules.ai.source_question_context import render_neutral_rule_stem
from app.modules.ai.source_question_identity import source_rule_identity

_LINE_BREAKS = "\r\n\v\f\u2028\u2029"
_SOURCE_HORIZONTAL_SPACE_CLASS = re.escape(SOURCE_HORIZONTAL_SPACE)
_POLAR_HEAD = re.compile(
    rf"(?<!\w)(?:(?i:не)[{_SOURCE_HORIZONTAL_SPACE_CLASS}]+)?"
    rf"[^\W\d_]+[{_SOURCE_HORIZONTAL_SPACE_CLASS}]+ли(?!\w)",
)
_PLACEHOLDER = re.compile(
    r"^(?:пропуск|вариант(?:\s+ответа)?|placeholder|blank|unknown|unreadable|"
    r"неизвестно|нет\s+данных|не\s+указано|n/?a|null|none)$",
    re.IGNORECASE,
)
_PLACEHOLDER_MARKER = re.compile(
    r"\[(?:пропуск|вариант(?:\s+ответа)?|placeholder|blank)\]",
)
_FORBIDDEN_AUTHORED_FIELDS = (
    "authored_stem",
    "question_stem",
    "question_text",
    "rendered_question",
    "source_edit_descriptors",
    "source_edits",
    "source_variants",
    "stem",
    "text",
    "token_edits",
    "variants",
)


class SourceQuoteBinding(TypedDict):
    source_id: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class SourceQuoteSpec:
    base: str
    stem: str
    owner: str
    inventory_key: str
    proposition_binding: Mapping[str, str | int]


def _fail(code: str) -> NoReturn:
    raise ValueError("source_quote_" + code)


def _normalized(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().replace("ё", "е").split(),
    )


def _cue_tokens(value: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", _normalized(value))


def _contains_phrase(haystack: str, needle: str) -> bool:
    haystack_tokens = _cue_tokens(haystack)
    needle_tokens = _cue_tokens(needle)
    return bool(needle_tokens) and any(
        haystack_tokens[start:start + len(needle_tokens)] == needle_tokens
        for start in range(len(haystack_tokens) - len(needle_tokens) + 1)
    )


def _is_placeholder(value: str) -> bool:
    if not any(character.isalnum() for character in value):
        return True
    if _contains_placeholder_marker(value):
        return True
    if "__" in value:
        return True
    normalized = _normalized(value).strip("[]{}()<>*_`'\".:;!?…—–- ")
    return bool(_PLACEHOLDER.fullmatch(normalized))


def _contains_placeholder_marker(value: str) -> bool:
    return _PLACEHOLDER_MARKER.search(_normalized(value)) is not None


def _alphabetic_token_count(value: str) -> int:
    count = 0
    inside_token = False
    for character in value:
        if character.isalpha():
            if not inside_token:
                count += 1
                inside_token = True
        else:
            inside_token = False
    return count


def _source_body_start(value: str) -> int:
    marker = parse_source_marker(value)
    return marker.content_start if marker is not None else 0


def _remaining_quote_context(quote: str, focus_start: int, focus_end: int) -> str:
    body_start = _source_body_start(quote)
    before = quote[body_start:focus_start] if body_start < focus_start else ""
    after = quote[max(body_start, focus_end):]
    return before + " " + after


def _validate_focus(focus: Any, quote: str) -> tuple[int, int]:
    if (
        not isinstance(focus, str)
        or not focus
        or focus != focus.strip()
        or len(focus) > 240
        or any(character in focus for character in _LINE_BREAKS)
    ):
        _fail("invalid_focus")
    if _is_placeholder(focus):
        _fail("placeholder_focus")
    marker_probe = focus + " synthetic_body"
    marker = parse_source_marker(marker_probe)
    if marker is not None and marker.raw_start == 0 and marker.content_start == len(focus) + 1:
        _fail("marker_focus")
    start = quote.find(focus)
    if 0 <= start < _source_body_start(quote):
        _fail("marker_focus")
    if start < 0 or quote.find(focus, start + 1) >= 0:
        _fail("unowned_focus")
    end = start + len(focus)
    if (
        (start > 0 and quote[start - 1].isalnum() and focus[0].isalnum())
        or (end < len(quote) and quote[end].isalnum() and focus[-1].isalnum())
    ):
        _fail("unowned_focus")
    return start, end


def _focus_overlaps_polar_head(quote: str, focus_start: int, focus_end: int) -> bool:
    return any(
        focus_start < head.end() and head.start() < focus_end
        for head in _POLAR_HEAD.finditer(quote)
    )


def source_polar_observation_focus(source: str) -> str | None:
    """Return a literal CHECK-WHETHER suffix, without completing its actor.

    This narrow structural locator supports omitted actor/modal prefixes in a
    rejected draft. It does not resolve entailment, infer an antonym or approve
    an option. Other observation verbs and multiple polar heads stay unproved.
    """
    if not isinstance(source, str) or not 1 <= len(source) <= 512:
        return None
    heads = tuple(_POLAR_HEAD.finditer(source))
    if len(heads) != 1:
        return None
    check = re.search(r"(?<!\w)проверить,[\s]*$", source[:heads[0].start()], re.IGNORECASE)
    if check is None:
        return None
    tail = source[heads[0].end():].rstrip(" .!?…;")
    if not any(character.isalpha() for character in tail):
        return None
    return source[check.start():].rstrip(" .!?…;")


def polar_head_only_contrast(left: str, right: str) -> bool:
    """Return whether two strings differ only in one embedded polar head.

    This is deliberately a key-blind structural predicate.  It does not decide
    which wording is correct, and it never rewrites either input string.
    """
    if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
        return False
    left_heads = tuple(_POLAR_HEAD.finditer(left))
    right_heads = tuple(_POLAR_HEAD.finditer(right))
    if len(left_heads) != 1 or len(right_heads) != 1:
        return False
    left_head, right_head = left_heads[0], right_heads[0]

    def layout(value: str) -> str:
        # Unlike slot cue matching, do not erase units/exponents or ё/е here.
        # A negative-only contrast needs unchanged material outside the head.
        return " ".join(value.casefold().split())

    if layout(left_head.group()) == layout(right_head.group()):
        return False
    left_outside = (
        layout(left[:left_head.start()]),
        layout(left[left_head.end():]).rstrip(".!?…").rstrip(),
    )
    right_outside = (
        layout(right[:right_head.start()]),
        layout(right[right_head.end():]).rstrip(".!?…").rstrip(),
    )
    return left_outside == right_outside


def _target_shape(target: Any) -> tuple[str, str, tuple[str, ...]]:
    try:
        requirements = target.answer_requirements
        component_owners = target.component_source_ids
        source_ids = target.source_ids
        focus = target.assessed_focus
        eligible = (
            target.construction_mode == "source_quote_slot"
            and not target.question_format
            and isinstance(requirements, Sequence)
            and not isinstance(requirements, str | bytes)
            and len(requirements) == 1
            and isinstance(requirements[0], Sequence)
            and not isinstance(requirements[0], str | bytes)
            and len(requirements[0]) == 1
            and isinstance(component_owners, Sequence)
            and not isinstance(component_owners, str | bytes)
            and len(component_owners) == 1
            and isinstance(component_owners[0], Sequence)
            and not isinstance(component_owners[0], str | bytes)
            and len(component_owners[0]) == 1
            and isinstance(source_ids, Sequence)
            and not isinstance(source_ids, str | bytes)
            and all(isinstance(source_id, str) for source_id in source_ids)
            and isinstance(focus, str)
            and requirements[0][0] == focus
            and target.fixed_source_context is None
            and getattr(target, "numeric_rule", None) is None
            and all(not getattr(target, field, None) for field in _FORBIDDEN_AUTHORED_FIELDS)
        )
    except (AttributeError, IndexError, TypeError):
        _fail("ineligible_target")
    if not eligible:
        _fail("ineligible_target")
    owner = component_owners[0][0]
    if (
        not isinstance(owner, str)
        or not owner
        or len(owner) > 192
        or any(character.isspace() for character in owner)
        or owner not in source_ids
    ):
        _fail("owner")
    return focus, owner, tuple(source_ids)


def _sources_by_id(sources: Any, required_ids: set[str]) -> dict[str, str]:
    if not isinstance(sources, Sequence) or isinstance(sources, str | bytes) or len(sources) > 256:
        _fail("owner")
    grouped: dict[str, list[Any]] = {required_id: [] for required_id in required_ids}
    for source in sources:
        candidate_id = getattr(source, "source_id", None)
        if not isinstance(candidate_id, str):
            continue
        if candidate_id in grouped:
            grouped[candidate_id].append(source)
    originals: dict[str, str] = {}
    for required_id, matches in grouped.items():
        if len(matches) != 1:
            _fail("owner")
        original = getattr(matches[0], "original_text", None)
        if not isinstance(original, str) or not original or len(original) > 65_536:
            _fail("original_bound")
        originals[required_id] = original
    return originals


def _canonical_proposition(value: Any, *, owner: str, original: str) -> SourceQuoteBinding:
    if not isinstance(value, Mapping):
        _fail("proposition_schema")
    keys = set(value)
    if keys not in ({"source_id", "quote"}, {"source_id", "quote", "start", "end"}):
        _fail("proposition_schema")
    if value["source_id"] != owner:
        _fail("owner")
    quote = value["quote"]
    if (
        not isinstance(quote, str)
        or not quote
        or quote != quote.strip()
        or len(quote) > 400
    ):
        _fail("quote_bound")
    start = original.find(quote)
    if start < 0 or original.find(quote, start + 1) >= 0:
        _fail("not_unique_original")
    end = start + len(quote)
    if (
        (start > 0 and original[start - 1].isalnum() and quote[0].isalnum())
        or (end < len(original) and original[end].isalnum() and quote[-1].isalnum())
    ):
        _fail("unbounded_original")
    canonical: SourceQuoteBinding = {
        "source_id": owner,
        "quote": quote,
        "start": start,
        "end": end,
    }
    if len(keys) == 4 and (
        type(value["start"]) is not int
        or value["start"] != canonical["start"]
        or type(value["end"]) is not int
        or value["end"] != canonical["end"]
    ):
        _fail("offset")
    return canonical


def _validated_context(
    target: Any,
    *,
    sources: Sequence[Any],
    source_ids: Sequence[Any],
) -> tuple[str, ...]:
    bindings = getattr(target, "original_context_bindings", ())
    if not isinstance(bindings, Sequence) or isinstance(bindings, str | bytes):
        _fail("context_schema")
    owners: list[str] = []
    for binding in bindings:
        if not isinstance(binding, Mapping) or not isinstance(binding.get("source_id"), str):
            _fail("context_schema")
        if binding["source_id"] not in source_ids:
            _fail("context_owner")
        owners.append(binding["source_id"])
    originals = _sources_by_id(sources, set(owners)) if owners else {}
    try:
        render_neutral_rule_stem(bindings, originals)
    except ValueError as error:
        suffix = str(error).removeprefix("source_question_context_")
        mapped = {
            "combined_bound": "context_bound",
            "quote_bound": "context_bound",
            "source_bound": "original_bound",
            "owner": "context_owner",
            "offset": "context_offset",
            "not_unique_literal": "context_literal",
            "duplicate": "context_duplicate",
            "schema": "context_schema",
            "render_schema": "context_schema",
            "render_bound": "context_bound",
        }.get(suffix, "context_schema")
        _fail(mapped)
    quotes_list: list[str] = []
    for binding in bindings:
        quote = binding["quote"]
        if not isinstance(quote, str):
            _fail("context_schema")
        quotes_list.append(quote)
    quotes = tuple(quotes_list)
    expected_context = " ".join(dict.fromkeys(quotes))
    if getattr(target, "context", "") != expected_context:
        _fail("unbound_context")
    return quotes


def build_quote_slot_spec(target: Any, sources: Sequence[Any]) -> SourceQuoteSpec:
    """Revalidate one exact source phrase and render one neutral document blank."""
    focus, owner, source_ids = _target_shape(target)
    originals = _sources_by_id(sources, {owner})
    proposition = _canonical_proposition(
        getattr(target, "source_quote_proposition", None),
        owner=owner,
        original=originals[owner],
    )
    quote = proposition["quote"]
    focus_start, focus_end = _validate_focus(focus, quote)
    if _focus_overlaps_polar_head(quote, focus_start, focus_end):
        _fail("polar_head_focus")
    context_quotes = _validated_context(target, sources=sources, source_ids=source_ids)
    if any(_contains_phrase(context_quote, focus) for context_quote in context_quotes):
        _fail("answer_disclosing_context")
    if _contains_placeholder_marker(quote) or any(
        _contains_placeholder_marker(context_quote) for context_quote in context_quotes
    ):
        _fail("placeholder_collision")
    source_context_count = _alphabetic_token_count(
        _remaining_quote_context(quote, focus_start, focus_end),
    ) + sum(
        _alphabetic_token_count(context_quote[_source_body_start(context_quote):])
        for context_quote in context_quotes
    )
    if source_context_count < 2:
        _fail("insufficient_context")
    blanked = quote[:focus_start] + "[пропуск]" + quote[focus_end:]
    context_prefix = "Условие: " + "\n".join(context_quotes) + "\n" if context_quotes else ""
    stem = (
        context_prefix
        + "Какой вариант верно дополняет правило по смыслу документа: «"
        + blanked
        + "»?"
    )
    if len(_PLACEHOLDER_MARKER.findall(_normalized(stem))) != 1:
        _fail("placeholder_collision")
    if _contains_phrase(stem, focus):
        _fail("answer_disclosing_stem")
    if len(stem) > 500 or stem != stem.strip():
        _fail("stem_bound")
    immutable_proposition: Mapping[str, str | int] = MappingProxyType({
        "source_id": proposition["source_id"],
        "quote": proposition["quote"],
        "start": proposition["start"],
        "end": proposition["end"],
    })
    return SourceQuoteSpec(
        base=focus,
        stem=stem,
        owner=owner,
        inventory_key=source_rule_identity(stem, focus),
        proposition_binding=immutable_proposition,
    )


def construct_quote_options(
    spec: SourceQuoteSpec,
    alternatives: Any,
    question_id: str,
) -> tuple[str, ...]:
    """Join and deterministically order raw choices; never return a key or verdict."""
    if (
        not isinstance(alternatives, Sequence)
        or isinstance(alternatives, str | bytes)
        or not 1 <= len(alternatives) <= 3
    ):
        _fail("options_schema")
    if (
        not isinstance(question_id, str)
        or not question_id
        or question_id != question_id.strip()
        or len(question_id) > 192
        or any(character in question_id for character in _LINE_BREAKS)
    ):
        _fail("options_question_id")
    base = getattr(spec, "base", None)
    inventory_key = getattr(spec, "inventory_key", None)
    if not isinstance(base, str) or not base or not isinstance(inventory_key, str) or not inventory_key:
        _fail("options_spec")
    choices = [base]
    for alternative in alternatives:
        if (
            not isinstance(alternative, str)
            or not alternative
            or alternative != alternative.strip()
            or len(alternative) > 240
            or any(character in alternative for character in _LINE_BREAKS)
        ):
            _fail("options_bound")
        if _is_placeholder(alternative):
            _fail("options_placeholder")
        choices.append(alternative)
    normalized = [_normalized(choice) for choice in choices]
    if len(set(normalized)) != len(normalized):
        _fail("options_duplicate")
    compact = ["".join(character for character in value if character.isalnum()) for value in normalized]
    for alternative, alternative_compact in zip(normalized[1:], compact[1:], strict=True):
        if (
            normalized[0] in alternative
            or alternative in normalized[0]
            or compact[0] in alternative_compact
            or alternative_compact in compact[0]
        ):
            _fail("options_containment")
    return tuple(sorted(choices, key=lambda option: hashlib.sha256(
        json.dumps([question_id, inventory_key, option], ensure_ascii=False).encode(),
    ).digest()))
