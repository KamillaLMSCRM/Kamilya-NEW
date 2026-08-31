from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("evaluate_release_gate.py")
SPEC = importlib.util.spec_from_file_location("evaluate_release_gate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
EXAMPLE = Path(__file__).parents[1] / "examples" / "no-go.json"


def envelope():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def evidence(evidence_id, index, *, state="PASS"):
    environment, kind, labels = MODULE.EVIDENCE_CONTRACT[evidence_id]
    payload = envelope()
    fingerprint = {
        "repo": payload["repo_fingerprint"],
        "dev": payload["dev_fingerprint"],
        "prod": payload["prod_fingerprint"],
    }[kind]
    return {
        "evidence_id": evidence_id,
        "state": state,
        "evidence_label": sorted(labels)[0],
        "release_sha": payload["release_sha"],
        "environment": environment,
        "target_fingerprint": fingerprint,
        "evidence_ref": f"REF-{index:016x}",
        "observed_at": "2026-08-23T12:00:00Z",
        "sensitive": False,
    }


def approval(scope, index):
    payload = envelope()
    kind = MODULE.APPROVAL_CONTRACT[scope]
    fingerprint = payload["dev_fingerprint"] if kind == "dev" else payload["prod_fingerprint"]
    return {
        "approval_id": f"AP-{index:016x}",
        "scope": scope,
        "status": "APPROVED",
        "evidence_label": "OWNER-CONFIRMED",
        "release_sha": payload["release_sha"],
        "target_fingerprint": fingerprint,
        "evidence_ref": f"REF-{index + 100:016x}",
        "approved_at": "2026-08-23T12:00:00Z",
        "sensitive": False,
    }


def complete_envelope():
    payload = envelope()
    payload["evidence"] = [
        evidence(evidence_id, index)
        for index, evidence_id in enumerate(MODULE.REQUIRED_EVIDENCE, start=1)
    ]
    payload["approvals"] = [
        approval(scope, index)
        for index, scope in enumerate(MODULE.APPROVAL_CONTRACT, start=1)
    ]
    return payload


def complete_profile(profile):
    payload = envelope()
    payload["profile"] = profile
    contract = MODULE.PROFILE_CONTRACTS[profile]
    required_evidence = tuple(
        item for _, stage in contract["stages"] for item in stage
    )
    payload["evidence"] = [
        evidence(evidence_id, index)
        for index, evidence_id in enumerate(required_evidence, start=1)
    ]
    payload["approvals"] = [
        approval(scope, index)
        for index, scope in enumerate(contract["approvals"], start=1)
    ]
    return payload


class ReleaseGateTests(unittest.TestCase):
    def test_bounded_schema_predeploy_requires_only_applicable_evidence(self):
        payload = complete_profile("bounded_schema_predeploy")
        result = MODULE.evaluate(payload)
        self.assertEqual(result["verdict"], "GO")
        self.assertEqual(result["profile"], "bounded_schema_predeploy")
        self.assertEqual(result["required_evidence"], 5)
        self.assertEqual(result["required_approvals"], 3)
        self.assertNotIn("MISSING:EV-PROD-REINDEX", result["blockers"])
        self.assertNotIn("MISSING_APPROVAL:provider_spend", result["blockers"])

        payload["approvals"] = [
            item
            for item in payload["approvals"]
            if item["scope"] != "production_migration"
        ]
        self.assertIn(
            "MISSING_APPROVAL:production_migration",
            MODULE.evaluate(payload)["blockers"],
        )

    def test_bounded_schema_final_keeps_postdeploy_readback_fail_closed(self):
        payload = complete_profile("bounded_schema_final")
        self.assertEqual(MODULE.evaluate(payload)["verdict"], "GO")
        payload["evidence"] = [
            item
            for item in payload["evidence"]
            if item["evidence_id"] != "EV-PROD-READBACK"
        ]
        self.assertIn(
            "MISSING:EV-PROD-READBACK",
            MODULE.evaluate(payload)["blockers"],
        )

    def test_unknown_profile_is_rejected(self):
        payload = envelope()
        payload["profile"] = "skip_checks"
        with self.assertRaises(MODULE.GateContractError):
            MODULE.evaluate(payload)

    def test_bounded_profile_rejects_unrelated_evidence_and_approval(self):
        payload = complete_profile("bounded_schema_predeploy")
        payload["evidence"].append(evidence("EV-PROD-REINDEX", 99))
        with self.assertRaisesRegex(
            MODULE.GateContractError,
            "evidence_not_applicable_to_profile",
        ):
            MODULE.evaluate(payload)

        payload = complete_profile("bounded_schema_predeploy")
        payload["approvals"].append(approval("provider_spend", 99))
        with self.assertRaisesRegex(
            MODULE.GateContractError,
            "approval_not_applicable_to_profile",
        ):
            MODULE.evaluate(payload)

    def test_empty_envelope_is_deterministic_no_go(self):
        result = MODULE.evaluate(envelope())
        self.assertEqual(result["verdict"], "NO_GO")
        self.assertEqual(result["required_evidence"], len(MODULE.REQUIRED_EVIDENCE))
        self.assertIn("MISSING:EV-DEV-UPGRADE", result["blockers"])
        self.assertIn("MISSING_APPROVAL:production_deploy", result["blockers"])

    def test_only_complete_exactly_bound_envelope_is_go(self):
        result = MODULE.evaluate(complete_envelope())
        self.assertEqual(result["verdict"], "GO")
        self.assertIs(result["actionable"], False)
        self.assertIs(result["root_reference_verification_required"], True)
        self.assertIn("ROOT MUST VERIFY EVERY REFERENCE", result["authority"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["completed_evidence"], result["required_evidence"])
        self.assertEqual(result["completed_approvals"], result["required_approvals"])

    def test_failed_and_out_of_order_evidence_cannot_go(self):
        payload = complete_envelope()
        payload["evidence"] = [
            item for item in payload["evidence"] if item["evidence_id"] != "EV-DEV-UPGRADE"
        ]
        result = MODULE.evaluate(payload)
        self.assertEqual(result["verdict"], "NO_GO")
        self.assertIn("MISSING:EV-DEV-UPGRADE", result["blockers"])
        self.assertIn("OUT_OF_ORDER:EV-CI", result["blockers"])

        failed = complete_envelope()
        next(item for item in failed["evidence"] if item["evidence_id"] == "EV-PROD-CANARY")["state"] = "FAIL"
        self.assertIn("FAIL:EV-PROD-CANARY", MODULE.evaluate(failed)["blockers"])

    def test_release_environment_target_label_and_ref_are_exact(self):
        mutations = {
            "environment": "kz-production",
            "target_fingerprint": "f" * 64,
            "evidence_label": "GRAPH-DERIVED",
            "evidence_ref": "person@example.test",
            "release_sha": "f" * 40,
        }
        for field, value in mutations.items():
            payload = complete_envelope()
            payload["evidence"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(MODULE.GateContractError):
                    MODULE.evaluate(payload)

    def test_approvals_are_exactly_scoped_owner_confirmed_and_bound(self):
        payload = complete_envelope()
        payload["approvals"] = [
            item for item in payload["approvals"] if item["scope"] != "production_deploy"
        ]
        self.assertIn("MISSING_APPROVAL:production_deploy", MODULE.evaluate(payload)["blockers"])

        invalid = complete_envelope()
        invalid["approvals"][0]["evidence_label"] = "INFERRED"
        with self.assertRaises(MODULE.GateContractError):
            MODULE.evaluate(invalid)

    def test_observability_canonical_identity_and_mutation_approvals_are_required(self):
        for evidence_id in (
            "EV-RELEASE-IDENTITY",
            "EV-PROD-OBSERVABILITY",
            "EV-CANONICAL-EVIDENCE",
        ):
            payload = complete_envelope()
            payload["evidence"] = [
                item for item in payload["evidence"] if item["evidence_id"] != evidence_id
            ]
            with self.subTest(evidence_id=evidence_id):
                self.assertIn(f"MISSING:{evidence_id}", MODULE.evaluate(payload)["blockers"])

        for scope in ("provider_spend", "production_reindex"):
            payload = complete_envelope()
            payload["approvals"] = [
                item for item in payload["approvals"] if item["scope"] != scope
            ]
            with self.subTest(scope=scope):
                self.assertIn(
                    f"MISSING_APPROVAL:{scope}",
                    MODULE.evaluate(payload)["blockers"],
                )

    def test_causal_evidence_and_approval_timestamps_fail_closed(self):
        payload = complete_envelope()
        next(
            item for item in payload["evidence"]
            if item["evidence_id"] == "EV-PROD-DEPLOY"
        )["observed_at"] = "2026-08-23T13:00:00Z"
        result = MODULE.evaluate(payload)
        self.assertIn(
            "TIME_ORDER:EV-PROD-DEPLOY>EV-PROD-READBACK",
            result["blockers"],
        )

        late = complete_envelope()
        next(
            item for item in late["approvals"]
            if item["scope"] == "production_reindex"
        )["approved_at"] = "2026-08-23T13:00:00Z"
        self.assertIn(
            "LATE_APPROVAL:production_reindex>EV-PROD-REINDEX",
            MODULE.evaluate(late)["blockers"],
        )

        causal_edges = (
            ("EV-ARTIFACT", "EV-BACKUP-RESTORE"),
            ("EV-ARTIFACT", "EV-PROD-MIGRATION"),
            ("EV-PROD-OBSERVABILITY", "EV-PROD-DEPLOY"),
        )
        for before_id, after_id in causal_edges:
            edge = complete_envelope()
            next(
                item for item in edge["evidence"] if item["evidence_id"] == before_id
            )["observed_at"] = "2026-08-23T13:00:00Z"
            with self.subTest(before=before_id, after=after_id):
                self.assertIn(
                    f"TIME_ORDER:{before_id}>{after_id}",
                    MODULE.evaluate(edge)["blockers"],
                )

    def test_arbitrary_opaque_reference_never_becomes_actionable(self):
        payload = complete_envelope()
        next(
            item for item in payload["evidence"]
            if item["evidence_id"] == "EV-RELEASE-IDENTITY"
        )["evidence_ref"] = "REF-deadbeefdeadbeef"
        result = MODULE.evaluate(payload)
        self.assertEqual(result["verdict"], "GO")
        self.assertIs(result["actionable"], False)
        self.assertIs(result["root_reference_verification_required"], True)

    def test_duplicates_unknown_fields_and_sensitive_records_are_rejected(self):
        duplicate = complete_envelope()
        duplicate["evidence"].append(dict(duplicate["evidence"][0]))
        with self.assertRaises(MODULE.GateContractError):
            MODULE.evaluate(duplicate)
        unknown = complete_envelope()
        unknown["unexpected"] = True
        with self.assertRaises(MODULE.GateContractError):
            MODULE.evaluate(unknown)
        sensitive = complete_envelope()
        sensitive["evidence"][0]["sensitive"] = True
        with self.assertRaises(MODULE.GateContractError):
            MODULE.evaluate(sensitive)

    def test_runtime_has_no_filesystem_subprocess_or_network_adapter(self):
        stdin = io.StringIO(json.dumps(envelope()))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with (
                mock.patch("builtins.open", side_effect=AssertionError("filesystem")),
                mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess")),
                mock.patch.object(socket, "socket", side_effect=AssertionError("network")),
            ):
                code = MODULE.main(stdin)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["verdict"], "NO_GO")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
