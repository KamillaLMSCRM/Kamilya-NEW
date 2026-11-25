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
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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
SERVICES = (
    "api",
    "worker-ai",
    "worker-documents",
    "worker-ops",
    "worker-ai-replica",
    "worker-documents-replica",
)
WORKERS = SERVICES[1:]
LEGACY_SERVICES = ("api", "worker-ai", "worker-documents", "worker-ops")
REPLICATED_WORKER_MIN_VERSION = (0, 11, 152)
WORKER_QUEUE_BINDINGS = {
    "worker-ai": ("ai",),
    "worker-documents": ("documents",),
    "worker-ops": ("maintenance", "notifications"),
    "worker-ai-replica": ("ai",),
    "worker-documents-replica": ("documents",),
}
WORKER_DRAIN_TIMEOUT_SECONDS = 300
WORKER_DRAIN_POLL_SECONDS = 10
WORKER_STOP_GRACE_SECONDS = 120
WORKER_STARTUP_TIMEOUT_SECONDS = 60
WORKER_CONTROL_CODE = r'''import json, sys
from app.core.celery_app import celery_app

op = sys.argv[1]
control = celery_app.control
if op == "snapshot":
    names = sys.argv[2:]
    inspect = control.inspect(timeout=2)
    active_queues = inspect.active_queues()
    active = inspect.active()
    reserved = inspect.reserved()
    scheduled = inspect.scheduled()
    queue_config = {}
    for name in names:
        queue = celery_app.amqp.queues[name]
        queue_config[name] = {
            "exchange_name": getattr(queue.exchange, "name", None),
            "exchange_type": getattr(queue.exchange, "type", None),
            "routing_key": queue.routing_key,
            "queue_arguments": queue.queue_arguments,
        }
    def counts(value):
        return {node: len(items or []) for node, items in (value or {}).items()}
    print(json.dumps({
        "active_queues": active_queues or {},
        "active": counts(active),
        "reserved": counts(reserved),
        "scheduled": counts(scheduled),
        "queue_config": queue_config,
    }, sort_keys=True, separators=(",", ":"), default=str))
elif op in ("cancel", "add"):
    queue_name, node = sys.argv[2:4]
    queue = celery_app.amqp.queues[queue_name]
    if op == "cancel":
        replies = control.cancel_consumer(queue_name, destination=[node], reply=True, timeout=2)
    else:
        options = {
            "queue_arguments": queue.queue_arguments,
            "durable": queue.durable,
            "auto_delete": queue.auto_delete,
        }
        for key in ("expires", "message_ttl", "max_length", "max_length_bytes", "max_priority"):
            value = getattr(queue, key, None)
            if value is not None:
                options[key] = value
        replies = control.add_consumer(
            queue_name,
            exchange=queue.exchange.name,
            exchange_type=queue.exchange.type,
            routing_key=queue.routing_key,
            options=options,
            destination=[node], reply=True, timeout=2,
        )
    merged = {}
    for item in replies or []:
        if isinstance(item, dict):
            merged.update(item)
    print(json.dumps(merged, sort_keys=True, separators=(",", ":"), default=str))
else:
    raise SystemExit("worker_control_operation_invalid")
'''


def services_for_product_version(product_version: str | None) -> tuple[str, ...]:
    """Keep pre-replica releases rollbackable with their original worker set."""
    if product_version is None:
        return LEGACY_SERVICES
    version = tuple(int(part) for part in product_version.split("."))
    return SERVICES if version >= REPLICATED_WORKER_MIN_VERSION else LEGACY_SERVICES
FEATURE_ENV = {
    "workbench": "METHODOLOGIST_WORKBENCH_ENABLED",
    "document_draft": "METHODOLOGIST_DOCUMENT_DRAFT_ENABLED",
    "lesson_correction": "METHODOLOGIST_LESSON_CORRECTION_ENABLED",
}
STAFF_FEATURE_ENV = {**FEATURE_ENV, "staff_structure": "STAFF_STRUCTURE_V3_ENABLED"}
# Effective settings, including old image defaults; no raw environment is emitted.
FEATURE_READBACK = (
    "import json; from app.core.config import get_settings; s=get_settings(); "
    f"names={FEATURE_ENV!r}; "
    "print(json.dumps({k:{'supported':hasattr(s,n),'enabled':getattr(s,n,False)} "
    "for k,n in names.items()}))"
)
STAFF_FEATURE_READBACK = (
    "import json; from app.core.config import get_settings; s=get_settings(); "
    f"names={STAFF_FEATURE_ENV!r}; "
    "print(json.dumps({k:{'supported':hasattr(s,n),'enabled':getattr(s,n,False)} "
    "for k,n in names.items()}))"
)


def _feature_flags(data: Any, label: str, *, include_staff: bool = False) -> dict[str, bool]:
    if not isinstance(data, dict):
        raise ReleasePlaneError(f"{label}_must_be_object")
    _exact_keys(data, set(STAFF_FEATURE_ENV if include_staff else FEATURE_ENV), label)
    if any(type(value) is not bool for value in data.values()):
        raise ReleasePlaneError(f"{label}_must_be_literal_booleans")
    if (data["document_draft"] or data["lesson_correction"]) and not data["workbench"]:
        raise ReleasePlaneError(f"{label}_requires_workbench")
    return dict(data)


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleasePlaneError("json_duplicate_key")
        result[key] = value
    return result


def feature_manifest_fields(candidate: str, previous: str, version: str) -> dict[str, Any]:
    """Workflow producer crosses the same strict flag seam as the host consumer."""
    candidate, previous = candidate.strip(), previous.strip()
    modern = bool(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)) and tuple(int(p) for p in version.split(".")) >= (0, 11, 71)
    if not candidate and not previous:
        if modern:
            raise ReleasePlaneError("v3_feature_flags_required")
        return {"schema_version": 1}
    if not candidate or not previous:
        raise ReleasePlaneError("feature_flags_require_both_objects")
    try:
        current_flags = json.loads(candidate, object_pairs_hook=_unique_json_pairs)
        old_flags = json.loads(previous, object_pairs_hook=_unique_json_pairs)
        staff = any(isinstance(item, dict) and "staff_structure" in item for item in (current_flags, old_flags))
        if modern and not staff:
            raise ReleasePlaneError("v3_feature_flags_required")
        return {"schema_version": 3 if staff else 2, "product_version": version,
                "feature_flags": _feature_flags(current_flags, "feature_flags", include_staff=staff),
                "previous_feature_flags": _feature_flags(old_flags, "previous_feature_flags", include_staff=staff)}
    except json.JSONDecodeError as error:
        raise ReleasePlaneError("feature_flags_json_invalid") from error


def _utc_now_iso() -> str:
    # VM126 uses Python 3.10; datetime.UTC is available only from Python 3.11.
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


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
    product_version: str | None = None
    feature_flags: dict[str, bool] | None = None
    previous_feature_flags: dict[str, bool] | None = None

    @classmethod
    def parse(cls, data: Any) -> ReleaseManifest:
        if not isinstance(data, dict):
            raise ReleasePlaneError("manifest_must_be_object")
        schema = data.get("schema_version")
        if type(schema) is not int or schema not in (1, 2, 3):
            raise ReleasePlaneError("manifest_schema_version_invalid")
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
            } | ({"product_version", "feature_flags", "previous_feature_flags"} if schema >= 2 else set()),
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
            product_version=data.get("product_version"),
            feature_flags=_feature_flags(data["feature_flags"], "feature_flags", include_staff=schema == 3) if schema >= 2 else None,
            previous_feature_flags=_feature_flags(data["previous_feature_flags"], "previous_feature_flags", include_staff=schema == 3) if schema >= 2 else None,
        )
        if schema >= 2:
            if not isinstance(manifest.product_version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest.product_version):
                raise ReleasePlaneError("product_version_invalid")
            version = tuple(int(part) for part in manifest.product_version.split("."))
            if version >= (0, 11, 71) and schema != 3:
                raise ReleasePlaneError("v3_requires_schema3")
            if schema == 3 and version < (0, 11, 63):
                raise ReleasePlaneError("staff_protocol_requires_version63")
            if version >= (0, 11, 71) and manifest.migration.mode == "exact" and (
                (manifest.migration.from_revision, manifest.migration.to_revision) != manifest.correction_revisions
            ):
                raise ReleasePlaneError("v3_migration_revision_invalid")
            if manifest.feature_flags and manifest.feature_flags["lesson_correction"]:
                if version < (0, 11, 39):
                    raise ReleasePlaneError("correction_requires_version39")
                expected_from, expected_to = manifest.correction_revisions
                if manifest.migration.mode == "exact" and (
                    manifest.migration.from_revision != expected_from or manifest.migration.to_revision != expected_to
                ):
                    raise ReleasePlaneError("correction_migration_revision_invalid")
            if manifest.feature_flags and manifest.feature_flags.get("staff_structure"):
                if manifest.migration.mode == "exact" and (
                    (manifest.migration.from_revision, manifest.migration.to_revision) != manifest.correction_revisions
                ):
                    raise ReleasePlaneError("staff_migration_revision_invalid")
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

    @property
    def correction_revisions(self) -> tuple[str, str]:
        """Known additive schema epochs, never an arbitrary revision range."""
        if self.product_version is None:
            raise ReleasePlaneError("correction_requires_product_version")
        version = tuple(int(part) for part in self.product_version.split("."))
        if version in {(0, 11, 152), (0, 11, 153), (0, 11, 154)}:
            return "0194", "0194"
        if (0, 11, 129) <= version <= (0, 11, 145) or version == (0, 11, 147):
            return "0192", "0192"
        if version == (0, 11, 148):
            return "0192", "0194"
        if version in {(0, 11, 149), (0, 11, 150), (0, 11, 151)}:
            return "0194", "0194"
        if version == (0, 11, 127):
            return "0191", "0192"
        if version >= (0, 11, 126):
            return "0190", "0191"
        if version >= (0, 11, 124):
            return "0188", "0190"
        if version >= (0, 11, 114):
            return "0187", "0188"
        if version >= (0, 11, 84):
            return "0186", "0187"
        if version >= (0, 11, 82):
            return "0185", "0186"
        if version >= (0, 11, 74):
            return "0184", "0185"
        if version >= (0, 11, 71):
            return "0183", "0184"
        if version >= (0, 11, 63):
            return "0181", "0183"
        if version >= (0, 11, 55):
            return "0180", "0181"
        if version >= (0, 11, 53):
            return "0179", "0180"
        return ("0178", "0179") if version >= (0, 11, 51) else ("0175", "0178")


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
        # Legacy Compose interpolation must use its explicit CLI dotenv file,
        # not ambient host feature flags. Schema2 overlays all three below.
        for name in FEATURE_ENV.values():
            process_env.pop(name, None)
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
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_pairs)
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

    def _slot_env(self, slot: str, image: str, release_sha: str, flags: Mapping[str, bool] | None = None) -> dict[str, str]:
        result = {
            "KAMILYA_API_IMAGE": image,
            "KAMILYA_RELEASE_SHA": release_sha,
            "KAMILYA_SLOT_PORT": str(self.config.slot_ports[slot]),
        }
        if flags is not None:
            result.update({STAFF_FEATURE_ENV[key]: str(value).lower() for key, value in flags.items()})
        return result

    def _feature_evidence(self) -> dict[str, Any]:
        if self.manifest.schema_version == 1:
            return {}
        return {"product_version": self.manifest.product_version,
                "feature_flags": self.manifest.feature_flags,
                "previous_feature_flags": self.manifest.previous_feature_flags}

    def _wait_health(self, url: str, release_sha: str, product_version: str | None = None) -> None:
        deadline = time.monotonic() + self.config.health_timeout_seconds
        while True:
            try:
                payload = self.health.read(url)
                if (
                    payload.get("release_sha") == release_sha
                    and payload.get("deployment_environment") == self.config.environment
                    and payload.get("status") == "ok"
                    and (product_version is None or payload.get("product_version") == product_version)
                ):
                    return
            except (OSError, ReleasePlaneError):
                pass
            if time.monotonic() >= deadline:
                raise ReleasePlaneError("health_identity_timeout")
            time.sleep(2)

    def _verify_services(self, slot: str, image: str, release_sha: str, flags: Mapping[str, bool] | None = None, services: Sequence[str] = SERVICES, *, allow_unsupported_disabled: bool = False) -> None:
        env = self._slot_env(slot, image, release_sha, flags)
        for service in services:
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
            if flags is not None:
                selected = self.runner.run([str(self.config.docker_binary), "exec", container,
                    "/app/.venv/bin/python", "-c", STAFF_FEATURE_READBACK if "staff_structure" in flags else FEATURE_READBACK])
                try:
                    effective = json.loads(selected, object_pairs_hook=_unique_json_pairs)
                    if not isinstance(effective, dict) or set(effective) != set(flags):
                        raise ValueError("shape")
                    for key, expected in flags.items():
                        item = effective[key]
                        if (not isinstance(item, dict) or set(item) != {"supported", "enabled"}
                            or type(item["supported"]) is not bool or type(item["enabled"]) is not bool
                            or item["enabled"] is not expected
                            or (not item["supported"] and (expected or not allow_unsupported_disabled))):
                            raise ValueError("flag")
                except (ValueError, ReleasePlaneError) as error:
                    raise ReleasePlaneError(f"container_feature_flag_mismatch:{service}") from error

    def _worker_control(self, slot: str, env: Mapping[str, str], operation: str,
                        *arguments: str, service: str = "api") -> dict[str, Any]:
        output = self.runner.run(self._compose(
            slot, "exec", "-T", service, "/app/.venv/bin/python", "-c",
            WORKER_CONTROL_CODE, operation, *arguments,
        ), env=env)
        try:
            value = json.loads(output, object_pairs_hook=_unique_json_pairs)
        except (json.JSONDecodeError, ReleasePlaneError) as error:
            raise ReleasePlaneError("worker_control_response_invalid") from error
        if not isinstance(value, dict):
            raise ReleasePlaneError("worker_control_response_invalid")
        return value

    def _worker_snapshot(self, slot: str, env: Mapping[str, str], workers: Sequence[str],
                         *, control_service: str = "api") -> dict[str, Any]:
        queues = sorted({queue for worker in workers for queue in WORKER_QUEUE_BINDINGS[worker]})
        value = self._worker_control(slot, env, "snapshot", *queues, service=control_service)
        if set(value) != {"active_queues", "active", "reserved", "scheduled", "queue_config"}:
            raise ReleasePlaneError("worker_snapshot_shape_invalid")
        active_queues = value["active_queues"]
        queue_config = value["queue_config"]
        if not isinstance(active_queues, dict) or not isinstance(queue_config, dict) or set(queue_config) != set(queues):
            raise ReleasePlaneError("worker_snapshot_shape_invalid")
        nodes = set(active_queues)
        if not nodes or any(not isinstance(node, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,255}", node)
                            for node in nodes):
            raise ReleasePlaneError("worker_snapshot_nodes_invalid")
        normalized: dict[str, tuple[str, ...]] = {}
        for node, bindings in active_queues.items():
            if not isinstance(bindings, list):
                raise ReleasePlaneError("worker_snapshot_bindings_invalid")
            names: list[str] = []
            for binding in bindings:
                if not isinstance(binding, dict) or not isinstance(binding.get("name"), str):
                    raise ReleasePlaneError("worker_snapshot_bindings_invalid")
                name = binding["name"]
                config = queue_config.get(name)
                exchange = binding.get("exchange")
                if (not isinstance(config, dict) or not isinstance(exchange, dict)
                    or exchange.get("name") != config.get("exchange_name")
                    or exchange.get("type") != config.get("exchange_type")
                    or binding.get("routing_key") != config.get("routing_key")
                    or binding.get("queue_arguments") != config.get("queue_arguments")):
                    raise ReleasePlaneError("worker_queue_binding_source_mismatch")
                names.append(name)
            if len(names) != len(set(names)):
                raise ReleasePlaneError("worker_snapshot_duplicate_binding")
            normalized[node] = tuple(sorted(names))
        for field in ("active", "reserved", "scheduled"):
            counts = value[field]
            if (not isinstance(counts, dict) or set(counts) != nodes
                or any(type(count) is not int or count < 0 for count in counts.values())):
                raise ReleasePlaneError("worker_snapshot_task_counts_invalid")
        value["normalized_bindings"] = normalized
        return value

    def _worker_node_bindings(self, slot: str, env: Mapping[str, str],
                              workers: Sequence[str]) -> dict[str, tuple[str, ...]]:
        expected: dict[str, tuple[str, ...]] = {}
        for service in workers:
            container = self.runner.run(self._compose(slot, "ps", "-q", service), env=env)
            if not container or "\n" in container or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", container):
                raise ReleasePlaneError(f"worker_container_identity_invalid:{service}")
            facts = self.runner.run([
                str(self.config.docker_binary), "inspect", "--format",
                "{{.Config.Hostname}}|{{json .Config.Cmd}}", container,
            ])
            try:
                hostname, raw_command = facts.split("|", 1)
                command = json.loads(raw_command, object_pairs_hook=_unique_json_pairs)
            except (ValueError, json.JSONDecodeError, ReleasePlaneError) as error:
                raise ReleasePlaneError(f"worker_container_command_invalid:{service}") from error
            if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", hostname)
                or not isinstance(command, list) or any(not isinstance(item, str) for item in command)
                or "worker" not in command):
                raise ReleasePlaneError(f"worker_container_command_invalid:{service}")
            declared: list[str] = []
            for index, item in enumerate(command):
                if item in {"--hostname", "-n"}:
                    if index + 1 >= len(command):
                        raise ReleasePlaneError(f"worker_hostname_template_invalid:{service}")
                    declared.append(command[index + 1])
                elif item.startswith("--hostname="):
                    declared.append(item.partition("=")[2])
            if len(declared) > 1:
                raise ReleasePlaneError(f"worker_hostname_template_invalid:{service}")
            # Celery's default node ID is celery@<hostname>. Release compose
            # templates use an explicit role@%h hostname for new containers.
            node = declared[0].replace("%h", hostname) if declared else f"celery@{hostname}"
            if "@" not in node or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}@[A-Za-z0-9_.-]{1,128}", node):
                raise ReleasePlaneError(f"worker_hostname_template_invalid:{service}")
            if node in expected:
                raise ReleasePlaneError("worker_node_identity_duplicate")
            expected[node] = tuple(sorted(WORKER_QUEUE_BINDINGS[service]))
        return expected

    @staticmethod
    def _expected_worker_bindings(workers: Sequence[str]) -> Counter[tuple[str, ...]]:
        try:
            return Counter(tuple(sorted(WORKER_QUEUE_BINDINGS[worker])) for worker in workers)
        except KeyError as error:
            raise ReleasePlaneError("worker_queue_binding_service_unknown") from error

    def _assert_worker_topology(self, snapshot: Mapping[str, Any], workers: Sequence[str]) -> None:
        if Counter(snapshot["normalized_bindings"].values()) != self._expected_worker_bindings(workers):
            raise ReleasePlaneError("worker_queue_topology_mismatch")

    @staticmethod
    def _assert_exact_worker_bindings(snapshot: Mapping[str, Any],
                                      expected: Mapping[str, Sequence[str]]) -> None:
        actual = snapshot["normalized_bindings"]
        normalized = {node: tuple(sorted(queues)) for node, queues in expected.items()}
        if actual != normalized:
            raise ReleasePlaneError("worker_queue_node_binding_mismatch")

    def _assert_worker_control_ack(self, reply: Mapping[str, Any], node: str, queue: str,
                                   operation: str) -> None:
        result = reply.get(node)
        if not isinstance(result, dict) or set(result) != {"ok"} or not isinstance(result["ok"], str):
            raise ReleasePlaneError(f"worker_{operation}_ack_missing:{queue}")
        message = result["ok"].lower()
        if queue.lower() not in message or not any(word in message for word in ("consum", "already")):
            raise ReleasePlaneError(f"worker_{operation}_ack_invalid:{queue}")

    def _restore_worker_consumers(self, slot: str, env: Mapping[str, str], workers: Sequence[str],
                                  expected: Mapping[str, Sequence[str]], *,
                                  control_service: str = "api") -> None:
        failures: list[str] = []
        try:
            self._worker_snapshot(slot, env, workers, control_service=control_service)
        except Exception:
            failures.append("initial_snapshot")
        # Always attempt every captured node/queue pair, even after a snapshot
        # or an individual acknowledgement fails; add_consumer is idempotent.
        for node, queues in expected.items():
            for queue in queues:
                try:
                    reply = self._worker_control(slot, env, "add", queue, node, service=control_service)
                    self._assert_worker_control_ack(reply, node, queue, "restore")
                except Exception:
                    failures.append(f"add:{queue}")
        try:
            restored = self._worker_snapshot(slot, env, workers, control_service=control_service)
            self._assert_exact_worker_bindings(restored, expected)
        except Exception:
            failures.append("final_exact_readback")
        # Consumer control replies can be lost after the broker accepted the
        # command. The final exact node-to-queue readback is authoritative; fail
        # restoration only when that state cannot be proved.
        if "final_exact_readback" in failures:
            raise ReleasePlaneError("worker_consumer_restore_failed")

    def _pause_and_drain_workers(self, slot: str, env: Mapping[str, str],
                                 workers: Sequence[str], *,
                                 control_service: str = "api") -> dict[str, tuple[str, ...]]:
        baseline = self._worker_snapshot(slot, env, workers, control_service=control_service)
        original = self._worker_node_bindings(slot, env, workers)
        self._assert_exact_worker_bindings(baseline, original)
        try:
            for node in sorted(original):
                for queue in original[node]:
                    reply = self._worker_control(slot, env, "cancel", queue, node, service=control_service)
                    self._assert_worker_control_ack(reply, node, queue, "pause")

            deadline = time.monotonic() + WORKER_DRAIN_TIMEOUT_SECONDS
            while True:
                snapshot = self._worker_snapshot(slot, env, workers, control_service=control_service)
                paused_bindings = snapshot["normalized_bindings"]
                if set(paused_bindings) != set(original) or any(paused_bindings[node] for node in original):
                    raise ReleasePlaneError("worker_consumer_pause_readback_failed")
                pending = sum(snapshot[field][node] for field in ("active", "reserved", "scheduled")
                              for node in snapshot[field])
                if pending == 0:
                    return original
                if time.monotonic() >= deadline:
                    raise ReleasePlaneError("worker_drain_timeout")
                time.sleep(WORKER_DRAIN_POLL_SECONDS)
        except Exception as error:
            try:
                self._restore_worker_consumers(slot, env, workers, original,
                                               control_service=control_service)
            except Exception as restore_error:
                raise ReleasePlaneError("worker_consumer_restore_failed") from restore_error
            if isinstance(error, ReleasePlaneError):
                raise
            raise ReleasePlaneError(f"worker_drain_failed:{type(error).__name__}") from error

    def _available_worker_control_service(self, slot: str, env: Mapping[str, str],
                                          workers: Sequence[str]) -> str:
        running = self._running_worker_services(slot, env, workers)
        if running:
            return running[0]
        raise ReleasePlaneError("worker_control_container_unavailable")

    def _running_worker_services(self, slot: str, env: Mapping[str, str],
                                 workers: Sequence[str]) -> tuple[str, ...]:
        running: list[str] = []
        for service in workers:
            container = self.runner.run(self._compose(slot, "ps", "-q", service), env=env)
            if not container:
                continue
            identities = container.splitlines()
            if (len(identities) != 1
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identities[0])):
                raise ReleasePlaneError(f"worker_container_identity_ambiguous:{service}")
            running.append(service)
        return tuple(running)

    def _wait_worker_topology(self, slot: str, env: Mapping[str, str],
                              workers: Sequence[str]) -> dict[str, tuple[str, ...]]:
        deadline = time.monotonic() + WORKER_STARTUP_TIMEOUT_SECONDS
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                expected = self._worker_node_bindings(slot, env, workers)
                control_service = self._available_worker_control_service(slot, env, workers)
                snapshot = self._worker_snapshot(slot, env, workers, control_service=control_service)
                self._assert_worker_topology(snapshot, workers)
                self._assert_exact_worker_bindings(snapshot, expected)
                return expected
            except Exception as error:
                last_error = error
                time.sleep(WORKER_DRAIN_POLL_SECONDS if WORKER_DRAIN_POLL_SECONDS < 3 else 2)
        if isinstance(last_error, ReleasePlaneError):
            raise ReleasePlaneError(f"candidate_worker_topology_unverified:{last_error}") from last_error
        raise ReleasePlaneError("candidate_worker_topology_unverified") from last_error

    def _active_worker_services(self, slot: str, image: str, release_sha: str,
                                 flags: Mapping[str, bool] | None = None) -> tuple[str, ...]:
        """Read and verify the exact supported previous worker topology."""
        env = self._slot_env(slot, image, release_sha, flags)
        present: set[str] = set()
        for service in WORKERS:
            container = self.runner.run(self._compose(slot, "ps", "-q", service), env=env)
            if container and "\n" in container:
                raise ReleasePlaneError(f"container_identity_invalid:{service}")
            if container:
                present.add(service)
        legacy = set(LEGACY_SERVICES[1:])
        replicas = set(WORKERS) - legacy
        if legacy <= present and not (replicas & present):
            services = LEGACY_SERVICES
        elif set(WORKERS) <= present:
            services = SERVICES
        else:
            raise ReleasePlaneError("active_worker_topology_invalid")
        self._verify_services(slot, image, release_sha, flags, services,
                              allow_unsupported_disabled=True)
        return services

    def _revision_matches(self, current: str, revision: str | None) -> bool:
        if self.manifest.schema_version == 1:
            return current.startswith(revision or "")
        return bool(re.fullmatch(re.escape(revision or "") + r"(?: \(head\))?", current.strip()))

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
            **self._feature_evidence(),
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
        started_at = _utc_now_iso()
        run_id = f"{self.manifest.release_id}-{uuid.uuid4().hex}"
        lock_fd: int | None = None
        retain_lock_for_recovery = False
        state = self._state()
        target_services = services_for_product_version(self.manifest.product_version)
        target_workers = target_services[1:]
        inactive = "green" if state.active_slot == "blue" else "blue"
        old_proxy = ""
        candidate_started = False
        old_workers_stopped = False
        previous_workers: tuple[str, ...] = LEGACY_SERVICES[1:]
        proxy_switched = False
        rollback_status = "not_required"
        rollback_error: str | None = None
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
                if self.manifest.schema_version >= 2:
                    self._verify_services(state.active_slot, state.image, state.release_sha,
                                          self.manifest.feature_flags, target_services)
                    self._wait_health(self.config.public_health_url, state.release_sha, self.manifest.product_version)
                    if (self.manifest.product_version is not None
                            and tuple(int(part) for part in self.manifest.product_version.split(".")) >= (0, 11, 71)):
                        candidate_env = self._slot_env(state.active_slot, state.image, state.release_sha, self.manifest.feature_flags)
                        current = self.runner.run(self._compose(state.active_slot, "run", "--rm", "--no-deps",
                            "--entrypoint", "/app/.venv/bin/alembic", "api", "current"), env=candidate_env)
                        if not self._revision_matches(current, self.manifest.correction_revisions[1]):
                            raise ReleasePlaneError("correction_schema_revision_mismatch")
                result = {
                    **self._feature_evidence(),
                    "run_id": run_id,
                    "release_id": self.manifest.release_id,
                    "release_sha": self.manifest.release_sha,
                    "status": "ALREADY_DEPLOYED",
                    "active_slot": state.active_slot,
                    "rollback": "not_required",
                    "started_at": started_at,
                    "finished_at": _utc_now_iso(),
                }
                self._write_evidence(result)
                return result
            if (
                state.release_sha != self.manifest.previous_release_sha
                or state.image != self.manifest.previous_image
            ):
                raise ReleasePlaneError("expected_previous_release_mismatch")

            previous_services = self._active_worker_services(
                state.active_slot, state.image, state.release_sha,
                self.manifest.previous_feature_flags if self.manifest.schema_version >= 2 else None,
            )
            previous_workers = previous_services[1:]

            self.runner.run([str(self.config.docker_binary), "pull", self.manifest.image])
            candidate_env = self._slot_env(inactive, self.manifest.image, self.manifest.release_sha, self.manifest.feature_flags)
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
                if self._revision_matches(current, self.manifest.migration.from_revision):
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
                    if not self._revision_matches(current, self.manifest.migration.to_revision):
                        raise ReleasePlaneError("migration_revision_after_mismatch")
                elif self._revision_matches(current, self.manifest.migration.to_revision):
                    self._require_migration_receipt()
                else:
                    raise ReleasePlaneError("migration_revision_before_mismatch")
            elif self.manifest.feature_flags and (
                self.manifest.feature_flags["lesson_correction"] or self.manifest.feature_flags.get("staff_structure")
                or (self.manifest.product_version is not None
                    and tuple(int(part) for part in self.manifest.product_version.split(".")) >= (0, 11, 71))
            ):
                current = self.runner.run(self._compose(inactive, "run", "--rm", "--no-deps",
                    "--entrypoint", "/app/.venv/bin/alembic", "api", "current"), env=candidate_env)
                if not self._revision_matches(current, self.manifest.correction_revisions[1]):
                    raise ReleasePlaneError("correction_schema_revision_mismatch")

            self.runner.run(self._compose(inactive, "down", "--remove-orphans"), env=candidate_env)
            candidate_started = True
            self.runner.run(
                self._compose(inactive, "up", "-d", "--no-deps", "api"), env=candidate_env
            )
            private_url = f"http://127.0.0.1:{self.config.slot_ports[inactive]}/health"
            self._wait_health(private_url, self.manifest.release_sha, self.manifest.product_version)
            if self.manifest.schema_version >= 2:
                self._verify_services(inactive, self.manifest.image, self.manifest.release_sha, self.manifest.feature_flags, ("api",))

            active_env = self._slot_env(state.active_slot, state.image, state.release_sha, self.manifest.previous_feature_flags)
            previous_worker_bindings = None
            if target_services == SERVICES or previous_services == SERVICES:
                # Pause exact queue consumers before checking in-flight work: a
                # preflight-only idle observation cannot close the enqueue race.
                previous_worker_bindings = self._pause_and_drain_workers(
                    state.active_slot, active_env, previous_workers
                )
            # Mark before the multi-service stop: Compose can partially stop the
            # old set and still return an error, so rollback must restore all of it.
            old_workers_stopped = True
            self.runner.run(self._compose(state.active_slot, "stop", "--timeout",
                                          str(WORKER_STOP_GRACE_SECONDS), *previous_workers), env=active_env)
            self.runner.run(
                self._compose(inactive, "up", "-d", "--no-deps", *target_workers), env=candidate_env
            )
            self._verify_services(inactive, self.manifest.image, self.manifest.release_sha,
                                  self.manifest.feature_flags, target_services)
            self._wait_worker_topology(inactive, candidate_env, target_workers)

            old_proxy = self.config.proxy_upstream_file.read_text(encoding="utf-8")
            _atomic_write(self.config.proxy_upstream_file, self._proxy_content(inactive), 0o644)
            try:
                self._reload_proxy()
            except ReleasePlaneError:
                _atomic_write(self.config.proxy_upstream_file, old_proxy, 0o644)
                self._reload_proxy()
                raise
            proxy_switched = True
            self._wait_health(self.config.public_health_url, self.manifest.release_sha, self.manifest.product_version)

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
                **self._feature_evidence(),
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
                "services": list(target_services),
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
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
                    active_env = self._slot_env(state.active_slot, state.image, state.release_sha, self.manifest.previous_feature_flags)
                    candidate_env = self._slot_env(
                        inactive, self.manifest.image, self.manifest.release_sha, self.manifest.feature_flags
                    )
                    if old_workers_stopped:
                        # Candidate consumers may already have admitted durable
                        # work. Pause and drain that exact set before stopping it;
                        # if this cannot be proved, retain the release lock and
                        # leave the sole candidate consumer set running for
                        # explicit operator recovery instead of risking loss or
                        # duplicate execution.
                        running_candidate_workers = self._running_worker_services(
                            inactive, candidate_env, WORKERS
                        )
                        if running_candidate_workers:
                            control_service = running_candidate_workers[0]
                            try:
                                self._pause_and_drain_workers(
                                    inactive, candidate_env, running_candidate_workers,
                                    control_service=control_service,
                                )
                            except Exception as drain_error:
                                rollback_status = "blocked_worker_drain"
                                retain_lock_for_recovery = True
                                rollback_error = f"candidate_worker_drain:{type(drain_error).__name__}"
                                raise ReleasePlaneError("candidate_worker_drain_unverified") from drain_error
                            self.runner.run(
                                self._compose(inactive, "stop", "--timeout",
                                              str(WORKER_STOP_GRACE_SECONDS), *running_candidate_workers),
                                env=candidate_env,
                            )
                    self.runner.run(
                        self._compose(inactive, "down", "--remove-orphans"), env=candidate_env
                    )
                    if old_workers_stopped:
                        self.runner.run(
                            self._compose(state.active_slot, "up", "-d", "--no-deps", *previous_workers),
                            env=active_env,
                        )
                        if previous_worker_bindings is not None:
                            rollback_bindings = self._worker_node_bindings(
                                state.active_slot, active_env, previous_workers
                            )
                            self._restore_worker_consumers(
                                state.active_slot, active_env, previous_workers, rollback_bindings
                            )
                    self._wait_health(
                        f"http://127.0.0.1:{self.config.slot_ports[state.active_slot]}/health",
                        state.release_sha,
                    )
                    if self.manifest.schema_version >= 2:
                        self._verify_services(state.active_slot, state.image, state.release_sha,
                                              self.manifest.previous_feature_flags, previous_services,
                                              allow_unsupported_disabled=True)
                    rollback_status = "completed"
                except Exception as rollback_failure:
                    if rollback_status != "blocked_worker_drain":
                        rollback_status = "failed"
                        rollback_error = f"rollback_failed:{type(rollback_failure).__name__}"
                    # Once the old worker set may have been stopped, any
                    # incomplete or ambiguous rollback must keep the lease so
                    # a concurrent release cannot hide the recovery state.
                    if old_workers_stopped and rollback_status != "completed":
                        retain_lock_for_recovery = True
            failure = {
                **self._feature_evidence(),
                "run_id": run_id,
                "release_id": self.manifest.release_id,
                "release_sha": self.manifest.release_sha,
                "previous_release_sha": state.release_sha,
                "status": "ROLLED_BACK" if rollback_status == "completed" else "FAILED",
                "failure": str(safe_error),
                "rollback": rollback_status,
                "rollback_error": rollback_error,
                "recovery_required": retain_lock_for_recovery,
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
            }
            self._write_evidence(failure)
            if safe_error is error:
                raise
            raise safe_error from error
        finally:
            if lock_fd is not None:
                if retain_lock_for_recovery:
                    marker = json.dumps({
                        "release_id": self.manifest.release_id,
                        "run_id": run_id,
                        "reason": "release_rollback_incomplete",
                    }, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
                    os.lseek(lock_fd, 0, os.SEEK_SET)
                    os.ftruncate(lock_fd, 0)
                    os.write(lock_fd, marker)
                    os.fsync(lock_fd)
                os.close(lock_fd)
                if not retain_lock_for_recovery:
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
