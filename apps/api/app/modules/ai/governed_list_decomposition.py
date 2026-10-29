"""Lossless structural proof for one flat governed-list decomposition.

This module proves only that a model moved source-owned list layout out of an
ordinary answer component without changing the owned row.  It does not prove
the resulting target's meaning, truth, usefulness, or admissibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.modules.ai.assessment_preservation import starts_with_known_infinitive_clause
from app.modules.ai.source_layout import parse_source_marker

_VALIDATION_ERROR = "source_plan_component_not_single_passage:"
_BOUNDS_VALIDATION_ERROR = (
    "source_plan_bounds:coherent_answer_bundle_exceeds_240:"
    "requires_semantic_split_not_object_fragments"
)
_MODALS = frozenset({
    "обязан", "обязана", "обязано", "обязаны",
    "должен", "должна", "должно", "должны",
})


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    quote: str


@dataclass(frozen=True, slots=True)
class GovernedListDecompositionProof:
    target_id: str
    obligation_id: str
    source_ref: str
    source_id: str
    source_locator: str
    source_sha256: str
    original_component: str
    header_suffix: str
    layout_separator: str
    layout_marker: str
    leaf_body: str
    retained_governing_bindings: tuple[dict[str, Any], ...]
    governor: _Span
    outer_owner: _Span
    leaf: _Span


def _lines(text: str) -> list[tuple[int, int, str, str]]:
    result: list[tuple[int, int, str, str]] = []
    for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", text):
        raw = match.group(0)
        if not raw:
            continue
        content = raw.rstrip("\r\n")
        separator = raw[len(content):]
        result.append((match.start(), match.start() + len(content), content, separator))
    return result


def _one_component(target: dict[str, Any], source_ref: str) -> str | None:
    if target.get("question_format") or target.get("construction_mode"):
        return None
    if target.get("source_refs") != [source_ref]:
        return None
    groups = target.get("answer_components")
    if (not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], dict)
            or groups[0].get("ref") != source_ref):
        return None
    terms = groups[0].get("terms")
    if not isinstance(terms, list) or len(terms) != 1 or not isinstance(terms[0], str):
        return None
    return terms[0]


def _unique_linked_obligation(
    target: dict[str, Any], obligation: dict[str, Any], source_ref: str, component: str,
) -> bool:
    target_id = target.get("id")
    return (
        isinstance(target_id, str)
        and isinstance(obligation.get("id"), str)
        and obligation.get("ref") == source_ref
        and obligation.get("quote") == component
        and obligation.get("target_ids") == [target_id]
        and isinstance(obligation.get("dimension"), str)
        and isinstance(obligation.get("evidence_level"), str)
    )


def _outer_owner(line: str) -> bool:
    if not line.endswith(":"):
        return False
    words = re.findall(r"[А-Яа-яЁё]+", line[:-1])
    return len(words) >= 2 and words[-1].casefold() in _MODALS


def prove_governed_list_decomposition(
    *,
    target: dict[str, Any],
    obligation: dict[str, Any],
    source_ref: str,
    source_id: str,
    source_locator: str,
    source_text: str,
    validation_error: str,
) -> GovernedListDecompositionProof | None:
    """Prove one exact header-plus-leaf component belongs to a flat source list."""
    if (
        not isinstance(validation_error, str)
        or not (
            validation_error.startswith(_VALIDATION_ERROR)
            or validation_error == _BOUNDS_VALIDATION_ERROR
        )
        or not all(isinstance(value, str) and value for value in (
            source_ref, source_id, source_locator, source_text,
        ))
    ):
        return None
    component = _one_component(target, source_ref)
    if component is None or not _unique_linked_obligation(target, obligation, source_ref, component):
        return None
    bindings = target.get("governing_bindings")
    if not isinstance(bindings, list) or any(not isinstance(row, dict) for row in bindings):
        return None
    if any(row.get("ref") != source_ref for row in bindings):
        return None
    contexts = target.get("context", [])
    if (not isinstance(contexts, list) or any(not isinstance(row, dict)
            or row.get("ref") != source_ref for row in contexts)):
        return None
    if any(str(row.get("branch_effect", "")).startswith("changes_") for row in bindings):
        return None

    separator_match = re.search(r"\r\n|\r|\n", component)
    if separator_match is None or re.search(r"\r\n|\r|\n", component[separator_match.end():]):
        return None
    header_suffix = component[:separator_match.start()]
    marked_leaf = component[separator_match.end():]
    if not header_suffix or not marked_leaf or not starts_with_known_infinitive_clause(header_suffix):
        return None
    marker = parse_source_marker(marked_leaf)
    if marker is None or not marker.decoration or marker.raw_start != 0:
        return None
    leaf_body = marked_leaf[marker.content_start:]
    if not leaf_body or leaf_body.endswith(":"):
        return None

    lines = _lines(source_text)
    leaf_indices = [index for index, (_, _, line, _) in enumerate(lines) if line == marked_leaf]
    if len(leaf_indices) != 1:
        return None
    leaf_index = leaf_indices[0]
    first = leaf_index
    while first > 0:
        candidate = parse_source_marker(lines[first - 1][2])
        if candidate is None or not candidate.decoration or candidate.family != marker.family:
            break
        first -= 1
    last = leaf_index
    while last + 1 < len(lines):
        candidate = parse_source_marker(lines[last + 1][2])
        if candidate is None or not candidate.decoration or candidate.family != marker.family:
            break
        last += 1
    if last - first + 1 < 2 or first < 2:
        return None
    for index in range(first, last + 1):
        sibling = parse_source_marker(lines[index][2])
        if (sibling is None or not sibling.decoration or sibling.family != marker.family
                or sibling.raw_marker != marker.raw_marker
                or lines[index][2][sibling.content_start:].endswith(":")):
            return None

    governor_line = lines[first - 1]
    governor_marker = parse_source_marker(governor_line[2])
    governor_body = (governor_line[2][governor_marker.content_start:]
                     if governor_marker is not None else governor_line[2])
    if (not governor_body.endswith(":") or governor_body.count(":") != 1
            or not governor_body.endswith(header_suffix)
            or source_text.count(header_suffix) != 1
            or governor_line[3] != component[separator_match.start():separator_match.end()]
            or lines[leaf_index - 1][3] != component[separator_match.start():separator_match.end()]):
        return None
    outer_line = lines[first - 2]
    if not _outer_owner(outer_line[2]):
        return None

    governor = _Span(governor_line[0], governor_line[1], governor_line[2])
    outer = _Span(outer_line[0], outer_line[1], outer_line[2])
    leaf_line = lines[leaf_index]
    leaf = _Span(leaf_line[0], leaf_line[1], leaf_line[2])
    return GovernedListDecompositionProof(
        target_id=target["id"],
        obligation_id=obligation["id"],
        source_ref=source_ref,
        source_id=source_id,
        source_locator=source_locator,
        source_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        original_component=component,
        header_suffix=header_suffix,
        layout_separator=component[separator_match.start():separator_match.end()],
        layout_marker=marker.raw_marker,
        leaf_body=leaf_body,
        retained_governing_bindings=tuple(json.loads(json.dumps(bindings))),
        governor=governor,
        outer_owner=outer,
        leaf=leaf,
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _same_multiset(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return sorted(map(_canonical, left)) == sorted(map(_canonical, right))


def _span_dict(span: _Span) -> dict[str, Any]:
    return {"start": span.start, "end": span.end, "quote": span.quote}


def validate_governed_list_repair(
    proof: GovernedListDecompositionProof,
    *,
    old_target: dict[str, Any],
    old_obligation: dict[str, Any],
    target: dict[str, Any],
    obligation: dict[str, Any],
) -> dict[str, Any]:
    """Validate the exact field patch and produce a server-owned receipt."""
    error = ValueError("governed_list_decomposition_invalid_repair")
    if target.get("id") != proof.target_id or obligation.get("id") != proof.obligation_id:
        raise error
    if old_target.get("id") != proof.target_id or old_obligation.get("id") != proof.obligation_id:
        raise error
    target_immutable = {key: value for key, value in old_target.items()
                        if key not in {"answer_components", "governing_bindings"}}
    if ({key: value for key, value in target.items()
         if key not in {"answer_components", "governing_bindings"}} != target_immutable):
        raise error
    obligation_immutable = {key: value for key, value in old_obligation.items() if key != "quote"}
    if {key: value for key, value in obligation.items() if key != "quote"} != obligation_immutable:
        raise error
    if target.get("answer_components") != [{"ref": proof.source_ref, "terms": [proof.leaf_body]}]:
        raise error
    if obligation.get("quote") != proof.leaf_body:
        raise error

    current = target.get("governing_bindings")
    if not isinstance(current, list) or any(not isinstance(row, dict) for row in current):
        raise error
    additions = [
        {"ref": proof.source_ref, "quote": proof.governor.quote, "role": "scope", "branch_effect": "none"},
        {"ref": proof.source_ref, "quote": proof.outer_owner.quote, "role": "actor", "branch_effect": "none"},
    ]
    retained = list(proof.retained_governing_bindings)
    if not _same_multiset(current, [*retained, *additions]):
        raise error
    if any(
        isinstance((quote := row.get("quote")), str)
        and (proof.leaf_body in quote or proof.leaf.quote in quote)
        for row in current
    ):
        raise error

    return {
        "version": "governed-list-decomposition-v1",
        "kind": "governed_list_decomposition",
        "semantic_approval": False,
        "target_id": proof.target_id,
        "obligation_id": proof.obligation_id,
        "source_ref": proof.source_ref,
        "source_id": proof.source_id,
        "source_locator": proof.source_locator,
        "source_sha256": proof.source_sha256,
        "original_component": proof.original_component,
        "header_suffix": proof.header_suffix,
        "layout_separator": proof.layout_separator,
        "layout_marker": proof.layout_marker,
        "leaf_body": proof.leaf_body,
        "retained_governing_bindings": retained,
        "governor": _span_dict(proof.governor),
        "outer_owner": _span_dict(proof.outer_owner),
        "leaf": {**_span_dict(proof.leaf), "body": proof.leaf_body},
    }


def validate_governed_list_receipt(
    receipt: dict[str, Any],
    *,
    target: dict[str, Any],
    obligation: dict[str, Any],
    source_ref: str,
    source_id: str,
    source_locator: str,
    source_text: str,
) -> dict[str, Any]:
    """Recompute a stored receipt against immutable source and canonical rows."""
    error = ValueError("governed_list_decomposition_receipt_invalid")
    if not isinstance(receipt, dict) or receipt.get("semantic_approval") is not False:
        raise error
    retained = receipt.get("retained_governing_bindings")
    if not isinstance(retained, list) or any(not isinstance(row, dict) for row in retained):
        raise error
    old_target = {**target,
        "answer_components": [{"ref": source_ref, "terms": [receipt.get("original_component")]}],
        "governing_bindings": retained}
    old_obligation = {**obligation, "quote": receipt.get("original_component")}
    proof = prove_governed_list_decomposition(
        target=old_target,
        obligation=old_obligation,
        source_ref=source_ref,
        source_id=source_id,
        source_locator=source_locator,
        source_text=source_text,
        validation_error=_VALIDATION_ERROR + "stored_receipt",
    )
    if proof is None:
        raise error
    expected = validate_governed_list_repair(
        proof,
        old_target=old_target,
        old_obligation=old_obligation,
        target=target,
        obligation=obligation,
    )
    if receipt != expected:
        raise error
    return receipt
