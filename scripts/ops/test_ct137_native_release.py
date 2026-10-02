from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.ops import ct137_native_release as release


SHA = "1" * 40
CURRENT = "2" * 40
ROLLBACK = "3" * 40


def _artifact(root: Path, *, release_sha: str = SHA, product_version: str = "0.11.1") -> Path:
    archive = root / f"frontend-native-{release_sha}.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for directory in (".next", "node_modules", "public"):
            member = tarfile.TarInfo(directory)
            member.type = tarfile.DIRTYPE
            output.addfile(member)
        files = {
            ".next/BUILD_ID": release_sha.encode("ascii"),
            "package.json": json.dumps({"name": "web", "version": product_version}).encode("utf-8"),
            "next.config.js": b"module.exports = {}",
            "security-headers.js": b"module.exports = {}",
        }
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            output.addfile(member, io.BytesIO(content))
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (root / "bundle.sha256").write_text(
        f"{archive_digest}  {archive.name}\n", encoding="ascii"
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "release_sha": release_sha,
                "product_version": product_version,
                "node_version": "v20.20.2",
                "platform": "linux",
                "arch": "x64",
                "libc": "musl",
                "api_url": "https://api.kml.kz/api",
                "sha256": archive_digest,
            }
        ),
        encoding="utf-8",
    )
    return archive


def _packet() -> release.ReleasePacket:
    return release.ReleasePacket.from_mapping(
        {
            "schema_version": 1,
            "release_id": "REL-WEB-NATIVE-20260924",
            "exact_sha": SHA,
            "source_branch": "master",
            "target_environment": "kz-production",
            "target_services": ["ct137-frontend"],
            "ci_run_id": 1001,
            "native_build_run_id": 1002,
            "expected_current_release": CURRENT,
            "rollback_sha": ROLLBACK,
            "migration_scope": "none",
            "owner_approval": "current task: improve native deployment",
            "smoke_scope": ["/healthz", "/login", "api-health"],
        }
    )


class FakeRepository:
    def verify(
        self, packet: release.ReleasePacket, product_version: str
    ) -> dict[str, str]:
        return {
            "remote_branch_sha": packet.exact_sha,
            "tag": f"v{product_version}",
            "tag_sha": packet.exact_sha,
        }


class FakeGithub:
    def verify(self, packet: release.ReleasePacket) -> dict[str, object]:
        return {
            "ci_run_id": packet.ci_run_id,
            "native_build_run_id": packet.native_build_run_id,
            "ci_conclusion": "success",
            "native_build_conclusion": "success",
        }


class FakeHost:
    def __init__(
        self, *, free_kib: int = 2_000_000, inventory_free_kib: int | None = None
    ) -> None:
        self.free_kib = free_kib
        self.inventory_free_kib = (
            free_kib if inventory_free_kib is None else inventory_free_kib
        )
        self.calls: list[tuple[object, ...]] = []
        self.current = CURRENT

    def status(self) -> dict[str, object]:
        self.calls.append(("status",))
        return {
            "current_sha": self.current,
            "marker_sha": self.current,
            "nginx_sha_occurrences": 2,
            "kamilya_web_running": True,
        }

    def boundary(self, rollback_sha: str) -> dict[str, object]:
        self.calls.append(("boundary", rollback_sha))
        return {
            "boundary": "PASS",
            "free_kib": self.free_kib,
            "rollback_sha": rollback_sha,
            "rollback_present": True,
        }

    def inventory(self) -> dict[str, object]:
        self.calls.append(("inventory",))
        return {
            "releases": [self.current, ROLLBACK],
            "staged": [],
            "free_kib": self.inventory_free_kib,
        }

    def stage(self, path: Path, digest: str) -> None:
        self.calls.append(("stage", path.name, digest))

    def deploy(self, release_sha: str, previous_sha: str, archive_digest: str) -> None:
        self.calls.append(("deploy", release_sha, previous_sha, archive_digest))
        self.current = release_sha


class FakePublic:
    def verify(self, release_sha: str) -> dict[str, object]:
        return {
            "release_sha": release_sha,
            "healthz": 200,
            "login": 200,
            "api_health": 200,
        }


class ArtifactTests(unittest.TestCase):
    def test_inspection_binds_sha_digest_runtime_and_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = _artifact(root)

            artifact = release.inspect_native_artifact(root, SHA)

            self.assertEqual(artifact.archive, archive)
            self.assertEqual(artifact.release_sha, SHA)
            self.assertEqual(artifact.product_version, "0.11.1")
            self.assertGreater(artifact.expanded_bytes, 0)
            self.assertEqual(
                release.required_capacity_bytes(artifact),
                2 * archive.stat().st_size
                + artifact.manifest.stat().st_size
                + artifact.expanded_bytes
                + release.MINIMUM_RESERVE_BYTES,
            )

    def test_inspection_rejects_manifest_or_checksum_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root)
            payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            payload["api_url"] = "https://example.invalid/api"
            (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                release.ReleaseBlocked, "artifact_api_url_mismatch"
            ):
                release.inspect_native_artifact(root, SHA)


class PacketTests(unittest.TestCase):
    def test_packet_rejects_non_frontend_scope_and_missing_authority(self) -> None:
        raw = _packet().to_mapping()
        raw["target_services"] = ["ct137-frontend", "vm126-api"]
        raw["owner_approval"] = ""

        with self.assertRaises(release.ReleaseBlocked):
            release.ReleasePacket.from_mapping(raw)

    def test_packet_file_requires_exact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release-packet.json"
            content = (
                json.dumps(_packet().to_mapping(), sort_keys=True) + "\n"
            ).encode("utf-8")
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()

            self.assertEqual(release.load_release_packet(path, digest), _packet())
            with self.assertRaisesRegex(
                release.ReleaseBlocked, "release_packet_digest_mismatch"
            ):
                release.load_release_packet(path, "0" * 64)


class ParserTests(unittest.TestCase):
    def test_host_status_and_boundary_parsers_reject_ambiguous_output(self) -> None:
        status = release.parse_host_status(
            '{"current_sha":"'
            + CURRENT
            + '","marker_sha":"'
            + CURRENT
            + '","nginx_sha_occurrences":2,"kamilya_web_running":true}\n'
            + '{"exit_code":0,"stderr_bytes":0}\n'
        )
        self.assertEqual(status["current_sha"], CURRENT)
        boundary = release.parse_boundary(
            "BOUNDARY_PASS restricted_helper_only\n"
            "NODE_VERSION=v24.18.1\n"
            "FREE_KB=2048000\n"
            "ROLLBACK_RELEASE_PRESENT\n"
            '{"boundary_exit":0,"stderr_bytes":0}\n',
            ROLLBACK,
        )
        self.assertEqual(boundary["free_kib"], 2_048_000)
        self.assertEqual(boundary["rollback_sha"], ROLLBACK)
        with self.assertRaises(release.ReleaseBlocked):
            release.parse_host_status(
                '{"current_sha":"'
                + CURRENT
                + '","marker_sha":"'
                + CURRENT
                + '","nginx_sha_occurrences":2,"kamilya_web_running":true}\n'
                + '{"current_sha":"'
                + CURRENT
                + '","marker_sha":"'
                + CURRENT
                + '","nginx_sha_occurrences":2,"kamilya_web_running":true}\n'
            )

    def test_inventory_parser_returns_only_exact_release_and_staged_rows(self) -> None:
        inventory = release.parse_inventory(
            "RELEASE " + CURRENT + "\n"
            "RELEASE " + ROLLBACK + "\n"
            "STAGED frontend-native-" + CURRENT + ".tar.gz 123\n"
            "FREE_KB=900000\n"
            '{"inventory_exit":0,"stderr_bytes":0}\n'
        )
        self.assertEqual(inventory["releases"], [CURRENT, ROLLBACK])
        self.assertEqual(inventory["free_kib"], 900_000)
        self.assertEqual(inventory["staged"][0]["bytes"], 123)
        with self.assertRaises(release.ReleaseBlocked):
            release.parse_inventory(
                "RELEASE ../escape\nFREE_KB=1\n"
                '{"inventory_exit":0,"stderr_bytes":0}\n'
            )


class GithubActionsTests(unittest.TestCase):
    def test_native_build_accepts_dev_for_exact_sha_but_ci_does_not(self) -> None:
        probe = release.GithubActionsProbe.__new__(release.GithubActionsProbe)
        probe._api = lambda endpoint: {
            "name": release.NATIVE_BUILD_WORKFLOW,
            "head_sha": SHA,
            "head_branch": "dev",
            "status": "completed",
            "conclusion": "success",
        }

        result = probe._run_identity(
            1002,
            release.NATIVE_BUILD_WORKFLOW,
            SHA,
            ("master", "dev"),
        )

        self.assertEqual(result["head_branch"], "dev")
        with self.assertRaisesRegex(
            release.ReleaseBlocked, "github_run_identity_mismatch"
        ):
            probe._run_identity(1002, release.NATIVE_BUILD_WORKFLOW, SHA, ("master",))


class OrchestrationTests(unittest.TestCase):
    def test_preflight_stops_before_staging_when_capacity_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root)
            host = FakeHost(free_kib=1)
            orchestrator = release.NativeReleaseOrchestrator(
                repository=FakeRepository(),
                github=FakeGithub(),
                host=host,
                public=FakePublic(),
            )

            with self.assertRaisesRegex(
                release.ReleaseBlocked, "insufficient_ct137_capacity"
            ):
                orchestrator.preflight(_packet(), root)

            self.assertFalse(any(call[0] in {"stage", "deploy"} for call in host.calls))

    def test_preflight_uses_lower_of_two_capacity_readbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root)
            host = FakeHost(free_kib=2_000_000, inventory_free_kib=1_999_996)
            orchestrator = release.NativeReleaseOrchestrator(
                repository=FakeRepository(),
                github=FakeGithub(),
                host=host,
                public=FakePublic(),
            )

            result = orchestrator.preflight(_packet(), root)

            self.assertEqual(result["host"]["conservative_free_kib"], 1_999_996)

    def test_execute_rechecks_preflight_stages_exact_pair_and_reads_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root)
            host = FakeHost()
            orchestrator = release.NativeReleaseOrchestrator(
                repository=FakeRepository(),
                github=FakeGithub(),
                host=host,
                public=FakePublic(),
            )

            result = orchestrator.execute(_packet(), root)

            stages = [call for call in host.calls if call[0] == "stage"]
            self.assertEqual(
                [stage[1] for stage in stages],
                [
                    f"frontend-native-{SHA}.tar.gz",
                    f"frontend-native-{SHA}.manifest.json",
                ],
            )
            self.assertEqual(sum(call[0] == "deploy" for call in host.calls), 1)
            self.assertEqual(sum(call[0] == "inventory" for call in host.calls), 2)
            self.assertEqual(result["status"], "RELEASE_OK")
            self.assertEqual(result["release_sha"], SHA)
            self.assertEqual(result["previous_release_sha"], CURRENT)
            self.assertEqual(result["technical_readback"]["release_sha"], SHA)
            self.assertEqual(
                result["host_inventory_readback"]["releases"], [SHA, ROLLBACK]
            )
            self.assertEqual(
                result["product_acceptance"], "SEPARATE_TEST_RUNNER_REQUIRED"
            )

    def test_execute_blocks_when_post_deploy_inventory_loses_rollback(self) -> None:
        class MissingRollbackAfterDeploy(FakeHost):
            def inventory(self) -> dict[str, object]:
                inventory = super().inventory()
                if self.current == SHA:
                    inventory["releases"] = [SHA]
                return inventory

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _artifact(root)
            orchestrator = release.NativeReleaseOrchestrator(
                repository=FakeRepository(),
                github=FakeGithub(),
                host=MissingRollbackAfterDeploy(),
                public=FakePublic(),
            )

            with self.assertRaisesRegex(
                release.ReleaseBlocked, "ct137_post_deploy_inventory_mismatch"
            ):
                orchestrator.execute(_packet(), root)


def test_native_workflow_defaults_off_and_attests_exact_build_flag() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/build-native-frontend.yml"
    source = workflow.read_text(encoding="utf-8")
    assert "default: false" in source
    assert '--env NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED="${WORKBENCH_ENABLED}"' in source
    assert 'workbench_enabled:flag==="true"' in source
    assert "workbench_activation_requires_28" in source
    assert source.index("workbench_activation_requires_28") < source.index("pnpm run build")
    assert '"build-config.json"' in source
    assert "manifest_sha256" in source


def test_failed_immutable26_is_rejected_without_manifest_rewrite(tmp_path) -> None:
    _artifact(tmp_path, product_version="0.11.26")
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["workbench_enabled"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_sidecar_invalid:sidecar_fields_invalid"):
        release.inspect_native_artifact(tmp_path, SHA)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_artifact_inspection_rejects_sidecar_fields_before_host_staging(tmp_path) -> None:
    _artifact(tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown_deployment_switch"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(
        release.ReleaseBlocked, "artifact_sidecar_invalid:sidecar_fields_invalid"
    ):
        release.inspect_native_artifact(tmp_path, SHA)


def _build_config(root: Path) -> Path:
    manifest = root / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    path = root / "build-config.json"
    path.write_text(json.dumps({
        "schema_version": 1, "release_sha": payload["release_sha"],
        "product_version": payload["product_version"], "sha256": payload["sha256"],
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "workbench_enabled": False,
    }), encoding="utf-8")
    return path


def test_compatibility27_uses_unchanged_host_manifest_and_bound_config(tmp_path) -> None:
    _artifact(tmp_path, product_version="0.11.27")
    path = _build_config(tmp_path)
    artifact = release.inspect_native_artifact(tmp_path, SHA)
    assert artifact.build_config_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "workbench_enabled" not in json.loads(artifact.manifest.read_text(encoding="utf-8"))


def test_compatibility27_config_fails_closed_before_staging(tmp_path) -> None:
    _artifact(tmp_path, product_version="0.11.27")
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
        release.inspect_native_artifact(tmp_path, SHA)
    path = _build_config(tmp_path)
    original = json.loads(path.read_text(encoding="utf-8"))
    for key, value in (
        ("schema_version", True), ("release_sha", CURRENT), ("product_version", "0.11.28"),
        ("sha256", "0" * 64), ("manifest_sha256", "0" * 64),
        ("workbench_enabled", True), ("workbench_enabled", 0), ("workbench_enabled", "false"),
        ("unknown", False),
    ):
        path.write_text(json.dumps({**original, key: value}), encoding="utf-8")
        with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
            release.inspect_native_artifact(tmp_path, SHA)
    path.write_text("[]", encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
        release.inspect_native_artifact(tmp_path, SHA)


def test_build_config_rejects_duplicate_json_keys(tmp_path) -> None:
    _artifact(tmp_path, product_version="0.11.27")
    path = _build_config(tmp_path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text[:-1] + ', "workbench_enabled": false}', encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
        release.inspect_native_artifact(tmp_path, SHA)


def test_execute_rechecks_config_after_preflight_without_staging(tmp_path) -> None:
    _artifact(tmp_path, product_version="0.11.27")
    path = _build_config(tmp_path)

    class MutatingHost(FakeHost):
        def boundary(self, rollback_sha: str) -> dict[str, object]:
            result = super().boundary(rollback_sha)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["workbench_enabled"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            return result

    host = MutatingHost()
    orchestrator = release.NativeReleaseOrchestrator(
        repository=FakeRepository(), github=FakeGithub(), host=host, public=FakePublic(),
    )
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
        orchestrator.execute(_packet(), tmp_path)
    assert not any(call[0] in ("stage", "deploy") for call in host.calls)


def test_download_never_trusts_nonempty_local_artifact_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    cache = tmp_path / "native-build"
    cache.mkdir()
    original = cache / "manifest.json"
    original.write_text("untrusted", encoding="utf-8")
    destinations = []

    def download(command, **kwargs):
        destination = Path(command[-1])
        assert destination.parent == cache
        assert not any(destination.iterdir())
        destinations.append(destination)
        (destination / "manifest.json").write_text("downloaded", encoding="utf-8")
        return ""

    monkeypatch.setattr(release, "_run", download)
    probe = object.__new__(release.GithubActionsProbe)
    probe.environment = {}
    assert probe.download(_packet(), cache) == destinations[0]
    assert probe.download(_packet(), cache) == destinations[1]
    assert destinations[0] != destinations[1]
    assert original.read_text(encoding="utf-8") == "untrusted"


def test_command_timeout_becomes_sanitized_release_block(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"synthetic-private-output", stderr=b"synthetic-private-error")

    monkeypatch.setattr(release.subprocess, "run", timeout)
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, r"^command_timeout:gh:seconds_300$") as caught:
        release._run(["gh", "run", "download", "opaque-id"])
    assert "synthetic-private" not in str(caught.exception)


def test_artifact_download_has_separate_bounded_timeout(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(release, "_run", lambda command, **kwargs: calls.append((command, kwargs)) or "")
    probe = object.__new__(release.GithubActionsProbe)
    probe.environment = {}
    destination = probe.download(_packet(), tmp_path / "native-build")
    assert destination.is_dir() and destination.parent == tmp_path / "native-build"
    assert calls[0][1]["timeout"] == 1200
    assert calls[0][0][:3] == ["gh", "run", "download"]


def test_cli_timeout_preserves_bounded_blocked_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(release, "load_release_packet", lambda *args: _packet())
    probe = object.__new__(release.GithubActionsProbe)
    probe.environment = {}
    monkeypatch.setattr(release, "GithubActionsProbe", lambda: probe)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(release.subprocess, "run", timeout)
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    evidence = tmp_path / "blocked.json"
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "command_timeout:gh"):
        release.main(["preflight", "--packet", str(tmp_path / "packet.json"), "--packet-sha256", "0" * 64, "--evidence", str(evidence)])
    result = json.loads(evidence.read_text())
    assert result["status"] == "BLOCKED" and result["mode"] == "preflight"
    assert result["reason"] == "command_timeout:gh:seconds_1200"
    assert result["release_sha"] == SHA and result["state_reconciliation_required"] is False


@unittest.skipUnless(os.name != "nt", "requires Unix symlink semantics")
def test_build_config_symlink_is_not_accepted(tmp_path) -> None:
    _artifact(tmp_path, product_version="0.11.27")
    path = _build_config(tmp_path)
    renamed = tmp_path / "alternate.json"
    path.rename(renamed)
    path.symlink_to(renamed)
    with unittest.TestCase().assertRaisesRegex(release.ReleaseBlocked, "artifact_build_config_invalid"):
        release.inspect_native_artifact(tmp_path, SHA)


if __name__ == "__main__":
    unittest.main(verbosity=2)
