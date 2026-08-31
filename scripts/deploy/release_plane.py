#!/usr/bin/env python3
"""Fail-closed two-slot release controller for Kamilya KZ production.

The controller is installed once on VM126. A release supplies only a strict,
non-executable JSON manifest. Commands, paths and topology come from the
root-owned host configuration, never from a release artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_IMAGE_RE = re.compile(
    r"^ghcr\.io/kamillalmscrm/kamilya-api@sha256:[0-9a-f]{64}$"
)
RELEASE_ID_RE = re.compile(r"^REL-[A-Z0-9][A-Z0-9-]{7,95}$")
REVISION_RE = re.compile(r"^[0-9]{4}$")
TOKEN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$")
SLOTS = ("blue", "green")
SERVICES = ("api", "worker-ai", "worker-documents", "worker-ops")
WORKERS = SERVICES[1:]


class ReleasePlaneError(RuntimeError):
    """Sanitized, operator-safe release failure."""


def _exact_keys(data: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(data)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ReleasePlaneError(f"{label}_keys_invalid:missing={missing}:extra={extra}")


def _absolute(path: str, label: str) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise ReleasePlaneError(f"{label}_must_be_absolute")
    return value


@dataclass(frozen=True)
class Migration:
    mode: str
    from_revision: str | None
    to_revision: str | None
    rollback_compatible: bool

    @classmethod
    def parse(cls, data: Any) -> Migration:
        if not isinstance(data, dict):
            raise ReleasePlaneError("migration_must_be_object")
        _exact_keys(
            data,
            {"mode", "from_revision", "to_revision", "rollback_compatible"},
            "migration",
        )
        migration = cls(
            mode=data["mode"],
            from_revision=data["from_revision"],
            to_revision=data["to_revision"],
            rollback_compatible=data["rollback_compatible"],
        )
        if migration.mode == "no-migration":
            if (
                migration.from_revision is not None
                or migration.to_revision is not None
                or migration.rollback_compatible is not False
            ):
                raise ReleasePlaneError("no_migration_contract_invalid")
            return migration
        if migration.mode != "exact":
            raise ReleasePlaneError("migration_mode_invalid")
        if not isinstance(migration.rollback_compatible, bool) or not migration.rollback_compatible:
            raise ReleasePlaneError("migration_requires_explicit_rollback_compatibility")
        if not isinstance(migration.from_revision, str) or not REVISION_RE.fullmatch(
            migration.from_revision
        ):
            raise ReleasePlaneError("migration_from_revision_invalid")
        if not isinstance(migration.to_revision, str) or not REVISION_RE.fullmatch(
            migration.to_revision
        ):
            raise ReleasePlaneError("migration_to_revision_invalid")
        if migration.from_revision == migration.to_revision:
            raise ReleasePlaneError("migration_revisions_must_differ")
        return migration


@dataclass(frozen=True)
class ReleaseManifest:
    schema_version: int
    release_id: str
    release_sha: str
    image: str
    previous_release_sha: str
    previous_image: str
    expected_environment: str
    migration: Migration

    @classmethod
    def parse(cls, data: Any) -> ReleaseManifest:
        if not isinstance(data, dict):
            raise ReleasePlaneError("manifest_must_be_object")
        _exact_keys(
            data,
            {
                "schema_version",
                "release_id",
                "release_sha",
                "image",
                "previous_release_sha",
                "previous_image",
                "expected_environment",
                "migration",
            },
            "manifest",
        )
        manifest = cls(
            schema_version=data["schema_version"],
            release_id=data["release_id"],
            release_sha=data["release_sha"],
            image=data["image"],
            previous_release_sha=data["previous_release_sha"],
            previous_image=data["previous_image"],
            expected_environment=data["expected_environment"],
            migration=Migration.parse(data["migration"]),
        )
        if manifest.schema_version != 1:
            raise ReleasePlaneError("manifest_schema_version_invalid")
        if not isinstance(manifest.release_id, str) or not RELEASE_ID_RE.fullmatch(
            manifest.release_id
        ):
            raise ReleasePlaneError("release_id_invalid")
        for label, value in (
            ("release_sha", manifest.release_sha),
            ("previous_release_sha", manifest.previous_release_sha),
        ):
            if not isinstance(value, str) or not SHA_RE.fullmatch(value):
                raise ReleasePlaneError(f"{label}_invalid")
        for label, value in (("image", manifest.image), ("previous_image", manifest.previous_image)):
            if not isinstance(value, str) or not DIGEST_IMAGE_RE.fullmatch(value):
                raise ReleasePlaneError(f"{label}_must_be_immutable_kamilya_digest")
        if manifest.release_sha == manifest.previous_release_sha:
            raise ReleasePlaneError("release_sha_must_change")
        if manifest.image == manifest.previous_image:
            raise ReleasePlaneError("image_digest_must_change")
        if manifest.expected_environment != "kz-production":
            raise ReleasePlaneError("expected_environment_invalid")
        return manifest


@dataclass(frozen=True)
class HostConfig:
    schema_version: int
    environment: str
    compose_file: Path
    env_file: Path
    state_file: Path
    evidence_dir: Path
    lock_file: Path
    proxy_upstream_file: Path
    proxy_upstream_name: str
    public_health_url: str
    slot_ports: dict[str, int]
    project_prefix: str
    backup_gate: Path
    backup_freshness_seconds: int
    docker_binary: Path
    nginx_binary: Path
    health_timeout_seconds: int

    @classmethod
    def parse(cls, data: Any) -> HostConfig:
        if not isinstance(data, dict):
            raise ReleasePlaneError("config_must_be_object")
        expected = {
            "schema_version",
            "environment",
            "compose_file",
            "env_file",
            "state_file",
            "evidence_dir",
            "lock_file",
            "proxy_upstream_file",
            "proxy_upstream_name",
            "public_health_url",
            "slot_ports",
            "project_prefix",
            "backup_gate",
            "backup_freshness_seconds",
            "docker_binary",
            "nginx_binary",
            "health_timeout_seconds",
        }
        _exact_keys(data, expected, "config")
        ports = data["slot_ports"]
        if not isinstance(ports, dict) or set(ports) != set(SLOTS):
            raise ReleasePlaneError("slot_ports_invalid")
        parsed_ports: dict[str, int] = {}
        for slot, port in ports.items():
            if not isinstance(port, int) or not 1024 <= port <= 65535:
                raise ReleasePlaneError(f"slot_port_invalid:{slot}")
            parsed_ports[slot] = port
        if len(set(parsed_ports.values())) != 2:
            raise ReleasePlaneError("slot_ports_must_be_unique")
        config = cls(
            schema_version=data["schema_version"],
            environment=data["environment"],
            compose_file=_absolute(data["compose_file"], "compose_file"),
            env_file=_absolute(data["env_file"], "env_file"),
            state_file=_absolute(data["state_file"], "state_file"),
            evidence_dir=_absolute(data["evidence_dir"], "evidence_dir"),
            lock_file=_absolute(data["lock_file"], "lock_file"),
            proxy_upstream_file=_absolute(data["proxy_upstream_file"], "proxy_upstream_file"),
            proxy_upstream_name=data["proxy_upstream_name"],
            public_health_url=data["public_health_url"],
            slot_ports=parsed_ports,
            project_prefix=data["project_prefix"],
            backup_gate=_absolute(data["backup_gate"], "backup_gate"),
            backup_freshness_seconds=data["backup_freshness_seconds"],
            docker_binary=_absolute(data["docker_binary"], "docker_binary"),
            nginx_binary=_absolute(data["nginx_binary"], "nginx_binary"),
            health_timeout_seconds=data["health_timeout_seconds"],
        )
        if config.schema_version != 1 or config.environment != "kz-production":
            raise ReleasePlaneError("host_config_identity_invalid")
        if not isinstance(config.proxy_upstream_name, str) or not TOKEN_RE.fullmatch(
            config.proxy_upstream_name
        ):
            raise ReleasePlaneError("proxy_upstream_name_invalid")
        if not isinstance(config.project_prefix, str) or not TOKEN_RE.fullmatch(config.project_prefix):
            raise ReleasePlaneError("project_prefix_invalid")
        if not isinstance(config.public_health_url, str) or not config.public_health_url.startswith(
            "https://api.kml.kz/"
        ):
            raise ReleasePlaneError("public_health_url_invalid")
        if not isinstance(config.backup_freshness_seconds, int) or not 300 <= config.backup_freshness_seconds <= 3600:
            raise ReleasePlaneError("backup_freshness_seconds_invalid")
        if not isinstance(config.health_timeout_seconds, int) or not 30 <= config.health_timeout_seconds <= 900:
            raise ReleasePlaneError("health_timeout_seconds_invalid")
        return config


@dataclass(frozen=True)
class RuntimeState:
    schema_version: int
    active_slot: str
    release_sha: str
    image: str

    @classmethod
    def parse(cls, data: Any) -> RuntimeState:
        if not isinstance(data, dict):
            raise ReleasePlaneError("state_must_be_object")
        _exact_keys(data, {"schema_version", "active_slot", "release_sha", "image"}, "state")
        state = cls(**data)
        if state.schema_version != 1 or state.active_slot not in SLOTS:
            raise ReleasePlaneError("state_identity_invalid")
        if not SHA_RE.fullmatch(state.release_sha) or not DIGEST_IMAGE_RE.fullmatch(state.image):
            raise ReleasePlaneError("state_release_identity_invalid")
        return state


class Runner(Protocol):
    def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str: ...


class SubprocessRunner:
    def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        completed = subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
            env=process_env,
        )
        if completed.returncode != 0:
            executable = Path(args[0]).name
            raise ReleasePlaneError(f"command_failed:{executable}:exit={completed.returncode}")
        return completed.stdout.strip()


class HealthReader(Protocol):
    def read(self, url: str) -> Mapping[str, Any]: ...


class UrlHealthReader:
    def read(self, url: str) -> Mapping[str, Any]:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed config URLs
            if response.status != 200:
                raise ReleasePlaneError("health_http_status_invalid")
            body = response.read(65537)
        if len(body) > 65536:
            raise ReleasePlaneError("health_response_too_large")
        try:
            data = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReleasePlaneError("health_response_invalid") from error
        if not isinstance(data, dict):
            raise ReleasePlaneError("health_response_not_object")
        return data


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleasePlaneError(f"json_read_failed:{path.name}") from error


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ReleasePlane:
    def __init__(
        self,
        manifest: ReleaseManifest,
        config: HostConfig,
        runner: Runner,
        health: HealthReader,
    ) -> None:
        self.manifest = manifest
        self.config = config
        self.runner = runner
        self.health = health

    def _state(self) -> RuntimeState:
        return RuntimeState.parse(_read_json(self.config.state_file))

    def _project(self, slot: str) -> str:
        return f"{self.config.project_prefix}-{slot}"

    def _compose(self, slot: str, *args: str) -> list[str]:
        return [
            str(self.config.docker_binary),
            "compose",
            "-p",
            self._project(slot),
            "--env-file",
            str(self.config.env_file),
            "-f",
            str(self.config.compose_file),
            *args,
        ]

    def _slot_env(self, slot: str, image: str, release_sha: str) -> dict[str, str]:
        return {
            "KAMILYA_API_IMAGE": image,
            "KAMILYA_RELEASE_SHA": release_sha,
            "KAMILYA_SLOT_PORT": str(self.config.slot_ports[slot]),
        }

    def _wait_health(self, url: str, release_sha: str) -> None:
        deadline = time.monotonic() + self.config.health_timeout_seconds
        while True:
            try:
                payload = self.health.read(url)
                if (
                    payload.get("release_sha") == release_sha
                    and payload.get("deployment_environment") == self.config.environment
                    and payload.get("status") == "ok"
                ):
                    return
            except (OSError, ReleasePlaneError):
                pass
            if time.monotonic() >= deadline:
                raise ReleasePlaneError("health_identity_timeout")
            time.sleep(2)

    def _verify_services(self, slot: str, image: str, release_sha: str) -> None:
        env = self._slot_env(slot, image, release_sha)
        for service in SERVICES:
            container = self.runner.run(self._compose(slot, "ps", "-q", service), env=env)
            if not container or "\n" in container:
                raise ReleasePlaneError(f"container_identity_invalid:{service}")
            facts = self.runner.run(
                [
                    str(self.config.docker_binary),
                    "inspect",
                    "--format",
                    "{{.Config.Image}}|{{.State.Status}}|{{.RestartCount}}",
                    container,
                ]
            )
            if facts != f"{image}|running|0":
                raise ReleasePlaneError(f"container_readback_mismatch:{service}")

    def _proxy_content(self, slot: str) -> str:
        port = self.config.slot_ports[slot]
        return (
            "# Managed by kamilya release-plane; manual edits are overwritten.\n"
            f"upstream {self.config.proxy_upstream_name} {{\n"
            f"    server 127.0.0.1:{port};\n"
            "    keepalive 32;\n"
            "}\n"
        )

    def _reload_proxy(self) -> None:
        self.runner.run([str(self.config.nginx_binary), "-t"])
        self.runner.run([str(self.config.nginx_binary), "-s", "reload"])

    def _write_evidence(self, payload: Mapping[str, Any]) -> None:
        self.config.evidence_dir.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        run_file = self.config.evidence_dir / f"{payload['run_id']}.json"
        with run_file.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(run_file, 0o600)
        ledger = self.config.evidence_dir / "release-ledger.jsonl"
        descriptor = os.open(ledger, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, content.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _migration_receipt_path(self) -> Path:
        return (
            self.config.evidence_dir
            / "migration-receipts"
            / f"{self.manifest.release_id}.json"
        )

    def _migration_receipt(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "release_id": self.manifest.release_id,
            "release_sha": self.manifest.release_sha,
            "image": self.manifest.image,
            "from_revision": self.manifest.migration.from_revision,
            "to_revision": self.manifest.migration.to_revision,
            "backup": "encrypted_verified_fresh",
        }

    def _write_migration_receipt(self) -> None:
        path = self._migration_receipt_path()
        payload = json.dumps(self._migration_receipt(), indent=2, sort_keys=True) + "\n"
        if path.exists():
            if _read_json(path) != self._migration_receipt():
                raise ReleasePlaneError("migration_receipt_conflict")
            return
        _atomic_write(path, payload)

    def _require_migration_receipt(self) -> None:
        path = self._migration_receipt_path()
        if not path.is_file() or _read_json(path) != self._migration_receipt():
            raise ReleasePlaneError("target_revision_without_matching_backup_receipt")

    def plan(self) -> dict[str, Any]:
        state = self._state()
        if self.manifest.expected_environment != self.config.environment:
            raise ReleasePlaneError("manifest_host_environment_mismatch")
        inactive = "green" if state.active_slot == "blue" else "blue"
        return {
            "status": "READY",
            "release_id": self.manifest.release_id,
            "release_sha": self.manifest.release_sha,
            "current_release_sha": state.release_sha,
            "active_slot": state.active_slot,
            "candidate_slot": inactive,
            "migration_mode": self.manifest.migration.mode,
            "network_attempted": False,
            "mutation_attempted": False,
        }

    def execute(self, confirmation: str) -> dict[str, Any]:
        if confirmation != self.manifest.release_id:
            raise ReleasePlaneError("release_confirmation_mismatch")
        started_at = datetime.now(UTC).isoformat()
        run_id = f"{self.manifest.release_id}-{uuid.uuid4().hex}"
        lock_fd: int | None = None
        state = self._state()
        inactive = "green" if state.active_slot == "blue" else "blue"
        old_proxy = ""
        candidate_started = False
        old_workers_stopped = False
        proxy_switched = False
        rollback_status = "not_required"
        try:
            try:
                lock_fd = os.open(self.config.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as error:
                raise ReleasePlaneError("release_lock_already_held") from error
            if self.manifest.expected_environment != self.config.environment:
                raise ReleasePlaneError("manifest_host_environment_mismatch")
            if (
                state.release_sha == self.manifest.release_sha
                and state.image == self.manifest.image
            ):
                result = {
                    "run_id": run_id,
                    "release_id": self.manifest.release_id,
                    "release_sha": self.manifest.release_sha,
                    "status": "ALREADY_DEPLOYED",
                    "active_slot": state.active_slot,
                    "rollback": "not_required",
                    "started_at": started_at,
                    "finished_at": datetime.now(UTC).isoformat(),
                }
                self._write_evidence(result)
                return result
            if (
                state.release_sha != self.manifest.previous_release_sha
                or state.image != self.manifest.previous_image
            ):
                raise ReleasePlaneError("expected_previous_release_mismatch")

            self.runner.run([str(self.config.docker_binary), "pull", self.manifest.image])
            candidate_env = self._slot_env(inactive, self.manifest.image, self.manifest.release_sha)
            if self.manifest.migration.mode == "exact":
                current = self.runner.run(
                    self._compose(
                        inactive,
                        "run",
                        "--rm",
                        "--no-deps",
                        "--entrypoint",
                        "/app/.venv/bin/alembic",
                        "api",
                        "current",
                    ),
                    env=candidate_env,
                )
                if current.startswith(self.manifest.migration.from_revision or ""):
                    self.runner.run(
                        [
                            str(self.config.backup_gate),
                            "--expected-revision",
                            self.manifest.migration.from_revision or "",
                            "--freshness-seconds",
                            str(self.config.backup_freshness_seconds),
                        ]
                    )
                    self._write_migration_receipt()
                    self.runner.run(
                        self._compose(
                            inactive,
                            "run",
                            "--rm",
                            "--no-deps",
                            "--entrypoint",
                            "/app/.venv/bin/alembic",
                            "api",
                            "upgrade",
                            self.manifest.migration.to_revision or "",
                        ),
                        env=candidate_env,
                    )
                    current = self.runner.run(
                        self._compose(
                            inactive,
                            "run",
                            "--rm",
                            "--no-deps",
                            "--entrypoint",
                            "/app/.venv/bin/alembic",
                            "api",
                            "current",
                        ),
                        env=candidate_env,
                    )
                    if not current.startswith(self.manifest.migration.to_revision or ""):
                        raise ReleasePlaneError("migration_revision_after_mismatch")
                elif current.startswith(self.manifest.migration.to_revision or ""):
                    self._require_migration_receipt()
                else:
                    raise ReleasePlaneError("migration_revision_before_mismatch")

            self.runner.run(self._compose(inactive, "down", "--remove-orphans"), env=candidate_env)
            candidate_started = True
            self.runner.run(
                self._compose(inactive, "up", "-d", "--no-deps", "api"), env=candidate_env
            )
            private_url = f"http://127.0.0.1:{self.config.slot_ports[inactive]}/health"
            self._wait_health(private_url, self.manifest.release_sha)

            active_env = self._slot_env(state.active_slot, state.image, state.release_sha)
            self.runner.run(self._compose(state.active_slot, "stop", *WORKERS), env=active_env)
            old_workers_stopped = True
            self.runner.run(
                self._compose(inactive, "up", "-d", "--no-deps", *WORKERS), env=candidate_env
            )
            self._verify_services(inactive, self.manifest.image, self.manifest.release_sha)

            old_proxy = self.config.proxy_upstream_file.read_text(encoding="utf-8")
            _atomic_write(self.config.proxy_upstream_file, self._proxy_content(inactive), 0o644)
            try:
                self._reload_proxy()
            except ReleasePlaneError:
                _atomic_write(self.config.proxy_upstream_file, old_proxy, 0o644)
                self._reload_proxy()
                raise
            proxy_switched = True
            self._wait_health(self.config.public_health_url, self.manifest.release_sha)

            new_state = {
                "schema_version": 1,
                "active_slot": inactive,
                "release_sha": self.manifest.release_sha,
                "image": self.manifest.image,
            }
            _atomic_write(
                self.config.state_file,
                json.dumps(new_state, indent=2, sort_keys=True) + "\n",
            )
            result = {
                "run_id": run_id,
                "release_id": self.manifest.release_id,
                "release_sha": self.manifest.release_sha,
                "previous_release_sha": state.release_sha,
                "image": self.manifest.image,
                "status": "DEPLOYED",
                "active_slot": inactive,
                "migration_mode": self.manifest.migration.mode,
                "migration_revision": self.manifest.migration.to_revision,
                "rollback": rollback_status,
                "services": list(SERVICES),
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
            }
            self._write_evidence(result)
            return result
        except Exception as error:
            safe_error = error if isinstance(error, ReleasePlaneError) else ReleasePlaneError(
                f"unexpected_failure:{type(error).__name__}"
            )
            if candidate_started:
                try:
                    if proxy_switched:
                        _atomic_write(self.config.proxy_upstream_file, old_proxy, 0o644)
                        self._reload_proxy()
                    active_env = self._slot_env(state.active_slot, state.image, state.release_sha)
                    if old_workers_stopped:
                        self.runner.run(
                            self._compose(state.active_slot, "up", "-d", "--no-deps", *WORKERS),
                            env=active_env,
                        )
                    candidate_env = self._slot_env(
                        inactive, self.manifest.image, self.manifest.release_sha
                    )
                    self.runner.run(
                        self._compose(inactive, "down", "--remove-orphans"), env=candidate_env
                    )
                    self._wait_health(
                        f"http://127.0.0.1:{self.config.slot_ports[state.active_slot]}/health",
                        state.release_sha,
                    )
                    rollback_status = "completed"
                except Exception:
                    rollback_status = "failed"
            failure = {
                "run_id": run_id,
                "release_id": self.manifest.release_id,
                "release_sha": self.manifest.release_sha,
                "previous_release_sha": state.release_sha,
                "status": "ROLLED_BACK" if rollback_status == "completed" else "FAILED",
                "failure": str(safe_error),
                "rollback": rollback_status,
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
            }
            self._write_evidence(failure)
            if safe_error is error:
                raise
            raise safe_error from error
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                self.config.lock_file.unlink(missing_ok=True)


def _load(manifest_path: Path, config_path: Path) -> tuple[ReleaseManifest, HostConfig]:
    return (
        ReleaseManifest.parse(_read_json(manifest_path)),
        HostConfig.parse(_read_json(config_path)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "plan", "execute"))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--confirm-release-id", default="")
    args = parser.parse_args(argv)
    try:
        manifest, config = _load(args.manifest, args.config)
        plane = ReleasePlane(manifest, config, SubprocessRunner(), UrlHealthReader())
        if args.command == "validate":
            result = {"status": "VALID", "release_id": manifest.release_id}
        elif args.command == "plan":
            result = plane.plan()
        else:
            result = plane.execute(args.confirm_release_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except ReleasePlaneError as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
