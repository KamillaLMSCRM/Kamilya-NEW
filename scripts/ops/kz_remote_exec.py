#!/usr/bin/env python3
"""Execute a reviewed Kamilya script through the canonical KZ SSH route."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import time
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_ENV_FILE = WORKSPACE_ROOT / ".env"
DEFAULT_KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"
MAX_SCRIPT_BYTES = 1024 * 1024
MAX_REMOTE_OUTPUT_BYTES = 64 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_LINE_RE = re.compile(
    r"^EVIDENCE(?:\|[a-z][a-z0-9_]{0,63}=[A-Za-z0-9._:/-]{1,256})+$"
)
HEADER_RE = re.compile(
    r"^# kamilya-(target|mode|correlation|output): ([A-Za-z0-9._:/-]+)$"
)
CANONICAL_PROXY_HOST = "92.38.49.167"
VM126_HOSTNAME = "kml"

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:postgres(?:ql)?|redis|rediss)://", re.IGNORECASE),
    re.compile(
        r"(?:^|\s|export\s+)[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|PRIVATE_KEY)\s*=",
        re.IGNORECASE,
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)\+?7[ -]?(?:\d[ -]?){10}(?!\d)"),
    re.compile(r"(?:^|[/\\])\.env(?:$|[\s/\\])", re.IGNORECASE),
    re.compile(r"/proc/(?:self|\d+)/environ", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*(?:set\s+-x|printenv|env\s*$)", re.IGNORECASE),
)

READ_ONLY_COMMANDS = {
    "hostname",
    "id",
    "uname",
    "uptime",
    "free",
    "df",
    "date",
    "docker",
    "systemctl",
    "journalctl",
    "curl",
    "grep",
    "test",
    "printf",
    "true",
    "false",
}
SHELL_CONTROL = re.compile(r"[`$;&|<>{}()\[\]*?~]")
DIRECT_EVIDENCE_PRINTF_RE = re.compile(
    r"^printf '((?:EVIDENCE(?:\|[a-z][a-z0-9_]{0,63}=[A-Za-z0-9._:/-]{1,256})+))(?:\\n)?'$"
)
FORMATTED_EVIDENCE_PRINTF_RE = re.compile(
    r"^printf '%s\\n' '((?:EVIDENCE(?:\|[a-z][a-z0-9_]{0,63}=[A-Za-z0-9._:/-]{1,256})+))'$"
)
DOCKER_EVIDENCE_FORMAT = (
    "EVIDENCE|container={{.Name}}|image={{.Config.Image}}|"
    "status={{.State.Status}}|restarts={{.RestartCount}}"
)
DOCKER_EVIDENCE_CONTAINER_RE = re.compile(
    r"kamilya-runtime-(?:api|worker-ai|worker-documents|worker-ops)-1"
)

MUTATING_PATTERNS = (
    re.compile(r"(^|[;&|]\s*)rm\s", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)mv\s", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)cp\s", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)mkdir\s", re.IGNORECASE),
    re.compile(r"(^|[;&|]\s*)touch\s", re.IGNORECASE),
    re.compile(r"\bsed\s+[^\n]*\s-i(?:\s|$)", re.IGNORECASE),
    re.compile(r"\bsystemctl\s+(?:start|stop|restart|reload|enable|disable)\b", re.IGNORECASE),
    re.compile(r"\bdocker(?:\s+compose)?\s+(?:up|down|restart|stop|start|rm|kill|pull|build)\b", re.IGNORECASE),
    re.compile(r"\b(?:apt|apt-get|dnf|yum|pip|npm|pnpm)\s+(?:install|remove|uninstall|upgrade|update)\b", re.IGNORECASE),
    re.compile(r"\b(?:chmod|chown|kill|pkill|reboot|shutdown)\b", re.IGNORECASE),
    re.compile(r"\b(?:DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b", re.IGNORECASE),
    re.compile(r"(^|[^<])>>?\s*[^&]"),
)

DISABLED_ALGORITHMS = {
    "ciphers": ["3des-cbc", "aes128-cbc", "aes192-cbc", "aes256-cbc", "blowfish-cbc", "cast128-cbc"],
    "kex": ["diffie-hellman-group1-sha1", "diffie-hellman-group-exchange-sha1"],
    "macs": ["hmac-md5", "hmac-md5-96", "hmac-sha1-96"],
    "keys": ["ssh-dss", "ssh-rsa"],
    "pubkeys": ["ssh-dss", "ssh-rsa"],
}


class GateBlocked(RuntimeError):
    """Fail-closed error with a stable, non-sensitive classifier."""

    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


class RemoteScriptBlocked(GateBlocked):
    """Remote failure carrying only evidence lines that passed the sanitizer."""

    def __init__(self, error_class: str, evidence: list[str]) -> None:
        super().__init__(error_class)
        self.evidence = evidence


@dataclass(frozen=True)
class TargetProfile:
    name: str
    expected_hostname: str
    remote_prefix: tuple[str, ...]

    def command(self, timeout: int, *remote_argv: str) -> str:
        # Every item is a source-controlled constant. User input is never joined.
        bounded = ("timeout", "--signal=TERM", "--kill-after=5s", f"{timeout}s")
        return " ".join((*self.remote_prefix, *bounded, *remote_argv))


VM126 = TargetProfile(
    name="vm126",
    expected_hostname=VM126_HOSTNAME,
    remote_prefix=(
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=/root/.ssh/known_hosts",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        "/root/.ssh/kamilya-vm126-admin",
        "kamilya-admin@10.77.77.2",
    ),
)

TARGETS = {VM126.name: VM126}


@dataclass(frozen=True)
class ScriptManifest:
    path: Path
    payload: bytes
    sha256: str
    target: str
    mode: str
    correlation: str


@dataclass(frozen=True)
class StageResult:
    exit_code: int
    stdout: bytes
    stderr: bytes


def _inside_repository(path: Path) -> bool:
    return path == REPO_ROOT or REPO_ROOT in path.parents


def resolve_target(name: str) -> TargetProfile:
    if name == "ct125":
        raise GateBlocked("ct125_route_not_configured")
    try:
        return TARGETS[name]
    except KeyError as exc:
        raise GateBlocked("target_not_allowed") from exc


def _metadata(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines()[:20]:
        match = HEADER_RE.fullmatch(line)
        if match:
            result[match.group(1)] = match.group(2)
    return result


def _assert_read_only(text: str) -> None:
    executable = [
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    if any(pattern.search(line) for line in executable for pattern in MUTATING_PATTERNS):
        raise GateBlocked("read_only_script_contains_mutation")
    for line in executable:
        stripped = line.strip()
        if stripped == "set -Eeuo pipefail":
            continue
        if stripped.startswith("printf"):
            direct = DIRECT_EVIDENCE_PRINTF_RE.fullmatch(stripped)
            formatted = FORMATTED_EVIDENCE_PRINTF_RE.fullmatch(stripped)
            rendered = (direct or formatted).group(1) if (direct or formatted) else ""
            if not rendered or not EVIDENCE_LINE_RE.fullmatch(rendered):
                raise GateBlocked("read_only_printf_not_evidence")
            continue
        try:
            argv = shlex.split(stripped, posix=True)
        except ValueError as exc:
            raise GateBlocked("read_only_command_parse_failed") from exc
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        safe_docker_evidence_format = (
            len(argv) == 5
            and argv[:3] == ["docker", "inspect", "--format"]
            and argv[3] == DOCKER_EVIDENCE_FORMAT
            and DOCKER_EVIDENCE_CONTAINER_RE.fullmatch(argv[4]) is not None
        )
        if SHELL_CONTROL.search(stripped) and not safe_docker_evidence_format:
            raise GateBlocked("read_only_shell_construct_not_allowed")
        if not argv or argv[0] not in READ_ONLY_COMMANDS:
            raise GateBlocked("read_only_command_not_allowed")
        if argv[0] == "docker" and (len(argv) < 2 or argv[1] not in {"ps", "stats", "inspect", "version", "info"}):
            raise GateBlocked("read_only_docker_command_not_allowed")
        if argv[0] == "systemctl" and (len(argv) < 2 or argv[1] not in {"is-active", "is-enabled", "show", "status"}):
            raise GateBlocked("read_only_systemctl_command_not_allowed")
        if argv[0] == "curl":
            if len(argv) != 5 or argv[:3] != ["curl", "-fsS", "--max-time"]:
                raise GateBlocked("read_only_curl_shape_not_allowed")
            try:
                curl_timeout = int(argv[3])
            except ValueError as exc:
                raise GateBlocked("read_only_curl_timeout_invalid") from exc
            if not 1 <= curl_timeout <= 30 or argv[4] != "http://10.77.77.2:8000/health":
                raise GateBlocked("read_only_curl_target_or_timeout_not_allowed")


def _assert_no_sensitive_content(text: str) -> None:
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise GateBlocked("script_contains_sensitive_material")


def load_script(
    path: Path,
    *,
    target: str,
    mode: str,
    correlation_id: str,
    expected_sha256: str,
) -> ScriptManifest:
    resolved = path.resolve(strict=True)
    if not _inside_repository(resolved) or resolved.is_symlink():
        raise GateBlocked("script_path_not_allowed")
    if resolved.suffix.lower() != ".sh" or not resolved.is_file():
        raise GateBlocked("script_type_not_allowed")
    payload = resolved.read_bytes()
    if not payload or len(payload) > MAX_SCRIPT_BYTES or b"\x00" in payload:
        raise GateBlocked("script_size_or_binary_invalid")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateBlocked("script_not_utf8") from exc
    if "\r" in text:
        raise GateBlocked("script_must_use_lf")
    lines = text.splitlines()
    if not lines or lines[0] != "#!/usr/bin/env bash":
        raise GateBlocked("bash_shebang_required")
    if "set -Eeuo pipefail" not in lines[:20]:
        raise GateBlocked("strict_bash_mode_required")

    metadata = _metadata(text)
    required = {"target", "mode", "correlation", "output"}
    if set(metadata) != required or metadata["output"] != "sanitized":
        raise GateBlocked("script_metadata_invalid")
    if metadata["target"] != target or metadata["mode"] != mode:
        raise GateBlocked("script_scope_mismatch")
    resolve_target(target)
    _assert_no_sensitive_content(text)
    if mode == "read-only":
        if metadata["correlation"] != "none" or correlation_id:
            raise GateBlocked("read_only_correlation_must_be_none")
        _assert_read_only(text)
    elif mode == "mutation":
        if not correlation_id or metadata["correlation"] != correlation_id:
            raise GateBlocked("exact_correlation_id_required")
    elif mode == "destructive":
        raise GateBlocked("destructive_mode_not_supported")
    else:
        raise GateBlocked("mode_not_allowed")

    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256:
        if not SHA256_RE.fullmatch(expected_sha256) or digest != expected_sha256:
            raise GateBlocked("script_sha256_mismatch")
    return ScriptManifest(resolved, payload, digest, target, mode, metadata["correlation"])


def load_env(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise GateBlocked("credential_source_unavailable") from exc
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def proxy_credentials(env_file: Path) -> tuple[str, str, str]:
    values = load_env(env_file)
    names = ("PROXY_VPS_HOST", "PROXY_VPS_LOGIN", "PROXY_VPS_PASSWORD")
    if any(not values.get(name) for name in names):
        raise GateBlocked("proxy_credentials_not_configured")
    host, username, password = (values[name] for name in names)
    if host != CANONICAL_PROXY_HOST:
        raise GateBlocked("proxy_identity_mismatch")
    return host, username, password


def assert_canonical_trust_paths(env_file: Path, known_hosts: Path) -> None:
    if env_file.resolve() != DEFAULT_ENV_FILE.resolve():
        raise GateBlocked("noncanonical_env_file_not_allowed")
    if known_hosts.resolve() != DEFAULT_KNOWN_HOSTS.resolve():
        raise GateBlocked("noncanonical_known_hosts_not_allowed")


def evidence_lines(output: bytes) -> list[str]:
    try:
        text = output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateBlocked("remote_evidence_contract_invalid") from exc
    lines = [line for line in text.splitlines() if line.startswith("EVIDENCE|")]
    if not lines or len(lines) > 50 or any(
        len(line) > 500 or not EVIDENCE_LINE_RE.fullmatch(line) for line in lines
    ):
        raise GateBlocked("remote_evidence_contract_invalid")
    return lines


def run_channel(client: Any, command: str, payload: bytes, timeout: int) -> StageResult:
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        raise GateBlocked("proxy_transport_inactive")
    channel = transport.open_session(timeout=timeout)
    stdout = bytearray()
    stderr = bytearray()
    overflow = False
    try:
        channel.exec_command(command)
        if payload:
            channel.sendall(payload)
        channel.shutdown_write()
        deadline = time.monotonic() + timeout
        while True:
            while channel.recv_ready():
                chunk = channel.recv(8192)
                if len(stdout) + len(chunk) <= MAX_REMOTE_OUTPUT_BYTES:
                    stdout.extend(chunk)
                else:
                    overflow = True
            while channel.recv_stderr_ready():
                chunk = channel.recv_stderr(8192)
                if len(stderr) + len(chunk) <= MAX_REMOTE_OUTPUT_BYTES:
                    stderr.extend(chunk)
                else:
                    overflow = True
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            if time.monotonic() >= deadline:
                raise GateBlocked("remote_termination_not_verified")
            time.sleep(0.02)
        exit_code = channel.recv_exit_status()
        if overflow:
            raise GateBlocked("remote_output_limit_exceeded_after_termination")
        return StageResult(exit_code, bytes(stdout), bytes(stderr))
    finally:
        channel.close()


def execute_stages(
    profile: TargetProfile,
    payload: bytes,
    expected_sha256: str,
    timeout: int,
    runner: Callable[[str, bytes], StageResult],
) -> dict[str, Any]:
    identity = runner(profile.command(timeout, "hostname"), b"")
    if identity.exit_code != 0:
        raise GateBlocked("target_identity_stage_failed")
    hostname = identity.stdout.decode("ascii", errors="ignore").strip()
    if hostname.casefold() != profile.expected_hostname.casefold():
        raise GateBlocked("target_identity_mismatch")

    remote_hash = runner(profile.command(timeout, "sha256sum"), payload)
    if remote_hash.exit_code != 0:
        raise GateBlocked("remote_hash_stage_failed")
    observed = remote_hash.stdout.decode("ascii", errors="ignore").split()
    if not observed or observed[0] != expected_sha256:
        raise GateBlocked("remote_hash_mismatch")

    syntax = runner(profile.command(timeout, "bash", "-n", "-s"), payload)
    if syntax.exit_code != 0:
        raise GateBlocked("remote_bash_syntax_failed")

    execution = runner(profile.command(timeout, "bash", "-se"), payload)
    if execution.exit_code != 0:
        try:
            sanitized_evidence = evidence_lines(execution.stdout)
        except GateBlocked:
            sanitized_evidence = []
        raise RemoteScriptBlocked("remote_script_failed", sanitized_evidence)
    return {
        "remote_sha256_verified": True,
        "target_identity_verified": True,
        "remote_bash_syntax_verified": True,
        "server_timeout_seconds": timeout,
        "remote_execution_exit_code": execution.exit_code,
        "evidence": evidence_lines(execution.stdout),
        "stdout_bytes": len(execution.stdout),
        "stdout_sha256": hashlib.sha256(execution.stdout).hexdigest(),
        "stderr_bytes": len(execution.stderr),
        "stderr_sha256": hashlib.sha256(execution.stderr).hexdigest(),
    }


def run_remote(manifest: ScriptManifest, env_file: Path, known_hosts: Path, timeout: int) -> dict[str, Any]:
    assert_canonical_trust_paths(env_file, known_hosts)
    try:
        import paramiko
    except ImportError as exc:
        raise GateBlocked("paramiko_dependency_missing") from exc

    if not known_hosts.is_file():
        raise GateBlocked("known_hosts_unavailable")
    host, username, password = proxy_credentials(env_file)
    client = paramiko.SSHClient()
    client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(
            hostname=host,
            port=22,
            username=username,
            password=password,
            allow_agent=False,
            look_for_keys=False,
            timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
            disabled_algorithms=DISABLED_ALGORITHMS,
        )
        profile = resolve_target(manifest.target)
        return execute_stages(
            profile,
            manifest.payload,
            manifest.sha256,
            timeout,
            lambda command, payload: run_channel(client, command, payload, timeout + 10),
        )
    except GateBlocked:
        raise
    except Exception as exc:
        raise GateBlocked("ssh_execution_failed") from exc
    finally:
        client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--mode", choices=("read-only", "mutation", "destructive"), default="read-only")
    parser.add_argument("--correlation-id", default="")
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def _emit(payload: dict[str, Any], *, stream: Any | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True), file=stream or sys.stdout)


def main() -> int:
    args = parse_args()
    try:
        if args.timeout < 5 or args.timeout > 300:
            raise GateBlocked("timeout_out_of_bounds")
        manifest = load_script(
            args.script,
            target=args.target,
            mode=args.mode,
            correlation_id=args.correlation_id,
            expected_sha256=args.expected_sha256,
        )
        if not args.execute:
            _emit(
                {
                    "status": "READY",
                    "evidence_label": "NOT VERIFIED",
                    "network_attempted": False,
                    "script_sha256": manifest.sha256,
                    "script_bytes": len(manifest.payload),
                    "target": manifest.target,
                    "mode": manifest.mode,
                }
            )
            return 0
        if not args.expected_sha256:
            raise GateBlocked("expected_sha256_required_for_execute")
        result = run_remote(manifest, DEFAULT_ENV_FILE, DEFAULT_KNOWN_HOSTS, args.timeout)
        _emit(
            {
                "status": "PASS",
                "evidence_label": "RUNTIME-DERIVED",
                "target": manifest.target,
                "mode": manifest.mode,
                "script_sha256": manifest.sha256,
                **result,
            }
        )
        return 0
    except (GateBlocked, FileNotFoundError) as exc:
        error_class = exc.error_class if isinstance(exc, GateBlocked) else "script_file_not_found"
        payload = {"status": "BLOCKED", "evidence_label": "BLOCKED", "error_class": error_class}
        if isinstance(exc, RemoteScriptBlocked) and exc.evidence:
            payload["evidence"] = exc.evidence
        _emit(payload, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
