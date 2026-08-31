from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("release_plane.py")
SPEC = importlib.util.spec_from_file_location("release_plane", MODULE_PATH)
assert SPEC and SPEC.loader
release_plane = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_plane
SPEC.loader.exec_module(release_plane)

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
OLD_IMAGE = "ghcr.io/kamillalmscrm/kamilya-api@sha256:" + "a" * 64
NEW_IMAGE = "ghcr.io/kamillalmscrm/kamilya-api@sha256:" + "b" * 64


def manifest(*, migration: bool = False):
    return release_plane.ReleaseManifest.parse(
        {
            "schema_version": 1,
            "release_id": "REL-20260831-RELEASE-PLANE-001",
            "release_sha": NEW_SHA,
            "image": NEW_IMAGE,
            "previous_release_sha": OLD_SHA,
            "previous_image": OLD_IMAGE,
            "expected_environment": "kz-production",
            "migration": {
                "mode": "exact" if migration else "no-migration",
                "from_revision": "0139" if migration else None,
                "to_revision": "0140" if migration else None,
                "rollback_compatible": migration,
            },
        }
    )


def config(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_slot": "blue",
                "release_sha": OLD_SHA,
                "image": OLD_IMAGE,
            }
        ),
        encoding="utf-8",
    )
    proxy = tmp_path / "upstream.conf"
    proxy.write_text("old-proxy\n", encoding="utf-8")
    return release_plane.HostConfig.parse(
        {
            "schema_version": 1,
            "environment": "kz-production",
            "compose_file": str(tmp_path / "compose.yml"),
            "env_file": str(tmp_path / "runtime.env"),
            "state_file": str(state),
            "evidence_dir": str(tmp_path / "evidence"),
            "lock_file": str(tmp_path / "release.lock"),
            "proxy_upstream_file": str(proxy),
            "proxy_upstream_name": "kamilya_api_active",
            "public_health_url": "https://api.kml.kz/health",
            "slot_ports": {"blue": 18000, "green": 18001},
            "project_prefix": "kamilya",
            "backup_gate": str(tmp_path / "backup-gate"),
            "backup_freshness_seconds": 900,
            "docker_binary": str(tmp_path / "docker"),
            "nginx_binary": str(tmp_path / "nginx"),
            "health_timeout_seconds": 30,
        }
    )


class FakeRunner:
    def __init__(self, *, fail_token: str = "", initial_revision: str = "0139") -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.fail_token = fail_token
        self.initial_revision = initial_revision

    def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
        call = tuple(args)
        self.calls.append((call, dict(env or {})))
        if self.fail_token and self.fail_token in " ".join(call):
            self.fail_token = ""
            raise release_plane.ReleasePlaneError("synthetic_command_failure")
        if " current" in " " + " ".join(call):
            return (
                "0140"
                if any(" upgrade 0140" in " " + " ".join(c[0]) for c in self.calls)
                else self.initial_revision
            )
        if " ps -q " in " ".join(call):
            return "container-id"
        if " inspect " in " ".join(call):
            return f"{NEW_IMAGE}|running|0"
        return ""


class FakeHealth:
    def __init__(self, *, fail_public: bool = False) -> None:
        self.fail_public = fail_public

    def read(self, url: str):
        if self.fail_public and url.startswith("https://"):
            raise release_plane.ReleasePlaneError("synthetic_public_health_failure")
        sha = OLD_SHA if ":18000/" in url else NEW_SHA
        return {"status": "ok", "release_sha": sha, "deployment_environment": "kz-production"}


def test_manifest_rejects_mutable_image_and_unsafe_migration() -> None:
    data = {
        "schema_version": 1,
        "release_id": "REL-20260831-RELEASE-PLANE-001",
        "release_sha": NEW_SHA,
        "image": "ghcr.io/kamillalmscrm/kamilya-api:latest",
        "previous_release_sha": OLD_SHA,
        "previous_image": OLD_IMAGE,
        "expected_environment": "kz-production",
        "migration": {
            "mode": "exact",
            "from_revision": "0139",
            "to_revision": "0140",
            "rollback_compatible": True,
        },
    }
    with pytest.raises(release_plane.ReleasePlaneError, match="immutable"):
        release_plane.ReleaseManifest.parse(data)
    data["image"] = NEW_IMAGE
    data["migration"]["rollback_compatible"] = False
    with pytest.raises(release_plane.ReleasePlaneError, match="rollback_compatibility"):
        release_plane.ReleaseManifest.parse(data)


def test_plan_is_read_only(tmp_path: Path) -> None:
    runner = FakeRunner()
    plane = release_plane.ReleasePlane(manifest(), config(tmp_path), runner, FakeHealth())
    result = plane.plan()
    assert result["status"] == "READY"
    assert result["candidate_slot"] == "green"
    assert result["mutation_attempted"] is False
    assert runner.calls == []


def test_successful_release_switches_slot_and_writes_append_only_evidence(tmp_path: Path) -> None:
    runner = FakeRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    result = plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert result["status"] == "DEPLOYED"
    state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    assert state == {
        "active_slot": "green",
        "image": NEW_IMAGE,
        "release_sha": NEW_SHA,
        "schema_version": 1,
    }
    assert "127.0.0.1:18001" in cfg.proxy_upstream_file.read_text(encoding="utf-8")
    records = (cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["status"] == "DEPLOYED"
    commands = [" ".join(call) for call, _ in runner.calls]
    assert any(" pull " in f" {command} " and NEW_IMAGE in command for command in commands)
    assert not any("backup-gate" in command for command in commands)


def test_exact_migration_runs_backup_before_alembic_upgrade(tmp_path: Path) -> None:
    runner = FakeRunner()
    plane = release_plane.ReleasePlane(manifest(migration=True), config(tmp_path), runner, FakeHealth())
    plane.execute("REL-20260831-RELEASE-PLANE-001")
    commands = [" ".join(call) for call, _ in runner.calls]
    backup_at = next(i for i, command in enumerate(commands) if "backup-gate" in command)
    upgrade_at = next(i for i, command in enumerate(commands) if "alembic api upgrade 0140" in command)
    assert backup_at < upgrade_at
    assert "--expected-revision 0139" in commands[backup_at]
    assert "--freshness-seconds 900" in commands[backup_at]


def test_migration_retry_requires_matching_pre_migration_backup_receipt(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    runner = FakeRunner(initial_revision="0140")
    plane = release_plane.ReleasePlane(manifest(migration=True), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="matching_backup_receipt"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    receipt = cfg.evidence_dir / "migration-receipts" / "REL-20260831-RELEASE-PLANE-001.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(plane._migration_receipt()), encoding="utf-8")
    result = plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert result["status"] == "DEPLOYED"
    commands = [" ".join(call) for call, _ in runner.calls]
    assert not any("backup-gate" in command for command in commands)
    assert not any("upgrade 0140" in command for command in commands)


def test_candidate_failure_before_worker_stop_keeps_current_runtime(tmp_path: Path) -> None:
    runner = FakeRunner(fail_token="up -d --no-deps api")
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="synthetic_command_failure"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    assert state["release_sha"] == OLD_SHA
    assert cfg.proxy_upstream_file.read_text(encoding="utf-8") == "old-proxy\n"
    commands = [" ".join(call) for call, _ in runner.calls]
    assert not any("kamilya-blue" in command and " stop " in f" {command} " for command in commands)
    assert any("kamilya-green" in command and "down --remove-orphans" in command for command in commands)


def test_public_health_failure_restores_proxy_and_old_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter((0.0, 31.0, 62.0, 93.0))
    monkeypatch.setattr(release_plane.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(release_plane.time, "sleep", lambda _seconds: None)
    runner = FakeRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth(fail_public=True))
    with pytest.raises(release_plane.ReleasePlaneError, match="health_identity_timeout"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert cfg.proxy_upstream_file.read_text(encoding="utf-8") == "old-proxy\n"
    assert json.loads(cfg.state_file.read_text(encoding="utf-8"))["release_sha"] == OLD_SHA
    commands = [" ".join(call) for call, _ in runner.calls]
    assert any("kamilya-blue" in command and "up -d --no-deps worker-ai" in command for command in commands)
    assert any("kamilya-green" in command and "down --remove-orphans" in command for command in commands)
    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["status"] == "ROLLED_BACK"
    assert failure["rollback"] == "completed"


def test_previous_identity_and_confirmation_are_fail_closed(tmp_path: Path) -> None:
    runner = FakeRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="confirmation"):
        plane.execute("WRONG")
    state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    state["release_sha"] = "3" * 40
    cfg.state_file.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(release_plane.ReleasePlaneError, match="expected_previous"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert runner.calls == []
