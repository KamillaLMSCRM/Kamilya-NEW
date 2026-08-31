#!/usr/bin/env python3
"""Build and verify a deterministic KZ release-plane upgrade bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
UPGRADE_ID_RE = re.compile(r"^RPLANE-[A-Z0-9][A-Z0-9-]{7,95}$")

FILES = {
    "controller": ("scripts/deploy/release_plane.py", "/opt/kamilya-release-plane/release_plane.py", 0o755),
    "upgrader": ("scripts/deploy/release_plane_upgrader.py", "/opt/kamilya-release-plane/release_plane_upgrader.py", 0o755),
    "slot_compose": ("infra/compose/kamilya-release-slot.yml", "/opt/kamilya-release-plane/kamilya-release-slot.yml", 0o644),
    "ct125_gate": ("infra/deploy/kamilya-ct125-release-gate.sh", "/opt/kamilya-release-plane/bin/kamilya-ct125-release-gate", 0o755),
    "release_runner": ("infra/deploy/kamilya-release-runner", "/usr/local/sbin/kamilya-release-runner", 0o755),
    "upgrade_runner": ("infra/deploy/kamilya-release-plane-upgrader", "/usr/local/sbin/kamilya-release-plane-upgrader", 0o755),
    "runner_service": ("infra/deploy/kamilya-release-runner.service", "/etc/systemd/system/kamilya-release-runner.service", 0o644),
    "host_config_schema": ("infra/deploy/kz-production.config.example.json", "validate-only", 0o644),
}


class BundleError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_identity(release_sha: str, upgrade_id: str, expected_controller: str) -> None:
    if not SHA_RE.fullmatch(release_sha):
        raise BundleError("release_sha_invalid")
    if not UPGRADE_ID_RE.fullmatch(upgrade_id):
        raise BundleError("upgrade_id_invalid")
    if not HASH_RE.fullmatch(expected_controller):
        raise BundleError("expected_controller_sha256_invalid")


def build(repo: Path, output: Path, release_sha: str, upgrade_id: str, expected_controller: str) -> dict:
    _validate_identity(release_sha, upgrade_id, expected_controller)
    if output.exists():
        raise BundleError("output_already_exists")
    output.mkdir(parents=True)
    records: dict[str, dict[str, object]] = {}
    for key, (source_name, destination, mode) in FILES.items():
        source = repo / source_name
        if not source.is_file() or source.is_symlink():
            raise BundleError(f"source_invalid:{key}")
        target_name = f"{key}.payload"
        target = output / target_name
        shutil.copyfile(source, target)
        records[key] = {
            "destination": destination,
            "mode": mode,
            "payload": target_name,
            "sha256": _sha256(target),
            "size": target.stat().st_size,
        }
    identity = {
        "schema_version": 1,
        "upgrade_id": upgrade_id,
        "release_sha": release_sha,
        "expected_controller_sha256": expected_controller,
        "files": records,
    }
    manifest = {**identity, "bundle_sha256": hashlib.sha256(_canonical(identity)).hexdigest()}
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def verify(bundle: Path) -> dict:
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError("manifest_invalid") from error
    expected_keys = {
        "schema_version", "upgrade_id", "release_sha", "expected_controller_sha256", "files", "bundle_sha256"
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise BundleError("manifest_keys_invalid")
    _validate_identity(
        manifest["release_sha"], manifest["upgrade_id"], manifest["expected_controller_sha256"]
    )
    if manifest["schema_version"] != 1 or set(manifest["files"]) != set(FILES):
        raise BundleError("manifest_contract_invalid")
    identity = {key: value for key, value in manifest.items() if key != "bundle_sha256"}
    if hashlib.sha256(_canonical(identity)).hexdigest() != manifest["bundle_sha256"]:
        raise BundleError("bundle_identity_mismatch")
    for key, (_, destination, mode) in FILES.items():
        record = manifest["files"][key]
        if not isinstance(record, dict) or set(record) != {"destination", "mode", "payload", "sha256", "size"}:
            raise BundleError(f"file_record_invalid:{key}")
        if record["destination"] != destination or record["mode"] != mode:
            raise BundleError(f"file_contract_mismatch:{key}")
        payload = bundle / record["payload"]
        if not payload.is_file() or payload.is_symlink():
            raise BundleError(f"payload_invalid:{key}")
        if payload.stat().st_size != record["size"] or _sha256(payload) != record["sha256"]:
            raise BundleError(f"payload_hash_mismatch:{key}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--repo", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--release-sha", required=True)
    build_parser.add_argument("--upgrade-id", required=True)
    build_parser.add_argument("--expected-controller-sha256", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (
            build(args.repo, args.output, args.release_sha, args.upgrade_id, args.expected_controller_sha256)
            if args.command == "build"
            else verify(args.bundle)
        )
        print(json.dumps({"status": "VALID", "upgrade_id": result["upgrade_id"], "bundle_sha256": result["bundle_sha256"]}, sort_keys=True))
        return 0
    except BundleError as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
