from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.deploy.test_release_runner_bridge import bridge
from scripts.ops import ct137_native_release as release
from scripts.ops.test_ct137_native_release import (
    CURRENT,
    ROLLBACK,
    SHA,
    FakeGithub,
    FakeHost,
    FakePublic,
    FakeRepository,
    _artifact,
)


def _packet(schema: int = 4, *, workbench: bool = True, document: bool = False, correction: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": schema,
        "release_id": "REL-CORRECTION-NATIVE-20261006",
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
    if schema >= 3:
        value["document_draft_enabled"] = document
    if schema == 4:
        value["lesson_correction_enabled"] = correction
    return value


class CorrectionNativeActivationTests(unittest.TestCase):
    def test_schema4_requires_literal_flag_and_workbench_dependency(self) -> None:
        packet = release.ReleasePacket.from_mapping(_packet())
        self.assertIs(packet.lesson_correction_enabled, True)
        with self.assertRaisesRegex(release.ReleaseBlocked, "lesson_correction_requires_workbench"):
            release.ReleasePacket.from_mapping(_packet(workbench=False, correction=True))
        missing = _packet()
        del missing["lesson_correction_enabled"]
        with self.assertRaisesRegex(release.ReleaseBlocked, "release_packet_fields_invalid"):
            release.ReleasePacket.from_mapping(missing)
        for value in ("true", 1, None):
            wrong = _packet()
            wrong["lesson_correction_enabled"] = value
            with self.assertRaisesRegex(release.ReleaseBlocked, "release_packet_lesson_correction_flag_invalid"):
                release.ReleasePacket.from_mapping(wrong)
        duplicate = json.dumps(_packet()).replace(
            '"lesson_correction_enabled": true',
            '"lesson_correction_enabled": true, "lesson_correction_enabled": false',
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "packet.json"
            path.write_text(duplicate, encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(release.ReleaseBlocked, "release_packet_json_invalid"):
                release.load_release_packet(path, digest)

    def test_old_packets_serialize_without_correction_metadata(self) -> None:
        for schema in (1, 2, 3):
            packet = release.ReleasePacket.from_mapping(_packet(schema, workbench=False, correction=False))
            result = packet.to_mapping()
            self.assertNotIn("lesson_correction_enabled", result)

    def test_schema3_build_config_binds_three_flags_and_rejects_bad_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root, product_version="0.11.39")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            config = {
                "schema_version": 3,
                "release_sha": SHA,
                "product_version": "0.11.39",
                "sha256": manifest["sha256"],
                "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
                "workbench_enabled": True,
                "document_draft_enabled": False,
                "lesson_correction_enabled": True,
            }
            (root / "build-config.json").write_text(json.dumps(config), encoding="utf-8")
            artifact = release.inspect_native_artifact(root, SHA)
            self.assertIs(artifact.lesson_correction_enabled, True)
            release._require_artifact_configuration(release.ReleasePacket.from_mapping(_packet()), artifact)
            disabled = dict(config)
            disabled.update(workbench_enabled=False, document_draft_enabled=False, lesson_correction_enabled=False)
            (root / "build-config.json").write_text(json.dumps(disabled), encoding="utf-8")
            disabled_artifact = release.inspect_native_artifact(root, SHA)
            release._require_artifact_configuration(
                release.ReleasePacket.from_mapping(_packet(workbench=False, document=False, correction=False)),
                disabled_artifact,
            )
            for omitted in ("workbench_enabled", "document_draft_enabled", "lesson_correction_enabled"):
                missing = dict(disabled)
                del missing[omitted]
                (root / "build-config.json").write_text(json.dumps(missing), encoding="utf-8")
                with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                    release.inspect_native_artifact(root, SHA)
            duplicate = json.dumps(config).replace(
                '"lesson_correction_enabled": true',
                '"lesson_correction_enabled": true, "lesson_correction_enabled": false',
            )
            (root / "build-config.json").write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                release.inspect_native_artifact(root, SHA)
            for update in ({"lesson_correction_enabled": "true"}, {"sha256": "0" * 64},
                           {"manifest_sha256": "0" * 64}, {"release_sha": "2" * 40},
                           {"product_version": "0.11.40"}, {"schema_version": 2}, {"extra": False}):
                bad = dict(config)
                bad.update(update)
                (root / "build-config.json").write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                    release.inspect_native_artifact(root, SHA)

    def test_old_version_correction_on_is_rejected_before_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root, product_version="0.11.38")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            config = {
                "schema_version": 2, "release_sha": SHA, "product_version": "0.11.38",
                "sha256": manifest["sha256"],
                "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
                "workbench_enabled": True, "document_draft_enabled": False,
                "lesson_correction_enabled": True,
            }
            (root / "build-config.json").write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
                release.inspect_native_artifact(root, SHA)

    def test_packet_artifact_mismatch_stops_before_host_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root, product_version="0.11.39")
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            (root / "build-config.json").write_text(json.dumps({
                "schema_version": 3, "release_sha": SHA, "product_version": "0.11.39",
                "sha256": manifest["sha256"],
                "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
                "workbench_enabled": True, "document_draft_enabled": False,
                "lesson_correction_enabled": True,
            }), encoding="utf-8")
            host = FakeHost()
            orchestrator = release.NativeReleaseOrchestrator(repository=FakeRepository(), github=FakeGithub(), host=host, public=FakePublic())
            packet = release.ReleasePacket.from_mapping(_packet(correction=False))
            with self.assertRaisesRegex(release.ReleaseBlocked, "artifact_lesson_correction_configuration_mismatch"):
                orchestrator.execute(packet, root)
            self.assertEqual(host.calls, [])

    def test_schema4_blocked_controller_receipt_preserves_all_flags(self) -> None:
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
            self.assertEqual(
                {key: technical[key] for key in ("workbench_enabled", "document_draft_enabled", "lesson_correction_enabled")},
                {"workbench_enabled": True, "document_draft_enabled": False, "lesson_correction_enabled": True},
            )
            bridge._bind_technical_evidence(
                {"schema_version": 4, "release_id": packet.release_id, "release_sha": packet.exact_sha,
                 "workbench_enabled": True, "document_draft_enabled": False, "lesson_correction_enabled": True},
                technical,
            )

    def test_bridge_schema4_requires_explicit_matching_correction(self) -> None:
        plan = {"schema_version": 4, "release_id": "REL-CORRECTION-NATIVE-20261006", "release_sha": SHA,
                "workbench_enabled": True, "document_draft_enabled": False, "lesson_correction_enabled": True}
        original = dict(plan)
        original.pop("schema_version")
        bridge._bind_technical_evidence(plan, original)
        for value in (None, "true", 1, False):
            technical = dict(original)
            if value is None:
                del technical["lesson_correction_enabled"]
            else:
                technical["lesson_correction_enabled"] = value
            with self.assertRaises(bridge.BridgeBlocked):
                bridge._bind_technical_evidence(plan, technical)

    def test_bridge_schema4_requires_all_three_flags_even_when_false(self) -> None:
        plan = {"schema_version": 4, "release_id": "REL-CORRECTION-NATIVE-20261006", "release_sha": SHA,
                "workbench_enabled": False, "document_draft_enabled": False, "lesson_correction_enabled": False}
        for omitted in ("workbench_enabled", "document_draft_enabled", "lesson_correction_enabled"):
            technical = {"release_id": plan["release_id"], "release_sha": SHA,
                         "workbench_enabled": False, "document_draft_enabled": False,
                         "lesson_correction_enabled": False}
            del technical[omitted]
            with self.assertRaises(bridge.BridgeBlocked):
                bridge._bind_technical_evidence(plan, technical)
        bridge._bind_technical_evidence(
            plan,
            {"release_id": plan["release_id"], "release_sha": SHA,
             "workbench_enabled": False, "document_draft_enabled": False,
             "lesson_correction_enabled": False},
        )

    def test_helper_manifest_remains_eight_field_contract(self) -> None:
        helper = (Path(__file__).resolve().parents[2] / "infra" / "deploy" / "kamilya-web-deploy.py").read_text(encoding="utf-8")
        self.assertIn('"release_sha", "product_version", "node_version", "platform", "arch", "libc", "api_url", "sha256"', helper)

    def test_workflow_guard_enforces_correction_version_dependency_and_literals(self) -> None:
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build-native-frontend.yml").read_text(encoding="utf-8")
        scripts = re.findall(r"node -e '\\''(.*?)'\\''", workflow)
        guard = next(value for value in scripts if "lesson_correction_activation_requires_39" in value)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for version, workbench, document, correction, accepted in (
                ("0.11.39", "true", "false", "true", True),
                ("0.11.39", "true", "false", "false", True),
                ("0.11.39", "false", "false", "true", False),
                ("0.11.39", "true", "true", "true", True),
                ("0.11.38", "true", "false", "true", False),
                ("0.11.39", "true", "false", "1", False),
            ):
                (directory / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
                env = {**os.environ,
                       "NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED": workbench,
                       "NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED": document,
                       "NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED": correction}
                result = subprocess.run(["node", "-e", guard], cwd=directory, env=env, capture_output=True, check=False)
                self.assertEqual(result.returncode == 0, accepted, (version, workbench, document, correction))

    def test_workflow_metadata_producer_emits_schema3_and_schema2_without_manifest_drift(self) -> None:
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build-native-frontend.yml").read_text(encoding="utf-8")
        scripts = re.findall(r"node -e '\\''(.*?)'\\''", workflow)
        producer = next(value for value in scripts if "manifest_sha256" in value and "build-config.json" in value)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "bundle.sha256").write_text("a" * 64 + "  bundle.tar.gz\n", encoding="utf-8")
            env = {**os.environ, "RELEASE_SHA": SHA, "NEXT_PUBLIC_API_URL": "https://api.kml.kz/api"}
            for version, document, correction, expected_schema in (
                ("0.11.39", "false", "true", 3),
                ("0.11.38", "false", "false", 2),
            ):
                (directory / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
                run_env = {**env,
                           "NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED": "true",
                           "NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED": document,
                           "NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED": correction}
                mocked_require = "const M=require('module');const L=M._load;M._load=(r,p,m)=>r==='/build/package.json'?require(process.cwd()+'/package.json'):L(r,p,m);"
                result = subprocess.run(["node", "-e", mocked_require + producer], cwd=directory, env=run_env, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(set(manifest), {"release_sha", "product_version", "node_version", "platform", "arch", "libc", "api_url", "sha256"})
                config = json.loads((directory / "build-config.json").read_text(encoding="utf-8"))
                self.assertEqual(config["schema_version"], expected_schema)
                self.assertIs(type(config["workbench_enabled"]), bool)
                self.assertIs(type(config["document_draft_enabled"]), bool)
                if expected_schema == 3:
                    self.assertIs(type(config["lesson_correction_enabled"]), bool)
                else:
                    self.assertNotIn("lesson_correction_enabled", config)


if __name__ == "__main__":
    unittest.main()
