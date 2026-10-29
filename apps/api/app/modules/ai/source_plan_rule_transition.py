"""Pure custody helpers for an audited ordinary-to-source-rule transition.

The helpers grant no admission.  They only derive a bounded request descriptor
from already-held evidence and compile one exact partial response with two
server-owned fields.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from typing import Any, TypeGuard

from app.modules.ai.source_rule_construction import source_rule_focus_issue

RULE_TRANSITION_POLICY = "ordinary-to-source-edit-rule-v1"
RULE_TRANSITION_PREVIEW_POLICY = "ordinary-to-source-edit-rule-preview-v1"
MAX_SOURCE_EDIT_RULE_CHARS = 240
_SOURCE_RULE_LINE_BREAKS = "\r\n\v\f\u2028\u2029"

_CURRENT_MODE_FIELDS = (
    "governing_bindings",
    "context",
    "question_format",
    "answer_components",
)
_AUDIT_REPAIR_FIELDS = frozenset({
    "source_refs",
    "governing_bindings",
    "context",
    "question_format",
    "answer_components",
    "construction_mode",
    "fixed_source_context",
    "assessed_focus",
    "source_quote_proposition",
})
_INCOMPATIBLE_AUDIT_FIELDS = frozenset({
    "source_refs",
    "fixed_source_context",
    "source_quote_proposition",
})
_OBLIGATION_FIELDS = frozenset({
    "id",
    "ref",
    "quote",
    "dimension",
    "target_ids",
    "evidence_level",
})
_TRANSITION_FIELDS = frozenset({
    "policy",
    "target_id",
    "source_refs",
    "repair_fields",
    "obligation",
    "held_component",
    "held_question_format",
    "semantic_approval",
    "requires_fresh_complete_audit",
})


class RuleTransitionError(ValueError):
    """Finite failure codes for malformed compiler input."""

    CODES = frozenset({
        "invalid_transition",
        "target_patch_schema",
        "target_identity",
        "answer_component",
        "question_format",
        "inventory_shape",
        "inventory_duplicate",
        "inventory_mutation",
        "inventory_new_link",
    })

    def __init__(self, code: str):
        if code not in self.CODES:
            raise ValueError("unknown_rule_transition_error")
        super().__init__("source_plan_rule_transition_" + code)
        self.code = code


def _string_collection(value: object) -> set[str] | None:
    if isinstance(value, str | bytes) or not isinstance(value, Collection):
        return None
    rows = list(value)
    if any(not isinstance(row, str) for row in rows):
        return None
    return set(rows)


def _repair_fields(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or any(not isinstance(row, str) for row in value):
        return None
    if len(value) != len(set(value)):
        return None
    return tuple(value)


def _single_component(value: object) -> tuple[str, str] | None:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
        return None
    group = value[0]
    terms = group.get("terms")
    if set(group) != {"ref", "terms"} or not isinstance(group.get("ref"), str):
        return None
    if not isinstance(terms, list) or len(terms) != 1 or not isinstance(terms[0], str):
        return None
    return group["ref"], terms[0]


def _ordinary_defaults_only(target: Mapping[str, Any]) -> bool:
    """Accept absent or harmless empty defaults; never infer a typed value."""
    allowed_defaults: dict[str, tuple[object, ...]] = {
        "assessed_focus": ("", None),
        "fixed_source_context": (None,),
        "source_quote_proposition": (None,),
        "original_context_bindings": (None, []),
    }
    return all(field not in target or target[field] in defaults
               for field, defaults in allowed_defaults.items())


def _immutable_full_focus_eligible(quote: object) -> TypeGuard[str]:
    """Match constructor bounds and its canonical protected-focus decision."""
    return (
        isinstance(quote, str)
        and bool(quote)
        and quote == quote.strip()
        and len(quote) <= MAX_SOURCE_EDIT_RULE_CHARS
        and not any(character in quote for character in _SOURCE_RULE_LINE_BREAKS)
        and source_rule_focus_issue(quote, quote) is None
    )


def _inspect_rule_transition_material(
    *,
    held_target: Mapping[str, Any],
    held_obligations: Sequence[Mapping[str, Any]],
    source_text_by_ref: Mapping[str, str],
    native_repair_fields: Sequence[str],
    admitted_target_ids: Collection[str],
    locked_target_ids: Collection[str],
) -> dict[str, Any] | None:
    """Validate immutable held material without granting audit authority."""
    if not isinstance(held_target, Mapping):
        return None
    target_id = held_target.get("id")
    source_refs = held_target.get("source_refs")
    if (not isinstance(target_id, str) or not target_id
            or held_target.get("construction_mode", "") != ""
            or not _ordinary_defaults_only(held_target)
            or not isinstance(source_refs, list) or not source_refs
            or any(not isinstance(ref, str) or not ref for ref in source_refs)
            or len(source_refs) != len(set(source_refs))):
        return None
    admitted = _string_collection(admitted_target_ids)
    locked = _string_collection(locked_target_ids)
    if admitted is None or locked is None or target_id in admitted or target_id in locked:
        return None
    try:
        native = _repair_fields(list(native_repair_fields))
    except TypeError:
        return None
    if native is None:
        return None
    if (isinstance(held_obligations, str | bytes)
            or not isinstance(held_obligations, Sequence)
            or not isinstance(source_text_by_ref, Mapping)):
        return None
    obligations: list[Mapping[str, Any]] = []
    for row in held_obligations:
        if (not isinstance(row, Mapping) or set(row) != _OBLIGATION_FIELDS
                or not isinstance(row.get("target_ids"), list)
                or any(not isinstance(owner, str) for owner in row["target_ids"])):
            return None
        if target_id in row["target_ids"]:
            obligations.append(row)
    if len(obligations) != 1:
        return None
    obligation = obligations[0]
    quote = obligation.get("quote")
    ref = obligation.get("ref")
    if (obligation.get("target_ids") != [target_id]
            or obligation.get("evidence_level") != "operational_decision"
            or not isinstance(obligation.get("id"), str) or not obligation["id"]
            or not isinstance(ref, str) or ref not in source_refs
            or not _immutable_full_focus_eligible(quote)
            or not isinstance(obligation.get("dimension"), str) or not obligation["dimension"]
            or not isinstance(source_text_by_ref.get(ref), str)
            or source_text_by_ref[ref].count(quote) != 1):
        return None
    question_format = held_target.get("question_format", "")
    if not isinstance(question_format, str):
        return None
    held_component = _single_component(held_target.get("answer_components"))
    return {
        "target_id": target_id,
        "source_refs": list(source_refs),
        "native_repair_fields": native,
        "obligation": obligation,
        "held_component": held_component,
        "held_question_format": question_format,
    }


def inspect_rule_transition_preview(
    *,
    held_target: Mapping[str, Any],
    held_obligations: Sequence[Mapping[str, Any]],
    source_text_by_ref: Mapping[str, str],
    native_repair_fields: Sequence[str] = (),
    admitted_target_ids: Collection[str] = (),
    locked_target_ids: Collection[str] = (),
) -> dict[str, Any] | None:
    """Describe one technically possible transition without authorizing it."""
    material = _inspect_rule_transition_material(
        held_target=held_target,
        held_obligations=held_obligations,
        source_text_by_ref=source_text_by_ref,
        native_repair_fields=native_repair_fields,
        admitted_target_ids=admitted_target_ids,
        locked_target_ids=locked_target_ids,
    )
    if material is None:
        return None
    obligation = material["obligation"]
    ref, quote = obligation["ref"], obligation["quote"]
    held_component = material["held_component"]
    held_wire = ({"ref": held_component[0], "terms": [held_component[1]]}
                 if held_component else None)
    candidate = {"ref": ref, "terms": [quote]}
    deltas = ["construction_mode"]
    if held_wire != candidate:
        deltas.append("answer_components")
    if material["held_question_format"]:
        deltas.append("question_format")
    return {
        "policy": RULE_TRANSITION_PREVIEW_POLICY,
        "target_id": material["target_id"],
        "source_refs": list(material["source_refs"]),
        "obligation_id": obligation["id"],
        "source_ref": ref,
        "construction_mode": {"held": "", "candidate": "source_edit_rule"},
        "assessed_focus": {
            "candidate": quote,
            "source": "immutable_obligation_quote",
        },
        "answer_component": {
            "held": held_wire,
            "candidate": candidate,
            "change_required": held_wire != candidate,
        },
        "would_change_fields": deltas,
        "semantic_approval": False,
        "authorized": False,
    }


def derive_rule_transition(
    *,
    held_target: Mapping[str, Any],
    held_obligations: Sequence[Mapping[str, Any]],
    source_text_by_ref: Mapping[str, str],
    audit_target_verdict: Mapping[str, Any] | None,
    native_repair_fields: Sequence[str] = (),
    admitted_target_ids: Collection[str] = (),
    locked_target_ids: Collection[str] = (),
) -> dict[str, Any] | None:
    """Derive one request-only transition, or no operation when ineligible.

    Audit authority is mandatory. Native fields are intersected with the held
    ordinary-mode field set and can never authorize or shape the transition.
    """
    if not isinstance(audit_target_verdict, Mapping):
        return None
    material = _inspect_rule_transition_material(
        held_target=held_target,
        held_obligations=held_obligations,
        source_text_by_ref=source_text_by_ref,
        native_repair_fields=native_repair_fields,
        admitted_target_ids=admitted_target_ids,
        locked_target_ids=locked_target_ids,
    )
    if material is None:
        return None
    target_id = material["target_id"]
    source_refs = material["source_refs"]

    fields = _repair_fields(audit_target_verdict.get("repair_fields"))
    errors = audit_target_verdict.get("errors")
    if (audit_target_verdict.get("target_id") != target_id
            or audit_target_verdict.get("admit") is not False
            or not isinstance(errors, list) or not errors
            or any(not isinstance(error, str) or not error.strip() for error in errors)
            or fields is None or "construction_mode" not in fields
            or not set(fields) <= _AUDIT_REPAIR_FIELDS
            or _INCOMPATIBLE_AUDIT_FIELDS & set(fields)):
        return None

    native = material["native_repair_fields"]
    producer_fields = tuple(field for field in _CURRENT_MODE_FIELDS
                            if field in set(fields) | set(native))
    obligation = material["obligation"]
    quote = obligation["quote"]
    ref = obligation["ref"]
    held_component = material["held_component"]
    component_matches = held_component == (ref, quote)
    if not component_matches and "answer_components" not in producer_fields:
        return None
    question_format = material["held_question_format"]
    if question_format and "question_format" not in producer_fields:
        return None

    return {
        "policy": RULE_TRANSITION_POLICY,
        "target_id": target_id,
        "source_refs": list(source_refs),
        "repair_fields": list(producer_fields),
        "obligation": deepcopy(dict(obligation)),
        "held_component": ({"ref": held_component[0], "quote": held_component[1]}
                           if held_component else None),
        "held_question_format": question_format,
        "semantic_approval": False,
        "requires_fresh_complete_audit": True,
    }


def _validate_transition(transition: object) -> Mapping[str, Any]:
    if not isinstance(transition, Mapping) or set(transition) != _TRANSITION_FIELDS:
        raise RuleTransitionError("invalid_transition")
    target_id = transition.get("target_id")
    source_refs = transition.get("source_refs")
    repair_fields = transition.get("repair_fields")
    obligation = transition.get("obligation")
    held_component = transition.get("held_component")
    if (transition.get("policy") != RULE_TRANSITION_POLICY
            or transition.get("semantic_approval") is not False
            or transition.get("requires_fresh_complete_audit") is not True
            or not isinstance(target_id, str) or not target_id
            or not isinstance(source_refs, list) or not source_refs
            or any(not isinstance(ref, str) or not ref for ref in source_refs)
            or len(source_refs) != len(set(source_refs))
            or not isinstance(repair_fields, list)
            or any(field not in _CURRENT_MODE_FIELDS for field in repair_fields)
            or len(repair_fields) != len(set(repair_fields))
            or not isinstance(obligation, Mapping) or set(obligation) != _OBLIGATION_FIELDS
            or obligation.get("target_ids") != [target_id]
            or obligation.get("evidence_level") != "operational_decision"
            or not isinstance(obligation.get("id"), str) or not obligation["id"]
            or not isinstance(obligation.get("ref"), str) or obligation["ref"] not in source_refs
            or not _immutable_full_focus_eligible(obligation.get("quote"))
            or not isinstance(obligation.get("dimension"), str) or not obligation["dimension"]
            or not isinstance(transition.get("held_question_format"), str)):
        raise RuleTransitionError("invalid_transition")
    if held_component is not None and (
        not isinstance(held_component, Mapping)
        or set(held_component) != {"ref", "quote"}
        or not isinstance(held_component.get("ref"), str)
        or not isinstance(held_component.get("quote"), str)
    ):
        raise RuleTransitionError("invalid_transition")
    return transition


def rule_transition_operation(transition: Mapping[str, Any]) -> dict[str, Any]:
    """Return request-only JSON metadata; the producer must not echo the tag."""
    transition = _validate_transition(transition)
    obligation = transition["obligation"]
    return {
        "target_id": transition["target_id"],
        "repair_fields": list(transition["repair_fields"]),
        "construction_mode_transition": {
            "policy": transition["policy"],
            "from": "",
            "to": "source_edit_rule",
            "obligation_id": obligation["id"],
            "assessed_focus_source": "immutable_obligation_quote",
            "context_receipt_source": "server_recompute_from_context",
            "inventory_policy": "retain_exact_existing_row",
            "semantic_approval": False,
            "requires_fresh_complete_audit": True,
        },
    }


def compile_rule_transition(
    transition: Mapping[str, Any],
    *,
    partial_target: Mapping[str, Any],
    incoming_obligations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile an exact M3 partial row; this neither parses nor admits it."""
    transition = _validate_transition(transition)
    target_id = transition["target_id"]
    repair_fields = transition["repair_fields"]
    obligation = transition["obligation"]
    held_component = transition["held_component"]
    expected_fields = {"id", *repair_fields}
    if not isinstance(partial_target, Mapping) or set(partial_target) != expected_fields:
        raise RuleTransitionError("target_patch_schema")
    if partial_target.get("id") != target_id:
        raise RuleTransitionError("target_identity")
    if any(field in repair_fields and not isinstance(partial_target[field], list)
           for field in ("governing_bindings", "context")):
        raise RuleTransitionError("target_patch_schema")

    components = (partial_target["answer_components"]
                  if "answer_components" in repair_fields else
                  ([{"ref": held_component["ref"], "terms": [held_component["quote"]]}]
                   if held_component is not None else None))
    if _single_component(components) != (
        obligation["ref"],
        obligation["quote"],
    ):
        raise RuleTransitionError("answer_component")
    question_format = (partial_target["question_format"]
                       if "question_format" in repair_fields else
                       transition["held_question_format"])
    if question_format != "":
        raise RuleTransitionError("question_format")

    if (isinstance(incoming_obligations, str | bytes)
            or not isinstance(incoming_obligations, Sequence)):
        raise RuleTransitionError("inventory_shape")
    seen: set[str] = set()
    for row in incoming_obligations:
        if (not isinstance(row, Mapping) or set(row) != _OBLIGATION_FIELDS
                or not isinstance(row.get("id"), str) or not row["id"]
                or not isinstance(row.get("target_ids"), list)
                or any(not isinstance(owner, str) for owner in row["target_ids"])
                or len(row["target_ids"]) != len(set(row["target_ids"]))):
            raise RuleTransitionError("inventory_shape")
        obligation_id = row["id"]
        if obligation_id in seen:
            raise RuleTransitionError("inventory_duplicate")
        seen.add(obligation_id)
        if obligation_id == obligation["id"] and dict(row) != dict(obligation):
            raise RuleTransitionError("inventory_mutation")
        target_ids = row["target_ids"]
        if obligation_id != obligation["id"] and target_id in target_ids:
            raise RuleTransitionError("inventory_new_link")

    compiled = deepcopy(dict(partial_target))
    compiled["construction_mode"] = "source_edit_rule"
    compiled["assessed_focus"] = obligation["quote"]
    return compiled


__all__ = [
    "MAX_SOURCE_EDIT_RULE_CHARS",
    "RULE_TRANSITION_POLICY",
    "RULE_TRANSITION_PREVIEW_POLICY",
    "RuleTransitionError",
    "compile_rule_transition",
    "derive_rule_transition",
    "inspect_rule_transition_preview",
    "rule_transition_operation",
]
