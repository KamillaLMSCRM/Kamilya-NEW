#!/usr/bin/env python3
"""Atomic, fail-closed installer for the VM126 Kamilya release plane."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_ROOT = Path("/opt/actions-runner/_work/_temp/kamilya-release-plane-upgrade")
STATE_ROOT = Path("/var/lib/kamilya-release-plane/upgrades")
UPGRADE_LOCK = Path("/run/lock/kamilya-release-plane-upgrade.lock")
RELEASE_LOCK = Path("/run/lock/kamilya-release-plane.lock")
CONFIG = Path("/etc/kamilya-release-plane/config.json")
TARGETS = {
    "controller": (Path("/opt/kamilya-release-plane/release_plane.py"), 0o755),
    "upgrader": (Path("/opt/kamilya-release-plane/release_plane_upgrader.py"), 0o755),
    "slot_compose": (Path("/opt/kamilya-release-plane/kamilya-release-slot.yml"), 0o644),
    "ct125_gate": (Path("/opt/kamilya-release-plane/bin/kamilya-ct125-release-gate"), 0o755),
    "release_runner": (Path("/usr/local/sbin/kamilya-release-runner"), 0o755),
    "upgrade_runner": (Path("/usr/local/sbin/kamilya-release-plane-upgrader"), 0o755),
    "runner_service": (Path("/etc/systemd/system/kamilya-release-runner.service"), 0o644),
    "host_config_schema": (None, 0o644),
}


class UpgradeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def run(args: list[str]) -> None:
    result = subprocess.run(args, check=False, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise UpgradeError(f"validation_command_failed:{Path(args[0]).name}")


def atomic_install(source: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle, source.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, 0, 0)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class Upgrader:
    def __init__(self, bundle_root: Path = BUNDLE_ROOT, targets=TARGETS) -> None:
        self.bundle_root = bundle_root
        self.targets = targets
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        path = self.bundle_root / "manifest.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UpgradeError("manifest_invalid") from error
        expected = {"schema_version", "upgrade_id", "release_sha", "expected_controller_sha256", "files", "bundle_sha256"}
        if not isinstance(data, dict) or set(data) != expected or data.get("schema_version") != 1:
            raise UpgradeError("manifest_contract_invalid")
        if set(data.get("files", {})) != set(self.targets):
            raise UpgradeError("manifest_file_set_invalid")
        identity = {key: value for key, value in data.items() if key != "bundle_sha256"}
        if hashlib.sha256(canonical(identity)).hexdigest() != data["bundle_sha256"]:
            raise UpgradeError("bundle_identity_mismatch")
        return data

    def _payload(self, key: str) -> Path:
        record = self.manifest["files"][key]
        target, mode = self.targets[key]
        expected_destination = str(target) if target else "validate-only"
        if set(record) != {"destination", "mode", "payload", "sha256", "size"}:
            raise UpgradeError(f"file_record_invalid:{key}")
        if record["destination"] != expected_destination or record["mode"] != mode:
            raise UpgradeError(f"file_contract_mismatch:{key}")
        payload = self.bundle_root / record["payload"]
        if not payload.is_file() or payload.is_symlink():
            raise UpgradeError(f"payload_invalid:{key}")
        if payload.stat().st_size != record["size"] or sha256(payload) != record["sha256"]:
            raise UpgradeError(f"payload_hash_mismatch:{key}")
        return payload

    def _already_installed(self) -> bool:
        for key, (target, _) in self.targets.items():
            if target is None:
                continue
            if not target.is_file() or sha256(target) != self.manifest["files"][key]["sha256"]:
                return False
        return True

    def validate(self, *, production_owner_check: bool = True) -> dict:
        manifest_path = self.bundle_root / "manifest.json"
        if production_owner_check:
            runner_uid = pwd.getpwnam("kamilya-release-runner").pw_uid
            if manifest_path.is_symlink() or manifest_path.stat().st_uid != runner_uid:
                raise UpgradeError("manifest_owner_invalid")
        if manifest_path.stat().st_size > 32768:
            raise UpgradeError("manifest_too_large")
        payloads = {key: self._payload(key) for key in self.targets}
        if RELEASE_LOCK.exists():
            raise UpgradeError("application_release_in_progress")
        if not self._already_installed():
            controller = self.targets["controller"][0]
            if controller is None or not controller.is_file():
                raise UpgradeError("installed_controller_missing")
            if sha256(controller) != self.manifest["expected_controller_sha256"]:
                raise UpgradeError("expected_controller_hash_mismatch")
        current_config = json.loads(CONFIG.read_text(encoding="utf-8"))
        schema_config = json.loads(payloads["host_config_schema"].read_text(encoding="utf-8"))
        if set(current_config) != set(schema_config):
            raise UpgradeError("host_config_schema_mismatch")
        run(["/usr/bin/python3", "-m", "py_compile", str(payloads["controller"]), str(payloads["upgrader"])])
        for key in ("ct125_gate", "release_runner", "upgrade_runner"):
            run(["/usr/bin/bash", "-n", str(payloads[key])])
        run(["/usr/bin/systemd-analyze", "verify", str(payloads["runner_service"])])
        return {"status": "VALID", "upgrade_id": self.manifest["upgrade_id"], "bundle_sha256": self.manifest["bundle_sha256"]}

    def execute(self) -> dict:
        self.validate()
        if self._already_installed():
            return {"status": "ALREADY_INSTALLED", "upgrade_id": self.manifest["upgrade_id"], "bundle_sha256": self.manifest["bundle_sha256"]}
        lock_fd = None
        upgrade_dir = STATE_ROOT / self.manifest["upgrade_id"]
        backup_dir = upgrade_dir / "backup"
        metadata: dict[str, dict[str, object]] = {}
        service_changed = False
        try:
            try:
                lock_fd = os.open(UPGRADE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as error:
                raise UpgradeError("upgrade_lock_already_held") from error
            if upgrade_dir.exists():
                raise UpgradeError("upgrade_id_already_used")
            backup_dir.mkdir(parents=True, mode=0o700)
            for key, (target, _) in self.targets.items():
                if target is None:
                    continue
                existed = target.is_file()
                metadata[key] = {"existed": existed, "mode": (target.stat().st_mode & 0o777) if existed else None}
                if existed:
                    shutil.copyfile(target, backup_dir / key)
                    os.chmod(backup_dir / key, 0o600)
                if key == "runner_service":
                    service_changed = not existed or sha256(target) != self.manifest["files"][key]["sha256"]
            for key, (target, mode) in self.targets.items():
                if target is not None:
                    atomic_install(self._payload(key), target, mode)
            run(["/usr/bin/systemctl", "daemon-reload"])
            run(["/usr/bin/python3", str(self.targets["controller"][0]), "--help"])
            for key, (target, _) in self.targets.items():
                if target is not None and sha256(target) != self.manifest["files"][key]["sha256"]:
                    raise UpgradeError(f"installed_hash_mismatch:{key}")
            receipt = {
                "schema_version": 1,
                "status": "INSTALLED",
                "upgrade_id": self.manifest["upgrade_id"],
                "release_sha": self.manifest["release_sha"],
                "bundle_sha256": self.manifest["bundle_sha256"],
                "runner_restart_required": service_changed,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
            receipt_path = upgrade_dir / "receipt.json"
            receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            os.chmod(receipt_path, 0o600)
            return receipt
        except Exception as error:
            if metadata:
                for key, values in metadata.items():
                    target = self.targets[key][0]
                    if target is None:
                        continue
                    if values["existed"]:
                        atomic_install(backup_dir / key, target, int(values["mode"]))
                    else:
                        target.unlink(missing_ok=True)
                subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=False, capture_output=True)
            if isinstance(error, UpgradeError):
                raise
            raise UpgradeError(f"unexpected_failure:{type(error).__name__}") from error
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                UPGRADE_LOCK.unlink(missing_ok=True)

    def readback(self) -> dict:
        if not self._already_installed():
            raise UpgradeError("installed_bundle_mismatch")
        return {"status": "INSTALLED", "upgrade_id": self.manifest["upgrade_id"], "bundle_sha256": self.manifest["bundle_sha256"]}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1 or argv[0] not in {"validate", "execute", "readback"}:
        return 2
    try:
        upgrader = Upgrader()
        result = getattr(upgrader, argv[0])()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (UpgradeError, OSError, json.JSONDecodeError) as error:
        reason = str(error) if isinstance(error, UpgradeError) else f"unexpected_failure:{type(error).__name__}"
        print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
