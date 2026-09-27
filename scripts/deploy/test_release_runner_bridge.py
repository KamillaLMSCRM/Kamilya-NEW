from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "deploy" / "release_runner_bridge.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("release_runner_bridge", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge = _load_module()


SHA = "1" * 40
CURRENT = "2" * 40
ROLLBACK = "3" * 40


def _packet_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "release_id": "REL-ECC-PILOT-20260927",
        "exact_sha": SHA,
        "source_branch": "master",
        "target_environment": "kz-production",
        "target_services": ["ct137-frontend"],
        "ci_run_id": 1001,
        "native_build_run_id": 1002,
        "expected_current_release": CURRENT,
        "rollback_sha": ROLLBACK,
        "migration_scope": "none",
        "owner_approval": "ECC pilot with no provider mutation",
        "smoke_scope": ["/healthz", "/login", "api-health"],
    }


class ReleaseRunnerBridgeTests(unittest.TestCase):
    def _packet(self, directory: Path) -> tuple[Path, str]:
        path = directory / "release-packet.json"
        content = (json.dumps(_packet_payload(), sort_keys=True) + "\n").encode()
        path.write_bytes(content)
        return path, hashlib.sha256(content).hexdigest()

    def test_digest_bound_packet_builds_compact_deterministic_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)

            result = bridge.plan_release(
                packet_path=packet,
                packet_sha256=digest,
                repo_root=ROOT,
                evidence_root=root / "evidence",
            )

        self.assertEqual(result["status"], "PLANNED")
        self.assertEqual(result["release_id"], "REL-ECC-PILOT-20260927")
        self.assertEqual(result["release_sha"], SHA)
        self.assertEqual(result["metrics"]["model_calls"], 0)
        self.assertEqual(result["metrics"]["policy_documents_read"], 0)
        self.assertTrue(result["metrics"]["deterministic"])
        self.assertEqual(
            [step["mode"] for step in result["steps"]], ["preflight", "execute"]
        )
        self.assertTrue(
            all(step["argv"][0] == sys.executable for step in result["steps"])
        )
        self.assertLess(len(json.dumps(result, sort_keys=True)), 4096)

    def test_digest_mismatch_stops_before_a_plan_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, _ = self._packet(root)

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "release_packet_digest_mismatch"
            ):
                bridge.plan_release(
                    packet_path=packet,
                    packet_sha256="0" * 64,
                    repo_root=ROOT,
                    evidence_root=root / "evidence",
                )

    def test_release_ok_without_product_acceptance_stays_not_ready(self) -> None:
        technical = {
            "status": "RELEASE_OK",
            "release_id": "REL-ECC-PILOT-20260927",
            "release_sha": SHA,
            "previous_release_sha": CURRENT,
            "rollback_sha": ROLLBACK,
            "product_acceptance": "SEPARATE_TEST_RUNNER_REQUIRED",
        }

        result = bridge.compact_handoff(technical=technical, acceptance=None)

        self.assertEqual(
            result["result"],
            "NOT READY; REL-ECC-PILOT-20260927 technical release complete",
        )
        self.assertEqual(result["changed"], f"ct137-frontend {CURRENT} -> {SHA}")
        self.assertIn("technical release SHA verified", result["verified"])
        self.assertEqual(result["blockers"], "product acceptance not supplied")
        self.assertEqual(
            result["next"], "run the separate Test Runner acceptance packet"
        )
        self.assertLess(len(json.dumps(result, sort_keys=True)), 2048)

    def test_release_ok_requires_explicit_separate_acceptance_contract(self) -> None:
        technical = {
            "status": "RELEASE_OK",
            "release_id": "REL-ECC-PILOT-20260927",
            "release_sha": SHA,
            "previous_release_sha": CURRENT,
            "rollback_sha": ROLLBACK,
        }

        with self.assertRaisesRegex(
            bridge.BridgeBlocked, "product_acceptance_contract_invalid"
        ):
            bridge.compact_handoff(technical=technical, acceptance=None)

    def test_release_and_product_acceptance_produce_root_review_handoff(self) -> None:
        technical = {
            "status": "RELEASE_OK",
            "release_id": "REL-ECC-PILOT-20260927",
            "release_sha": SHA,
            "previous_release_sha": CURRENT,
            "rollback_sha": ROLLBACK,
            "product_acceptance": "SEPARATE_TEST_RUNNER_REQUIRED",
        }
        acceptance = {
            "status": "PASS",
            "release_id": "REL-ECC-PILOT-20260927",
            "release_sha": SHA,
            "scope": ["training-log"],
        }

        result = bridge.compact_handoff(technical=technical, acceptance=acceptance)

        self.assertEqual(
            result["result"], "READY FOR ROOT REVIEW; REL-ECC-PILOT-20260927"
        )
        self.assertEqual(result["blockers"], "none")
        self.assertEqual(result["next"], "root acceptance decision")
        self.assertIn("product acceptance PASS", result["verified"])


if __name__ == "__main__":
    unittest.main()
