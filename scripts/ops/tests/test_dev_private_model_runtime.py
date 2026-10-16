"""Database-free tests of the exact native DEV launcher seam."""
import base64
import importlib.util
import os
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
