#!/usr/bin/env python3
"""Deterministic ECC pilot bridge for prepared CT137 release packets.

The bridge deliberately does not execute a release.  It validates one existing
digest-bound packet, builds the exact controller invocation plan, and compacts
technical/Test Runner evidence into the five-field root handoff.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


def _load_ct137_release_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "ops" / "ct137_native_release.py"
    )
    spec = importlib.util.spec_from_file_location("ct137_native_release", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ct137_release_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ct137_release = _load_ct137_release_module()
BridgeBlocked = _ct137_release.ReleaseBlocked

MAX_EVIDENCE_BYTES = 64 * 1024


def plan_release(
    *,
    packet_path: Path,
    packet_sha256: str,
    repo_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    """Return the immutable preflight/execute plan for one CT137 packet."""

    packet_path = packet_path.resolve(strict=True)
    repo_root = repo_root.resolve(strict=True)
    controller = repo_root / "scripts" / "ops" / "ct137_native_release.py"
    if not controller.is_file():
        raise BridgeBlocked("ct137_release_controller_missing")

    packet = _ct137_release.load_release_packet(packet_path, packet_sha256)
    release_evidence = evidence_root.resolve() / packet.release_id
    artifact_dir = release_evidence / "native-build"

    def command(mode: str) -> list[str]:
        return [
            sys.executable,
            str(controller),
            mode,
            "--packet",
            str(packet_path),
            "--packet-sha256",
            packet_sha256,
            "--artifact-dir",
            str(artifact_dir),
            "--evidence",
            str(release_evidence / f"{mode}.json"),
        ]

    return {
        "status": "PLANNED",
        "release_id": packet.release_id,
        "release_sha": packet.exact_sha,
        "target_environment": packet.target_environment,
        "target_services": list(packet.target_services),
        "packet_sha256": packet_sha256,
        "steps": [
            {"mode": "preflight", "argv": command("preflight")},
            {"mode": "execute", "argv": command("execute")},
        ],
        "metrics": {
            "deterministic": True,
            "model_calls": 0,
            "policy_documents_read": 0,
            "controller_commands": 2,
        },
    }


def compact_handoff(
    *,
    technical: Mapping[str, Any],
    acceptance: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Compact controller/Test Runner evidence without interpreting raw logs."""

    status = technical.get("status")
    release_id = _required_string(technical, "release_id")
    if status == "BLOCKED":
        reason = _required_string(technical, "reason")
        return {
            "result": f"BLOCKED; {release_id}",
            "changed": "none",
            "verified": "deterministic controller returned a structured block",
            "blockers": reason,
            "next": "root must resolve the named gate and issue a new exact packet",
        }
    if status == "READY":
        release_sha = _required_string(technical, "release_sha")
        return {
            "result": f"NOT READY; {release_id} preflight complete",
            "changed": "none",
            "verified": f"preflight READY for {release_sha}",
            "blockers": "release execution not performed",
            "next": "execute the same digest-bound packet after approval remains current",
        }
    if status != "RELEASE_OK":
        raise BridgeBlocked("technical_evidence_status_invalid")
    if technical.get("product_acceptance") != "SEPARATE_TEST_RUNNER_REQUIRED":
        raise BridgeBlocked("product_acceptance_contract_invalid")

    release_sha = _required_string(technical, "release_sha")
    previous_sha = _required_string(technical, "previous_release_sha")
    rollback_sha = _required_string(technical, "rollback_sha")
    changed = f"ct137-frontend {previous_sha} -> {release_sha}"
    verified = f"technical release SHA verified; rollback retained {rollback_sha}"

    if acceptance is None:
        return {
            "result": f"NOT READY; {release_id} technical release complete",
            "changed": changed,
            "verified": verified,
            "blockers": "product acceptance not supplied",
            "next": "run the separate Test Runner acceptance packet",
        }

    if (
        acceptance.get("status") != "PASS"
        or acceptance.get("release_id") != release_id
        or acceptance.get("release_sha") != release_sha
    ):
        return {
            "result": f"NOT READY; {release_id} acceptance mismatch",
            "changed": changed,
            "verified": verified,
            "blockers": "product acceptance missing, failed, or bound to another release",
            "next": "root must obtain matching Test Runner evidence",
        }

    scope = acceptance.get("scope")
    if (
        not isinstance(scope, list)
        or not scope
        or not all(isinstance(item, str) and item for item in scope)
    ):
        raise BridgeBlocked("acceptance_scope_invalid")
    return {
        "result": f"READY FOR ROOT REVIEW; {release_id}",
        "changed": changed,
        "verified": f"{verified}; product acceptance PASS scope={','.join(scope)}",
        "blockers": "none",
        "next": "root acceptance decision",
    }


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise BridgeBlocked(f"{name}_invalid")
    return value


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise BridgeBlocked("evidence_too_large")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except BridgeBlocked:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise BridgeBlocked("evidence_unreadable") from exc
    if not isinstance(payload, dict):
        raise BridgeBlocked("evidence_json_invalid")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--packet", required=True, type=Path)
    plan.add_argument("--packet-sha256", required=True)
    plan.add_argument("--repo-root", required=True, type=Path)
    plan.add_argument("--evidence-root", required=True, type=Path)

    handoff = subparsers.add_parser("handoff")
    handoff.add_argument("--technical", required=True, type=Path)
    handoff.add_argument("--acceptance", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan_release(
                packet_path=args.packet,
                packet_sha256=args.packet_sha256,
                repo_root=args.repo_root,
                evidence_root=args.evidence_root,
            )
        else:
            result = compact_handoff(
                technical=_read_json(args.technical),
                acceptance=_read_json(args.acceptance) if args.acceptance else None,
            )
        print(
            json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        )
        return 0
    except BridgeBlocked as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
