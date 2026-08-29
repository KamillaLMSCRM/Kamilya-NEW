#!/usr/bin/env python3
"""Build inert learning candidates from one sanitized JSON stdin envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, TextIO

EVENT_FIELDS = {"event_id", "observed_at", "project", "kind", "fingerprint", "error_class", "evidence_label", "source_type", "source_ref", "sensitive"}
ENVELOPE_FIELDS = {"schema_version", "events", "reviewed_revisions"}
ALLOWED_PROJECTS = {"Kamilya-NEW", "kamilya-landing"}
ALLOWED_KINDS = {"TOOL_FAILURE", "TEST_FAILURE", "RUNTIME_ALERT", "REVIEW_FINDING", "PROCEDURE_GAP", "RULE_GAP", "ARCHITECTURE_DECISION", "SECURITY_FINDING"}
ALLOWED_LABELS = {"GIT-DERIVED", "RUNTIME-DERIVED", "OWNER-CONFIRMED", "PROVIDER-CONFIRMED", "GRAPH-DERIVED", "INFERRED", "NOT VERIFIED", "BLOCKED"}
ALLOWED_SOURCE_TYPES = {"git", "source", "test", "runtime", "provider", "owner", "agent_report", "memory", "plan", "handoff", "graph"}
DIRECT_SOURCE_TYPES = {"git", "source", "test", "runtime", "provider", "owner"}
SOURCE_LABELS = {
    "git": {"GIT-DERIVED"}, "source": {"GIT-DERIVED"}, "test": {"GIT-DERIVED"},
    "runtime": {"RUNTIME-DERIVED"}, "provider": {"PROVIDER-CONFIRMED"},
    "owner": {"OWNER-CONFIRMED"}, "graph": {"GRAPH-DERIVED"},
    "agent_report": {"NOT VERIFIED", "BLOCKED", "INFERRED"},
    "memory": {"NOT VERIFIED", "BLOCKED", "INFERRED"},
    "plan": {"NOT VERIFIED", "BLOCKED", "INFERRED"},
    "handoff": {"NOT VERIFIED", "BLOCKED", "INFERRED"},
}
ALLOWED_ERROR_CLASSES = {"TIMEOUT", "AUTHENTICATION_FAILED", "AUTHORIZATION_DENIED", "ROUTE_UNAVAILABLE", "NETWORK_UNAVAILABLE", "TOOL_MISSING", "DEPENDENCY_MISSING", "VALIDATION_FAILED", "TEST_FAILED", "RUNTIME_MISMATCH", "RESOURCE_PRESSURE", "SECURITY_CONTROL_FAILED", "UNKNOWN_SANITIZED"}
EVENT_ID_RE = re.compile(r"^EVT-[0-9a-f]{16,64}$")
OBSERVATION_ID_RE = re.compile(r"^OBS-[0-9a-f]{16,64}$")
SOURCE_REF_RE = re.compile(r"^REF-[0-9a-f]{16,64}$")
CANDIDATE_ID_RE = re.compile(r"^LC-[0-9a-f]{20}$")
REVISION_ID_RE = re.compile(r"^LR-[0-9a-f]{20}$")
UNSAFE_TEXT_RE = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|authorization|cookie)\s*[:=]")
MAX_INPUT_BYTES = 1024 * 1024
MAX_EVENTS = 10000


class InputContractError(ValueError):
    """Raised when input violates the sanitized envelope contract."""


def _canonical_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputContractError("observed_at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputContractError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_event(raw: Any, item_number: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InputContractError(f"event {item_number}: event must be an object")
    if set(raw) - EVENT_FIELDS:
        raise InputContractError(f"event {item_number}: unknown fields are forbidden")
    if EVENT_FIELDS - set(raw):
        raise InputContractError(f"event {item_number}: required fields are missing")
    if raw["sensitive"] is not False:
        raise InputContractError(f"event {item_number}: sensitive input is forbidden")
    if any(not isinstance(raw[field], str) for field in EVENT_FIELDS - {"sensitive"}):
        raise InputContractError(f"event {item_number}: all event fields must be strings")
    if raw["project"] not in ALLOWED_PROJECTS:
        raise InputContractError(f"event {item_number}: project is outside Kamilya scope")
    if raw["kind"] not in ALLOWED_KINDS:
        raise InputContractError(f"event {item_number}: unsupported kind")
    if raw["evidence_label"] not in ALLOWED_LABELS:
        raise InputContractError(f"event {item_number}: unsupported evidence label")
    if raw["source_type"] not in ALLOWED_SOURCE_TYPES:
        raise InputContractError(f"event {item_number}: unsupported source type")
    if raw["evidence_label"] not in SOURCE_LABELS[raw["source_type"]]:
        raise InputContractError(f"event {item_number}: evidence label does not match source type")
    if raw["error_class"] not in ALLOWED_ERROR_CLASSES:
        raise InputContractError(f"event {item_number}: unsupported error_class")
    if not EVENT_ID_RE.fullmatch(raw["event_id"]):
        raise InputContractError(f"event {item_number}: unsafe event_id")
    if not OBSERVATION_ID_RE.fullmatch(raw["fingerprint"]):
        raise InputContractError(f"event {item_number}: unsafe fingerprint")
    if not SOURCE_REF_RE.fullmatch(raw["source_ref"]):
        raise InputContractError(f"event {item_number}: unsafe source_ref")
    if any(UNSAFE_TEXT_RE.search(value) for value in raw.values() if isinstance(value, str)):
        raise InputContractError(f"event {item_number}: secret-like content is forbidden")
    normalized = dict(raw)
    normalized["observed_at"] = _canonical_timestamp(raw["observed_at"])
    return normalized


def validate_reviewed_revisions(raw: Any) -> set[tuple[str, str]]:
    if not isinstance(raw, list):
        raise InputContractError("reviewed_revisions must be a list")
    result: set[tuple[str, str]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != {"candidate_id", "revision_id"}:
            raise InputContractError(f"reviewed revision {index}: invalid entry")
        candidate_id, revision_id = item["candidate_id"], item["revision_id"]
        if not isinstance(candidate_id, str) or not CANDIDATE_ID_RE.fullmatch(candidate_id):
            raise InputContractError(f"reviewed revision {index}: invalid candidate ID")
        if not isinstance(revision_id, str) or not REVISION_ID_RE.fullmatch(revision_id):
            raise InputContractError(f"reviewed revision {index}: invalid revision ID")
        result.add((candidate_id, revision_id))
    return result


def validate_envelope(raw: Any) -> tuple[list[Any], set[tuple[str, str]]]:
    if not isinstance(raw, dict) or set(raw) != ENVELOPE_FIELDS:
        raise InputContractError("stdin envelope schema is invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise InputContractError("unsupported envelope schema_version")
    if not isinstance(raw["events"], list):
        raise InputContractError("events must be a list")
    if len(raw["events"]) > MAX_EVENTS:
        raise InputContractError("event count exceeds the limit")
    return raw["events"], validate_reviewed_revisions(raw["reviewed_revisions"])


def read_stdin_envelope(stream: TextIO | None = None) -> Any:
    if stream is None:
        payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise InputContractError("stdin envelope exceeds the size limit")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputContractError("stdin envelope must be UTF-8") from exc
    else:
        text = stream.read(MAX_INPUT_BYTES + 1)
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise InputContractError("stdin envelope exceeds the size limit")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputContractError("stdin envelope is invalid JSON") from exc


def _candidate_id(key: tuple[str, str, str, str]) -> str:
    return f"LC-{hashlib.sha256(chr(31).join(key).encode('utf-8')).hexdigest()[:20]}"


def _revision_id(items: list[dict[str, Any]]) -> str:
    fields = ("event_id", "observed_at", "evidence_label", "source_type", "source_ref")
    canonical = [{field: item[field] for field in fields} for item in sorted(items, key=lambda item: item["event_id"])]
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"LR-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _destination(kind: str) -> str:
    return {"PROCEDURE_GAP": "reviewed project skill", "RULE_GAP": "governing AGENTS.md", "ARCHITECTURE_DECISION": "ADR", "REVIEW_FINDING": "no persistence until independently reproduced"}.get(kind, "ERRORS.md candidate plus deterministic test/CI/script control")


def collect_candidates(events: Iterable[Any], reviewed_revisions: set[tuple[str, str]] | None = None, min_occurrences: int = 2) -> list[dict[str, Any]]:
    if type(min_occurrences) is not int or min_occurrences < 2:
        raise InputContractError("min_occurrences must be at least 2")
    try:
        raw_events = list(events)
    except TypeError as exc:
        raise InputContractError("events must be iterable") from exc
    if len(raw_events) > MAX_EVENTS:
        raise InputContractError("event count exceeds the limit")
    reviewed_revisions = reviewed_revisions or set()
    for candidate_id, revision_id in reviewed_revisions:
        if not CANDIDATE_ID_RE.fullmatch(candidate_id) or not REVISION_ID_RE.fullmatch(revision_id):
            raise InputContractError("reviewed revision IDs are invalid")
    validated = [validate_event(raw, index) for index, raw in enumerate(raw_events, start=1)]
    unique_events: dict[str, dict[str, Any]] = {}
    for event in validated:
        existing = unique_events.get(event["event_id"])
        if existing is not None and existing != event:
            raise InputContractError("conflicting duplicate event_id")
        unique_events[event["event_id"]] = event
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in unique_events.values():
        grouped[(event["project"], event["kind"], event["fingerprint"], event["error_class"])].append(event)
    candidates: list[dict[str, Any]] = []
    for key in sorted(grouped):
        items = grouped[key]
        reported_refs = {item["source_ref"] for item in items}
        if len(items) < min_occurrences or len(reported_refs) < min_occurrences:
            continue
        candidate_id, revision_id = _candidate_id(key), _revision_id(items)
        if (candidate_id, revision_id) in reviewed_revisions:
            continue
        direct = sorted({item["source_type"] for item in items if item["source_type"] in DIRECT_SOURCE_TYPES})
        contextual = sorted({item["source_type"] for item in items if item["source_type"] not in DIRECT_SOURCE_TYPES})
        observed = sorted(item["observed_at"] for item in items)
        candidates.append({
            "candidate_id": candidate_id, "revision_id": revision_id, "state": "CANDIDATE_ONLY",
            "project": key[0], "kind": key[1], "fingerprint": key[2], "error_class": key[3],
            "event_count": len(items), "distinct_reported_refs": len(reported_refs),
            "event_ids": sorted(item["event_id"] for item in items), "observed_from": observed[0], "observed_to": observed[-1],
            "evidence_state": "DIRECT_EVIDENCE_PRESENT" if direct else "UNVERIFIED_REPORT_PATTERN",
            "evidence_labels": sorted({item["evidence_label"] for item in items}),
            "direct_source_types": direct, "contextual_source_types": contextual,
            "suggested_destination": _destination(key[1]),
            "required_gate": "root verify source independence, symptom, root cause, fix, and regression before persistence" if direct else "obtain independent source/test/provider/runtime evidence before persistence",
            "authority": "NONE; ROOT REVIEW REQUIRED",
        })
    return candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-occurrences", type=int, default=2)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = read_stdin_envelope(stdin)
        events, reviewed = validate_envelope(raw)
        candidates = collect_candidates(events, reviewed, args.min_occurrences)
    except InputContractError as exc:
        print(f"learning-candidate-triage: {exc}", file=sys.stderr)
        return 2
    if not candidates:
        return 0
    print(json.dumps({"schema_version": 1, "status": "CANDIDATES", "candidates": candidates}, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
