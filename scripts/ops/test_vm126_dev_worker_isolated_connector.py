"""Isolated DEV connector is selected only by the exact managed opt-in."""
import hashlib
from pathlib import Path

import pytest

from scripts.ops import vm126_dev_worker_env_receiver as receiver
from scripts.ops import vm126_dev_worker_runtime as runtime
from scripts.ops import vm126_dev_worker_stage as stage
from scripts.ops.kz_remote_exec import StageResult
from scripts.ops.test_vm126_dev_worker_env import PROJECT_FINGERPRINT, RELEASE, managed_payload, payload

ISOLATED = "http://172.17.0.1:19000/v1"
LOOPBACK = "http://127.0.0.1:18999/v1"


@pytest.fixture(autouse=True)
def pin_project(monkeypatch):
    monkeypatch.setattr(receiver, "DATABASE_PROJECT_FINGERPRINT", PROJECT_FINGERPRINT)


def source(body):
    values = dict(line.split("=", 1) for line in body.decode().splitlines())
    values["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    return values


def build(*, isolated=False):
    return receiver.build_payload_from_render_values(source(managed_payload()), RELEASE,
                                                      isolated_managed_connector=isolated)


def test_fixed_endpoint_is_opt_in_and_default_is_unchanged():
    assert receiver.ISOLATED_MANAGED_CONNECTOR_URL == ISOLATED
    default = receiver.build_payload_from_render_values(source(managed_payload()), RELEASE)
    explicit_false = build(isolated=False)
    isolated = build(isolated=True)
    assert default == explicit_false and f"CHATGPT_RESERVE_URL={LOOPBACK}\n".encode() in default
    assert f"CHATGPT_RESERVE_URL={ISOLATED}\n".encode() in isolated
    assert b"DEPLOYMENT_ENVIRONMENT=vm-development-worker\n" in isolated
    assert receiver.validate_payload(isolated, RELEASE, hashlib.sha256(isolated).hexdigest())["release_sha"] == RELEASE


@pytest.mark.parametrize("flag", [1, 0, "true", None, [], {}])
def test_nonboolean_opt_in_is_rejected(flag):
    with pytest.raises((TypeError, ValueError)):
        build(isolated=flag)


def test_direct_and_noncanonical_render_scope_cannot_opt_in():
    with pytest.raises(ValueError):
        receiver.build_payload_from_render_values(source(payload()), RELEASE, isolated_managed_connector=True)
    values = source(managed_payload())
    values["DEPLOYMENT_ENVIRONMENT"] = "render-production-worker"
    with pytest.raises(ValueError):
        receiver.build_payload_from_render_values(values, RELEASE, isolated_managed_connector=True)


@pytest.mark.parametrize("url", [ISOLATED, "http://172.17.0.2:19000/v1", "http://172.17.0.1:19001/v1",
                                  "https://172.17.0.1:19000/v1", "http://evil.example:19000/v1"])
@pytest.mark.parametrize("isolated", [False, True])
def test_render_source_cannot_supply_isolated_or_arbitrary_endpoint(url, isolated):
    values = source(managed_payload())
    values["CHATGPT_RESERVE_URL"] = url
    with pytest.raises(ValueError):
        receiver.build_payload_from_render_values(values, RELEASE, isolated_managed_connector=isolated)


@pytest.mark.parametrize("url", ["http://172.17.0.2:19000/v1", "http://172.17.0.1:19001/v1",
                                  "https://172.17.0.1:19000/v1", "http://evil.example:19000/v1"])
def test_staged_payload_rejects_arbitrary_endpoint(url):
    body = managed_payload().replace(LOOPBACK.encode(), url.encode())
    with pytest.raises(ValueError):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())


def test_exact_payload_selects_receiver_v4_and_legacy_paths_stay_pinned():
    scenarios = [(build(isolated=True), stage.RECEIVER_PATH_V4, stage.RECEIVER_SHA_V4),
                 (managed_payload(), stage.RECEIVER_PATH_V3, stage.RECEIVER_SHA_V3),
                 (payload(), stage.RECEIVER_PATH, stage.RECEIVER_SHA)]
    for body, path, digest in scenarios:
        calls = []
        def runner(command, sent):
            calls.append((command, sent))
            if "hostname" in command:
                return StageResult(0, stage.VM126.expected_hostname.encode(), b"")
            if "sha256sum" in command:
                return StageResult(0, f"{digest}  {path}\n".encode(), b"")
            output = (f"STATUS|status=installed|release_sha={RELEASE}|payload_sha256="
                      f"{hashlib.sha256(body).hexdigest()}|keycount={len(body.splitlines())}\n")
            return StageResult(0, output.encode(), b"")
        assert stage.stage_payload(body, RELEASE, digest, runner)["status"] == "installed"
        assert path in calls[1][0] and path in calls[2][0] and calls[2][1] == body
        calls.clear()
        wrong = stage.RECEIVER_SHA_V3 if path == stage.RECEIVER_PATH_V4 else stage.RECEIVER_SHA_V4
        with pytest.raises(ValueError):
            stage.stage_payload(body, RELEASE, wrong, runner)
        assert not calls


@pytest.mark.parametrize("mode", ["isolated", "loopback", "direct"])
def test_runtime_checks_matching_receiver_identity_and_path(monkeypatch, mode):
    body = {"isolated": lambda: build(isolated=True), "loopback": managed_payload, "direct": payload}[mode]()
    values = dict(line.split("=", 1) for line in body.decode().splitlines())
    receiver_bytes = {"isolated": b"v4", "loopback": b"v3", "direct": b"v2"}
    monkeypatch.setattr(runtime, "RECEIVER_SHA_V4", hashlib.sha256(receiver_bytes["isolated"]).hexdigest())
    monkeypatch.setattr(runtime, "RECEIVER_SHA_V3", hashlib.sha256(receiver_bytes["loopback"]).hexdigest())
    monkeypatch.setattr(runtime, "RECEIVER_SHA", hashlib.sha256(receiver_bytes["direct"]).hexdigest())
    runtime.receiver_identity(values, receiver_bytes[mode])
    wrong = "direct" if mode != "direct" else "isolated"
    with pytest.raises(ValueError, match="receiver_changed"):
        runtime.receiver_identity(values, receiver_bytes[wrong])
    paths = []
    def secure_file(path, file_mode):
        paths.append(Path(path))
        if len(paths) == 1:
            return body
        raise ValueError("stop after observing selected path")
    monkeypatch.setattr(runtime, "EXPECTED_IDENTITY", {"image": "x", "release_sha": RELEASE,
                        "environment_sha256": hashlib.sha256(body).hexdigest()}, raising=False)
    monkeypatch.setattr(runtime, "inspect", lambda: {"Config": {"Env": [f"RELEASE_SHA={RELEASE}"]}})
    monkeypatch.setattr(runtime, "secure_file", secure_file)
    assert runtime.main() == 1
    suffix = {"isolated": "v4", "loopback": "v3", "direct": "v2"}[mode]
    assert paths[1].name == f"vm126_dev_worker_env_receiver-{suffix}.py"
