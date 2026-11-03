"""Exact ORIGINAL-domain display candidates; never a semantic witness vote."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from typing import Any, NoReturn, cast

from app.modules.ai.source_assessment_graph import _hash
from app.modules.ai.source_assessment_plan import SourcePlanError, _case_context_metadata, _parse
from app.modules.ai.source_case_projection import CaseProjectionSource, bind_case_context
from app.modules.ai.source_frame_applications import CompiledApplicationGraph, application_partition_custody

POLICY = "application-display-witness-v1"
_MAX_ROWS = 4096


def _fail(code: str) -> NoReturn:
    raise SourcePlanError("source_applications_display_" + code)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unique(rows: Any, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        _fail("resources")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get(field), str)
                or not row[field] or len(row[field]) > 256 or row[field] in result):
            _fail("integrity")
        result[row[field]] = row
    return result


def _checked_view(receipt: dict[str, Any]) -> dict[str, Any]:
    if (not isinstance(receipt, dict) or receipt.get("view_sha256") != _hash(
            {key: value for key, value in receipt.items() if key != "view_sha256"})):
        _fail("integrity")
    view = receipt["view"]
    sources = _unique(view["sources"], "ref")
    targets = _unique(view["targets"], "id")
    _unique(view["relations"], "id")
    _unique(view["evidence_spans"], "id")
    if set(receipt["target_map"]) != set(targets) or len(set(receipt["target_map"].values())) != len(targets):
        _fail("integrity")
    units = _unique(view["original_units"], "unit_id")
    for source in sources.values():
        if (type(source.get("primary")) is not bool or not isinstance(source.get("source_id"), str)
                or not source["source_id"] or not isinstance(source.get("text"), str)
                or not source["text"] or len(source["text"]) > 65536):
            _fail("integrity")
    for unit in units.values():
        unit_source = sources.get(unit["ref"])
        if (unit_source is None or unit_source["primary"] is not True or unit["source_id"] != unit_source["source_id"]
                or unit["source_sha256"] != _sha(unit_source["text"])):
            _fail("integrity")
    for target in targets.values():
        owners = target["owner_handles"]
        if (not isinstance(owners, list) or not owners or any(not isinstance(owner, str) for owner in owners)
                or owners != sorted(set(owners)) or receipt["owner_routes"][target["id"]]["owner_handles"] != owners
                or not isinstance(target["source_refs"], list) or not target["source_refs"]
                or any(ref not in sources or sources[ref]["primary"] is not True for ref in target["source_refs"])
                or not isinstance(target["context"], list) or len(target["context"]) > 16
                or not isinstance(target["unit_ids"], list)
                or any(unit not in units for unit in target["unit_ids"])):
            _fail("integrity")
    return cast(dict[str, Any], view)


def _span(row: dict[str, Any], source: dict[str, Any]) -> tuple[int, int, str]:
    start, end = row["start"], row["end"]
    text = source["text"]
    if (row["ref"] != source["ref"] or row["source_id"] != source["source_id"]
            or row["source_sha256"] != _sha(text) or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(text)):
        _fail("context_custody")
    quote = text[start:end]
    if row.get("whole_source") is True:
        if start != 0 or end != len(text) or ("quote" in row and row["quote"] != text):
            _fail("context_custody")
    elif row.get("quote") != quote:
        _fail("context_custody")
    return start, end, quote


def _applied_fork(receipt: dict[str, Any], target: dict[str, Any], source: dict[str, Any]) -> str | None:
    view = receipt["view"]
    evidence = {row["id"]: row for row in view["evidence_spans"]}
    canonical = receipt["target_map"][target["id"]]
    applied = {row["relation_id"] for row in target["assembled_assessment_projection"]["available_native_supports"]
               if row.get("credit") == "context_only"}
    candidates: set[str] = set()
    for relation in view["relations"]:
        rid = relation["id"]
        if (relation["kind"] != "timing_partition" or relation["role"] != "timing"
                or relation["effect"] != "changes_timing" or rid not in target["relation_ids"] or rid not in applied
                or rid not in target["native_relation_ids_by_axis"]["temporal_setting"]
                or target["id"] not in relation["target_ids"]
                or sorted(relation["owner_handles"]) != target["owner_handles"]
                or not any(row["target_id"] == canonical and rid in row["claim_ids"] for row in receipt["memberships"])):
            continue
        pairs = [row for row in relation["branch_pairs"] if row["target_id"] == target["id"]]
        if len(pairs) != 1 or pairs[0]["answer_evidence_id"] not in target["own_answer_evidence_ids"]:
            continue
        fork = evidence[relation["evidence_id"]]
        if fork["ref"] != source["ref"]:
            continue
        start, end, quote = _span(fork, source)
        selector = _span(evidence[pairs[0]["selector_evidence_id"]], source)
        answer = _span(evidence[pairs[0]["answer_evidence_id"]], source)
        if (not start <= selector[0] < selector[1] <= end or not start <= answer[0] < answer[1] <= end
                or not (selector[1] <= answer[0] or answer[1] <= selector[0])):
            _fail("context_custody")
        candidates.add(quote)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _inventory(receipt: dict[str, Any], view: dict[str, Any]) -> list[dict[str, Any]]:
    sources = {row["ref"]: row for row in view["sources"]}
    units = {row["unit_id"]: row for row in view["original_units"]}
    result: list[dict[str, Any]] = []
    for target in view["targets"]:
        seen: set[tuple[str, int, int]] = set()
        for context in target["context"]:
            if (not isinstance(context, dict) or set(context) != {"ref", "text"}
                    or not isinstance(context["ref"], str) or context["ref"] not in target["source_refs"]
                    or not isinstance(context["text"], str) or not context["text"]
                    or not any(units[unit]["ref"] == context["ref"] for unit in target["unit_ids"])):
                _fail("context_custody")
            source, quote = sources[context["ref"]], context["text"]
            if quote not in source["text"]:
                if quote in {row["text"] for row in _case_context_metadata(source)}:
                    continue
                _fail("context_custody")
            original = CaseProjectionSource(source["source_id"], source["text"], source["text"])
            try:
                bound = bind_case_context(original, quote)
            except ValueError:
                fork = _applied_fork(receipt, target, source)
                if fork is None:
                    _fail("context_custody")
                try:
                    bound = bind_case_context(original, quote, within_quote=fork)
                except ValueError as exc:
                    raise SourcePlanError("source_applications_display_context_custody") from exc
            key = (source["ref"], bound.start, bound.end)
            if key in seen:
                _fail("context_custody")
            seen.add(key)
            if len(result) >= _MAX_ROWS:
                _fail("resources")
            result.append({"id": f"C{len(result) + 1}", "target_id": target["id"], "ref": source["ref"],
                "source_id": source["source_id"], "source_sha256": bound.original_sha256,
                "start": bound.start, "end": bound.end, "quote_sha256": bound.quote_sha256,
                "text": quote, "credit": "context_only", "semantic_approval": False})
    return result


def build_display_inventory(receipt: dict[str, Any], graph: CompiledApplicationGraph) -> list[dict[str, Any]]:
    """Project only canonical displayed original text from a validated graph."""
    try:
        view = _checked_view(receipt)
        application_partition_custody(graph)
        refs = dict(graph.source_facts)
        if (receipt["application_receipt_sha256"] != graph.receipt_sha256
                or receipt["application_wire_sha256"] != graph.wire_sha256
                or receipt["source_fact_sha256"] != graph.source_sha256
                or _hash({ref: asdict(fact) for ref, fact in refs.items()}) != graph.source_sha256
                or {row["ref"] for row in view["sources"]} != set(refs)
                or {row["ref"] for row in view["sources"] if row["primary"]} != {unit.ref for unit in graph.compiled.units}):
            _fail("integrity")
        for source in view["sources"]:
            fact = refs[source["ref"]]
            if any(source[key] != value for key, value in (
                    ("source_id", fact.fact_id), ("text", fact.value), ("subject", fact.subject), ("attribute", fact.attribute))):
                _fail("integrity")
        # Re-derive the same native canonical plan as the caller from the
        # source-bound graph. The parser may normalize case to the exact source
        # quote; comparing against the pre-normalized compiler wire incorrectly
        # rejects valid custody. Never trust the supplied view as normalization.
        _, _, canonical_plan = _parse(
            json.dumps(graph.compiled.plan, ensure_ascii=False), refs,
            {unit.ref for unit in graph.compiled.units}, partition_targets=False,
            _application_partition_custody=application_partition_custody(graph),
        )
        rows = {row["id"]: row for row in canonical_plan["targets"]}
        if set(receipt["target_map"].values()) != set(rows):
            _fail("integrity")
        for target in view["targets"]:
            canonical = receipt["target_map"][target["id"]]
            owners = sorted(owner for owner, ids in graph.compiled.frame_targets.items() if canonical in ids)
            if (target["owner_handles"] != owners or target["context"] != rows[canonical]["context"]
                    or target["source_refs"] != rows[canonical]["source_refs"]):
                _fail("integrity")
        return _inventory(receipt, view)
    except SourcePlanError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SourcePlanError("source_applications_display_integrity") from exc


def validate_display_selection(receipt: dict[str, Any], target_id: str, ids: Any) -> list[dict[str, Any]]:
    """Recompute every stored proof; selected display does not approve meaning."""
    try:
        view = _checked_view(receipt)
        if (view.get("display_context_policy") != POLICY or not isinstance(target_id, str)
                or target_id not in receipt["target_map"] or not isinstance(ids, list) or len(ids) > _MAX_ROWS
                or any(not isinstance(identity, str) for identity in ids) or ids != sorted(set(ids))):
            _fail("selection")
        expected = _inventory(receipt, view)
        if view.get("display_witnesses") != expected:
            _fail("integrity")
        for target in view["targets"]:
            if target.get("display_context_ids") != sorted(row["id"] for row in expected if row["target_id"] == target["id"]):
                _fail("integrity")
        known = {row["id"]: row for row in expected if row["target_id"] == target_id}
        if any(identity not in known for identity in ids):
            _fail("selection")
        return deepcopy([known[identity] for identity in ids])
    except SourcePlanError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SourcePlanError("source_applications_display_integrity") from exc
