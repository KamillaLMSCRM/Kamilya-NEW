from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def _fake_repo(
        self,
        directory: Path,
        *,
        mismatched_sha: bool = False,
        forced_status: str | None = None,
        write_evidence: bool = True,
        exit_code: int = 0,
    ) -> Path:
        repo = directory / "repo"
        controller = repo / "scripts" / "ops" / "ct137_native_release.py"
        controller.parent.mkdir(parents=True)
        release_sha = "9" * 40 if mismatched_sha else SHA
        status_expression = (
            repr(forced_status)
            if forced_status is not None
            else "'READY' if args.mode == 'preflight' else 'RELEASE_OK'"
        )
        write_block = (
            "args.evidence.parent.mkdir(parents=True, exist_ok=True)\n"
            "args.evidence.write_text(json.dumps(payload), encoding='utf-8')"
            if write_evidence
            else "pass"
        )
        controller.write_text(
            f"""from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('mode')
parser.add_argument('--packet')
parser.add_argument('--packet-sha256')
parser.add_argument('--artifact-dir')
parser.add_argument('--evidence', type=Path)
args = parser.parse_args()
payload = {{
    'status': {status_expression},
    'release_id': 'REL-ECC-PILOT-20260927',
    'release_sha': '{release_sha}',
    'previous_release_sha': '{CURRENT}',
    'rollback_sha': '{ROLLBACK}',
}}
if args.mode == 'execute':
    payload['product_acceptance'] = 'SEPARATE_TEST_RUNNER_REQUIRED'
{write_block}
print('raw controller output must not be propagated')
raise SystemExit({exit_code})
""",
            encoding="utf-8",
        )
        return repo

    def test_digest_bound_packet_builds_compact_deterministic_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)

            result = bridge.plan_release(
                packet_path=packet,
                packet_sha256=digest,
                repo_root=ROOT,
                evidence_root=ROOT / ".release-evidence",
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
                    evidence_root=ROOT / ".release-evidence",
                )

    def test_plan_cli_returns_one_bounded_json_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "plan",
                    "--packet",
                    str(packet),
                    "--packet-sha256",
                    digest,
                    "--repo-root",
                    str(ROOT),
                    "--evidence-root",
                    str(ROOT / ".release-evidence"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(payload["status"], "PLANNED")
        self.assertLess(len(completed.stdout), 4096)

    def test_plan_cli_returns_one_structured_error_for_invalid_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, _ = self._packet(root)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "plan",
                    "--packet",
                    str(packet),
                    "--packet-sha256",
                    "0" * 64,
                    "--repo-root",
                    str(ROOT),
                    "--evidence-root",
                    str(ROOT / ".release-evidence"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

        payload = json.loads(completed.stderr)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["reason"], "release_packet_digest_mismatch")
        self.assertLess(len(completed.stderr), 256)

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

    def test_dispatch_preflight_runs_once_and_returns_compact_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root)

            result = bridge.dispatch_release(
                mode="preflight",
                packet_path=packet,
                packet_sha256=digest,
                repo_root=repo,
                evidence_root=repo / ".release-evidence",
                confirm_release_id="",
            )

        self.assertEqual(
            result["result"], "NOT READY; REL-ECC-PILOT-20260927 preflight complete"
        )
        self.assertEqual(result["changed"], "none")
        self.assertNotIn("raw controller output", json.dumps(result))

    def test_dispatch_execute_requires_exact_release_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root)

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "execute_confirmation_mismatch"
            ):
                bridge.dispatch_release(
                    mode="execute",
                    packet_path=packet,
                    packet_sha256=digest,
                    repo_root=repo,
                    evidence_root=repo / ".release-evidence",
                    confirm_release_id="WRONG",
                )

    def test_dispatch_execute_stays_not_ready_until_separate_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root)

            result = bridge.dispatch_release(
                mode="execute",
                packet_path=packet,
                packet_sha256=digest,
                repo_root=repo,
                evidence_root=repo / ".release-evidence",
                confirm_release_id="REL-ECC-PILOT-20260927",
            )

        self.assertEqual(
            result["result"],
            "NOT READY; REL-ECC-PILOT-20260927 technical release complete",
        )
        self.assertEqual(result["blockers"], "product acceptance not supplied")

    def test_dispatch_rejects_controller_evidence_for_another_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root, mismatched_sha=True)

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "technical_evidence_release_sha_mismatch"
            ):
                bridge.dispatch_release(
                    mode="preflight",
                    packet_path=packet,
                    packet_sha256=digest,
                    repo_root=repo,
                    evidence_root=repo / ".release-evidence",
                    confirm_release_id="",
                )

    def test_plan_rejects_evidence_root_outside_exact_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root)

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "evidence_root_outside_checkout"
            ):
                bridge.plan_release(
                    packet_path=packet,
                    packet_sha256=digest,
                    repo_root=repo,
                    evidence_root=root / "outside",
                )

    def test_plan_rejects_noncanonical_evidence_root_inside_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root)

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "evidence_root_not_canonical"
            ):
                bridge.plan_release(
                    packet_path=packet,
                    packet_sha256=digest,
                    repo_root=repo,
                    evidence_root=repo / "artifacts",
                )

    def test_dispatch_preflight_rejects_execute_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root, forced_status="RELEASE_OK")

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "controller_phase_status_mismatch"
            ):
                bridge.dispatch_release(
                    mode="preflight",
                    packet_path=packet,
                    packet_sha256=digest,
                    repo_root=repo,
                    evidence_root=repo / ".release-evidence",
                    confirm_release_id="",
                )

    def test_dispatch_rejects_stale_evidence_after_controller_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root, write_evidence=False, exit_code=1)
            evidence = (
                repo / ".release-evidence" / "REL-ECC-PILOT-20260927" / "preflight.json"
            )
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "release_id": "REL-ECC-PILOT-20260927",
                        "release_sha": SHA,
                        "reason": "stale_reason",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                bridge.BridgeBlocked, "controller_evidence_not_fresh"
            ):
                bridge.dispatch_release(
                    mode="preflight",
                    packet_path=packet,
                    packet_sha256=digest,
                    repo_root=repo,
                    evidence_root=repo / ".release-evidence",
                    confirm_release_id="",
                )

    def test_execute_timeout_requires_state_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet, digest = self._packet(root)
            repo = self._fake_repo(root)

            with mock.patch.object(
                bridge.subprocess,
                "run",
                side_effect=bridge.subprocess.TimeoutExpired("controller", 1800),
            ):
                with self.assertRaisesRegex(
                    bridge.BridgeBlocked,
                    "controller_timeout_state_reconciliation_required",
                ):
                    bridge.dispatch_release(
                        mode="execute",
                        packet_path=packet,
                        packet_sha256=digest,
                        repo_root=repo,
                        evidence_root=repo / ".release-evidence",
                        confirm_release_id="REL-ECC-PILOT-20260927",
                    )


if __name__ == "__main__":
    unittest.main()
