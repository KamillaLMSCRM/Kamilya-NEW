#!/usr/bin/python3 -I
"""Privileged, native CT137 deployment helper for an already-built web artifact.

Install the reviewed file only after the owner-approved distro Python 3.10+
dependency is present on webkml, using this fixed command:
  doas install -o root -g root -m 0750 /home/kamilya-admin/incoming/kamilya-web-deploy.py /usr/local/sbin/kamilya-web-deploy

The installed command supports deployment and explicitly approved maintenance:
  doas /usr/local/sbin/kamilya-web-deploy status
  doas /usr/local/sbin/kamilya-web-deploy deploy <40-hex-sha> <expected-old-sha> <64-hex-archive-sha256>
  doas /usr/local/sbin/kamilya-web-deploy cleanup-plan <obsolete-sha> <current-sha> <rollback-sha>
  doas /usr/local/sbin/kamilya-web-deploy cleanup <envelope-sha256>

It deliberately does not build, install dependencies, run package scripts, use
containers, contact a network endpoint, or touch the landing service.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

try:  # Windows can run the pure parser tests; Alpine deploy requires fcntl.
    import fcntl
except ImportError:  # pragma: no cover - exercised by the Windows test import.
    fcntl = None  # type: ignore[assignment]


INSTALL_COMMAND = (
    "doas install -o root -g root -m 0750 "
    "/home/kamilya-admin/incoming/kamilya-web-deploy.py "
    "/usr/local/sbin/kamilya-web-deploy"
)
INSTALLED_PATH = Path("/usr/local/sbin/kamilya-web-deploy")
HOSTNAME = "webkml"
WEB_USER = "kamilya-web"
BASE = Path("/opt/kamilya-web")
RELEASES = BASE / "releases"
CURRENT = BASE / "current"
MARKER = Path("/etc/kamilya-web-release")
NGINX = Path("/etc/nginx/http.d/default.conf")
INCOMING = Path("/home/kamilya-admin/incoming")
RECEIPTS = BASE / "cleanup-receipts"
RECOVERY_RECORDS = BASE / "recovery-evidence"
LOCK = Path("/run/lock/kamilya-web-deploy.lock")
MINIMUM_RESERVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 100_000
COMMAND_TIMEOUT_SECONDS = 30
STARTUP_DEADLINE_SECONDS = 60
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FILES = ("package.json", "next.config.js", "security-headers.js")
TOP_LEVEL_ALLOWLIST = frozenset({".next", "node_modules", "public", *REQUIRED_FILES, "release-identity.json"})
SIDECAR_FIELDS = frozenset(
    {"release_sha", "product_version", "node_version", "platform", "arch", "libc", "api_url", "sha256"}
)


class DeployError(RuntimeError):
    """An expected fail-closed deployment error."""


@dataclass(frozen=True)
class ArchiveLayout:
    members: dict[str, tarfile.TarInfo]
    directories: frozenset[str]


def require_hex(value: str, label: str, length: int) -> str:
    matcher = SHA_RE if length == 40 else HASH_RE
    if not matcher.fullmatch(value):
        raise DeployError(f"invalid_{label}")
    return value


def archive_for(sha: str) -> Path:
    require_hex(sha, "sha", 40)
    return INCOMING / f"frontend-native-{sha}.tar.gz"


def sidecar_for(sha: str) -> Path:
    require_hex(sha, "sha", 40)
    return INCOMING / f"frontend-native-{sha}.manifest.json"


def normal_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise DeployError("unsafe_archive_path")
    if name.endswith("/"):
        name = name[:-1]
    if not name or "//" in name:
        raise DeployError("unsafe_archive_path")
    parts = PurePosixPath(name).parts
    if any(part in ("", ".", "..") for part in parts):
        raise DeployError("unsafe_archive_path")
    return "/".join(parts)


def resolve_relative(base: str, linkname: str) -> str:
    if not linkname or "\x00" in linkname or "\\" in linkname or linkname.startswith("/"):
        raise DeployError("unsafe_archive_link")
    combined = posixpath.normpath(posixpath.join(base, linkname))
    if combined in ("", ".") or combined == ".." or combined.startswith("../") or combined.startswith("/"):
        raise DeployError("unsafe_archive_link")
    return combined


def _parents(name: str) -> Iterable[str]:
    parts = name.split("/")
    for index in range(1, len(parts)):
        yield "/".join(parts[:index])


def _safe_member_type(member: tarfile.TarInfo) -> bool:
    return member.isdir() or member.isreg() or member.issym() or member.islnk()


def validate_archive_members(members: Iterable[tarfile.TarInfo]) -> ArchiveLayout:
    """Accept only regular files, directories, and confined relative symlinks."""
    entries: dict[str, tarfile.TarInfo] = {}
    directories: set[str] = set()
    for member in members:
        if len(entries) >= MAX_MEMBERS:
            raise DeployError("archive_member_limit_exceeded")
        name = normal_member_name(member.name)
        if not _safe_member_type(member) or member.size < 0:
            raise DeployError("unsafe_archive_member_type")
        if name in entries:
            raise DeployError("duplicate_archive_path")
        entries[name] = member
        directories.update(_parents(name))
        if member.isdir():
            directories.add(name)
    for name, member in entries.items():
        if any(entries[parent].issym() for parent in _parents(name) if parent in entries):
            raise DeployError("archive_member_below_symlink")
        if member.issym():
            resolve_relative(posixpath.dirname(name), member.linkname)

    def target_of(name: str, require_regular: bool) -> str:
        current = name
        seen: set[str] = set()
        for _ in range(41):
            if current in seen:
                raise DeployError("symlink_cycle")
            seen.add(current)
            entry = entries.get(current)
            if entry is None:
                if current in directories and not require_regular:
                    return current
                raise DeployError("dangling_archive_symlink")
            if entry.isreg():
                return current
            if entry.isdir():
                if not require_regular:
                    return current
                raise DeployError("link_target_not_regular")
            if entry.issym():
                current = resolve_relative(posixpath.dirname(current), entry.linkname)
                continue
            if entry.islnk():
                current = normal_member_name(entry.linkname)
                continue
            raise DeployError("link_target_not_regular")
        raise DeployError("symlink_chain_too_deep")

    for name, member in entries.items():
        if member.issym():
            target_of(resolve_relative(posixpath.dirname(name), member.linkname), require_regular=False)
        if member.islnk():
            if not name.startswith("node_modules/"):
                raise DeployError("hardlink_outside_node_modules")
            target_of(normal_member_name(member.linkname), require_regular=True)
    return ArchiveLayout(entries, frozenset(directories))


def expanded_size(layout: ArchiveLayout) -> int:
    total = sum(member.size for member in layout.members.values() if member.isreg())
    if total > MAX_EXPANDED_BYTES:
        raise DeployError("archive_expanded_size_limit_exceeded")
    return total


def _is_regular(layout: ArchiveLayout, name: str) -> bool:
    member = layout.members.get(name)
    return member is not None and member.isreg()


def _has_directory(layout: ArchiveLayout, name: str) -> bool:
    member = layout.members.get(name)
    return name in layout.directories or (member is not None and member.issym())


def require_artifact_shape(layout: ArchiveLayout) -> None:
    missing = [name for name in REQUIRED_FILES if not _is_regular(layout, name)]
    next_entry = layout.members.get(".next")
    if missing or (next_entry is not None and next_entry.issym()) or not _has_directory(layout, ".next") or not _has_directory(layout, "node_modules"):
        raise DeployError("artifact_shape_invalid")
    if any(name.split("/", 1)[0] not in TOP_LEVEL_ALLOWLIST for name in layout.members):
        raise DeployError("unexpected_top_level_content")
    if any(name == ".git" or name.startswith(".git/") for name in layout.members):
        raise DeployError("git_content_forbidden")
    if any(
        Path(name).name.startswith(".env")
        and not (name.startswith("node_modules/") and Path(name).name == ".env.example")
        for name in layout.members
    ):
        raise DeployError("environment_file_forbidden")


def validate_identity(tar: tarfile.TarFile, layout: ArchiveLayout, sha: str) -> None:
    """Verify optional package/build identifiers without requiring metadata in the tar."""
    package = layout.members["package.json"]
    try:
        package_data = json.load(tar.extractfile(package))
    except (json.JSONDecodeError, OSError, TypeError, UnicodeDecodeError) as exc:
        raise DeployError("package_json_invalid") from exc
    package_identity = {package_data[key] for key in ("gitHead", "release_sha", "git_sha") if key in package_data}
    if package_identity and package_identity != {sha}:
        raise DeployError("package_identity_mismatch")
    build_id = layout.members.get(".next/BUILD_ID")
    if build_id is not None:
        if not build_id.isreg():
            raise DeployError("build_id_not_regular")
        raw_build_id = tar.extractfile(build_id).read(128).decode("ascii", "strict").strip()
        if SHA_RE.fullmatch(raw_build_id) and raw_build_id != sha:
            raise DeployError("build_identity_mismatch")


def snapshot_file(source_path: Path, expected_hash: str | None, snapshot_dir: Path, prefix: str, max_bytes: int) -> Path:
    """Open once without following links, then copy it to a root-only snapshot."""
    try:
        fd = os.open(source_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise DeployError("archive_open_failed") from exc
    try:
        source_stat = os.fstat(fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise DeployError("archive_not_regular")
        if source_stat.st_size > max_bytes:
            raise DeployError("snapshot_size_limit_exceeded")
        snapshot_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(snapshot_dir, 0o700)
        out_fd, temporary = tempfile.mkstemp(prefix=prefix, dir=snapshot_dir)
        snapshot = Path(temporary)
        digest = hashlib.sha256()
        copied = 0
        try:
            with os.fdopen(fd, "rb", closefd=False) as source, os.fdopen(out_fd, "wb") as destination:
                while True:
                    chunk = source.read(min(1024 * 1024, max_bytes + 1 - copied))
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > max_bytes:
                        raise DeployError("snapshot_size_limit_exceeded")
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            os.chmod(snapshot, 0o600)
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise
        if expected_hash is not None and digest.hexdigest() != expected_hash:
            snapshot.unlink(missing_ok=True)
            raise DeployError("archive_checksum_mismatch")
        return snapshot
    finally:
        os.close(fd)


def snapshot_archive(archive: Path, expected_hash: str, snapshot_dir: Path) -> Path:
    """Snapshot archive bytes before TarFile parses any archive member."""
    return snapshot_file(archive, expected_hash, snapshot_dir, "archive-", MAX_ARCHIVE_BYTES)


def validate_sidecar(sidecar: Path, sha: str, archive_hash: str) -> None:
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeployError("sidecar_invalid") from exc
    if not isinstance(payload, dict) or frozenset(payload) != SIDECAR_FIELDS:
        raise DeployError("sidecar_fields_invalid")
    if payload["release_sha"] != sha or payload["sha256"] != archive_hash:
        raise DeployError("sidecar_artifact_binding_mismatch")
    if not isinstance(payload["product_version"], str) or not payload["product_version"] or len(payload["product_version"]) > 80:
        raise DeployError("sidecar_product_version_invalid")
    if not isinstance(payload["node_version"], str) or not re.fullmatch(r"v?20\.\d+\.\d+", payload["node_version"]):
        raise DeployError("sidecar_node20_required")
    if payload["platform"] != "linux" or payload["arch"] != "x64" or payload["libc"] != "musl":
        raise DeployError("sidecar_runtime_mismatch")
    if payload["api_url"] != "https://api.kml.kz/api":
        raise DeployError("sidecar_api_url_mismatch")


def available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def require_disk_space(path: Path, bytes_needed: int) -> None:
    if available_bytes(path) < bytes_needed + MINIMUM_RESERVE_BYTES:
        raise DeployError("insufficient_disk_space")


def safe_extract(tar: tarfile.TarFile, layout: ArchiveLayout, destination: Path) -> None:
    """Extract validated bytes without TarFile.extract* path/link side effects."""
    destination.mkdir(mode=0o700)
    hardlinks: list[tuple[Path, tarfile.TarInfo]] = []
    for name, member in layout.members.items():
        target = destination.joinpath(*name.split("/"))
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if member.isdir():
            target.mkdir(mode=0o700, exist_ok=True)
        elif member.issym():
            os.symlink(member.linkname, target)
        elif member.islnk():
            hardlinks.append((target, member))
        else:
            source = tar.extractfile(member)
            if source is None:
                raise DeployError("archive_read_failed")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(target, flags, 0o600)
            written = 0
            try:
                with source, os.fdopen(fd, "wb") as output:
                    os.fchmod(output.fileno(), 0o700 if member.mode & 0o111 else 0o600)
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > member.size:
                            raise DeployError("archive_size_mismatch")
                        output.write(chunk)
                if written != member.size:
                    raise DeployError("archive_size_mismatch")
            except Exception:
                target.unlink(missing_ok=True)
                raise
    for target, member in hardlinks:
        source = destination.joinpath(*resolved_hardlink_target(layout, member.linkname).split("/"))
        if not stat.S_ISREG(source.lstat().st_mode):
            raise DeployError("hardlink_target_missing_after_extract")
        os.link(source, target, follow_symlinks=False)


def resolved_hardlink_target(layout: ArchiveLayout, linkname: str) -> str:
    current = normal_member_name(linkname)
    seen: set[str] = set()
    for _ in range(41):
        if current in seen:
            raise DeployError("hardlink_cycle")
        seen.add(current)
        member = layout.members.get(current)
        if member is None:
            raise DeployError("hardlink_target_missing_after_extract")
        if member.isreg():
            return current
        if member.islnk():
            current = normal_member_name(member.linkname)
            continue
        raise DeployError("hardlink_target_not_regular")
    raise DeployError("hardlink_chain_too_deep")


def _walk_no_follow(root: Path) -> Iterable[Path]:
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        yield current_path
        for filename in files:
            yield current_path / filename
        directories[:] = [name for name in directories if not (current_path / name).is_symlink()]
        for dirname in directories:
            yield current_path / dirname


def harden_release(release: Path) -> None:
    next_root = release / ".next"
    if next_root.is_symlink() or not next_root.is_dir():
        raise DeployError("next_root_not_real_directory")
    for path in _walk_no_follow(release):
        path_stat = path.lstat()
        if path.is_symlink():
            os.lchown(path, 0, 0)
        elif stat.S_ISDIR(path_stat.st_mode):
            os.chown(path, 0, 0)
            os.chmod(path, 0o755)
        elif stat.S_ISREG(path_stat.st_mode):
            os.chown(path, 0, 0)
            os.chmod(path, 0o755 if path_stat.st_mode & 0o111 else 0o644)
        else:
            raise DeployError("unexpected_extracted_type")
    cache = release / ".next" / "cache"
    if cache.is_symlink():
        raise DeployError("cache_symlink_forbidden")
    cache.mkdir(mode=0o750, parents=True, exist_ok=True)
    for path in _walk_no_follow(cache):
        if path.is_symlink():
            raise DeployError("cache_symlink_forbidden")
        os.chown(path, _user_id(), _group_id())
        os.chmod(path, 0o750 if path.is_dir() else 0o640)


def _user_id() -> int:
    import pwd
    return pwd.getpwnam(WEB_USER).pw_uid


def _group_id() -> int:
    import grp
    return grp.getgrnam(WEB_USER).gr_gid


def read_marker() -> str:
    return MARKER.read_text(encoding="ascii").strip()


def current_sha() -> str:
    if not CURRENT.is_symlink():
        raise DeployError("current_not_symlink")
    resolved = CURRENT.resolve(strict=True)
    if resolved.parent != RELEASES or not SHA_RE.fullmatch(resolved.name):
        raise DeployError("current_target_invalid")
    return resolved.name


def run_checked(*command: str) -> None:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeployError("command_timeout_" + command[0].replace("/", "_")) from exc
    if completed.returncode != 0:
        raise DeployError("command_failed_" + command[0].replace("/", "_"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def http_route(path: str) -> tuple[int, str]:
    request = urllib.request.Request("http://127.0.0.1:3000" + path, method="GET")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")
    except OSError as exc:
        raise DeployError("application_http_failed") from exc


def require_application_routes(routes: tuple[str, ...]) -> None:
    for route in routes:
        status_code, location = http_route(route)
        if 200 <= status_code < 300:
            continue
        if 300 <= status_code < 400 and location.startswith("/login"):
            continue
        raise DeployError("application_route_failed_" + route.strip("/").replace("/", "_"))


def wait_for_application_routes(routes: tuple[str, ...]) -> None:
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while True:
        try:
            require_application_routes(routes)
            return
        except DeployError:
            if time.monotonic() >= deadline:
                raise DeployError("application_startup_deadline_exceeded") from None
            time.sleep(2)


def require_nginx_identity(sha: str) -> None:
    config = NGINX.read_text(encoding="utf-8")
    if config.count(sha) != 2:
        raise DeployError("nginx_identity_guard_failed")


def require_baseline(expected_old: str) -> None:
    if current_sha() != expected_old or read_marker() != expected_old:
        raise DeployError("expected_old_mismatch")
    require_nginx_identity(expected_old)
    run_checked("rc-service", "kamilya-web", "status")
    run_checked("rc-service", "nginx", "status")
    require_application_routes(("/login",))


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def atomic_current(release: Path) -> None:
    temporary = CURRENT.with_name(CURRENT.name + ".new")
    temporary.unlink(missing_ok=True)
    os.symlink(release, temporary)
    os.replace(temporary, CURRENT)


def backups_for(sha: str) -> tuple[Path, Path]:
    directory = BASE / "deploy-backups"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prefix = directory / f"{stamp}-{sha}"
    nginx_backup, marker_backup = prefix.with_suffix(".nginx"), prefix.with_suffix(".marker")
    shutil.copyfile(NGINX, nginx_backup)
    shutil.copyfile(MARKER, marker_backup)
    for backup in (nginx_backup, marker_backup):
        os.chown(backup, 0, 0)
        os.chmod(backup, 0o600)
    return nginx_backup, marker_backup


def failed_name(sha: str) -> Path:
    return RELEASES / f"{sha}.failed.{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.{os.getpid()}"


def rollback(old: str, nginx_backup: Path, marker_backup: Path, candidate: Path | None) -> None:
    atomic_current(RELEASES / old)
    atomic_write(MARKER, marker_backup.read_bytes())
    atomic_write(NGINX, nginx_backup.read_bytes())
    run_checked("nginx", "-t")
    run_checked("rc-service", "nginx", "reload")
    run_checked("rc-service", "kamilya-web", "restart")
    wait_for_application_routes(("/login",))
    require_baseline(old)
    if candidate is not None and candidate.exists() and current_sha() != candidate.name:
        os.rename(candidate, failed_name(candidate.name.split(".")[0]))


@contextlib.contextmanager
def deployment_lock(exclusive: bool):
    if fcntl is None:
        raise DeployError("fcntl_required_on_target")
    LOCK.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with open(LOCK, "a+", encoding="ascii") as lock_file:
        os.chmod(LOCK, 0o600)
        try:
            fcntl.flock(lock_file, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeployError("deployment_lock_busy") from exc
        yield


def deploy(sha: str, expected_old: str, archive_hash: str) -> None:
    sha = require_hex(sha, "sha", 40)
    expected_old = require_hex(expected_old, "expected_old", 40)
    archive_hash = require_hex(archive_hash, "archive_sha256", 64)
    if sha == expected_old:
        raise DeployError("candidate_equals_expected_old")
    archive = archive_for(sha)
    sidecar = sidecar_for(sha)
    candidate: Path | None = None
    snapshot: Path | None = None
    sidecar_snapshot: Path | None = None
    nginx_backup: Path | None = None
    marker_backup: Path | None = None
    switched = False
    with deployment_lock(exclusive=True):
        try:
            require_baseline(expected_old)
            if (RELEASES / sha).exists():
                raise DeployError("release_already_exists")
            archive_stat = archive.lstat()
            sidecar_stat = sidecar.lstat()
            if not stat.S_ISREG(archive_stat.st_mode) or not stat.S_ISREG(sidecar_stat.st_mode):
                raise DeployError("archive_not_regular")
            if archive_stat.st_size > MAX_ARCHIVE_BYTES:
                raise DeployError("archive_size_limit_exceeded")
            require_disk_space(BASE, archive_stat.st_size + sidecar_stat.st_size)
            snapshot = snapshot_archive(archive, archive_hash, BASE / ".deploy-tmp")
            sidecar_snapshot = snapshot_file(sidecar, None, BASE / ".deploy-tmp", "sidecar-", 64 * 1024)
            validate_sidecar(sidecar_snapshot, sha, archive_hash)
            with tarfile.open(snapshot, "r:gz") as tar:
                layout = validate_archive_members(tar)
                require_artifact_shape(layout)
                validate_identity(tar, layout, sha)
                require_disk_space(BASE, expanded_size(layout))
                candidate = RELEASES / ("." + sha + ".staging." + str(os.getpid()))
                if candidate.exists():
                    raise DeployError("staging_path_exists")
                safe_extract(tar, layout, candidate)
            harden_release(candidate)
            release = RELEASES / sha
            os.rename(candidate, release)
            candidate = release
            nginx_backup, marker_backup = backups_for(sha)
            config = NGINX.read_text(encoding="utf-8")
            if config.count(expected_old) != 2:
                raise DeployError("nginx_expected_old_guard_failed")
            candidate_nginx = config.replace(expected_old, sha)
            if candidate_nginx.count(sha) != 2 or expected_old in candidate_nginx:
                raise DeployError("nginx_candidate_guard_failed")
            switched = True
            atomic_current(release)
            atomic_write(MARKER, (sha + "\n").encode("ascii"))
            run_checked("rc-service", "kamilya-web", "restart")
            atomic_write(NGINX, candidate_nginx.encode("utf-8"))
            run_checked("nginx", "-t")
            run_checked("rc-service", "nginx", "reload")
            if current_sha() != sha or read_marker() != sha:
                raise DeployError("new_identity_guard_failed")
            require_nginx_identity(sha)
            wait_for_application_routes(("/login", "/admin/settings/ai"))
            write_recovery_record(sha, archive_hash, digest_file(sidecar_snapshot))
        except Exception as exc:
            if switched and nginx_backup is not None and marker_backup is not None:
                try:
                    rollback(expected_old, nginx_backup, marker_backup, candidate)
                except Exception as rollback_exc:
                    raise DeployError("rollback_verification_failed") from rollback_exc
            elif candidate is not None and candidate.exists():
                os.rename(candidate, failed_name(sha))
            if isinstance(exc, DeployError):
                raise
            raise DeployError("deploy_failed") from exc
        finally:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
            if sidecar_snapshot is not None:
                sidecar_snapshot.unlink(missing_ok=True)


def status() -> dict[str, object]:
    """Read only: do not create a lock, backup, temporary file, restart, or request."""
    sha = current_sha()
    marker = read_marker()
    nginx_count = NGINX.read_text(encoding="utf-8").count(sha)
    try:
        service = subprocess.run(
            ("rc-service", "kamilya-web", "status"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).returncode == 0
    except subprocess.TimeoutExpired as exc:
        raise DeployError("command_timeout_rc-service") from exc
    return {"current_sha": sha, "marker_sha": marker, "nginx_sha_occurrences": nginx_count, "kamilya_web_running": service}


def tree_fingerprint(path: Path) -> tuple[str, int]:
    """Hash names, modes, link targets and file bytes without following symlinks."""
    digest, total, count, rows = hashlib.sha256(), 0, 0, []
    device = path.lstat().st_dev
    for parent, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        for name in sorted(directories + files):
            item = Path(parent) / name
            info = item.lstat()
            count += 1
            if count > MAX_MEMBERS or info.st_dev != device or os.path.ismount(item):
                raise DeployError("cleanup_tree_boundary")
            row = [item.relative_to(path).as_posix(), stat.S_IMODE(info.st_mode)]
            if stat.S_ISLNK(info.st_mode):
                row.extend(["link", os.readlink(item)])
            elif stat.S_ISDIR(info.st_mode):
                row.append("directory")
            elif stat.S_ISREG(info.st_mode):
                file_hash = hashlib.sha256()
                with item.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        file_hash.update(block)
                total += info.st_size
                if total > MAX_EXPANDED_BYTES:
                    raise DeployError("cleanup_tree_size_limit")
                row.extend(["file", info.st_size, file_hash.hexdigest()])
            else:
                raise DeployError("cleanup_special_file")
            rows.append(row)
    for row in sorted(rows, key=lambda row: row[0]):
        digest.update((json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n").encode())
    return digest.hexdigest(), total


def require_cleanup_rollback(current: str, rollback_sha: str) -> None:
    require_root_directory(BASE)
    backup_dir = BASE / "deploy-backups"
    require_root_directory(backup_dir, 0o700)
    backups = sorted(backup_dir.glob(f"*-{current}.marker"))
    try:
        recorded = read_root_control(backups[-1]).decode("ascii").strip() if backups else None
    except UnicodeError as exc:
        raise DeployError("cleanup_rollback_invalid") from exc
    if recorded != rollback_sha:
        raise DeployError("cleanup_rollback_mismatch")
    previous = RELEASES / rollback_sha
    if previous.is_symlink() or not previous.is_dir() or not (previous / "package.json").is_file():
        raise DeployError("cleanup_rollback_missing")


def require_cleanup_dependencies(target: Path) -> None:
    """Fail closed on active configuration, landing pointers or process references."""
    for item in [Path("/opt/kamilya-landing/current"), CURRENT]:
        if item.exists() and item.resolve().is_relative_to(target):
            raise DeployError("cleanup_active_pointer")
    configs = [*Path("/etc/nginx").rglob("*.conf"),
               Path("/etc/init.d/kamilya-web"), Path("/etc/conf.d/kamilya-web"),
               Path("/etc/init.d/kamilya-landing"), Path("/etc/conf.d/kamilya-landing")]
    for item in configs:
        if item.exists() and target.name in item.read_text(encoding="utf-8"):
            raise DeployError("cleanup_config_reference")
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            # Maintenance CLI contains the SHA, but never the full target path.
            if str(target).encode() in (process / "cmdline").read_bytes():
                raise DeployError("cleanup_process_reference")
            for link in [process / "cwd", process / "exe", *(process / "fd").iterdir()]:
                try:
                    value = os.readlink(link)
                except FileNotFoundError:
                    continue
                if value == str(target) or value.startswith(str(target) + "/"):
                    raise DeployError("cleanup_process_reference")
        except FileNotFoundError:
            continue  # The process exited during the read-only scan.


def cleanup_plan(sha: str, expected_current: str, rollback_sha: str) -> dict[str, object]:
    for value in (sha, expected_current, rollback_sha):
        require_hex(value, "cleanup_sha", 40)
    if sha in (expected_current, rollback_sha) or expected_current == rollback_sha:
        raise DeployError("cleanup_protected_release")
    require_baseline(expected_current)
    require_cleanup_rollback(expected_current, rollback_sha)
    target = RELEASES / sha
    if RELEASES.is_symlink() or target.is_symlink() or not target.is_dir():
        raise DeployError("cleanup_not_real_directory")
    if target.resolve().parent != RELEASES.resolve() or os.path.ismount(target):
        raise DeployError("cleanup_path_boundary")
    require_cleanup_dependencies(target)
    fingerprint, size = tree_fingerprint(target)
    return {"release_sha": sha, "current_sha": expected_current, "rollback_sha": rollback_sha,
            "tree_sha256": fingerprint, "regular_file_bytes": size}


def cleanup_envelope_path(digest: str) -> Path:
    require_hex(digest, "cleanup_envelope_sha256", 64)
    return INCOMING / f"cleanup-envelope-{digest}.json"


def read_control_file(path: Path, *, owner_uids: tuple[int, ...], max_size: int) -> bytes:
    """Read a bounded root-controlled file without following a symlink."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise DeployError("cleanup_nofollow_required")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid not in owner_uids
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > max_size):
                raise DeployError("cleanup_control_permissions")
            content = stream.read(max_size + 1)
            if len(content) > max_size:
                raise DeployError("cleanup_control_size")
            return content
    except OSError as exc:
        raise DeployError("cleanup_control_unreadable") from exc


def read_root_control(path: Path) -> bytes:
    """Read one bounded root-owned control file through a verified descriptor."""
    return read_control_file(path, owner_uids=(0,), max_size=2048)


def read_cleanup_envelope(digest: str) -> tuple[dict[str, object], Path]:
    path = cleanup_envelope_path(digest)
    require_cleanup_incoming()
    try:
        content = read_control_file(path, owner_uids=(INCOMING.lstat().st_uid,), max_size=8192)
    except DeployError:
        raise
    if hashlib.sha256(content).hexdigest() != digest:
        raise DeployError("cleanup_envelope_digest_mismatch")
    try:
        envelope = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise DeployError("cleanup_envelope_invalid") from exc
    if not isinstance(envelope, dict):
        raise DeployError("cleanup_envelope_invalid")
    required = {"release_sha", "current_sha", "rollback_sha", "tree_sha256", "regular_file_bytes",
                "recovery_archive_sha256", "recovery_manifest_sha256"}
    if set(envelope) != required:
        raise DeployError("cleanup_envelope_fields")
    for key in ("release_sha", "current_sha", "rollback_sha"):
        require_hex(str(envelope[key]), key, 40)
    for key in ("tree_sha256", "recovery_archive_sha256", "recovery_manifest_sha256"):
        require_hex(str(envelope[key]), key, 64)
    if (not isinstance(envelope["regular_file_bytes"], int)
            or not 0 <= envelope["regular_file_bytes"] <= MAX_EXPANDED_BYTES):
        raise DeployError("cleanup_envelope_regular_file_bytes")
    return envelope, path


def require_cleanup_incoming() -> None:
    info = INCOMING.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid == 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise DeployError("cleanup_incoming_permissions")


def require_root_directory(path: Path, mode: int | None = None) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise DeployError("cleanup_control_parent_missing") from exc
    actual = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or actual & 0o022 or (mode is not None and actual != mode):
        raise DeployError("cleanup_control_parent_permissions")


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_root_control_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        require_root_directory(path, 0o700)
        return
    path.mkdir(mode=0o700)
    os.chown(path, 0, 0)
    os.chmod(path, 0o700)
    require_root_directory(path, 0o700)


def recovery_record_path(release_sha: str) -> Path:
    require_hex(release_sha, "recovery_release_sha", 40)
    return RECOVERY_RECORDS / f"{release_sha}.json"


def write_recovery_record(release_sha: str, archive_hash: str, manifest_hash: str) -> None:
    require_hex(archive_hash, "recovery_archive_sha256", 64)
    require_hex(manifest_hash, "recovery_manifest_sha256", 64)
    ensure_root_control_directory(RECOVERY_RECORDS)
    payload = {
        "release_sha": release_sha,
        "recovery_archive_sha256": archive_hash,
        "recovery_manifest_sha256": manifest_hash,
    }
    content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    path = recovery_record_path(release_sha)
    if path.exists() or path.is_symlink():
        if read_root_control(path) != content:
            raise DeployError("recovery_record_mismatch")
        return
    atomic_write(path, content, 0o600)


def require_recovery_record(envelope: dict[str, object]) -> None:
    require_root_directory(RECOVERY_RECORDS, 0o700)
    content = read_root_control(recovery_record_path(str(envelope["release_sha"])))
    try:
        record = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise DeployError("recovery_record_invalid") from exc
    expected = {
        "release_sha": envelope["release_sha"],
        "recovery_archive_sha256": envelope["recovery_archive_sha256"],
        "recovery_manifest_sha256": envelope["recovery_manifest_sha256"],
    }
    if record != expected:
        raise DeployError("recovery_record_mismatch")


def cleanup_receipt_path(envelope_digest: str) -> Path:
    require_hex(envelope_digest, "cleanup_envelope_sha256", 64)
    return RECEIPTS / f"{envelope_digest}.json"


def write_cleanup_receipt(path: Path, payload: dict[str, object]) -> None:
    atomic_write(path, (json.dumps(payload, sort_keys=True) + "\n").encode("ascii"), 0o600)


def cleanup(envelope_digest: str) -> dict[str, object]:
    require_hex(envelope_digest, "cleanup_envelope_sha256", 64)
    with deployment_lock(exclusive=True):
        envelope, envelope_path = read_cleanup_envelope(envelope_digest)
        plan = cleanup_plan(str(envelope["release_sha"]), str(envelope["current_sha"]), str(envelope["rollback_sha"]))
        if any(envelope.get(key) != value for key, value in plan.items()):
            raise DeployError("cleanup_plan_changed")
        require_recovery_record(envelope)
        if not shutil.rmtree.avoids_symlink_attacks:
            raise DeployError("cleanup_safe_rmtree_required")
        free_before = shutil.disk_usage(BASE).free
        if free_before < MINIMUM_RESERVE_BYTES:
            raise DeployError("cleanup_reserve_already_breached")
        require_cleanup_parent()
        ensure_root_control_directory(RECEIPTS)
        receipt = cleanup_receipt_path(envelope_digest)
        if receipt.exists() or receipt.is_symlink():
            raise DeployError("cleanup_receipt_exists")
        receipt_payload = {
            **plan,
            "status": "STARTED",
            "envelope_sha256": envelope_digest,
            "recovery_archive_sha256": envelope["recovery_archive_sha256"],
            "recovery_manifest_sha256": envelope["recovery_manifest_sha256"],
            "free_before": free_before,
        }
        write_cleanup_receipt(receipt, receipt_payload)
        parent_fd = os.open(RELEASES, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                shutil.rmtree(str(envelope["release_sha"]), dir_fd=parent_fd)
            except Exception as exc:
                write_cleanup_receipt(receipt, {**receipt_payload, "status": "FAILED_AFTER_START"})
                raise DeployError("cleanup_delete_failed") from exc
        finally:
            os.close(parent_fd)
        free_after = shutil.disk_usage(BASE).free
        current = str(envelope["current_sha"])
        rollback = str(envelope["rollback_sha"])
        try:
            if free_after < MINIMUM_RESERVE_BYTES:
                raise DeployError("cleanup_reserve_breached")
            require_baseline(current)
            require_cleanup_rollback(current, rollback)
            if (RELEASES / str(envelope["release_sha"])).exists():
                raise DeployError("cleanup_absence_failed")
        except Exception as exc:
            reason = str(exc) if isinstance(exc, DeployError) else "cleanup_postcheck_failed"
            try:
                write_cleanup_receipt(
                    receipt,
                    {**receipt_payload, "status": "CLEANED_POSTCHECK_FAILED", "free_after": free_after,
                     "postcheck_reason": reason},
                )
            except Exception:
                pass  # The durable STARTED receipt still proves mutation began.
            if isinstance(exc, DeployError):
                raise
            raise DeployError("cleanup_postcheck_failed") from exc
        completed = {**receipt_payload, "status": "CLEANED", "free_after": free_after}
        try:
            write_cleanup_receipt(receipt, completed)
        except Exception as exc:
            raise DeployError("cleanup_receipt_finalize_failed") from exc
        return completed


def require_cleanup_parent() -> None:
    parent_info = RELEASES.lstat()
    if parent_info.st_uid != 0 or stat.S_IMODE(parent_info.st_mode) & 0o022:
        raise DeployError("cleanup_parent_permissions")


def sanitize_environment() -> None:
    os.environ.clear()
    os.environ.update({"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1"})


def require_host() -> None:
    if os.geteuid() != 0:
        raise DeployError("root_required")
    if socket.gethostname() != HOSTNAME:
        raise DeployError("hostname_guard_failed")
    if sys.version_info < (3, 10):
        raise DeployError("python_3_10_or_newer_required")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    deploy_parser = commands.add_parser("deploy")
    deploy_parser.add_argument("sha")
    deploy_parser.add_argument("expected_old")
    deploy_parser.add_argument("archive_sha256")
    for name in ("cleanup-plan",):
        maintenance = commands.add_parser(name)
        maintenance.add_argument("sha")
        maintenance.add_argument("expected_current")
        maintenance.add_argument("rollback_sha")
    cleanup_parser = commands.add_parser("cleanup")
    cleanup_parser.add_argument("envelope_sha256")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sanitize_environment()
    require_host()
    if args.command == "status":
        print(json.dumps(status(), sort_keys=True))
    elif args.command == "cleanup-plan":
        print(json.dumps(cleanup_plan(args.sha, args.expected_current, args.rollback_sha), sort_keys=True))
    elif args.command == "cleanup":
        print(json.dumps(cleanup(args.envelope_sha256), sort_keys=True))
    else:
        deploy(args.sha, args.expected_old, args.archive_sha256)
        print(json.dumps({"status": "RELEASE_OK", "sha": args.sha, "previous": args.expected_old}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from None
