"""Database-free tests of the exact native DEV launcher seam."""
import base64
import importlib.util
import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "dev_private_model_runtime.py"
spec = importlib.util.spec_from_file_location("dev_model_runtime", PATH)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def environment():
    return {"DEPLOYMENT_ENVIRONMENT": "render-development", "DEV_MODEL_SSH_ROLE": "api",
        "DEV_MODEL_SSH_ENABLED": "true",
        "DEV_MODEL_SSH_KEY_B64": base64.b64encode(b"-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic\n").decode(),
        "DEV_MODEL_SSH_KNOWN_HOST": runtime.HOST + " ssh-ed25519 " + "A" * 68,
        "CHATGPT_RESERVE_TOKEN": "synthetic_application_bearer"}


@pytest.mark.parametrize("change,code", [
    ({"DEPLOYMENT_ENVIRONMENT": "kz-production"}, "wrong_environment"),
    ({"DEV_MODEL_SSH_ROLE": "superadmin"}, "wrong_environment"),
    ({"DEV_MODEL_SSH_KEY_B64": "not base64"}, "invalid_private_credential"),
    ({"DEV_MODEL_SSH_KEY_B64": base64.b64encode(b"not a key").decode()}, "invalid_private_credential"),
    ({"DEV_MODEL_SSH_KNOWN_HOST": "untrusted ssh-ed25519 " + "A" * 68}, "invalid_host_pin"),
    ({"DEV_MODEL_SSH_KNOWN_HOST": runtime.HOST + " ssh-ed25519 " + "A" * 68 + "\nother"}, "invalid_host_pin"),
])
def test_config_denies_unsafe_input(change, code):
    with pytest.raises(runtime.RuntimeBlocked, match=code):
        runtime.credentials({**environment(), **change})


def test_child_has_no_tunnel_credentials_but_keeps_application_bearer():
    child = runtime.child_environment(environment())
    assert not any(key.startswith("DEV_MODEL_SSH_") for key in child)
    assert child["CHATGPT_RESERVE_TOKEN"] == "synthetic_application_bearer"


def test_worker_has_its_own_exact_dev_environment():
    config = {**environment(), "DEV_MODEL_SSH_ROLE": "worker", "DEPLOYMENT_ENVIRONMENT": "render-development-worker"}
    assert runtime.credentials(config)
    with pytest.raises(runtime.RuntimeBlocked, match="wrong_environment"):
        runtime.credentials({**config, "DEPLOYMENT_ENVIRONMENT": "render-development"})


def test_ssh_has_only_minimal_nonsecret_environment():
    assert runtime.ssh_environment({**environment(), "PATH": "safe-bin", "LANG": "C"}) == {"PATH": "safe-bin", "LANG": "C"}


def test_ssh_argv_is_pinned_no_secret_no_shell_or_public_listener():
    command = runtime.ssh_command(Path("identity"), Path("hosts"))
    assert command[-1] == "kamilya-dev-models@92.38.49.167"
    forwards = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "-L"]
    assert forwards == ["127.0.0.1:18999:10.77.77.2:18999", "127.0.0.1:18889:10.77.77.4:18005"]
    assert "-R" not in command and "-D" not in command and "-N" in command
    for required in ("StrictHostKeyChecking=yes", "BatchMode=yes", "IdentitiesOnly=yes",
                     "ExitOnForwardFailure=yes", "ForwardAgent=no", "IdentityAgent=none"):
        assert required in command
    assert "synthetic" not in " ".join(command)


def test_dead_ssh_is_not_ready():
    class Dead:
        def poll(self):
            return 255
    with pytest.raises(runtime.RuntimeBlocked, match="ssh_start_failed"):
        runtime.await_forward(Dead(), seconds=0.1)


@pytest.mark.parametrize("error,expected", [
    (b"Load key '/private/sensitive': error in libcrypto", "identity_crypto_error"),
    (b"kamilya-dev-models@host: Permission denied (publickey).", "authentication_denied"),
    (b"bind [127.0.0.1]:18999: Address already in use", "local_bind_conflict"),
    (b"connect to host host port 22: Connection timed out", "network_connect_timeout"),
])
def test_startup_diagnostics_are_fixed_codes_not_raw_data(error, expected):
    class Dead:
        stderr = io.BytesIO(error)
        def poll(self):
            return 255
    with pytest.raises(runtime.RuntimeBlocked, match="ssh_start_failed_" + expected):
        runtime.await_forward(Dead(), seconds=0.1)


def test_diagnostic_pipe_is_continuously_drained_and_memory_bounded():
    process = subprocess.Popen([sys.executable, "-c", "import sys; sys.stderr.write('x'*200000)"],
        stderr=subprocess.PIPE)
    runtime.drain_diagnostics(process)
    process.wait(timeout=5)
    process._kamilya_diagnostic_pump.join(timeout=1)
    assert len(process._kamilya_diagnostic_tail) == 65536
    assert "exit_0_diagnostic_bytes_65536" in runtime.ssh_failure(process)
    runtime.stop(process)


def test_empty_stderr_keeps_actual_exit_status_without_raw_output():
    class Dead:
        stderr = io.BytesIO()
        def poll(self):
            return -9
    assert runtime.ssh_failure(Dead()) == "ssh_start_failed_exit_-9_diagnostic_bytes_0"


def test_short_reset_diagnostic_is_classified_without_waiting_for_pipe_eof():
    """A flushed short SSH error must not disappear behind buffered read(1024)."""
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    writer = os.fdopen(write_fd, "wb")

    class Dead:
        stderr = stream

        def poll(self):
            return 255

    process = Dead()
    try:
        runtime.drain_diagnostics(process)
        writer.write(b"kex_exchange_identification: read: Connection reset by peer\n")
        writer.flush()
        assert runtime.ssh_failure(process) == "ssh_start_failed_network_connection_reset"
    finally:
        writer.close()
        process._kamilya_diagnostic_pump.join(timeout=1)
        stream.close()


def test_main_failure_has_one_safe_startup_identity(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(runtime.sys, "argv", [str(PATH), "--", "synthetic-child"])
    monkeypatch.setenv("RENDER_INSTANCE_ID", "synthetic-instance")
    monkeypatch.setenv("DEV_MODEL_SSH_RUN_ID", "foreign-untrusted-value")
    monkeypatch.setenv("CHATGPT_RESERVE_TOKEN", "never-log-this-value")

    def fail(_argv, source):
        seen.append(source["DEV_MODEL_SSH_RUN_ID"])
        raise runtime.RuntimeBlocked("ssh_start_failed_network_connection_reset")

    monkeypatch.setattr(runtime, "run", fail)
    assert runtime.main() == 78
    line = capsys.readouterr().out
    assert len(seen) == 1 and re.fullmatch(r"[0-9a-f]{12}", seen[0])
    assert "|startup_id=" + seen[0] in line
    assert re.search(r"\|instance_hash=[0-9a-f]{12}(?:\n|$)", line)
    assert "synthetic-instance" not in line
    assert "foreign-untrusted-value" not in line and "never-log-this-value" not in line


@pytest.mark.parametrize("failure,retry", [
    ("ssh_start_failed_network_connection_reset", True),
    ("ssh_start_failed_network_connection_closed", True),
    ("ssh_start_failed_authentication_denied", False),
    ("ssh_start_failed_host_pin_rejected", False),
    ("ssh_start_failed_exit_255_diagnostic_bytes_0", False),
    ("ssh_start_failed_network_connect_timeout", False),
])
def test_only_one_pre_auth_transport_recovery_preserves_strict_failures(monkeypatch, capsys, failure, retry):
    processes = []
    stopped = []
    def spawn(*_args, **_kwargs):
        process = object()
        processes.append(process)
        return process
    def ready(_process):
        if len(processes) == 1:
            raise runtime.RuntimeBlocked(failure)
    monkeypatch.setattr(runtime, "spawn", spawn)
    monkeypatch.setattr(runtime, "stop", stopped.append)
    monkeypatch.setattr(runtime, "drain_diagnostics", lambda _process: None)
    monkeypatch.setattr(runtime, "await_forward", ready)
    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)
    source = {"DEV_MODEL_SSH_RUN_ID": "a" * 12, "RENDER_INSTANCE_ID": "synthetic-instance"}
    if retry:
        assert runtime.start_forward(Path("identity"), Path("hosts"), source) is processes[1]
        assert stopped == [processes[0]]
        output = capsys.readouterr().out
        assert "|startup_id=" + "a" * 12 in output
        phases = [line.split('|')[1] for line in output.splitlines()]
        assert phases == ['dev_private_models=forward_starting', 'dev_private_models=forward_cleanup', 'dev_private_models=forward_stopped', 'dev_private_models=startup_retry_once', 'dev_private_models=forward_starting', 'dev_private_models=forward_ready']
    else:
        with pytest.raises(runtime.RuntimeBlocked, match=failure):
            runtime.start_forward(Path("identity"), Path("hosts"), source)
        assert len(processes) == 1 and stopped == processes
        output = capsys.readouterr().out
        assert 'startup_retry_once' not in output
        assert [line.split('|')[1] for line in output.splitlines()] == ['dev_private_models=forward_starting', 'dev_private_models=forward_cleanup', 'dev_private_models=forward_stopped']
    assert 'synthetic-instance' not in output


def test_second_transport_reset_stops_without_unbounded_reconnect(monkeypatch):
    processes = []
    stopped = []
    def spawn(*_args, **_kwargs):
        process = object()
        processes.append(process)
        return process
    def failed(_process):
        raise runtime.RuntimeBlocked("ssh_start_failed_network_connection_reset")
    monkeypatch.setattr(runtime, "spawn", spawn)
    monkeypatch.setattr(runtime, "stop", stopped.append)
    monkeypatch.setattr(runtime, "drain_diagnostics", lambda _process: None)
    monkeypatch.setattr(runtime, "await_forward", failed)
    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)
    with pytest.raises(runtime.RuntimeBlocked, match="network_connection_reset"):
        runtime.start_forward(Path("identity"), Path("hosts"), {})
    assert len(processes) == 2 and stopped == processes


def test_unrelated_listener_never_establishes_ssh_ownership(monkeypatch):
    class Live:
        pid = 123
        def poll(self):
            return None
    monkeypatch.setattr(runtime, "owns_listeners", lambda _pid: False)
    monkeypatch.setattr(runtime, "_available", lambda _port: True)
    with pytest.raises(runtime.RuntimeBlocked, match="ssh_start_timeout"):
        runtime.await_forward(Live(), seconds=0.01)


def test_disabled_launcher_preserves_child_exit_code(tmp_path):
    result = subprocess.run([sys.executable, str(PATH), "--", sys.executable, "-c",
        "import os,sys; assert 'DEV_MODEL_SSH_KEY_B64' not in os.environ; sys.exit(7)"],
        env={**os.environ, **environment(), "DEV_MODEL_SSH_ENABLED": "false"}, capture_output=True, timeout=5)
    assert result.returncode == 7


def test_wrong_env_never_starts_ssh_or_child(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("spawned child"))
    with pytest.raises(runtime.RuntimeBlocked, match="wrong_environment"):
        runtime.run(["uvicorn"], {**environment(), "DEPLOYMENT_ENVIRONMENT": "kz-production"})


def test_owned_process_is_terminated_and_reaped():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    runtime.stop(process)
    assert process.poll() is not None
