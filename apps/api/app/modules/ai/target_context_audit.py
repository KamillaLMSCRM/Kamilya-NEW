"""Negative-only target context audit contract.

Uses the existing six application-context axes without application-graph witness
or cohort semantics. This code never infers missing context, source meaning,
answers, bindings, coverage, causality, or positive admission.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

CONTEXT_AXES = ("participants", "temporal_setting", "condition", "exception", "prerequisite", "antecedent")
CONTEXT_STATUSES = frozenset({"not_required", "covered", "missing", "ambiguous"})
NEGATIVE_STATUSES = frozenset({"missing", "ambiguous"})


class TargetContextAuditError(ValueError):
    """Malformed context transport is not a source or semantic judgment."""


def target_context_negatives(verdict: Any, target_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Require exactly every target and every axis; return only negative axes."""
    if not isinstance(verdict, dict):
        raise TargetContextAuditError("source_plan_invalid_audit")
    if "target_context_verdicts" not in verdict:
        raise TargetContextAuditError("source_plan_missing_target_context_verdicts")
    rows = verdict["target_context_verdicts"]
    if not isinstance(rows, list) or len(rows) != len(target_ids):
        raise TargetContextAuditError("source_plan_invalid_target_context_inventory")
    known = set(target_ids)
    if len(known) != len(target_ids):
        raise TargetContextAuditError("source_plan_invalid_target_context_inventory")
    negatives: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) not in ({"target_id", "axes"}, {"target_id", "axes", "candidates"}):
            raise TargetContextAuditError("source_plan_invalid_target_context_verdict")
        tid = row["target_id"]
        if not isinstance(tid, str) or tid not in known or tid in seen:
            raise TargetContextAuditError("source_plan_invalid_target_context_inventory")
        seen.add(tid)
        axes = row["axes"]
        if (not isinstance(axes, dict) or set(axes) != set(CONTEXT_AXES)
                or any(not isinstance(status, str) or status not in CONTEXT_STATUSES
                       for status in axes.values())):
            raise TargetContextAuditError("source_plan_invalid_target_context_axes")
        failures = tuple(axis for axis in CONTEXT_AXES if axes[axis] in NEGATIVE_STATUSES)
        if failures:
            negatives[tid] = failures
    if seen != known:
        raise TargetContextAuditError("source_plan_invalid_target_context_inventory")
    return negatives


def withhold_incomplete_target_context(verdict: Any, target_ids: tuple[str, ...]) -> dict[str, Any]:
    """Monotonically veto named targets; preserve raw context rows in audit digest."""
    negatives = target_context_negatives(verdict, target_ids)
    votes = verdict.get("target_verdicts")
    if not isinstance(votes, list):
        raise TargetContextAuditError("source_plan_invalid_target_verdicts")
    by_id: dict[str, dict[str, Any]] = {}
    for vote in votes:
        tid = vote.get("target_id") if isinstance(vote, dict) else None
        if not isinstance(tid, str) or tid not in target_ids or tid in by_id:
            raise TargetContextAuditError("source_plan_invalid_target_verdicts")
        if (type(vote.get("admit")) is not bool or not isinstance(vote.get("errors"), list)
                or any(not isinstance(error,str) or not error.strip() for error in vote["errors"])
                or vote["admit"] != (not vote["errors"])):
            raise TargetContextAuditError("source_plan_invalid_target_verdicts")
        fields = vote.get("repair_fields")
        if (not isinstance(fields,list) or any(not isinstance(field,str) for field in fields)
                or len(set(fields)) != len(fields)
                or (vote["admit"] and fields) or (not vote["admit"] and not fields)):
            raise TargetContextAuditError("source_plan_invalid_target_repair_fields")
        by_id[tid] = vote
    if set(by_id) != set(target_ids):
        raise TargetContextAuditError("source_plan_missing_target_verdict")
    canonical: dict[str, Any] = deepcopy(verdict)
    for vote in canonical["target_verdicts"]:
        tid = vote["target_id"]
        if tid not in negatives:
            continue
        vote["admit"] = False
        error = "context_incomplete:" + ",".join(negatives[tid])
        if error not in vote["errors"]:
            vote["errors"].append(error)
        if "governing_bindings" not in vote["repair_fields"]:
            vote["repair_fields"].append("governing_bindings")
    return canonical


def withhold_isolated_target_context(
    verdict: Any,
    target_ids: tuple[str, ...],
    partition_errors: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    """Withhold malformed partition owners while preserving valid peer audits.

    Row/axis and target-vote inventories remain strict through the existing
    validator.  Partition errors are server-owned negatives, not synthesized
    axes, candidate classifications, bindings, or positive votes.
    """
    if (
        not isinstance(partition_errors, Mapping)
        or any(
            not isinstance(target_id, str)
            or target_id not in target_ids
            or not isinstance(errors, tuple)
            or not errors
            or any(not isinstance(error, str) or not error for error in errors)
            or len(set(errors)) != len(errors)
            for target_id, errors in partition_errors.items()
        )
    ):
        raise TargetContextAuditError("source_plan_invalid_target_context_partition_errors")
    negatives = target_context_negatives(verdict, target_ids)
    for target_id in partition_errors:
        negatives.pop(target_id, None)  # Invalid rows never supply semantic axes.
    canonical = withhold_incomplete_target_context(verdict, target_ids)
    votes = {row["target_id"]: row for row in canonical["target_verdicts"]}
    for target_id, errors in partition_errors.items():
        vote = votes[target_id]
        # Remove only a context negative derived from the invalid row itself;
        # preserve every original/model/native refusal and repair field.
        row = next(item for item in verdict["target_verdicts"] if item["target_id"] == target_id)
        vote.clear()
        vote.update(deepcopy(row))
        vote["admit"] = False
        error = "context_partition_invalid:" + ",".join(errors)
        if error not in vote["errors"]:
            vote["errors"].append(error)
        # A malformed critic enumeration proves no defect in the source-plan
        # target. Preserve substantive model repair fields, but never mint new
        # authoring authority from this server-owned format veto.
    return canonical


def additive_binding_targets(verdict: Any, target_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Missing context allows additions, never silently drops existing bindings."""
    target_context_negatives(verdict, target_ids)
    rows = {row["target_id"]: row for row in verdict["target_context_verdicts"]}
    binding_gaps = {row["target_id"] for row in verdict.get("target_verdicts", [])
                    if isinstance(row, dict) and row.get("admit") is False
                    and "governing_bindings" in row.get("repair_fields", [])
                    and any(isinstance(error, str) and error.startswith("context_binding_missing:")
                            for error in row.get("errors", []))}
    return tuple(tid for tid in target_ids if ("missing" in rows[tid]["axes"].values() or tid in binding_gaps)
                 and "ambiguous" not in rows[tid]["axes"].values())


def withhold_missing_context_bindings(
    verdict: Any, target_ids: tuple[str, ...], binding_gaps: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    """Withhold exact applied-but-unbound scope without inventing semantic axes.

    Gaps must be rederived from the current server candidate inventory, never
    accepted from a provider or used as positive evidence.
    """
    if (not isinstance(binding_gaps, tuple) or len(set(binding_gaps)) != len(binding_gaps)
            or any(not isinstance(gap, tuple) or len(gap) != 2
                   or gap[0] not in target_ids or not isinstance(gap[1], str) or not gap[1]
                   for gap in binding_gaps)):
        raise TargetContextAuditError("source_plan_invalid_context_binding_gaps")
    canonical = withhold_incomplete_target_context(verdict, target_ids)
    votes = {row["target_id"]: row for row in canonical["target_verdicts"]}
    for target_id, facet_id in binding_gaps:
        vote = votes[target_id]
        vote["admit"] = False
        error = "context_binding_missing:" + facet_id
        if error not in vote["errors"]:
            vote["errors"].append(error)
        if "governing_bindings" not in vote["repair_fields"]:
            vote["repair_fields"].append("governing_bindings")
    return canonical


def ambiguous_context_targets(verdict: Any, target_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Ambiguity withholds; it never independently authorizes a binding repair."""
    target_context_negatives(verdict, target_ids)
    rows = {row["target_id"]: row for row in verdict["target_context_verdicts"]}
    return tuple(tid for tid in target_ids if "ambiguous" in rows[tid]["axes"].values())


def validate_additive_binding_repair(
    proposed: dict[str, Any], held: dict[str, Any], additive_targets: tuple[str, ...],
) -> None:
    """Adjunct AFTER native partial-row owner/field scope validation, not a parser.

    The caller must already reject foreign/duplicate targets, missing authorized
    fields and unauthorized non-binding edits. Native exact-source binding parse,
    complete inventory checks and fresh audit remain mandatory afterwards.
    """
    original = {row["id"]: row for row in held["targets"]}
    for row in proposed["targets"]:
        if row["id"] not in additive_targets or "governing_bindings" not in row:
            continue
        bindings = row["governing_bindings"]
        old = original[row["id"]].get("governing_bindings", [])
        if not isinstance(bindings, list) or any(binding not in bindings for binding in old):
            raise TargetContextAuditError("source_plan_context_repair_dropped_existing_binding")
