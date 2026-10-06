from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ops import ct137_native_release as release
from scripts.ops.test_ct137_native_release import (
    CURRENT, ROLLBACK, SHA, FakeGithub, FakeHost, FakePublic, FakeRepository, _artifact,
)
from scripts.deploy.test_release_runner_bridge import bridge


def _packet(schema: int = 3, *, workbench: bool = True, document: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": schema,
        "release_id": "REL-DOCUMENT-NATIVE-20261005",
        "exact_sha": SHA,
        "source_branch": "master",
        "target_environment": "kz-production",
        "target_services": ["ct137-frontend"],
        "ci_run_id": 1001,
        "native_build_run_id": 1002,
        "expected_current_release": CURRENT,
        "rollback_sha": ROLLBACK,
        "migration_scope": "none",
        "owner_approval": "synthetic packet contract",
        "smoke_scope": ["/healthz", "/login", "api-health"],
    }
    if schema >= 2:
        value["workbench_enabled"] = workbench
    if schema == 3:
        value["document_draft_enabled"] = document
    return value


class DocumentNativeActivationTests(unittest.TestCase):
    def test_schema3_blocked_main_receipt_preserves_both_flags_for_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet = release.ReleasePacket.from_mapping(_packet())

            class FakeProbe:
                environment = {}

                def download(self, _packet, _destination):
                    return root

            class BlockedOrchestrator:
                def __init__(self, **_kwargs):
                    pass

                def preflight(self, _packet, _artifact_dir):
                    raise release.ReleaseBlocked("insufficient_ct137_capacity")

            original_loader = release.load_release_packet
            original_probe = release.GithubActionsProbe
            original_orchestrator = release.NativeReleaseOrchestrator
            original_root = release.REPO_ROOT
            evidence = root / "blocked.json"
            try:
                release.load_release_packet = lambda *_args: packet
                release.GithubActionsProbe = FakeProbe
                release.NativeReleaseOrchestrator = BlockedOrchestrator
                release.REPO_ROOT = root
                with self.assertRaisesRegex(release.ReleaseBlocked, "insufficient_ct137_capacity"):
                    release.main(["preflight", "--packet", str(root / "packet.json"), "--packet-sha256", "0" * 64, "--evidence", str(evidence)])
            finally:
                release.load_release_packet = original_loader
                release.GithubActionsProbe = original_probe
                release.NativeReleaseOrchestrator = original_orchestrator
                release.REPO_ROOT = original_root

            technical = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(technical["status"], "BLOCKED")
            self.assertEqual(technical["reason"], "insufficient_ct137_capacity")
            self.assertIs(technical["workbench_enabled"], True)
            self.assertIs(technical["document_draft_enabled"], True)
            bridge._bind_technical_evidence(
                {"schema_version": 3, "release_id": packet.release_id, "release_sha": packet.exact_sha,
                 "workbench_enabled": True, "document_draft_enabled": True}, technical,
            )
            handoff = bridge.compact_handoff(technical=technical, acceptance=None)
            self.assertEqual(handoff["blockers"], "insufficient_ct137_capacity")

    def test_schema3_requires_document_flag_and_workbench(self) -> None:
        packet = release.ReleasePacket.from_mapping(_packet())
        self.assertTrue(packet.workbench_enabled)
        self.assertTrue(packet.document_draft_enabled)
        with self.assertRaisesRegex(release.ReleaseBlocked, "document_draft_requires_workbench"):
            release.ReleasePacket.from_mapping(_packet(workbench=False, document=True))
        missing = _packet()
        del missing["document_draft_enabled"]
        with self.assertRaisesRegex(release.ReleaseBlocked, "release_packet_fields_invalid"):
            release.ReleasePacket.from_mapping(missing)
        wrong = _packet()
        wrong["document_draft_enabled"] = "true"
        with self.assertRaisesRegex(release.ReleaseBlocked, "release_packet_document_draft_flag_invalid"):
            release.ReleasePacket.from_mapping(wrong)
        schema2 = _packet(2, workbench=True, document=False)
        schema2["document_draft_enabled"] = False
        with self.assertRaisesRegex(release.ReleaseBlocked, "release_packet_fields_invalid"):
            release.ReleasePacket.from_mapping(schema2)

    def test_schema1_and_schema2_serialize_without_document_metadata(self) -> None:
        for schema in (1, 2):
            packet = release.ReleasePacket.from_mapping(_packet(schema, workbench=False, document=False))
            result = packet.to_mapping()
            self.assertNotIn("document_draft_enabled", result)
            if schema == 1:
                self.assertNotIn("workbench_enabled", result)

    def test_schema3_artifact_config_is_typed_and_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root, product_version="0.11.38")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            import hashlib

            manifest_digest = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
            config = {
                "schema_version": 2,
                "release_sha": SHA,
                "product_version": "0.11.38",
                "sha256": manifest["sha256"],
                "manifest_sha256": manifest_digest,
                "workbench_enabled": True,
                "document_draft_enabled": True,
            }
            (root / "build-config.json").write_text(json.dumps(config), encoding="utf-8")
            artifact = release.inspect_native_artifact(root, SHA)
            self.assertIs(artifact.document_draft_enabled, True)
            release._require_artifact_configuration(
                release.ReleasePacket.from_mapping(_packet()), artifact
            )

            for update in (
                {"document_draft_enabled": "true"},
                {"document_draft_enabled": 1},
                {"extra": False},
            ):
                bad = dict(config)
                bad.update(update)
                (root / "build-config.json").write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                    release.inspect_native_artifact(root, SHA)

            duplicate = json.dumps(config).replace('"document_draft_enabled": true', '"document_draft_enabled": true, "document_draft_enabled": false')
            (root / "build-config.json").write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                release.inspect_native_artifact(root, SHA)

    def test_old_version_document_on_and_packet_artifact_mismatch_fail_before_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root, product_version="0.11.37")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            import hashlib
            (root / "build-config.json").write_text(json.dumps({
                "schema_version": 1, "release_sha": SHA, "product_version": "0.11.37",
                "sha256": manifest["sha256"],
                "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
                "workbench_enabled": True, "document_draft_enabled": True,
            }), encoding="utf-8")
            with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                release.inspect_native_artifact(root, SHA)

    def test_workflow_validation_executable_rejects_false_workbench(self) -> None:
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build-native-frontend.yml").read_text()
        scripts = re.findall(r"node -e '\\''(.*?)'\\''", workflow)
        guard = next(value for value in scripts if "document_draft_activation_requires_38" in value)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for version, workbench, document, accepted in (
                ("0.11.38", "false", "false", True),
                ("0.11.38", "false", "true", False),
                ("0.11.38", "true", "true", True),
                ("0.11.37", "true", "true", False),
                ("0.11.38", "true", "1", False),
            ):
                (directory / "package.json").write_text(json.dumps({"version": version}))
                env = {**os.environ, "NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED": workbench,
                       "NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED": document,
                       "NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED": "false"}
                result = subprocess.run(["node", "-e", guard], cwd=directory, env=env,
                                        capture_output=True, check=False)
                self.assertEqual(result.returncode == 0, accepted, (version, workbench, document))

    def test_document_mismatch_stops_before_any_host_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root, product_version="0.11.38")
            manifest = json.loads((root / "manifest.json").read_text())
            import hashlib
            config = {"schema_version": 2, "release_sha": SHA, "product_version": "0.11.38",
                      "sha256": manifest["sha256"],
                      "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
                      "workbench_enabled": True, "document_draft_enabled": True}
            (root / "build-config.json").write_text(json.dumps(config))
            for schema in (2, 3):
                host = FakeHost()
                orchestrator = release.NativeReleaseOrchestrator(repository=FakeRepository(),
                    github=FakeGithub(), host=host, public=FakePublic())
                packet = release.ReleasePacket.from_mapping(_packet(schema, document=False))
                with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_document_draft_configuration_mismatch"):
                    orchestrator.execute(packet, root)
                self.assertEqual(host.calls, [])

    def test_bridge_schema3_requires_explicit_typed_matching_both_flags(self) -> None:
        plan = {"schema_version": 3, "release_id": "REL-DOCUMENT-NATIVE-20261005",
                "release_sha": SHA, "workbench_enabled": False, "document_draft_enabled": False}
        original = {"release_id": plan["release_id"], "release_sha": SHA,
                    "workbench_enabled": False, "document_draft_enabled": False}
        bridge._bind_technical_evidence(plan, original)
        for key in ("workbench_enabled", "document_draft_enabled"):
            for value in (None, "false", 0, True):
                technical = dict(original)
                if value is None:
                    del technical[key]
                else:
                    technical[key] = value
                with self.assertRaises(bridge.BridgeBlocked):
                    bridge._bind_technical_evidence(plan, technical)

    def test_workflow_has_document_input_and_keeps_eight_field_manifest(self) -> None:
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build-native-frontend.yml").read_text()
        helper = (Path(__file__).resolve().parents[2] / "infra" / "deploy" / "kamilya-web-deploy.py").read_text()
        self.assertIn("document_draft_enabled:", workflow)
        self.assertIn("NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED", workflow)
        self.assertIn('schema_version:correctionSchema?3:documentSchema?2:1', workflow)
        self.assertIn('"release_sha", "product_version", "node_version", "platform", "arch", "libc", "api_url", "sha256"', helper)


if __name__ == "__main__":
    unittest.main()
