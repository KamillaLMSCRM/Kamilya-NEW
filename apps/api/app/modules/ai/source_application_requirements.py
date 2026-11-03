"""Strict LOCAL refusal subjects; allowed edits never define semantic success."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, NoReturn

from app.modules.ai.source_application_fields import APPLICATION_REPAIR_FIELDS
from app.modules.ai.source_assessment_graph import SourceGraphError, _handle, _hash
from app.modules.ai.source_assessment_plan import SourcePlanError
from app.modules.ai.source_frame_patch import _validate_json

POLICY = "application-requirement-audit-v4"
CONTEXT_AXES = ("participants", "temporal_setting", "condition", "exception", "prerequisite", "antecedent")
CONTEXT_FUNCTIONS = ("actor_identity", "recipient_identity", "temporal_setting", "condition", "exception", "static_scope",
                     "prior_action_prerequisite", "antecedent_reference", "quantity_support", "operator_support")
NATIVE_ASPECT_FIELDS = ("source_refs", "answer_components", "assessed_focus", "question_format", "construction_mode",
                        "source_quote_proposition", "fixed_source_context")
_TOP = {"source_refs", "target_verdicts", "application_verdicts", "relation_verdicts", "context_verdicts", "source_gaps", "unit_verdicts"}
_TARGET = {"target_id", "admit", "errors", "repair_fields", "requirements"}
_FUNCTION_AXES = {"actor_identity": "participants", "recipient_identity": "participants",
                  "temporal_setting": "temporal_setting", "condition": "condition", "exception": "exception",
                  "prior_action_prerequisite": "prerequisite", "antecedent_reference": "antecedent"}


def _fail(suffix: str) -> NoReturn:
    raise SourcePlanError("source_applications_requirement_" + suffix)


def _anchor(evidence_id: Any, receipt: dict[str, Any], selection: str = "") -> dict[str, Any]:
    if not isinstance(evidence_id, str):
        _fail("anchor")
    view = receipt.get("view")
    if (not isinstance(view, dict) or not isinstance(view.get("evidence_spans"), list)
            or not isinstance(view.get("sources"), list)
            or any(not isinstance(row, dict) for row in [*view["evidence_spans"], *view["sources"]])):
        _fail("anchor")
    spans = [row for row in view["evidence_spans"] if row.get("id") == evidence_id]
    if len(spans) != 1:
        _fail("anchor")
    span = spans[0]
    sources = [row for row in view["sources"] if row.get("ref") == span.get("ref")]
    if len(sources) != 1:
        _fail("anchor")
    source = sources[0]
    text = source.get("text")
    start, end = span.get("start"), span.get("end")
    if (source.get("primary") is not True or not isinstance(text, str) or not isinstance(source.get("ref"), str)
            or not isinstance(source.get("source_id"), str) or not source["source_id"]
            or span.get("source_id") != source["source_id"]
            or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)):
        _fail("anchor")
    try:
        source["ref"].encode("utf-8")
        source["source_id"].encode("utf-8")
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        quote = text[start:end]
        quote_sha = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise SourcePlanError("source_applications_requirement_anchor") from exc
    if span.get("source_sha256") != source_sha:
        _fail("anchor")
    if span.get("whole_source") is True:
        if start != 0 or end != len(text) or ("quote" in span and span["quote"] != text):
            _fail("anchor")
    elif span.get("quote") != quote:
        _fail("anchor")
    if selection:
        offset = quote.find(selection)
        if offset < 0 or quote.rfind(selection) != offset:
            _fail("anchor_selection")
        start += offset
        end = start + len(selection)
        quote_sha = hashlib.sha256(selection.encode("utf-8")).hexdigest()
    return {"ref": source["ref"], "source_id": source["source_id"], "source_sha256": source_sha,
            "start": start, "end": end, "quote_sha256": quote_sha}


def _subject(subject: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(subject, dict) or not isinstance(subject.get("type"), str):
        _fail("subject")
    kind = subject["type"]
    if kind == "native_aspect":
        if set(subject) != {"type", "field"} or subject.get("field") not in NATIVE_ASPECT_FIELDS:
            _fail("subject")
        return deepcopy(subject)
    if kind == "context_function":
        if (set(subject) not in ({"type", "function", "evidence_id"}, {"type", "function", "evidence_id", "quote"})
                or subject.get("function") not in CONTEXT_FUNCTIONS
                or not isinstance(subject.get("quote", ""), str) or len(subject.get("quote", "")) > 4096):
            _fail("subject")
        return {"type": kind, "function": subject["function"],
                "anchor": _anchor(subject["evidence_id"], receipt, subject.get("quote", ""))}
    _fail("subject")


def _context_negatives(response: dict[str, Any], known: list[str], receipt: dict[str, Any]) -> dict[str, set[str]]:
    display_enabled = "display_context_policy" in receipt["view"]
    if display_enabled:
        from app.modules.ai.source_application_display import POLICY as DISPLAY_POLICY

        if receipt["view"]["display_context_policy"] != DISPLAY_POLICY:
            _fail("display_policy")
    rows = response["context_verdicts"]
    if not isinstance(rows, list) or len(rows) != len(known):
        _fail("context_inventory")
    result: dict[str, set[str]] = {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"target_id", "axes"}
                or not isinstance(row["target_id"], str) or row["target_id"] not in known
                or row["target_id"] in result or not isinstance(row["axes"], list)
                or len(row["axes"]) != len(CONTEXT_AXES)):
            _fail("context_inventory")
        seen: set[str] = set()
        negative: set[str] = set()
        for axis in row["axes"]:
            fields = {"axis", "status", "own_answer_support", "reason"}
            if display_enabled:
                fields.add("display_context_ids")
            if (not isinstance(axis, dict) or set(axis) != fields
                    or not isinstance(axis["axis"], str) or axis["axis"] not in CONTEXT_AXES or axis["axis"] in seen
                    or not isinstance(axis["status"], str)
                    or axis["status"] not in ("not_required", "covered", "missing", "ambiguous")
                    or type(axis["own_answer_support"]) is not bool
                    or not isinstance(axis["reason"], str) or len(axis["reason"]) > 240):
                _fail("context_axis")
            if display_enabled:
                from app.modules.ai.source_application_display import validate_display_selection

                validate_display_selection(receipt, row["target_id"], axis["display_context_ids"])
                if axis["display_context_ids"] and axis["status"] != "covered":
                    _fail("negative_display_selection")
            seen.add(axis["axis"])
            if axis["status"] in ("missing", "ambiguous"):
                negative.add(axis["axis"])
        result[row["target_id"]] = negative
    return result


def normalize_requirement_audit(response: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    """Project this LOCAL wire to legacy syntax without changing any fresh vote."""
    try:
        _validate_json(response)
    except SourceGraphError as exc:
        raise SourcePlanError("source_applications_requirement_resources") from exc
    if len(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()) > 256 * 1024:
        _fail("resources")
    if not isinstance(response, dict) or set(response) != _TOP:
        _fail("wire")
    view = receipt.get("view")
    if not isinstance(view, dict) or not isinstance(view.get("targets"), list):
        _fail("inventory")
    targets = view["targets"]
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in targets):
        _fail("inventory")
    known = [row["id"] for row in targets]
    if len(known) != len(set(known)):
        _fail("inventory")
    context_negatives = _context_negatives(response, known, receipt)
    votes = response["target_verdicts"]
    if not isinstance(votes, list) or len(votes) != len(known):
        _fail("inventory")
    seen = set()
    normalized = []
    total = 0
    for vote in votes:
        if (not isinstance(vote, dict) or set(vote) != _TARGET or not isinstance(vote["target_id"], str)
                or vote["target_id"] not in known or vote["target_id"] in seen or type(vote["admit"]) is not bool):
            _fail("target")
        target_id = vote["target_id"]
        seen.add(target_id)
        errors, fields, requirements = vote["errors"], vote["repair_fields"], vote["requirements"]
        if (not isinstance(errors, list) or len(errors) > 8
                or any(not isinstance(error, str) or not error.strip() or len(error) > 240 for error in errors)
                or not isinstance(fields, list) or any(not isinstance(field, str) or field not in APPLICATION_REPAIR_FIELDS for field in fields)
                or len(fields) != len(set(fields)) or vote["admit"] != (not errors) or vote["admit"] != (not fields)
                or not isinstance(requirements, list) or len(requirements) > 32
                or vote["admit"] != (not requirements)):
            _fail("target")
        total += len(requirements)
        if total > 4096:
            _fail("resources")
        requirement_ids, subjects, covered = set(), set(), set()
        canonical_rows = []
        for row in requirements:
            if (not isinstance(row, dict) or set(row) != {"id", "error_indices", "subject"}
                    or not _handle(row["id"]) or row["id"] in requirement_ids):
                _fail("record")
            indices = row["error_indices"]
            if (not isinstance(indices, list) or not indices
                    or any(type(index) is not int or not 0 <= index < len(errors) for index in indices)
                    or len(indices) != len(set(indices))):
                _fail("indices")
            subject = _subject(row["subject"], receipt)
            fingerprint = _hash(subject)
            if fingerprint in subjects:
                _fail("duplicate_subject")
            subjects.add(fingerprint)
            requirement_ids.add(row["id"])
            covered.update(indices)
            canonical_rows.append({"id": row["id"], "error_indices": deepcopy(indices), "subject": subject})
        if covered != set(range(len(errors))):
            _fail("uncovered_errors")
        context_axes = {
            _FUNCTION_AXES[subject["function"]]
            for row in canonical_rows for subject in [row["subject"]]
            if subject["type"] == "context_function" and subject["function"] in _FUNCTION_AXES
        }
        literal_context = any(row["subject"] == {"type": "native_aspect", "field": "fixed_source_context"}
                              for row in canonical_rows)
        if context_negatives[target_id] and (vote["admit"] or (
                not literal_context and not context_negatives[target_id] <= context_axes)):
            _fail("context_coverage")
        normalized.append({"target_id": target_id, "requirements": canonical_rows})
    legacy = deepcopy(response)
    for vote in legacy["target_verdicts"]:
        vote.pop("requirements")
    result = {"policy": POLICY, "raw_sha256": _hash(response), "legacy_wire": legacy, "requirements": normalized}
    return {**result, "receipt_sha256": _hash(result)}
