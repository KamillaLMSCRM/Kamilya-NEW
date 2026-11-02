"""Local-only, injected-transport staging contract for the VM126 DEV worker env."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.ops.kz_remote_exec import (
    StageResult,
    VM126,
    assert_canonical_trust_paths,
    proxy_credentials,
    run_channel,
)
from scripts.ops.vm126_dev_worker_env_receiver import validate_payload

RELEASE_RE = re.compile(r"^[0-9a-f]{40}$")
RECEIVER_PATH = "/opt/kamilya-dev-worker/releases/vm126_dev_worker_env_receiver-v2.py"
RECEIVER_SHA = "a7470cca32295122245796acf17c9f8d6e3c7b904f417ac78b8ee069354b61ae"
RECEIVER_PATH_V3 = "/opt/kamilya-dev-worker/releases/vm126_dev_worker_env_receiver-v3.py"
RECEIVER_SHA_V3 = "5561169088dfdeade62f4566d468cfb0ae0d4587513138163efc892748db790a"
STATUS_RE = re.compile(r"^STATUS\|status=(installed|already_present)\|release_sha=([0-9a-f]{40})\|payload_sha256=([0-9a-f]{64})\|keycount=([1-9][0-9]{0,2})$")


def canonical_transport_preflight(env_file: Path, known_hosts: Path) -> tuple[str, str]:
    """Validate canonical paths and return non-secret proxy identity only."""
    assert_canonical_trust_paths(env_file, known_hosts)
    host, username, _password = proxy_credentials(env_file)
    return host, username


def stage_payload(payload: bytes, release_sha: str, receiver_sha: str, runner: Callable[[str, bytes], StageResult], timeout: int = 30) -> dict[str, str]:
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise ValueError("timeout_invalid")
    if not RELEASE_RE.fullmatch(release_sha) or not re.fullmatch(r"[0-9a-f]{64}", receiver_sha):
        raise ValueError("identity_format_invalid")
    payload_hash = hashlib.sha256(payload).hexdigest()
    validated = validate_payload(payload, release_sha, payload_hash)
    managed = b"AI_MANAGED_LUNA_QA_DEV_ENABLED=true\n" in payload.splitlines(keepends=True)
    receiver_path = RECEIVER_PATH_V3 if managed else RECEIVER_PATH
    if receiver_sha != (RECEIVER_SHA_V3 if managed else RECEIVER_SHA):
        raise ValueError("receiver_identity_invalid")
    identity = runner(VM126.command(timeout, "hostname"), b"")
    if identity.exit_code != 0 or identity.stdout.decode("ascii", "ignore").strip().casefold() != VM126.expected_hostname.casefold():
        raise RuntimeError("target_identity_mismatch")
    receiver_check = runner(VM126.command(timeout, "sudo", "-n", "sha256sum", receiver_path), b"")
    if receiver_check.exit_code != 0 or receiver_check.stdout.decode("ascii", "ignore").split()[:1] != [receiver_sha]:
        raise RuntimeError("receiver_hash_mismatch")
    command = VM126.command(timeout, "sudo", "-n", "python3", receiver_path,
                            "--release-sha", release_sha,
                            "--expected-payload-sha256", payload_hash)
    result = runner(command, payload)
    if result.exit_code != 0 or result.stderr:
        raise RuntimeError("receiver_install_failed")
    try:
        if result.stdout.count(b"\n") != 1 or not result.stdout.endswith(b"\n"):
            raise RuntimeError("receiver_output_invalid")
        line = result.stdout[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("receiver_output_invalid") from exc
    match = STATUS_RE.fullmatch(line)
    if not match or match.group(2) != release_sha or match.group(3) != payload_hash or match.group(4) != validated["keycount"]:
        raise RuntimeError("receiver_output_invalid")
    return {"status": match.group(1), "release_sha": match.group(2), "payload_sha256": match.group(3), "keycount": match.group(4)}


def stage_over_client(client: Any, payload: bytes, release_sha: str, receiver_sha: str, timeout: int = 30) -> dict[str, str]:
    return stage_payload(
        payload,
        release_sha,
        receiver_sha,
        lambda command, body: run_channel(client, command, body, timeout),
        timeout,
    )
