"""Compile source-owned recognition questions, without a truth/key verdict."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.modules.ai.assessment_preservation import source_verb_government_issue
from app.modules.ai.source_question_context import render_neutral_rule_stem
from app.modules.ai.source_question_identity import source_rule_identity
from app.modules.ai.source_question_parts import validate_fixed_source_context
from app.modules.ai.source_question_variants import materialize_source_variants

_SENTENCE_ENVELOPE = ".,;!?…«»\"'“”‘’()[]{} \t\r\n"


@dataclass(frozen=True)
class SourceRuleSpec:
    base: str
    stem: str
    owner: str
    inventory_key: str
    applicability: tuple[str, ...] = ()
    assessed_focus: str = ""


def _cue_tokens(value: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", value.casefold().replace("ё", "е"))


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Negative cue guard only; never normalization of saved/source text."""
    haystack_tokens = _cue_tokens(haystack)
    needle_tokens = _cue_tokens(needle)
    return bool(needle_tokens) and any(haystack_tokens[start:start + len(needle_tokens)] == needle_tokens
        for start in range(len(haystack_tokens) - len(needle_tokens) + 1))


def _changed_original_fragments(original: str, replacement: str) -> tuple[str, ...]:
    """Isolate changed tokens within an already bounded edit, including all symbols."""
    before, after = _cue_tokens(original), _cue_tokens(replacement)
    fragments = []
    for operation, first, last, _, _ in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if operation == "equal":
            continue
        changed = before[first:last]
        if operation == "insert" and before:
            changed = before[first:first + 1] or before[-1:]
        if changed:
            fragments.append(" ".join(changed))
    return tuple(fragments)


def _modal_weakening_only(base: str, alternative: str) -> bool:
    """Negative bounded form guard, not a truth/key or arbitrary prose classifier."""
    before, after = _cue_tokens(base), _cue_tokens(alternative)
    changes = [op for op in SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if op[0] != "equal"]
    if len(changes) != 1:
        return False
    operation, first, last, changed_first, changed_last = changes[0]
    if operation != "replace" or last - first != 1 or changed_last - changed_first != 1:
        return False
    if first and before[first - 1] == "не":
        return False
    required = {"должен", "должна", "должно", "должны", "обязан", "обязана", "обязано", "обязаны",
                "необходимо", "нужно", "следует", "требуется"}
    permitted = {"может", "могут", "можно", "вправе", "разрешается", "допускается", "допустимо"}
    return before[first] in required and after[changed_first] in permitted


def protected_source_edit_spans(base: str) -> tuple[tuple[str, int, int], ...]:
    """Conservative contrast exclusions, not meaning or assessed-coverage proof."""
    spans = []
    stack = []
    for index, character in enumerate(base):
        if character == "(":
            stack.append(index)
        elif character == ")":
            if not stack:
                return (("unbalanced_qualification", 0, len(base)),)
            spans.append(("qualification", stack.pop(), index + 1))
    if stack:
        return (("unbalanced_qualification", 0, len(base)),)
    for particle in re.finditer(r"(?<!\w)ли(?!\w)", base, re.I):
        words = list(re.finditer(r"\w+", base[:particle.start()]))
        if not words:
            start = 0
        else:
            start = words[-1].start()
            if len(words) > 1 and words[-2].group().casefold() == "не":
                start = words[-2].start()
        # A comma + infinitive is NOT proof that an embedded question ended.
        spans.append(("polar_observation", start, len(base)))
    return tuple(spans)


def _protected_edit_issue(base: str, start: int, end: int, replacement: str) -> str | None:
    original = base[start:end]
    prefix = 0
    while prefix < min(len(original), len(replacement)) and original[prefix] == replacement[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(original) - prefix, len(replacement) - prefix)
           and original[-suffix - 1] == replacement[-suffix - 1]):
        suffix += 1
    first, last = start + prefix, end - suffix
    for kind, left, right in protected_source_edit_spans(base):
        if first == last:
            overlaps = left <= first <= right if kind != "qualification" else left < first < right
        else:
            overlaps = first < right and last > left
        if overlaps:
            return "source_rule_protected_" + kind
    return None


def _focus_changed(base: str, focus: str, start: int, end: int, replacement: str) -> bool:
    left, right = base.index(focus), base.index(focus) + len(focus)
    for operation, first, last, _, _ in SequenceMatcher(
        None, base[start:end], replacement, autojunk=False,
    ).get_opcodes():
        if operation == "equal":
            continue
        first, last = start + first, start + last
        if (first == last and left <= first <= right) or (first < right and last > left):
            return True
    return False


def source_rule_focus_issue(base: str, focus: object) -> str | None:
    """Negative focus checks shared by construction and multi-field feedback."""
    if not isinstance(focus, str) or len(focus) > 240 or focus != focus.strip():
        return "source_rule_invalid_assessed_focus"
    protected = protected_source_edit_spans(base)
    if not focus:
        return "source_rule_missing_assessed_focus" if protected else None
    start = base.find(focus)
    end = start + len(focus)
    if (start < 0 or base.find(focus, start + 1) >= 0
            or (start > 0 and base[start - 1].isalnum() and focus[0].isalnum())
            or (end < len(base) and base[end].isalnum() and focus[-1].isalnum())):
        return "source_rule_unowned_assessed_focus"
    if any(start < right and end > left for _, left, right in protected):
        return "source_rule_protected_assessed_focus"
    return None


def build_rule_spec(target: Any, sources: Sequence[Any]) -> SourceRuleSpec:
    """Revalidate every premise from original bytes; never convert a legacy target."""
    if (target.construction_mode != "source_edit_rule" or target.question_format
            or getattr(target, "source_quote_proposition", None) is not None
            or len(target.answer_requirements) != 1 or len(target.answer_requirements[0]) != 1
            or len(target.component_source_ids) != 1 or len(target.component_source_ids[0]) != 1):
        raise ValueError("source_rule_ineligible_target")
    owner = target.component_source_ids[0][0]
    owned = [source for source in sources if source.source_id == owner]
    if len(owned) != 1 or owner not in target.source_ids:
        raise ValueError("source_rule_owner")
    original = owned[0].original_text
    base = target.answer_requirements[0][0]
    if (not isinstance(original, str) or not original or len(original) > 65_536
            or not isinstance(base, str) or not base or base != base.strip() or len(base) > 240
            or any(character in base for character in "\r\n\v\f\u2028\u2029")):
        raise ValueError("source_rule_original_bounds")
    position = original.find(base)
    if position < 0 or original.find(base, position + 1) >= 0:
        raise ValueError("source_rule_not_unique_original")
    focus = target.assessed_focus
    if issue := source_rule_focus_issue(base, focus):
        raise ValueError(issue)
    focus = focus or base
    originals = {source.source_id: source.original_text for source in sources if source.original_text}
    bindings = target.original_context_bindings
    context = " ".join(dict.fromkeys(row.get("quote", "") for row in bindings if isinstance(row, dict)))
    if target.context != context:
        raise ValueError("source_rule_unbound_context")
    if any(not isinstance(row, dict) or row.get("source_id") not in target.source_ids for row in bindings):
        raise ValueError("source_rule_context_owner")
    stem = render_neutral_rule_stem(bindings, originals)
    if _contains_phrase(context, base.strip(_SENTENCE_ENVELOPE)):
        raise ValueError("source_rule_answer_disclosing_context")
    fixed = target.fixed_source_context
    if fixed is not None:
        fixed = validate_fixed_source_context(fixed, source_id=owner, source_text=original, variable=base)
        if _contains_phrase(context, fixed["fixed_text"].strip(_SENTENCE_ENVELOPE)):
            raise ValueError("source_rule_repeated_fixed_context")
        if any(row["source_id"] == owner and row["start"] < fixed["fixed_end"]
               and row["end"] > fixed["fixed_start"] for row in bindings):
            raise ValueError("source_rule_repeated_fixed_context")
        insertion = ("[вариант] " + fixed["fixed_text"] if fixed["position"] == "suffix"
                     else fixed["fixed_text"] + " [вариант]")
        context_prefix = stem.rsplit("\n", 1)[0] + "\n" if bindings else ""
        stem = context_prefix + "Дополните правило: «" + insertion + "»."
        if len(stem) > 500:
            raise ValueError("source_rule_stem_bound")
    return SourceRuleSpec(base, stem, owner, source_rule_identity(stem, base, assessed_focus=focus),
                          tuple(row["quote"] for row in bindings), focus)


def construct_rule_options(spec: SourceRuleSpec, variants: Any, question_id: str) -> tuple[str, ...]:
    """Unmark/order materialized options; callers still require two blind critics."""
    options = materialize_source_variants(spec.base, variants)
    source_tokens = re.findall(r"\S+", spec.base)
    raw_tokens = list(re.finditer(r"\S+", spec.base))
    for variant in variants:
        first, last = variant["token_span"]
        original_edit = " ".join(source_tokens[first - 1:last])
        if any(_contains_phrase(" ".join(spec.applicability), fragment)
               for fragment in _changed_original_fragments(original_edit, variant["replacement"])):
            raise ValueError("source_rule_answer_disclosing_context")
        if issue := _protected_edit_issue(spec.base, raw_tokens[first - 1].start(), raw_tokens[last - 1].end(),
                                          variant["replacement"]):
            raise ValueError(issue)
        if not _focus_changed(spec.base, spec.assessed_focus or spec.base, raw_tokens[first - 1].start(),
                              raw_tokens[last - 1].end(), variant["replacement"]):
            raise ValueError("source_rule_focus_not_discriminated")
    if any(_modal_weakening_only(spec.base, option) for option in options if option != spec.base):
        raise ValueError("source_rule_unproved_modal_contradiction")
    if spec.assessed_focus:
        for option in options:
            if option != spec.base and (issue := source_verb_government_issue(spec.base, spec.assessed_focus, option)):
                raise ValueError(issue)
    return tuple(sorted(options, key=lambda option: hashlib.sha256(
        json.dumps([question_id, spec.inventory_key, option], ensure_ascii=False).encode()).digest()))
