#!/usr/bin/env python3
"""Pure, deterministic GO/NO_GO evaluator for sanitized release evidence."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TextIO

ENVELOPE_FIELDS = {
    "schema_version", "project", "release_sha", "repo_fingerprint",
    "dev_fingerprint", "prod_fingerprint", "evidence", "approvals",
}
EVIDENCE_FIELDS = {
    "evidence_id", "state", "evidence_label", "release_sha", "environment",
    "target_fingerprint", "evidence_ref", "observed_at", "sensitive",
}
APPROVAL_FIELDS = {
    "approval_id", "scope", "status", "evidence_label", "release_sha",
    "target_fingerprint", "evidence_ref", "approved_at", "sensitive",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
REF_RE = re.compile(r"^REF-[0-9a-f]{16,64}$")
APPROVAL_RE = re.compile(r"^AP-[0-9a-f]{16,64}$")
MAX_INPUT_BYTES = 1024 * 1024

STAGES = (
    ("LOCAL", ("EV-LOCAL-TESTS", "EV-RELEASE-IDENTITY")),
    ("DEV", (
        "EV-DEV-UPGRADE", "EV-DEV-DOWNGRADE-REUPGRADE", "EV-DEV-FORCE-RLS",
        "EV-DEV-ACTIVE-REVISION", "EV-DEV-FTS-EXPLAIN", "EV-DEV-CLEANUP",
    )),
    ("BUILD", ("EV-CI", "EV-ARTIFACT")),
    ("READINESS", ("EV-BACKUP-RESTORE",)),
    ("CANARY", (
        "EV-PROD-MIGRATION", "EV-PROD-REINDEX", "EV-PROD-CANARY",
        "EV-PROD-CROSS-TENANT", "EV-PROD-LATENCY-COST",
        "EV-PROD-OBSERVABILITY",
    )),
    ("RELEASE", (
        "EV-PROD-DEPLOY", "EV-PROD-READBACK", "EV-PROD-ROLLBACK",
        "EV-PROD-CLEANUP", "EV-CANONICAL-EVIDENCE",
    )),
)
REQUIRED_EVIDENCE = tuple(item for _, stage in STAGES for item in stage)
EVIDENCE_CONTRACT = {
    "EV-LOCAL-TESTS": ("local", "repo", {"GIT-DERIVED"}),
    "EV-RELEASE-IDENTITY": ("git-remote", "repo", {"GIT-DERIVED", "PROVIDER-CONFIRMED"}),
    "EV-DEV-UPGRADE": ("supabase-dev", "dev", {"RUNTIME-DERIVED"}),
    "EV-DEV-DOWNGRADE-REUPGRADE": ("supabase-dev", "dev", {"RUNTIME-DERIVED"}),
    "EV-DEV-FORCE-RLS": ("supabase-dev", "dev", {"RUNTIME-DERIVED"}),
    "EV-DEV-ACTIVE-REVISION": ("supabase-dev", "dev", {"RUNTIME-DERIVED"}),
    "EV-DEV-FTS-EXPLAIN": ("supabase-dev", "dev", {"RUNTIME-DERIVED"}),
    "EV-DEV-CLEANUP": ("supabase-dev", "dev", {"RUNTIME-DERIVED"}),
    "EV-CI": ("github-ci", "repo", {"PROVIDER-CONFIRMED"}),
    "EV-ARTIFACT": ("release-artifact", "repo", {"PROVIDER-CONFIRMED"}),
    "EV-BACKUP-RESTORE": ("kz-production", "prod", {"RUNTIME-DERIVED", "PROVIDER-CONFIRMED"}),
    "EV-PROD-MIGRATION": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-REINDEX": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-CANARY": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-CROSS-TENANT": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-LATENCY-COST": ("kz-production", "prod", {"RUNTIME-DERIVED", "PROVIDER-CONFIRMED"}),
    "EV-PROD-OBSERVABILITY": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-DEPLOY": ("kz-production", "prod", {"PROVIDER-CONFIRMED", "RUNTIME-DERIVED"}),
    "EV-PROD-READBACK": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-ROLLBACK": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-PROD-CLEANUP": ("kz-production", "prod", {"RUNTIME-DERIVED"}),
    "EV-CANONICAL-EVIDENCE": ("canonical-docs", "repo", {"GIT-DERIVED"}),
}
APPROVAL_CONTRACT = {
    "dev_isolated_mutation": "dev",
    "provider_spend": "prod",
    "production_migration": "prod",
    "production_reindex": "prod",
    "production_canary": "prod",
    "production_deploy": "prod",
    "production_cleanup": "prod",
}
EVIDENCE_CAUSALITY = (
    ("EV-RELEASE-IDENTITY", "EV-CI"),
    ("EV-CI", "EV-ARTIFACT"),
    ("EV-ARTIFACT", "EV-BACKUP-RESTORE"),
    ("EV-ARTIFACT", "EV-PROD-MIGRATION"),
    ("EV-DEV-UPGRADE", "EV-DEV-DOWNGRADE-REUPGRADE"),
    ("EV-BACKUP-RESTORE", "EV-PROD-MIGRATION"),
    ("EV-PROD-MIGRATION", "EV-PROD-REINDEX"),
    ("EV-PROD-REINDEX", "EV-PROD-CANARY"),
    ("EV-PROD-CANARY", "EV-PROD-CROSS-TENANT"),
    ("EV-PROD-CANARY", "EV-PROD-LATENCY-COST"),
    ("EV-PROD-CANARY", "EV-PROD-OBSERVABILITY"),
    ("EV-PROD-CROSS-TENANT", "EV-PROD-DEPLOY"),
    ("EV-PROD-LATENCY-COST", "EV-PROD-DEPLOY"),
    ("EV-PROD-OBSERVABILITY", "EV-PROD-DEPLOY"),
    ("EV-PROD-DEPLOY", "EV-PROD-READBACK"),
    ("EV-PROD-READBACK", "EV-PROD-CLEANUP"),
    ("EV-PROD-CLEANUP", "EV-CANONICAL-EVIDENCE"),
)
APPROVAL_CAUSALITY = {
    "dev_isolated_mutation": "EV-DEV-UPGRADE",
    "provider_spend": "EV-PROD-LATENCY-COST",
    "production_migration": "EV-PROD-MIGRATION",
    "production_reindex": "EV-PROD-REINDEX",
    "production_canary": "EV-PROD-CANARY",
    "production_deploy": "EV-PROD-DEPLOY",
    "production_cleanup": "EV-PROD-CLEANUP",
}
ALLOWED_STATES = {"PASS", "FAIL", "NOT_VERIFIED", "BLOCKED"}


class GateContractError(ValueError):
    """Raised when an evidence envelope is malformed or ambiguously bound."""


@dataclass(frozen=True, slots=True)
class ValidEvidence:
    evidence_id: str
    state: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ValidApproval:
    scope: str
    approved_at: datetime


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise GateContractError(f"{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateContractError(f"{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GateContractError(f"{field}_timezone_required")
    return parsed.astimezone(timezone.utc)


def _fingerprint_for(kind: str, envelope: dict[str, Any]) -> str:
    return {
        "repo": envelope["repo_fingerprint"],
        "dev": envelope["dev_fingerprint"],
        "prod": envelope["prod_fingerprint"],
    }[kind]


def _validate_envelope_header(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != ENVELOPE_FIELDS:
        raise GateContractError("envelope_schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise GateContractError("schema_version_invalid")
    if raw["project"] != "Kamilya-NEW":
        raise GateContractError("project_scope_invalid")
    if not isinstance(raw["release_sha"], str) or not SHA_RE.fullmatch(raw["release_sha"]):
        raise GateContractError("release_sha_invalid")
    for field in ("repo_fingerprint", "dev_fingerprint", "prod_fingerprint"):
        if not isinstance(raw[field], str) or not FINGERPRINT_RE.fullmatch(raw[field]):
            raise GateContractError(f"{field}_invalid")
    if len({raw["repo_fingerprint"], raw["dev_fingerprint"], raw["prod_fingerprint"]}) != 3:
        raise GateContractError("target_fingerprints_must_be_distinct")
    if not isinstance(raw["evidence"], list) or not isinstance(raw["approvals"], list):
        raise GateContractError("evidence_and_approvals_must_be_lists")
    return raw


def _validate_evidence(raw: Any, envelope: dict[str, Any], index: int) -> ValidEvidence:
    if not isinstance(raw, dict) or set(raw) != EVIDENCE_FIELDS:
        raise GateContractError(f"evidence_{index}_schema_invalid")
    evidence_id = raw["evidence_id"]
    if evidence_id not in EVIDENCE_CONTRACT:
        raise GateContractError(f"evidence_{index}_id_invalid")
    if raw["sensitive"] is not False:
        raise GateContractError(f"evidence_{index}_sensitive_forbidden")
    if raw["state"] not in ALLOWED_STATES:
        raise GateContractError(f"evidence_{index}_state_invalid")
    environment, fingerprint_kind, labels = EVIDENCE_CONTRACT[evidence_id]
    if raw["environment"] != environment:
        raise GateContractError(f"evidence_{index}_environment_mismatch")
    if raw["target_fingerprint"] != _fingerprint_for(fingerprint_kind, envelope):
        raise GateContractError(f"evidence_{index}_target_mismatch")
    if raw["release_sha"] != envelope["release_sha"]:
        raise GateContractError(f"evidence_{index}_release_mismatch")
    if raw["evidence_label"] not in labels:
        raise GateContractError(f"evidence_{index}_label_invalid")
    if not isinstance(raw["evidence_ref"], str) or not REF_RE.fullmatch(raw["evidence_ref"]):
        raise GateContractError(f"evidence_{index}_ref_invalid")
    observed_at = _timestamp(raw["observed_at"], f"evidence_{index}_observed_at")
    return ValidEvidence(
        evidence_id=evidence_id,
        state=raw["state"],
        observed_at=observed_at,
    )


def _validate_approval(raw: Any, envelope: dict[str, Any], index: int) -> ValidApproval:
    if not isinstance(raw, dict) or set(raw) != APPROVAL_FIELDS:
        raise GateContractError(f"approval_{index}_schema_invalid")
    scope = raw["scope"]
    if scope not in APPROVAL_CONTRACT:
        raise GateContractError(f"approval_{index}_scope_invalid")
    if raw["sensitive"] is not False:
        raise GateContractError(f"approval_{index}_sensitive_forbidden")
    if not isinstance(raw["approval_id"], str) or not APPROVAL_RE.fullmatch(raw["approval_id"]):
        raise GateContractError(f"approval_{index}_id_invalid")
    if raw["status"] != "APPROVED" or raw["evidence_label"] != "OWNER-CONFIRMED":
        raise GateContractError(f"approval_{index}_authority_invalid")
    if raw["release_sha"] != envelope["release_sha"]:
        raise GateContractError(f"approval_{index}_release_mismatch")
    fingerprint_kind = APPROVAL_CONTRACT[scope]
    if raw["target_fingerprint"] != _fingerprint_for(fingerprint_kind, envelope):
        raise GateContractError(f"approval_{index}_target_mismatch")
    if not isinstance(raw["evidence_ref"], str) or not REF_RE.fullmatch(raw["evidence_ref"]):
        raise GateContractError(f"approval_{index}_ref_invalid")
    approved_at = _timestamp(raw["approved_at"], f"approval_{index}_approved_at")
    return ValidApproval(scope=scope, approved_at=approved_at)


def evaluate(raw: Any) -> dict[str, Any]:
    envelope = _validate_envelope_header(raw)
    evidence_items = [
        _validate_evidence(item, envelope, index)
        for index, item in enumerate(envelope["evidence"], start=1)
    ]
    if len({item.evidence_id for item in evidence_items}) != len(evidence_items):
        raise GateContractError("evidence_ids_must_be_unique")
    approval_items = [
        _validate_approval(item, envelope, index)
        for index, item in enumerate(envelope["approvals"], start=1)
    ]
    if len({item.scope for item in approval_items}) != len(approval_items):
        raise GateContractError("approval_scopes_must_be_unique")

    evidence = {item.evidence_id: item.state for item in evidence_items}
    evidence_by_id = {item.evidence_id: item for item in evidence_items}
    blockers: list[str] = []
    passed_prior_stages = True
    for stage_name, stage_ids in STAGES:
        stage_passed = all(evidence.get(evidence_id) == "PASS" for evidence_id in stage_ids)
        for evidence_id in stage_ids:
            state = evidence.get(evidence_id)
            if state is None:
                blockers.append(f"MISSING:{evidence_id}")
            elif state != "PASS":
                blockers.append(f"{state}:{evidence_id}")
            elif not passed_prior_stages:
                blockers.append(f"OUT_OF_ORDER:{evidence_id}")
        passed_prior_stages = passed_prior_stages and stage_passed

    for before_id, after_id in EVIDENCE_CAUSALITY:
        before = evidence_by_id.get(before_id)
        after = evidence_by_id.get(after_id)
        if before and after and before.observed_at > after.observed_at:
            blockers.append(f"TIME_ORDER:{before_id}>{after_id}")

    approvals_by_scope = {item.scope: item for item in approval_items}
    provided_approvals = set(approvals_by_scope)
    for scope in APPROVAL_CONTRACT:
        if scope not in provided_approvals:
            blockers.append(f"MISSING_APPROVAL:{scope}")
    for scope, operation_id in APPROVAL_CAUSALITY.items():
        approval = approvals_by_scope.get(scope)
        operation = evidence_by_id.get(operation_id)
        if approval and operation and approval.approved_at > operation.observed_at:
            blockers.append(f"LATE_APPROVAL:{scope}>{operation_id}")

    return {
        "schema_version": 1,
        "project": "Kamilya-NEW",
        "release_sha": envelope["release_sha"],
        "verdict": "NO_GO" if blockers else "GO",
        "completed_evidence": sum(state == "PASS" for state in evidence.values()),
        "required_evidence": len(REQUIRED_EVIDENCE),
        "completed_approvals": len(provided_approvals),
        "required_approvals": len(APPROVAL_CONTRACT),
        "blockers": blockers,
        "actionable": False,
        "root_reference_verification_required": True,
        "authority": "STRUCTURAL EVALUATION ONLY; ROOT MUST VERIFY EVERY REFERENCE",
    }


def read_envelope(stream: TextIO | None = None) -> Any:
    if stream is None:
        payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise GateContractError("input_size_exceeded")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GateContractError("input_utf8_required") from exc
    else:
        text = stream.read(MAX_INPUT_BYTES + 1)
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise GateContractError("input_size_exceeded")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GateContractError("input_json_invalid") from exc


def main(stdin: TextIO | None = None) -> int:
    try:
        result = evaluate(read_envelope(stdin))
    except GateContractError as exc:
        print(f"kamilya-release-evidence-gate: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
