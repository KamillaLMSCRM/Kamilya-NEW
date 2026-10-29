"""Construct bounded operational options without deciding truth or answer keys."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.modules.ai.assessment_components import ComponentRequirement, OwnedComponent
from app.modules.ai.assessment_preservation import source_verb_government_edit_focus
from app.modules.ai.source_alternative_edit import derive_source_edits
from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE
from app.modules.ai.source_rule_construction import (
    SourceRuleSpec,
    construct_rule_options,
    protected_source_edit_spans,
)

MAX_OPTION_CHARS = 240
MAX_COMPONENTS = 2
MAX_PROPOSALS = 3
MAX_ID_CHARS = 192
MAX_SOURCE_CHARS = 65_536
_LINE_BREAKS = frozenset("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_HORIZONTAL_SPACE_CHARS = frozenset(SOURCE_HORIZONTAL_SPACE)
_RUSSIAN_WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
_EXEMPTION_TAIL = re.compile(r"(?<!\w)(?:кроме|за\s+исключением)(?!\w)", re.I)


@dataclass(frozen=True)
class OperationalComponentSpec:
    component_id: str
    source_id: str
    base: str
    action_focus: str


@dataclass(frozen=True)
class OperationalOptionSpec:
    target_id: str
    components: tuple[OperationalComponentSpec, ...]
    inventory_key: str


def _single_line(value: str) -> bool:
    return not any(character in _LINE_BREAKS for character in value)


def _bounded_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_ID_CHARS
        and value[0].isalnum()
        and all(character.isalnum() or character in ":._-" for character in value)
    )


def _component_belongs_to_target(component_id: object, target_id: str) -> bool:
    if not isinstance(component_id, str) or not _bounded_id(component_id):
        return False
    prefix = f"{target_id}:C"
    suffix = component_id[len(prefix):] if component_id.startswith(prefix) else ""
    return bool(suffix and suffix.isascii() and suffix.isdigit() and int(suffix) >= 1)


def _inventory_key(
    target_id: str,
    components: Sequence[OperationalComponentSpec],
) -> str:
    payload = [
        "operational-option-v1",
        target_id,
        [
            [
                component.component_id,
                component.source_id,
                component.base,
                component.action_focus,
            ]
            for component in components
        ],
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _valid_base(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= MAX_OPTION_CHARS
        and _single_line(value)
    )


def build_operational_spec(
    target_id: str,
    requirements: Sequence[ComponentRequirement],
    sources: Sequence[Any],
) -> OperationalOptionSpec | None:
    """Bind one or two exact source-owned components without semantic approval."""

    if not _bounded_id(target_id):
        return None
    if (
        isinstance(requirements, str | bytes)
        or not isinstance(requirements, Sequence)
        or not 1 <= len(requirements) <= MAX_COMPONENTS
        or isinstance(sources, str | bytes)
        or not isinstance(sources, Sequence)
        or not 1 <= len(sources) <= 4_096
    ):
        return None

    components: list[OperationalComponentSpec] = []
    seen_components: set[str] = set()
    owner_intervals: dict[str, list[tuple[int, int]]] = {}
    for requirement in requirements:
        if (
            not isinstance(requirement, ComponentRequirement)
            or requirement.target_id != target_id
            or requirement.full_set is not False
            or not isinstance(requirement.alternatives, tuple)
            or len(requirement.alternatives) != 1
            or not _component_belongs_to_target(requirement.component_id, target_id)
            or requirement.component_id in seen_components
        ):
            return None
        alternative = requirement.alternatives[0]
        if (
            not isinstance(alternative, OwnedComponent)
            or not _bounded_id(alternative.source_id)
            or not _valid_base(alternative.text)
        ):
            return None
        owners = [
            source
            for source in sources
            if getattr(source, "source_id", None) == alternative.source_id
        ]
        if len(owners) != 1:
            return None
        original = getattr(owners[0], "original_text", None)
        if (
            not isinstance(original, str)
            or not original
            or len(original) > MAX_SOURCE_CHARS
        ):
            return None
        prefix = r"(?<!\w)" if re.match(r"\w", alternative.text[0]) else ""
        suffix = r"(?!\w)" if re.match(r"\w", alternative.text[-1]) else ""
        occurrences = list(
            re.finditer(prefix + re.escape(alternative.text) + suffix, original)
        )
        if len(occurrences) != 1:
            return None
        interval = occurrences[0].span()
        if any(
            interval[0] < owned_end and interval[1] > owned_start
            for owned_start, owned_end in owner_intervals.setdefault(
                alternative.source_id,
                [],
            )
        ):
            return None
        action_focus = _source_action_focus(alternative.text)
        if action_focus is None:
            return None
        owner_intervals[alternative.source_id].append(interval)
        seen_components.add(requirement.component_id)
        components.append(
            OperationalComponentSpec(
                requirement.component_id,
                alternative.source_id,
                alternative.text,
                action_focus,
            )
        )

    combined = "; ".join(component.base for component in components)
    if len(combined) > MAX_OPTION_CHARS or not _single_line(combined):
        return None
    immutable_components = tuple(components)
    return OperationalOptionSpec(
        target_id,
        immutable_components,
        _inventory_key(target_id, immutable_components),
    )


@lru_cache(maxsize=1)
def _morphology() -> Any:
    import pymorphy3  # type: ignore[import-untyped]

    return pymorphy3.MorphAnalyzer()


def _is_unambiguous_infinitive(word: str) -> bool:
    try:
        normalized = word.casefold()
        if not _morphology().word_is_known(normalized):
            return False
        parses = _morphology().parse(normalized)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return bool(parses) and {parse.tag.POS for parse in parses} == {"INFN"}


def _noun_lemma(word: str) -> str | None:
    try:
        normalized = word.casefold()
        if not _morphology().word_is_known(normalized):
            return None
        parses = _morphology().parse(normalized)
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
    if not parses or {parse.tag.POS for parse in parses} != {"NOUN"}:
        return None
    lemmas = {parse.normal_form for parse in parses}
    return next(iter(lemmas)) if len(lemmas) == 1 else None


def _is_known_preposition(word: str) -> bool:
    try:
        normalized = word.casefold()
        if not _morphology().word_is_known(normalized):
            return False
        parses = _morphology().parse(normalized)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    if not parses or parses[0].tag.POS != "PREP":
        return False
    # One-letter Russian prepositions also receive dictionary initial/abbreviation
    # analyses. Longer words must have no competing lexical part of speech.
    return len(normalized) == 1 or {parse.tag.POS for parse in parses} == {"PREP"}


def _governor_phrase_signature(value: str) -> tuple[str, str, str] | None:
    matches = list(_RUSSIAN_WORD.finditer(value))
    if (
        len(matches) != 3
        or matches[0].start() != 0
        or matches[-1].end() != len(value)
    ):
        return None
    for left, right in zip(matches, matches[1:], strict=False):
        gap = value[left.end() : right.start()]
        if not gap or any(character not in _HORIZONTAL_SPACE_CHARS for character in gap):
            return None
    verb, prep, noun = (match.group() for match in matches)
    noun_lemma = _noun_lemma(noun)
    if (
        not _is_unambiguous_infinitive(verb)
        or not _is_known_preposition(prep)
        or noun_lemma is None
    ):
        return None
    return verb, prep, noun_lemma


def _source_action_focus(base: str) -> str | None:
    protected = protected_source_edit_spans(base)
    exemption = _EXEMPTION_TAIL.search(base)
    candidates: list[str] = []
    for match in _RUSSIAN_WORD.finditer(base):
        if not _is_unambiguous_infinitive(match.group()):
            continue
        if any(
            match.start() < protected_end and match.end() > protected_start
            for _, protected_start, protected_end in protected
        ):
            continue
        if exemption is not None and match.start() >= exemption.start():
            continue
        candidates.append(match.group())
    if len(candidates) != 1:
        return None
    phrase = source_verb_government_edit_focus(base, candidates[0])
    if phrase is not None:
        phrase_end = len(phrase)
        if not any(
            protected_start < phrase_end and protected_end > 0
            for _, protected_start, protected_end in protected
        ) and (exemption is None or phrase_end <= exemption.start()):
            return phrase
    return candidates[0]


def _unique_action_focus_span(base: str, focus: object) -> tuple[int, int] | None:
    if (
        not isinstance(focus, str)
        or not focus
        or focus != focus.strip()
        or len(focus) > MAX_OPTION_CHARS
    ):
        return None
    matches = list(re.finditer(rf"(?<!\w){re.escape(focus)}(?!\w)", base))
    if len(matches) != 1:
        return None
    if _RUSSIAN_WORD.fullmatch(focus) is not None:
        if not _is_unambiguous_infinitive(focus):
            return None
    else:
        first = _RUSSIAN_WORD.match(focus)
        if (
            first is None
            or source_verb_government_edit_focus(base, first.group()) != focus
        ):
            return None
    start, end = matches[0].span()
    if any(
        start < protected_end and end > protected_start
        for _, protected_start, protected_end in protected_source_edit_spans(base)
    ):
        return None
    exemption = _EXEMPTION_TAIL.search(base)
    if exemption is not None and start >= exemption.start():
        return None
    return start, end


def _validate_spec(spec: object) -> OperationalOptionSpec:
    if not isinstance(spec, OperationalOptionSpec) or not _bounded_id(spec.target_id):
        raise ValueError("invalid_operational_spec")
    if not isinstance(spec.components, tuple) or not 1 <= len(spec.components) <= 2:
        raise ValueError("invalid_operational_spec")
    seen: set[str] = set()
    for component in spec.components:
        if (
            not isinstance(component, OperationalComponentSpec)
            or not _component_belongs_to_target(component.component_id, spec.target_id)
            or not _bounded_id(component.source_id)
            or component.component_id in seen
            or not _valid_base(component.base)
            or component.action_focus != _source_action_focus(component.base)
        ):
            raise ValueError("invalid_operational_spec")
        seen.add(component.component_id)
    combined = "; ".join(component.base for component in spec.components)
    if len(combined) > MAX_OPTION_CHARS or spec.inventory_key != _inventory_key(
        spec.target_id,
        spec.components,
    ):
        raise ValueError("invalid_operational_spec")
    return spec


def _materialize_proposal(
    spec: OperationalOptionSpec,
    proposal: Mapping[str, Any],
    question_id: str,
) -> str:
    if set(proposal) != {"component_id", "action_focus", "replacement"}:
        raise ValueError("invalid_operational_proposal")
    component_id = proposal["component_id"]
    action_focus = proposal["action_focus"]
    replacement = proposal["replacement"]
    matches = [
        (index, component)
        for index, component in enumerate(spec.components)
        if component.component_id == component_id
    ]
    if (
        len(matches) != 1
        or not isinstance(replacement, str)
        or not replacement
        or replacement != replacement.strip()
        or len(replacement) > MAX_OPTION_CHARS
        or not _single_line(replacement)
    ):
        raise ValueError("invalid_operational_proposal")
    component_index, component = matches[0]
    if action_focus != component.action_focus:
        raise ValueError("invalid_operational_action_focus")
    focus_span = _unique_action_focus_span(component.base, action_focus)
    if focus_span is None:
        raise ValueError("invalid_operational_action_focus")
    focus_start, focus_end = focus_span
    prefix = component.base[:focus_start]
    suffix = component.base[focus_end:]
    if not replacement or replacement == component.base[focus_start:focus_end]:
        raise ValueError("invalid_operational_action_replacement")
    replacement_action = replacement[3:] if replacement.startswith("не ") else replacement
    if replacement.startswith("не") and not replacement.startswith("не "):
        raise ValueError("invalid_operational_action_replacement")
    if _RUSSIAN_WORD.fullmatch(action_focus) is None:
        source_signature = _governor_phrase_signature(action_focus)
        replacement_signature = _governor_phrase_signature(replacement_action)
        if (
            source_signature is None
            or replacement_signature is None
            or source_signature[2] != replacement_signature[2]
            or (
                not replacement.startswith("не ")
                and source_signature[0].casefold()
                == replacement_signature[0].casefold()
            )
        ):
            raise ValueError("invalid_operational_action_replacement")
    elif (
        _RUSSIAN_WORD.fullmatch(replacement_action) is None
        or not _is_unambiguous_infinitive(replacement_action)
    ):
        raise ValueError("invalid_operational_action_replacement")

    alternative = f"{prefix}{replacement}{suffix}"
    if not _valid_base(alternative):
        raise ValueError("operational_option_too_long")
    variants = derive_source_edits(component.base, (alternative,))
    rule_spec = SourceRuleSpec(
        base=component.base,
        stem="",
        owner=component.source_id,
        inventory_key=hashlib.sha256(
            f"{spec.inventory_key}:{component.component_id}".encode()
        ).hexdigest(),
        assessed_focus=action_focus,
    )
    validated = construct_rule_options(rule_spec, variants, question_id)
    if set(validated) != {component.base, alternative}:
        raise ValueError("operational_reconstruction_mismatch")

    parts = [item.base for item in spec.components]
    parts[component_index] = alternative
    option = "; ".join(parts)
    if len(option) > MAX_OPTION_CHARS or not _single_line(option):
        raise ValueError("operational_option_too_long")
    return option


def materialize_operational_options(
    spec: OperationalOptionSpec,
    proposals: Sequence[Mapping[str, Any]],
    question_id: str,
) -> tuple[str, ...]:
    """Return deterministic unmarked options; no position is a truth verdict."""

    validated_spec = _validate_spec(spec)
    if (
        isinstance(proposals, str | bytes)
        or not isinstance(proposals, Sequence)
        or not 1 <= len(proposals) <= MAX_PROPOSALS
        or not _bounded_id(question_id)
    ):
        raise ValueError("invalid_operational_options_input")

    base = "; ".join(component.base for component in validated_spec.components)
    options = [base]
    seen_proposals: set[tuple[object, object, object]] = set()
    for proposal in proposals:
        if (
            not isinstance(proposal, Mapping)
            or set(proposal) != {"component_id", "action_focus", "replacement"}
            or any(
                not isinstance(proposal[key], str)
                for key in ("component_id", "action_focus", "replacement")
            )
        ):
            raise ValueError("invalid_operational_proposal")
        signature = (
            proposal.get("component_id"),
            proposal.get("action_focus"),
            proposal.get("replacement"),
        )
        if signature in seen_proposals:
            raise ValueError("duplicate_operational_proposal")
        seen_proposals.add(signature)
        option = _materialize_proposal(validated_spec, proposal, question_id)
        if option in options:
            raise ValueError("duplicate_operational_option")
        options.append(option)

    return tuple(
        sorted(
            options,
            key=lambda option: hashlib.sha256(
                json.dumps(
                    [question_id, validated_spec.inventory_key, option],
                    ensure_ascii=False,
                ).encode()
            ).digest(),
        )
    )
