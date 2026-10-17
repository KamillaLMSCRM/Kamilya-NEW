"""Opt-in Render DEV SSH supervision; no production imports or public listeners."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HOST = "92.38.49.167"
USER = "kamilya-dev-models"
FORWARDS = ((18999, "10.77.77.2", 18999), (18889, "10.77.77.4", 18005))


class RuntimeBlocked(Exception):
    """Carries a fixed safe code, never raw library/subprocess errors."""


def diagnostic_context(source: dict[str, str]) -> str:
    """Correlate startup markers without publishing provider metadata or secrets."""
    startup_id = source.get("DEV_MODEL_SSH_RUN_ID", "")
    if not re.fullmatch(r"[0-9a-f]{12}", startup_id):
        startup_id = "unknown"
    instance = source.get("RENDER_INSTANCE_ID", "")
    instance_hash = hashlib.sha256(instance.encode()).hexdigest()[:12] if instance else "unknown"
    return "|startup_id=" + startup_id + "|instance_hash=" + instance_hash


def credentials(env: dict[str, str]) -> tuple[bytes, str]:
    expected_env = {"api": "render-development", "worker": "render-development-worker"}
    if env.get("DEPLOYMENT_ENVIRONMENT") != expected_env.get(env.get("DEV_MODEL_SSH_ROLE"), "DENIED"):
        raise RuntimeBlocked("wrong_environment")
    if env.get("DEV_MODEL_SSH_ROLE") not in {"api", "worker"}:
        raise RuntimeBlocked("wrong_role")
    encoded = env.get("DEV_MODEL_SSH_KEY_B64", "")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise RuntimeBlocked("invalid_private_credential") from None
    if len(key) > 16384 or not key.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n"):
        raise RuntimeBlocked("invalid_private_credential")
    known = env.get("DEV_MODEL_SSH_KNOWN_HOST", "")
    if not re.fullmatch(re.escape(HOST) + r" ssh-ed25519 [A-Za-z0-9+/]{40,}={0,2}", known):
        raise RuntimeBlocked("invalid_host_pin")
    return key, known


def ssh_command(key_path: Path, known_path: Path) -> list[str]:
    command = ["ssh", "-F", "none", "-N", "-T", "-p", "22", "-i", str(key_path),
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_path}", "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no", "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
        "-o", "LogLevel=DEBUG1", "-o", "ForwardAgent=no"]
    for local, destination, port in FORWARDS:
        command += ["-L", f"127.0.0.1:{local}:{destination}:{port}"]
    return command + [f"{USER}@{HOST}"]


def child_environment(env: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in env.items() if not key.startswith("DEV_MODEL_SSH_")}


def ssh_environment(env: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in env.items() if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}


def owns_listeners(pid: int) -> bool:
    """Match loopback listening socket inodes to the spawned SSH process, not TCP reachability."""
    try:
        inodes = {os.readlink(path) for path in Path(f"/proc/{pid}/fd").iterdir()}
        rows = Path(f"/proc/{pid}/net/tcp").read_text().splitlines()[1:]
        owned = {int(parts[1].split(":")[1], 16) for row in rows
            if len(parts := row.split()) >= 10 and parts[3] == "0A"
            and parts[1].startswith("0100007F:") and f"socket:[{parts[9]}]" in inodes}
        return {port for port, _, _ in FORWARDS} <= owned
    except OSError:
        return False


def _available(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def await_forward(process: subprocess.Popen, seconds: float = 12) -> None:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if process.poll() is not None:
            raise RuntimeBlocked(ssh_failure(process))
        if owns_listeners(process.pid) and process.poll() is None:
            return
        time.sleep(0.1)
    raise RuntimeBlocked("ssh_start_timeout")


def ssh_failure(process: subprocess.Popen) -> str:
    """Classify bounded private diagnostics; never emit raw SSH output."""
    pump = getattr(process, "_kamilya_diagnostic_pump", None)
    if pump is not None:
        pump.join(timeout=0.5)
        raw = bytes(process._kamilya_diagnostic_tail).lower()
    else:
        stream = getattr(process, "stderr", None)
        raw = b"" if stream is None else stream.read(65537).lower()
    for fragment, code in (
        (b"error in libcrypto", "identity_crypto_error"),
        (b"openssl version mismatch", "system_openssl_mismatch"),
        (b"permission denied", "authentication_denied"),
        (b"host key verification failed", "host_pin_rejected"),
        (b"address already in use", "local_bind_conflict"),
        (b"connection timed out", "network_connect_timeout"),
        (b"connection refused", "network_connect_refused"),
        (b"bad configuration option", "unsupported_ssh_option"),
        (b"cannot assign requested address", "local_bind_unavailable"),
        (b"no hostkeys available", "host_key_algorithm_unavailable"),
        (b"connection reset", "network_connection_reset"),
        (b"connection closed", "network_connection_closed"),
        (b"kex_exchange_identification", "key_exchange_failed"),
        (b"invalid format", "identity_invalid_format"),
        (b"bad permissions", "identity_bad_permissions"),
        (b"network is unreachable", "network_unreachable"),
    ):
        if fragment in raw:
            return "ssh_start_failed_" + code
    return "ssh_start_failed_exit_" + str(process.poll()) + "_diagnostic_bytes_" + str(len(raw))


def ssh_progress(raw: bytes) -> tuple[str, str]:
    """Map private OpenSSH diagnostics to fixed stages, never raw text or addresses."""
    stage = "unknown"
    for pattern, candidate in (
        (rb"^debug1: Connection established\.$", "tcp_established"),
        (rb"^debug1: Remote protocol version 2\.0, remote software version [^\r\n]+$", "peer_banner"),
        (rb"^debug1: SSH2_MSG_KEXINIT (?:sent|received)$", "key_exchange"),
        (rb"^Authenticated to [^\r\n]+ using [^\r\n]+\.$", "authenticated"),
    ):
        if re.search(pattern, raw, re.MULTILINE):
            stage = candidate
    operation = "unknown"
    if re.search(rb"^ssh: connect to host [^\r\n]+: Connection reset by peer$", raw, re.MULTILINE):
        operation = "connect"
    elif re.search(rb"^kex_exchange_identification: read: Connection reset by peer$", raw, re.MULTILINE):
        operation = "banner_read"
    elif re.search(rb"^kex_exchange_identification: write: Connection reset by peer$", raw, re.MULTILINE):
        operation = "banner_write"
    return stage, operation


def drain_diagnostics(process: subprocess.Popen) -> None:
    """Drain continuously so SSH cannot block on a full private stderr pipe."""
    tail = bytearray()
    process._kamilya_diagnostic_tail = tail

    def pump():
        try:
            # read() may wait for 1024 bytes even after a short SSH error was
            # flushed. read1() exposes available bytes without requiring EOF.
            while chunk := process.stderr.read1(1024):
                tail.extend(chunk)
                if len(tail) > 65536:
                    del tail[:-65536]
        except (OSError, ValueError):
            pass

    thread = threading.Thread(target=pump, daemon=True, name="dev-ssh-diagnostics")
    process._kamilya_diagnostic_pump = thread
    thread.start()


def stop(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    group = getattr(process, "_kamilya_own_session", False)
    if group:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        if group:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait(timeout=3)
    finally:
        if group:
            # The leader can exit before a descendant which ignored SIGTERM.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stream = getattr(process, "stderr", None)
        if stream is not None:
            stream.close()
        pump = getattr(process, "_kamilya_diagnostic_pump", None)
        if pump is not None:
            pump.join(timeout=1)


def spawn(argv: list[str], **kwargs) -> subprocess.Popen:
    grouped = os.name != "nt"
    process = subprocess.Popen(argv, start_new_session=grouped, **kwargs)
    process._kamilya_own_session = grouped
    return process


def start_forward(identity: Path, hosts: Path, source: dict[str, str]) -> subprocess.Popen:
    """One bounded startup recovery for an observed pre-auth transport reset.

    Never retry identity/host-pin/policy failures or reconnect a live application.
    """
    transient = {"ssh_start_failed_network_connection_reset", "ssh_start_failed_network_connection_closed"}
    for attempt in range(2):
        print("EVIDENCE|dev_private_models=forward_starting|attempt=" + str(attempt + 1)
            + diagnostic_context(source), flush=True)
        process = spawn(ssh_command(identity, hosts), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=ssh_environment(source))
        try:
            drain_diagnostics(process)
            await_forward(process)
            print("EVIDENCE|dev_private_models=forward_ready|attempt=" + str(attempt + 1)
                + diagnostic_context(source), flush=True)
            return process
        except BaseException as exc:
            print("EVIDENCE|dev_private_models=forward_cleanup|attempt=" + str(attempt + 1)
                + diagnostic_context(source), flush=True)
            stop(process)
            print("EVIDENCE|dev_private_models=forward_stopped|attempt=" + str(attempt + 1)
                + diagnostic_context(source), flush=True)
            if isinstance(exc, RuntimeBlocked):
                stage, operation = ssh_progress(bytes(getattr(process, "_kamilya_diagnostic_tail", b"")))
                print("EVIDENCE|dev_private_models=forward_failure|attempt=" + str(attempt + 1)
                    + "|stage=" + stage + "|operation=" + operation
                    + diagnostic_context(source), flush=True)
            if isinstance(exc, RuntimeBlocked) and str(exc) in transient and attempt == 0:
                print("EVIDENCE|dev_private_models=startup_retry_once|reason=" + str(exc)
                    + diagnostic_context(source), flush=True)
                time.sleep(1)
            else:
                raise
    raise RuntimeBlocked("ssh_start_attempts_exhausted")


def run(argv: list[str], env: dict[str, str] | None = None) -> int:
    source = dict(os.environ if env is None else env)
    if not argv:
        raise RuntimeBlocked("child_command_missing")
    if source.get("DEV_MODEL_SSH_ENABLED") != "true":
        # Existing disabled behavior, including its normal process/signal ownership.
        if os.name == "nt":
            # Windows has no POSIX process replacement; preserve the child status.
            return subprocess.call(argv, env=child_environment(source))
        os.execvpe(argv[0], argv, child_environment(source))
        return 1
    key, known = credentials(source)
    if not sys.platform.startswith("linux"):
        raise RuntimeBlocked("enabled_runtime_requires_linux")
    if shutil.which("ssh") is None:
        raise RuntimeBlocked("ssh_binary_unavailable")
    if any(_available(port) for port, _, _ in FORWARDS):
        raise RuntimeBlocked("local_port_owned_elsewhere")
    ssh = child = probe = None
    terminating = False

    def terminate(_signum, _frame):
        nonlocal terminating
        terminating = True

    previous = {sig: signal.signal(sig, terminate) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with tempfile.TemporaryDirectory(prefix="kamilya-dev-models-") as directory:
            folder = Path(directory)
            folder.chmod(0o700)
            identity, hosts = folder / "identity", folder / "known_hosts"
            for path, contents in ((identity, key), (hosts, (known + "\n").encode())):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(contents)
            key = b""
            ssh = start_forward(identity, hosts, source)
            if terminating:
                return 143
            safe_env = child_environment(source)
            print("EVIDENCE|dev_private_models=consumer_starting|role=" + source["DEV_MODEL_SSH_ROLE"]
                + diagnostic_context(source), flush=True)
            child = spawn(argv, env=safe_env, stdin=subprocess.DEVNULL)
            if source.get("DEV_MODEL_ACCEPTANCE_ID"):
                probe_path = Path(__file__).with_name("dev_private_model_acceptance.py")
                probe_env = {**safe_env, "DEV_MODEL_ACCEPTANCE_ROLE": source["DEV_MODEL_SSH_ROLE"],
                    "DB_POOL_SIZE": "1", "DB_MAX_OVERFLOW": "0"}
                probe = spawn([sys.executable, str(probe_path)], env=probe_env,
                    stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("EVIDENCE|dev_private_models=connected|role=" + source["DEV_MODEL_SSH_ROLE"]
                + diagnostic_context(source), flush=True)
            while not terminating:
                if ssh.poll() is not None:
                    raise RuntimeBlocked("ssh_connection_lost")
                result = child.poll()
                if result is not None:
                    return result
                time.sleep(0.25)
            return 143
    finally:
        # Stop the consumer before its private channel; reap even on failed startup.
        cleanup_failed = False
        for owned in (probe, child, ssh):
            try:
                stop(owned)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if cleanup_failed:
            raise RuntimeBlocked("owned_process_cleanup_failed")


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    source = dict(os.environ)
    # Native process identity is fresh for every invocation, never supplied by
    # a provider setting and never inherited by the application child.
    source["DEV_MODEL_SSH_RUN_ID"] = uuid.uuid4().hex[:12]
    try:
        return run(argv, source)
    except RuntimeBlocked as exc:
        print("EVIDENCE|dev_private_models=blocked|reason=" + str(exc)
            + diagnostic_context(source), flush=True)
        return 78
    except Exception:
        print("EVIDENCE|dev_private_models=blocked|reason=internal_failure"
            + diagnostic_context(source), flush=True)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
