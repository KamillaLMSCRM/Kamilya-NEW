"""Structural validation for source-owned assessment component realizations.

This module validates explicit ownership and exact source/candidate spans. It
does not infer morphology, semantic equivalence, answer keys, or correctness.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_TARGETS = 96
MAX_COMPONENTS_PER_TARGET = 12
MAX_REQUIREMENTS = MAX_TARGETS * MAX_COMPONENTS_PER_TARGET
MAX_ALTERNATIVES = 8
MAX_ROWS = MAX_REQUIREMENTS
MAX_REALIZATIONS = 4
MAX_ID_CHARS = 192
MAX_SOURCE_ID_CHARS = 192
MAX_SOURCE_REF_CHARS = 32
MAX_COMPONENT_TEXT_CHARS = 512
MAX_CANDIDATE_SPAN_CHARS = 2000
MAX_CANDIDATE_TEXT_CHARS = 65536
MAX_SOURCE_PASSAGES = 4096
MAX_SOURCE_PASSAGE_CHARS = 65536

_SOURCE_REF = re.compile(r"^S[1-9]\d*P[1-9]\d*$")
_PART_ROLES = {"stem": "fixed_context", "answer": "discriminating_answer"}


@dataclass(frozen=True)
class OwnedComponent:
    source_id: str
    text: str


@dataclass(frozen=True)
class ComponentRequirement:
    target_id: str
    component_id: str
    alternatives: tuple[OwnedComponent, ...]
    full_set: bool = False


@dataclass(frozen=True)
class ValidatedComponentBinding:
    """Reviewer/examiner agreement signature; candidate quotes stay private."""

    target_id: str
    component_id: str
    source_id: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class ComponentValidationResult:
    valid_target_ids: tuple[str, ...]
    failures: tuple[dict[str, Any], ...]
    component_bindings: tuple[ValidatedComponentBinding, ...] = ()


def _failure(code: str, **locator: Any) -> dict[str, Any]:
    return {"code": code, **{key: value for key, value in locator.items() if value is not None}}


def _bounded_identifier(value: Any, maximum: int = MAX_ID_CHARS) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value[0].isalnum()
        and all(character.isalnum() or character in ":._-" for character in value)
    )


def _safe_identifier(value: Any, maximum: int = MAX_ID_CHARS) -> str | None:
    return value if _bounded_identifier(value, maximum) else None


def _validate_requirements(
    requirements: Sequence[ComponentRequirement],
) -> tuple[dict[str, ComponentRequirement], tuple[str, ...], tuple[dict[str, Any], ...]]:
    if (
        isinstance(requirements, str | bytes)
        or not isinstance(requirements, Sequence)
        or not 1 <= len(requirements) <= MAX_REQUIREMENTS
    ):
        return {}, (), (_failure("invalid_requirements_bounds"),)

    indexed: dict[str, ComponentRequirement] = {}
    targets: list[str] = []
    target_components: dict[str, list[int]] = defaultdict(list)
    target_full_set: dict[str, bool] = {}
    failures: list[dict[str, Any]] = []

    for requirement_index, requirement in enumerate(requirements):
        if not isinstance(requirement, ComponentRequirement):
            failures.append(_failure("invalid_requirement_shape", requirement_index=requirement_index))
            continue
        target_id = requirement.target_id
        component_id = requirement.component_id
        locator = {"target_id": target_id, "component_id": component_id}
        if not _bounded_identifier(target_id):
            failures.append(_failure(
                "invalid_target_id",
                component_id=_safe_identifier(component_id),
            ))
            continue
        expected_prefix = f"{target_id}:C"
        component_suffix = component_id[len(expected_prefix):] if isinstance(component_id, str) else ""
        if (
            not _bounded_identifier(component_id)
            or not component_id.startswith(expected_prefix)
            or not component_suffix.isascii()
            or not component_suffix.isdigit()
            or int(component_suffix) < 1
        ):
            failures.append(_failure(
                "invalid_component_id",
                target_id=_safe_identifier(target_id),
                component_id=_safe_identifier(component_id),
            ))
            continue
        if component_id in indexed:
            failures.append(_failure("duplicate_component_requirement", **locator))
            continue
        if not isinstance(requirement.full_set, bool):
            failures.append(_failure("invalid_requirement_full_set", **locator))
            continue
        alternatives = requirement.alternatives
        if not isinstance(alternatives, tuple) or not 1 <= len(alternatives) <= MAX_ALTERNATIVES:
            failures.append(_failure("invalid_requirement_alternatives", **locator))
            continue
        seen_alternatives: set[tuple[str, str]] = set()
        alternative_error = False
        for alternative in alternatives:
            if not isinstance(alternative, OwnedComponent):
                failures.append(_failure("invalid_requirement_alternative_shape", **locator))
                alternative_error = True
                break
            if not _bounded_identifier(alternative.source_id, MAX_SOURCE_ID_CHARS):
                failures.append(_failure("invalid_requirement_source_id", **locator))
                alternative_error = True
                break
            if (
                not isinstance(alternative.text, str)
                or not alternative.text.strip()
                or alternative.text != alternative.text.strip()
                or len(alternative.text) > MAX_COMPONENT_TEXT_CHARS
            ):
                failures.append(_failure("invalid_requirement_text", **locator))
                alternative_error = True
                break
            signature = (alternative.source_id, alternative.text)
            if signature in seen_alternatives:
                failures.append(_failure("duplicate_requirement_alternative", **locator))
                alternative_error = True
                break
            seen_alternatives.add(signature)
        if alternative_error:
            continue

        if target_id not in target_full_set:
            targets.append(target_id)
            target_full_set[target_id] = requirement.full_set
        elif target_full_set[target_id] != requirement.full_set:
            failures.append(_failure("inconsistent_target_full_set", **locator))
            continue
        component_number = int(component_suffix)
        target_components[target_id].append(component_number)
        indexed[component_id] = requirement

    if len(targets) > MAX_TARGETS:
        failures.append(_failure("too_many_component_targets"))
    for target_id, numbers in target_components.items():
        if len(numbers) > MAX_COMPONENTS_PER_TARGET:
            failures.append(_failure("too_many_target_components", target_id=target_id))
        elif sorted(numbers) != list(range(1, len(numbers) + 1)):
            failures.append(_failure("noncontiguous_component_ids", target_id=target_id))
    if failures:
        return {}, (), tuple(failures)
    return indexed, tuple(targets), ()


def _validate_outer_inputs(
    rows: Sequence[Mapping[str, Any]],
    stem: str,
    answer: str,
    source_passages: Mapping[str, tuple[str, str]],
    key_source_ids: set[str],
) -> tuple[dict[str, Any], ...]:
    failures: list[dict[str, Any]] = []
    if isinstance(rows, str | bytes) or not isinstance(rows, Sequence) or len(rows) > MAX_ROWS:
        failures.append(_failure("invalid_realization_rows_bounds"))
    if not isinstance(stem, str) or not isinstance(answer, str):
        failures.append(_failure("invalid_candidate_text_shape"))
    elif len(stem) > MAX_CANDIDATE_TEXT_CHARS or len(answer) > MAX_CANDIDATE_TEXT_CHARS:
        failures.append(_failure("invalid_candidate_text_bounds"))
    if not isinstance(source_passages, Mapping) or len(source_passages) > MAX_SOURCE_PASSAGES:
        failures.append(_failure("invalid_source_passages_bounds"))
    if not isinstance(key_source_ids, set) or len(key_source_ids) > MAX_SOURCE_PASSAGES or any(
        not _bounded_identifier(source_id, MAX_SOURCE_ID_CHARS) for source_id in key_source_ids
    ):
        failures.append(_failure("invalid_key_source_ids"))
    return tuple(failures)


def validate_component_realizations(
    requirements: Sequence[ComponentRequirement],
    rows: Sequence[Mapping[str, Any]],
    *,
    stem: str,
    answer: str,
    source_passages: Mapping[str, tuple[str, str]],
    key_source_ids: set[str],
) -> ComponentValidationResult:
    """Validate structural component maps without treating them as semantic proof."""
    indexed, target_order, requirement_failures = _validate_requirements(requirements)
    if requirement_failures:
        return ComponentValidationResult((), requirement_failures)
    outer_failures = _validate_outer_inputs(rows, stem, answer, source_passages, key_source_ids)
    if outer_failures:
        return ComponentValidationResult((), outer_failures)

    target_requirements: dict[str, list[ComponentRequirement]] = defaultdict(list)
    for target_requirement in requirements:
        target_requirements[target_requirement.target_id].append(target_requirement)

    failures: list[dict[str, Any]] = []
    invalid_targets: set[str] = set()
    mapped_components: set[str] = set()
    bindings: dict[str, ValidatedComponentBinding] = {}
    fatal = False

    for row_index, realization_row in enumerate(rows):
        if not isinstance(realization_row, Mapping) or set(realization_row) != {
            "target_id", "component_id", "source_ref", "realizations"
        }:
            failures.append(_failure("invalid_component_mapping_shape", row_index=row_index))
            fatal = True
            continue
        target_id = realization_row["target_id"]
        component_id = realization_row["component_id"]
        source_ref = realization_row["source_ref"]
        row_locator = {
            "row_index": row_index,
            "target_id": _safe_identifier(target_id),
            "component_id": _safe_identifier(component_id),
            "source_ref": source_ref
            if isinstance(source_ref, str) and len(source_ref) <= MAX_SOURCE_REF_CHARS
            else None,
        }
        if not _bounded_identifier(target_id) or not _bounded_identifier(component_id):
            failures.append(_failure("invalid_component_mapping_ids", **row_locator))
            fatal = True
            continue
        requirement = indexed.get(component_id)
        if requirement is None:
            failures.append(_failure("unknown_component_id", **row_locator))
            fatal = True
            continue
        if target_id != requirement.target_id:
            failures.append(_failure("component_target_mismatch", **row_locator))
            invalid_targets.add(requirement.target_id)
            continue
        if component_id in mapped_components:
            failures.append(_failure("duplicate_component_mapping", **row_locator))
            invalid_targets.add(target_id)
            continue
        mapped_components.add(component_id)
        if not isinstance(source_ref, str) or not _SOURCE_REF.fullmatch(source_ref):
            failures.append(_failure("invalid_source_ref", **row_locator))
            invalid_targets.add(target_id)
            continue
        passage = source_passages.get(source_ref)
        if passage is None:
            failures.append(_failure("unknown_source_ref", **row_locator))
            invalid_targets.add(target_id)
            continue
        if (
            not isinstance(passage, tuple)
            or len(passage) != 2
            or not _bounded_identifier(passage[0], MAX_SOURCE_ID_CHARS)
            or not isinstance(passage[1], str)
            or len(passage[1]) > MAX_SOURCE_PASSAGE_CHARS
        ):
            failures.append(_failure("invalid_source_passage", **row_locator))
            invalid_targets.add(target_id)
            continue
        source_id, source_text = passage
        owner_alternatives = [
            alternative for alternative in requirement.alternatives
            if alternative.source_id == source_id
        ]
        if not owner_alternatives:
            failures.append(_failure("component_source_owner_mismatch", **row_locator))
            invalid_targets.add(target_id)
            continue
        if source_id not in key_source_ids:
            failures.append(_failure("unsupported_key_source", **row_locator))
            invalid_targets.add(target_id)
            continue
        if not any(alternative.text in source_text for alternative in owner_alternatives):
            failures.append(_failure("component_not_literal_in_source", **row_locator))
            invalid_targets.add(target_id)
            continue

        component_realizations = realization_row["realizations"]
        if (
            not isinstance(component_realizations, list)
            or not 1 <= len(component_realizations) <= MAX_REALIZATIONS
        ):
            failures.append(_failure("invalid_component_realizations_bounds", **row_locator))
            invalid_targets.add(target_id)
            continue
        roles: set[str] = set()
        realization_signatures: set[tuple[str, str, str]] = set()
        row_valid = True
        for realization_index, realization in enumerate(component_realizations):
            realization_locator = {**row_locator, "realization_index": realization_index}
            if not isinstance(realization, Mapping) or set(realization) != {"part", "role", "quote"}:
                failures.append(_failure("invalid_realization_shape", **realization_locator))
                row_valid = False
                continue
            part, role, quote = (realization[key] for key in ("part", "role", "quote"))
            if not isinstance(part, str) or part not in _PART_ROLES:
                failures.append(_failure("invalid_realization_part", **realization_locator))
                row_valid = False
                continue
            if not isinstance(role, str) or role not in _PART_ROLES.values():
                failures.append(_failure("invalid_realization_role", **realization_locator))
                row_valid = False
                continue
            if _PART_ROLES[part] != role:
                failures.append(_failure("realization_role_part_mismatch", **realization_locator))
                row_valid = False
                continue
            if (
                not isinstance(quote, str)
                or not quote.strip()
                or quote != quote.strip()
                or len(quote) > MAX_CANDIDATE_SPAN_CHARS
            ):
                failures.append(_failure("invalid_realization_quote", **realization_locator))
                row_valid = False
                continue
            candidate_text = stem if part == "stem" else answer
            if quote not in candidate_text:
                failures.append(_failure("candidate_span_not_literal", **realization_locator))
                row_valid = False
                continue
            signature = (part, role, quote)
            if signature in realization_signatures:
                failures.append(_failure("duplicate_component_realization", **realization_locator))
                row_valid = False
                continue
            realization_signatures.add(signature)
            roles.add(role)
        if not row_valid:
            invalid_targets.add(target_id)
            continue
        bindings[component_id] = ValidatedComponentBinding(
            target_id, component_id, source_id, tuple(sorted(roles))
        )

    for target_id in target_order:
        target_bindings: list[ValidatedComponentBinding] = []
        for requirement in target_requirements[target_id]:
            binding = bindings.get(requirement.component_id)
            if binding is None:
                failures.append(_failure(
                    "missing_component_mapping",
                    target_id=target_id,
                    component_id=requirement.component_id,
                ))
                invalid_targets.add(target_id)
            else:
                target_bindings.append(binding)
        if target_id in invalid_targets:
            continue
        if target_requirements[target_id][0].full_set:
            for binding in target_bindings:
                if "discriminating_answer" not in binding.roles:
                    failures.append(_failure(
                        "full_set_component_not_discriminating",
                        target_id=target_id,
                        component_id=binding.component_id,
                    ))
                    invalid_targets.add(target_id)
        elif not any("discriminating_answer" in binding.roles for binding in target_bindings):
            failures.append(_failure(
                "ordinary_target_missing_discriminating_answer", target_id=target_id
            ))
            invalid_targets.add(target_id)

    valid_target_ids = () if fatal else tuple(
        target_id for target_id in target_order if target_id not in invalid_targets
    )
    valid_bindings = tuple(
        bindings[requirement.component_id]
        for requirement in requirements
        if requirement.target_id in valid_target_ids and requirement.component_id in bindings
    )
    return ComponentValidationResult(valid_target_ids, tuple(failures), valid_bindings)


def compare_component_validation_results(
    reviewer: ComponentValidationResult,
    examiner: ComponentValidationResult,
) -> ComponentValidationResult:
    """Require owner and answer-discrimination agreement on independently valid maps.

    Redundant fixed-context spans need not be identical when both maps already
    preserve the complete owned proposition. Stem-only versus answer-bearing
    components still disagree. Returned bindings use the symmetric intersection.
    """
    if not isinstance(reviewer, ComponentValidationResult) or not isinstance(
        examiner, ComponentValidationResult
    ):
        return ComponentValidationResult((), (_failure("invalid_component_validation_result"),))

    reviewer_targets = set(reviewer.valid_target_ids)
    examiner_targets = set(examiner.valid_target_ids)
    target_order = tuple(dict.fromkeys((*reviewer.valid_target_ids, *examiner.valid_target_ids)))
    failures: list[dict[str, Any]] = []
    valid_targets: list[str] = []
    agreed_bindings: list[ValidatedComponentBinding] = []

    for target_id in target_order:
        if target_id not in reviewer_targets or target_id not in examiner_targets:
            failures.append(_failure("reviewer_examiner_target_disagreement", target_id=target_id))
            continue
        reviewer_map = {
            binding.component_id: binding
            for binding in reviewer.component_bindings
            if binding.target_id == target_id
        }
        examiner_map = {
            binding.component_id: binding
            for binding in examiner.component_bindings
            if binding.target_id == target_id
        }
        target_failed = False
        for component_id in sorted(set(reviewer_map) | set(examiner_map)):
            reviewer_binding = reviewer_map.get(component_id)
            examiner_binding = examiner_map.get(component_id)
            if (
                reviewer_binding is None
                or examiner_binding is None
                or reviewer_binding.source_id != examiner_binding.source_id
                or ("discriminating_answer" in reviewer_binding.roles)
                != ("discriminating_answer" in examiner_binding.roles)
            ):
                failures.append(_failure(
                    "reviewer_examiner_component_disagreement",
                    target_id=target_id,
                    component_id=component_id,
                ))
                target_failed = True
        if not reviewer_map and not examiner_map:
            failures.append(_failure("reviewer_examiner_empty_component_map", target_id=target_id))
            target_failed = True
        if not target_failed:
            valid_targets.append(target_id)
            agreed_bindings.extend(
                ValidatedComponentBinding(target_id, component_id, binding.source_id,
                    tuple(sorted(set(binding.roles) & set(examiner_map[component_id].roles))))
                for component_id, binding in reviewer_map.items()
            )

    return ComponentValidationResult(tuple(valid_targets), tuple(failures), tuple(agreed_bindings))
