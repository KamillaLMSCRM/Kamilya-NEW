"""One fail-closed interface for a CT137 native frontend release.

The privileged host helper remains the deployment mechanism.  This module owns
the release-level contract around it: exact source/CI identity, immutable bundle
inspection, host capacity and rollback preflight, ordered execution, and
technical readback.  Product acceptance deliberately remains a separate Test
Runner responsibility.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMUM_RESERVE_BYTES = 512 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID_RE = re.compile(r"^REL-[A-Z0-9][A-Z0-9-]{7,95}$")
EXPECTED_API_URL = "https://api.kml.kz/api"
EXPECTED_SERVICE = "ct137-frontend"
GITHUB_REPOSITORY = "KamillaLMSCRM/Kamilya-NEW"
CI_WORKFLOW = "CI"
NATIVE_BUILD_WORKFLOW = "Build native frontend bundle"


class ReleaseBlocked(RuntimeError):
    """A release invariant failed before acceptance could be claimed."""


@dataclass(frozen=True)
class NativeArtifact:
    release_sha: str
    product_version: str
    archive: Path
    manifest: Path
    archive_sha256: str
    manifest_sha256: str
    archive_bytes: int
    expanded_bytes: int


@dataclass(frozen=True)
class ReleasePacket:
    schema_version: int
    release_id: str
    exact_sha: str
    source_branch: str
    target_environment: str
    target_services: tuple[str, ...]
    ci_run_id: int
    native_build_run_id: int
    expected_current_release: str
    rollback_sha: str
    migration_scope: str
    owner_approval: str
    smoke_scope: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ReleasePacket":
        expected = {
            "schema_version",
            "release_id",
            "exact_sha",
            "source_branch",
            "target_environment",
            "target_services",
            "ci_run_id",
            "native_build_run_id",
            "expected_current_release",
            "rollback_sha",
            "migration_scope",
            "owner_approval",
            "smoke_scope",
        }
        if set(raw) != expected:
            raise ReleaseBlocked("release_packet_fields_invalid")
        try:
            packet = cls(
                schema_version=raw["schema_version"],
                release_id=raw["release_id"],
                exact_sha=raw["exact_sha"],
                source_branch=raw["source_branch"],
                target_environment=raw["target_environment"],
                target_services=tuple(raw["target_services"]),
                ci_run_id=raw["ci_run_id"],
                native_build_run_id=raw["native_build_run_id"],
                expected_current_release=raw["expected_current_release"],
                rollback_sha=raw["rollback_sha"],
                migration_scope=raw["migration_scope"],
                owner_approval=raw["owner_approval"],
                smoke_scope=tuple(raw["smoke_scope"]),
            )
        except (KeyError, TypeError) as exc:
            raise ReleaseBlocked("release_packet_types_invalid") from exc
        packet.validate()
        return packet

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ReleaseBlocked("release_packet_schema_invalid")
        if not isinstance(self.release_id, str) or not RELEASE_ID_RE.fullmatch(
            self.release_id
        ):
            raise ReleaseBlocked("release_id_invalid")
        for label, value in (
            ("exact_sha", self.exact_sha),
            ("expected_current_release", self.expected_current_release),
            ("rollback_sha", self.rollback_sha),
        ):
            if not isinstance(value, str) or not SHA_RE.fullmatch(value):
                raise ReleaseBlocked(f"{label}_invalid")
        if len({self.exact_sha, self.expected_current_release, self.rollback_sha}) != 3:
            raise ReleaseBlocked("release_identity_not_distinct")
        if self.source_branch != "master":
            raise ReleaseBlocked("source_branch_invalid")
        if self.target_environment != "kz-production":
            raise ReleaseBlocked("target_environment_invalid")
        if self.target_services != (EXPECTED_SERVICE,):
            raise ReleaseBlocked("target_services_invalid")
        if self.migration_scope != "none":
            raise ReleaseBlocked("frontend_migration_scope_invalid")
        if not isinstance(self.owner_approval, str) or not self.owner_approval.strip():
            raise ReleaseBlocked("owner_approval_missing")
        if not isinstance(self.ci_run_id, int) or self.ci_run_id <= 0:
            raise ReleaseBlocked("ci_run_id_invalid")
        if (
            not isinstance(self.native_build_run_id, int)
            or self.native_build_run_id <= 0
        ):
            raise ReleaseBlocked("native_build_run_id_invalid")
        if self.smoke_scope != ("/healthz", "/login", "api-health"):
            raise ReleaseBlocked("technical_smoke_scope_invalid")

    def to_mapping(self) -> dict[str, Any]:
        result = asdict(self)
        result["target_services"] = list(self.target_services)
        result["smoke_scope"] = list(self.smoke_scope)
        return result


class RepositoryProbe(Protocol):
    def verify(self, packet: ReleasePacket, product_version: str) -> dict[str, Any]: ...


class GithubProbe(Protocol):
    def verify(self, packet: ReleasePacket) -> dict[str, Any]: ...


class HostProbe(Protocol):
    def status(self) -> dict[str, Any]: ...
    def boundary(self, rollback_sha: str) -> dict[str, Any]: ...
    def inventory(self) -> dict[str, Any]: ...
    def stage(self, path: Path, digest: str) -> None: ...
    def deploy(
        self, release_sha: str, previous_sha: str, archive_digest: str
    ) -> None: ...


class PublicProbe(Protocol):
    def verify(self, release_sha: str) -> dict[str, Any]: ...


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_release_packet(path: Path, expected_sha256: str) -> ReleasePacket:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ReleaseBlocked("release_packet_digest_invalid")
    try:
        content = path.resolve(strict=True).read_bytes()
    except OSError as exc:
        raise ReleaseBlocked("release_packet_unreadable") from exc
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ReleaseBlocked("release_packet_digest_mismatch")
    try:
        payload = json.loads(content)
    except (UnicodeError, ValueError) as exc:
        raise ReleaseBlocked("release_packet_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ReleaseBlocked("release_packet_json_invalid")
    return ReleasePacket.from_mapping(payload)


def parse_host_status(output: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and "current_sha" in payload:
            rows.append(payload)
    if len(rows) != 1:
        raise ReleaseBlocked("ct137_status_ambiguous")
    row = rows[0]
    if set(row) != {
        "current_sha",
        "marker_sha",
        "nginx_sha_occurrences",
        "kamilya_web_running",
    }:
        raise ReleaseBlocked("ct137_status_fields_invalid")
    return row


def parse_boundary(output: str, rollback_sha: str) -> dict[str, Any]:
    lines = output.splitlines()
    free = [
        line.removeprefix("FREE_KB=") for line in lines if line.startswith("FREE_KB=")
    ]
    if (
        lines.count("BOUNDARY_PASS restricted_helper_only") != 1
        or lines.count("ROLLBACK_RELEASE_PRESENT") != 1
        or len(free) != 1
        or not free[0].isdigit()
    ):
        raise ReleaseBlocked("ct137_boundary_output_invalid")
    envelope = []
    for line in lines:
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and "boundary_exit" in payload:
            envelope.append(payload)
    if len(envelope) != 1 or envelope[0] != {"boundary_exit": 0, "stderr_bytes": 0}:
        raise ReleaseBlocked("ct137_boundary_command_failed")
    return {
        "boundary": "PASS",
        "free_kib": int(free[0]),
        "rollback_sha": rollback_sha,
        "rollback_present": True,
    }


def parse_inventory(output: str) -> dict[str, Any]:
    releases: list[str] = []
    staged: list[dict[str, Any]] = []
    free: list[str] = []
    envelopes: list[dict[str, Any]] = []
    staged_name = re.compile(
        r"^frontend-native-[0-9a-f]{40}\.(?:tar\.gz|manifest\.json)$"
    )
    for line in output.splitlines():
        if line.startswith("RELEASE "):
            value = line.removeprefix("RELEASE ")
            if not SHA_RE.fullmatch(value) or value in releases:
                raise ReleaseBlocked("ct137_inventory_release_invalid")
            releases.append(value)
        elif line.startswith("STAGED "):
            parts = line.split(" ")
            if (
                len(parts) != 3
                or not staged_name.fullmatch(parts[1])
                or not parts[2].isdigit()
            ):
                raise ReleaseBlocked("ct137_inventory_staged_invalid")
            staged.append({"name": parts[1], "bytes": int(parts[2])})
        elif line.startswith("FREE_KB="):
            free.append(line.removeprefix("FREE_KB="))
        else:
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict) and "inventory_exit" in payload:
                envelopes.append(payload)
    if (
        len(free) != 1
        or not free[0].isdigit()
        or len(envelopes) != 1
        or envelopes[0] != {"inventory_exit": 0, "stderr_bytes": 0}
    ):
        raise ReleaseBlocked("ct137_inventory_output_invalid")
    return {"releases": releases, "staged": staged, "free_kib": int(free[0])}


def _deploy_helper() -> Any:
    path = REPO_ROOT / "infra/deploy/kamilya-web-deploy.py"
    spec = importlib.util.spec_from_file_location("kamilya_web_deploy_contract", path)
    if spec is None or spec.loader is None:
        raise ReleaseBlocked("deploy_helper_import_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inspect_native_artifact(directory: Path, release_sha: str) -> NativeArtifact:
    if not SHA_RE.fullmatch(release_sha):
        raise ReleaseBlocked("artifact_release_sha_invalid")
    directory = directory.resolve(strict=True)
    archive = directory / f"frontend-native-{release_sha}.tar.gz"
    manifest = directory / f"frontend-native-{release_sha}.manifest.json"
    if not manifest.exists():
        manifest = directory / "manifest.json"
    checksum = directory / "bundle.sha256"
    if not archive.is_file() or not manifest.is_file() or not checksum.is_file():
        raise ReleaseBlocked("artifact_files_missing")
    archive_digest = _digest(archive)
    expected_checksum = f"{archive_digest}  {archive.name}\n"
    if checksum.read_text(encoding="ascii") != expected_checksum:
        raise ReleaseBlocked("artifact_checksum_file_mismatch")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseBlocked("artifact_manifest_invalid") from exc
    if (
        payload.get("release_sha") != release_sha
        or payload.get("sha256") != archive_digest
    ):
        raise ReleaseBlocked("artifact_manifest_binding_mismatch")
    if payload.get("api_url") != EXPECTED_API_URL:
        raise ReleaseBlocked("artifact_api_url_mismatch")
    if (payload.get("platform"), payload.get("arch"), payload.get("libc")) != (
        "linux",
        "x64",
        "musl",
    ):
        raise ReleaseBlocked("artifact_runtime_mismatch")
    if not re.fullmatch(r"v?20\.\d+\.\d+", str(payload.get("node_version", ""))):
        raise ReleaseBlocked("artifact_node20_required")
    product_version = payload.get("product_version")
    if not isinstance(product_version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", product_version
    ):
        raise ReleaseBlocked("artifact_product_version_invalid")
    helper = _deploy_helper()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            layout = helper.validate_archive_members(tar.getmembers())
            helper.require_artifact_shape(layout)
            helper.validate_identity(tar, layout, release_sha)
            expanded_bytes = helper.expanded_size(layout)
    except (tarfile.TarError, OSError, helper.DeployError) as exc:
        raise ReleaseBlocked(f"artifact_archive_invalid:{exc}") from exc
    return NativeArtifact(
        release_sha=release_sha,
        product_version=product_version,
        archive=archive,
        manifest=manifest,
        archive_sha256=archive_digest,
        manifest_sha256=_digest(manifest),
        archive_bytes=archive.stat().st_size,
        expanded_bytes=expanded_bytes,
    )


def required_capacity_bytes(artifact: NativeArtifact) -> int:
    """Conservative pre-staging budget: incoming, snapshot, extraction, reserve."""
    return (
        2 * artifact.archive_bytes
        + artifact.manifest.stat().st_size
        + artifact.expanded_bytes
        + MINIMUM_RESERVE_BYTES
    )


def _require_host_status(status: Mapping[str, Any], expected_sha: str) -> None:
    if (
        status.get("current_sha") != expected_sha
        or status.get("marker_sha") != expected_sha
        or status.get("nginx_sha_occurrences") != 2
        or status.get("kamilya_web_running") is not True
    ):
        raise ReleaseBlocked("ct137_current_identity_mismatch")


class NativeReleaseOrchestrator:
    def __init__(
        self,
        *,
        repository: RepositoryProbe,
        github: GithubProbe,
        host: HostProbe,
        public: PublicProbe,
    ) -> None:
        self.repository = repository
        self.github = github
        self.host = host
        self.public = public

    def preflight(self, packet: ReleasePacket, artifact_dir: Path) -> dict[str, Any]:
        packet.validate()
        artifact = inspect_native_artifact(artifact_dir, packet.exact_sha)
        repository = self.repository.verify(packet, artifact.product_version)
        github = self.github.verify(packet)
        status = self.host.status()
        _require_host_status(status, packet.expected_current_release)
        inventory = self.host.inventory()
        releases = inventory.get("releases")
        if (
            not isinstance(releases, list)
            or packet.expected_current_release not in releases
            or packet.rollback_sha not in releases
        ):
            raise ReleaseBlocked("ct137_release_inventory_mismatch")
        boundary = self.host.boundary(packet.rollback_sha)
        if (
            boundary.get("boundary") != "PASS"
            or boundary.get("rollback_present") is not True
        ):
            raise ReleaseBlocked("ct137_boundary_failed")
        if boundary.get("rollback_sha") != packet.rollback_sha:
            raise ReleaseBlocked("ct137_rollback_identity_mismatch")
        boundary_free_kib = boundary.get("free_kib")
        inventory_free_kib = inventory.get("free_kib")
        if not isinstance(boundary_free_kib, int) or not isinstance(
            inventory_free_kib, int
        ):
            raise ReleaseBlocked("ct137_capacity_readback_invalid")
        free_kib = min(boundary_free_kib, inventory_free_kib)
        if free_kib * 1024 < required_capacity_bytes(artifact):
            raise ReleaseBlocked("insufficient_ct137_capacity")
        return {
            "status": "READY",
            "release_id": packet.release_id,
            "release_sha": packet.exact_sha,
            "previous_release_sha": packet.expected_current_release,
            "rollback_sha": packet.rollback_sha,
            "artifact": {
                "archive_sha256": artifact.archive_sha256,
                "manifest_sha256": artifact.manifest_sha256,
                "archive_bytes": artifact.archive_bytes,
                "expanded_bytes": artifact.expanded_bytes,
                "required_capacity_bytes": required_capacity_bytes(artifact),
            },
            "repository": repository,
            "github": github,
            "host": {
                "status": status,
                "inventory": inventory,
                "boundary": boundary,
                "conservative_free_kib": free_kib,
            },
        }

    def execute(self, packet: ReleasePacket, artifact_dir: Path) -> dict[str, Any]:
        preflight = self.preflight(packet, artifact_dir)
        artifact = inspect_native_artifact(artifact_dir, packet.exact_sha)
        scoped_manifest = (
            artifact.manifest.parent
            / f"frontend-native-{packet.exact_sha}.manifest.json"
        )
        created_scoped_manifest = scoped_manifest != artifact.manifest
        if created_scoped_manifest:
            if scoped_manifest.exists():
                if _digest(scoped_manifest) != artifact.manifest_sha256:
                    raise ReleaseBlocked("sha_scoped_manifest_conflict")
            else:
                shutil.copyfile(artifact.manifest, scoped_manifest)
        try:
            self.host.stage(artifact.archive, artifact.archive_sha256)
            self.host.stage(scoped_manifest, artifact.manifest_sha256)
            self.host.deploy(
                packet.exact_sha,
                packet.expected_current_release,
                artifact.archive_sha256,
            )
        finally:
            if created_scoped_manifest:
                scoped_manifest.unlink(missing_ok=True)
        after = self.host.status()
        _require_host_status(after, packet.exact_sha)
        after_inventory = self.host.inventory()
        after_releases = after_inventory.get("releases")
        if (
            not isinstance(after_releases, list)
            or packet.exact_sha not in after_releases
            or packet.rollback_sha not in after_releases
            or not isinstance(after_inventory.get("free_kib"), int)
        ):
            raise ReleaseBlocked("ct137_post_deploy_inventory_mismatch")
        technical = self.public.verify(packet.exact_sha)
        if technical.get("release_sha") != packet.exact_sha:
            raise ReleaseBlocked("public_release_identity_mismatch")
        return {
            "status": "RELEASE_OK",
            "release_id": packet.release_id,
            "release_sha": packet.exact_sha,
            "previous_release_sha": packet.expected_current_release,
            "rollback_sha": packet.rollback_sha,
            "preflight": preflight,
            "host_readback": after,
            "host_inventory_readback": after_inventory,
            "technical_readback": technical,
            "product_acceptance": "SEPARATE_TEST_RUNNER_REQUIRED",
        }


def _run(
    command: list[str], *, env: Mapping[str, str] | None = None, timeout: int = 300
) -> str:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=None if env is None else dict(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        reason = completed.stderr.strip().splitlines()[-1:] or ["no_stderr"]
        raise ReleaseBlocked(
            "command_failed:"
            + Path(command[0]).name
            + ":"
            + re.sub(r"[^a-zA-Z0-9_.:-]", "_", reason[0])[:160]
        )
    return completed.stdout


class LocalRepositoryProbe:
    def verify(self, packet: ReleasePacket, product_version: str) -> dict[str, Any]:
        remote_sha = _run(
            ["git", "rev-parse", f"origin/{packet.source_branch}"]
        ).strip()
        if remote_sha != packet.exact_sha:
            raise ReleaseBlocked("remote_branch_sha_mismatch")
        version = _run(["git", "show", f"{packet.exact_sha}:VERSION"]).strip()
        if version != product_version:
            raise ReleaseBlocked("source_product_version_mismatch")
        try:
            web_package = json.loads(
                _run(["git", "show", f"{packet.exact_sha}:apps/web/package.json"])
            )
        except ValueError as exc:
            raise ReleaseBlocked("source_web_package_invalid") from exc
        if web_package.get("version") != product_version:
            raise ReleaseBlocked("source_web_version_mismatch")
        tag = f"v{product_version}"
        tag_sha = _run(["git", "rev-parse", f"refs/tags/{tag}^{{}}"]).strip()
        if tag_sha != packet.exact_sha:
            raise ReleaseBlocked("release_tag_sha_mismatch")
        return {"remote_branch_sha": remote_sha, "tag": tag, "tag_sha": tag_sha}


def _canonical_github_environment() -> dict[str, str]:
    candidates = [
        REPO_ROOT / ".env",
        Path(r"C:\Kamilya New\Kamilya-NEW\.env"),
        Path(r"C:\Kamilya New\.env"),
    ]
    token = None
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8-sig").splitlines():
            if raw.startswith("GITHUB_TOKEN="):
                token = raw.split("=", 1)[1].strip().strip("\"'")
                break
        if token:
            break
    if not token:
        raise ReleaseBlocked("canonical_github_token_missing")
    environment = os.environ.copy()
    environment["GITHUB_TOKEN"] = token
    environment.pop("GH_TOKEN", None)
    return environment


class GithubActionsProbe:
    def __init__(self) -> None:
        self.environment = _canonical_github_environment()

    def _api(self, endpoint: str) -> Any:
        output = _run(
            ["gh", "api", f"repos/{GITHUB_REPOSITORY}/{endpoint}"],
            env=self.environment,
        )
        try:
            return json.loads(output)
        except ValueError as exc:
            raise ReleaseBlocked("github_response_invalid") from exc

    def _run_identity(
        self,
        run_id: int,
        workflow: str,
        sha: str,
        allowed_branches: tuple[str, ...],
    ) -> dict[str, Any]:
        payload = self._api(f"actions/runs/{run_id}")
        if (
            payload.get("name") != workflow
            or payload.get("head_sha") != sha
            or payload.get("head_branch") not in allowed_branches
            or payload.get("status") != "completed"
            or payload.get("conclusion") != "success"
        ):
            raise ReleaseBlocked("github_run_identity_mismatch")
        return {
            "id": run_id,
            "workflow": workflow,
            "head_sha": sha,
            "head_branch": payload["head_branch"],
            "conclusion": "success",
        }

    def verify(self, packet: ReleasePacket) -> dict[str, Any]:
        ci = self._run_identity(
            packet.ci_run_id,
            CI_WORKFLOW,
            packet.exact_sha,
            (packet.source_branch,),
        )
        native = self._run_identity(
            packet.native_build_run_id,
            NATIVE_BUILD_WORKFLOW,
            packet.exact_sha,
            (packet.source_branch, "dev"),
        )
        artifacts = self._api(f"actions/runs/{packet.native_build_run_id}/artifacts")
        expected_name = f"frontend-native-{packet.exact_sha}"
        matches = [
            item
            for item in artifacts.get("artifacts", [])
            if item.get("name") == expected_name and item.get("expired") is False
        ]
        if len(matches) != 1:
            raise ReleaseBlocked("native_build_artifact_missing_or_ambiguous")
        return {
            "ci": ci,
            "native_build": native,
            "artifact_id": matches[0].get("id"),
            "artifact_name": expected_name,
        }

    def download(self, packet: ReleasePacket, destination: Path) -> Path:
        destination = destination.resolve()
        if not destination.is_relative_to(REPO_ROOT):
            raise ReleaseBlocked("artifact_destination_outside_checkout")
        if destination.exists() and any(destination.iterdir()):
            return destination
        destination.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "gh",
                "run",
                "download",
                str(packet.native_build_run_id),
                "--repo",
                GITHUB_REPOSITORY,
                "--name",
                f"frontend-native-{packet.exact_sha}",
                "--dir",
                str(destination),
            ],
            env=self.environment,
        )
        return destination


class Ct137HostCli:
    def __init__(self) -> None:
        self.controller = REPO_ROOT / "scripts/ops/ct137_native_deploy.py"

    def _controller(self, *arguments: str) -> str:
        return _run([sys.executable, str(self.controller), *arguments], timeout=360)

    def status(self) -> dict[str, Any]:
        return parse_host_status(self._controller("--status"))

    def boundary(self, rollback_sha: str) -> dict[str, Any]:
        return parse_boundary(
            self._controller(
                "--verify-boundary", "--expected-rollback-sha", rollback_sha
            ),
            rollback_sha,
        )

    def inventory(self) -> dict[str, Any]:
        return parse_inventory(self._controller("--inventory"))

    def stage(self, path: Path, digest: str) -> None:
        self._controller(
            "--stage-file", str(path.resolve(strict=True)), "--expected-sha256", digest
        )

    def deploy(self, release_sha: str, previous_sha: str, archive_digest: str) -> None:
        self._controller("--deploy", release_sha, previous_sha, archive_digest)


class PublicHttpProbe:
    @staticmethod
    def _request(url: str) -> tuple[int, Mapping[str, str], bytes]:
        request = urllib.request.Request(
            url, headers={"User-Agent": "KamilyaReleaseReadback/1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.headers, response.read(1024 * 1024)
        except (OSError, urllib.error.HTTPError) as exc:
            raise ReleaseBlocked("public_http_readback_failed") from exc

    def verify(self, release_sha: str) -> dict[str, Any]:
        health_status, health_headers, health_body = self._request(
            "https://app.kml.kz/healthz"
        )
        login_status, _, login_body = self._request("https://app.kml.kz/login")
        api_status, _, api_body = self._request("https://api.kml.kz/health")
        if (
            health_status != 200
            or health_headers.get("X-Kamilya-Release") != release_sha
            or release_sha.encode("ascii") not in health_body
        ):
            raise ReleaseBlocked("public_health_release_mismatch")
        if login_status != 200 or b"<html" not in login_body.lower():
            raise ReleaseBlocked("public_login_readback_failed")
        if api_status != 200 or not api_body:
            raise ReleaseBlocked("public_api_health_failed")
        return {
            "release_sha": release_sha,
            "healthz": health_status,
            "login": login_status,
            "api_health": api_status,
        }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    if not path.is_relative_to(REPO_ROOT):
        raise ReleaseBlocked("evidence_path_outside_checkout")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "execute"))
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    packet = load_release_packet(args.packet, args.packet_sha256)
    try:
        github = GithubActionsProbe()
        artifact_dir = args.artifact_dir or (
            REPO_ROOT / ".release-evidence" / packet.release_id / "native-build"
        )
        artifact_dir = github.download(packet, artifact_dir)
        orchestrator = NativeReleaseOrchestrator(
            repository=LocalRepositoryProbe(),
            github=github,
            host=Ct137HostCli(),
            public=PublicHttpProbe(),
        )
        result = (
            orchestrator.preflight(packet, artifact_dir)
            if args.mode == "preflight"
            else orchestrator.execute(packet, artifact_dir)
        )
    except ReleaseBlocked as exc:
        _write_json(
            args.evidence,
            {
                "status": "BLOCKED",
                "mode": args.mode,
                "release_id": packet.release_id,
                "release_sha": packet.exact_sha,
                "reason": str(exc),
                "state_reconciliation_required": args.mode == "execute",
            },
        )
        raise
    _write_json(args.evidence, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleaseBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from None
