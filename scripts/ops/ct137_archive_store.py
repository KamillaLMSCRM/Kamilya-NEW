"""Publish and restore exact release packages on the off-host archive VPS."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import stat
import tempfile
import uuid
from pathlib import Path

ARCHIVE_HOST = "173.249.51.164"
ARCHIVE_IDENTITY = "vmi3311535"
ARCHIVE_ROOT = "/opt/kamilya-release-archives"
CREDENTIALS = Path(r"C:\Kamilya New\Kamilya-NEW\.env")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")


class ArchiveError(RuntimeError):
    """The archive or its transfer could not be verified."""


def file_hash(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def read_settings(path: Path) -> dict[str, str]:
    return {
        key.strip(): value.strip().strip("\"'")
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
        for key, value in [line.split("=", 1)]
    }


def ssh_client(host: str, user: str, password: str):
    import paramiko

    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(host, username=user, password=password, allow_agent=False,
                       look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    except Exception:
        client.close()
        raise
    return client


def command(client, script: str, timeout: int = 90) -> str:
    _, stdout, stderr = client.exec_command(script, timeout=timeout)
    output = stdout.read(16384).decode()
    if stdout.channel.recv_exit_status() or stderr.read(4096):
        raise ArchiveError("remote_command_failed")
    return output.strip()


def package_names(kind: str, sha: str) -> tuple[set[str], set[str]]:
    if not SHA.fullmatch(sha):
        raise ArchiveError("archive_release_sha_invalid")
    if kind == "web":
        return {f"frontend-native-{sha}.tar.gz", "bundle.sha256"}, {
            "manifest.json", f"frontend-native-{sha}.manifest.json", "build-config.json"
        }
    if kind == "landing":
        return {"source.tar.gz", "source.sha256"}, set()
    raise ArchiveError("archive_kind_invalid")


def require_names(kind: str, sha: str, names: set[str]) -> None:
    required, optional = package_names(kind, sha)
    if not required <= names <= (required | optional):
        raise ArchiveError("archive_package_files_invalid")
    if kind == "web" and len(names & {"manifest.json", f"frontend-native-{sha}.manifest.json"}) != 1:
        raise ArchiveError("archive_manifest_invalid")


class VpsArchiveStore:
    def __init__(self, client):
        self.client = client

    def _directory(self, kind: str, sha: str, create: bool) -> str:
        package_names(kind, sha)
        if command(self.client, 'test "$(id -un)" = root && hostname') != ARCHIVE_IDENTITY:
            raise ArchiveError("archive_server_identity_mismatch")
        base = ARCHIVE_ROOT
        script = ["set -eu", "umask 077"]
        for directory in (base, f"{base}/ct137", f"{base}/ct137/{kind}", f"{base}/ct137/{kind}/{sha}"):
            path = shlex.quote(directory)
            script.append(f"test ! -L {path}")
            if create:
                script.append(f"mkdir -p -- {path}")
            script.append(f"test -d {path} && test \"$(stat -c '%u:%g:%a' {path})\" = 0:0:700")
        command(self.client, "\n".join(script))
        return directory

    def _remote_matches(self, remote: str, size: int, digest: str) -> None:
        path = shlex.quote(remote)
        result = command(self.client, f"""
set -eu
test ! -L {path} && test -f {path}
test "$(stat -c '%u:%g:%a:%s' {path})" = 0:0:600:{size}
sha256sum -- {path}
""", timeout=300)
        if result.split()[0] != digest:
            raise ArchiveError("archive_remote_checksum_mismatch")

    def _put(self, sftp, source: Path, remote: str, size: int, digest: str) -> None:
        try:
            sftp.lstat(remote)
        except FileNotFoundError:
            partial = f"{remote}.{uuid.uuid4().hex}.partial"
            try:
                with sftp.open(partial, "wx") as outgoing, source.open("rb") as incoming:
                    sftp.chmod(partial, 0o600)
                    outgoing.set_pipelined(True)
                    while data := incoming.read(1024 * 1024):
                        outgoing.write(data)
                self._remote_matches(partial, size, digest)
                # Linux hard-link publishes atomically and never replaces another upload.
                source_name, final_name = shlex.quote(partial), shlex.quote(remote)
                command(self.client, f"ln -T -- {source_name} {final_name} || test -f {final_name}")
            finally:
                try:
                    sftp.remove(partial)
                except FileNotFoundError:
                    pass
        self._remote_matches(remote, size, digest)

    def publish(self, kind: str, sha: str, files: dict[str, tuple[Path, str]]) -> dict:
        require_names(kind, sha, set(files))
        metadata = {}
        for name, (path, expected) in sorted(files.items()):
            if not DIGEST.fullmatch(expected) or file_hash(path) != expected:
                raise ArchiveError("archive_local_checksum_mismatch")
            metadata[name] = {"bytes": path.stat().st_size, "sha256": expected}
        receipt = {"schema": 1, "kind": kind, "release_sha": sha, "files": metadata}
        directory = self._directory(kind, sha, create=True)
        with self.client.open_sftp() as sftp, tempfile.TemporaryDirectory() as temp:
            sftp.get_channel().settimeout(90)
            manifest = Path(temp) / "receipt.json"
            manifest.write_bytes((json.dumps(receipt, sort_keys=True) + "\n").encode())
            for name, (path, expected) in files.items():
                self._put(sftp, path, f"{directory}/{name}", metadata[name]["bytes"], expected)
            self._put(sftp, manifest, f"{directory}/receipt.json", manifest.stat().st_size, file_hash(manifest))
        return {**receipt, "server": ARCHIVE_IDENTITY, "directory": directory}

    def restore(self, kind: str, sha: str, destination: Path) -> dict:
        directory = self._directory(kind, sha, create=False)
        if destination.exists():
            raise ArchiveError("archive_restore_destination_exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp, self.client.open_sftp() as sftp:
            sftp.get_channel().settimeout(90)
            staging = Path(temp) / "package"
            staging.mkdir()
            remote_receipt = f"{directory}/receipt.json"
            info = sftp.lstat(remote_receipt)
            if not stat.S_ISREG(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o600) or info.st_size > 16384:
                raise ArchiveError("archive_receipt_invalid")
            with sftp.open(remote_receipt) as receipt_file:
                receipt = json.loads(receipt_file.read(16385))
            if receipt.get("schema") != 1 or receipt.get("kind") != kind or receipt.get("release_sha") != sha:
                raise ArchiveError("archive_receipt_identity_mismatch")
            require_names(kind, sha, set(receipt["files"]))
            for name, metadata in receipt["files"].items():
                size, expected = metadata["bytes"], metadata["sha256"]
                if not isinstance(size, int) or size <= 0 or not DIGEST.fullmatch(expected):
                    raise ArchiveError("archive_receipt_metadata_invalid")
                remote = f"{directory}/{name}"
                self._remote_matches(remote, size, expected)
                local = staging / name
                sftp.get(remote, str(local), max_concurrent_prefetch_requests=16)
                if local.stat().st_size != size or file_hash(local) != expected:
                    raise ArchiveError("archive_restored_checksum_mismatch")
            staging.rename(destination)
        return {**receipt, "server": ARCHIVE_IDENTITY, "directory": directory}


def connect_archive():
    return ssh_client(ARCHIVE_HOST, "root", read_settings(CREDENTIALS)["vps_root_password"])


def publish_package(kind: str, sha: str, files: dict[str, tuple[Path, str]]) -> dict:
    try:
        with connect_archive() as client:
            return VpsArchiveStore(client).publish(kind, sha, files)
    except Exception:
        raise ArchiveError("offhost_archive_publish_unverified") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("web", "landing"))
    parser.add_argument("sha")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        with connect_archive() as client:
            receipt = VpsArchiveStore(client).restore(args.kind, args.sha, args.destination)
    except Exception:
        raise SystemExit("BLOCKED: offhost_archive_restore_unverified") from None
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
