from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "vm_runtime", ROOT / "scripts/ops/vm126_dev_worker_runtime.py"
)
runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(runtime)


def row() -> dict:
    image = "ghcr.io/kamillalmscrm/kamilya-api@sha256:" + "a" * 64
    return {
        "Name": "/kamilya-dev-worker",
        "Id": "b" * 64,
        "Image": image,
        "Config": {
            "Image": image,
            "Cmd": runtime.COMMAND,
            "Entrypoint": [],
            "Hostname": "kamilya-dev-worker",
            "User": "10001:10001",
            "Env": ["RELEASE_SHA=" + "c" * 40],
        },
        "State": {"Status": "running", "Running": True, "StartedAt": "now"},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapAdd": [],
            "Devices": [],
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NanoCpus": 1000000000,
            "Memory": 1073741824,
            "NetworkMode": "bridge",
            "PortBindings": None,
            "Binds": None,
            "Tmpfs": {"/tmp": ""},
        },
        "NetworkSettings": {"Networks": {"bridge": {}}, "Ports": {}},
        "Mounts": [],
    }


def staged() -> dict[str, str]:
    return {"RELEASE_SHA": "c" * 40}


def inherited() -> dict[str, str]:
    return {}


def test_verify_container_accepts_exact_hardened_shape() -> None:
    image, release = runtime.verify_container(row(), staged(), inherited())
    assert image.endswith("a" * 64)
    assert release == "c" * 40


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda r: r["Config"].update({"User": "0"}), "process_invalid"),
        (lambda r: r["Config"].update({"Cmd": ["sh"]}), "command_invalid"),
        (lambda r: r["HostConfig"].update({"Memory": 0}), "resources_invalid"),
        (lambda r: r["HostConfig"].update({"NetworkMode": "host"}), "network_invalid"),
        (
            lambda r: r["HostConfig"].update({"Binds": ["/var/run/docker.sock:/x"]}),
            "mounts_invalid",
        ),
        (lambda r: r["HostConfig"].update({"CapDrop": []}), "capabilities_invalid"),
    ],
)
def test_verify_container_rejects_unsafe_reductions(mutation, reason: str) -> None:
    value = row()
    mutation(value)
    with pytest.raises(ValueError, match=reason):
        runtime.verify_container(value, staged(), inherited())


def test_health_contract_is_specific_and_not_a_generic_ping() -> None:
    assert "active_queues" in runtime.HEALTH_CODE
    assert "destination=[node]" in runtime.HEALTH_CODE
    assert "VM_DEV_CONSUMER_READY" in runtime.HEALTH_CODE
    assert "documents" in runtime.HEALTH_CODE and "maintenance" in runtime.HEALTH_CODE


def test_literal_verify_shell_embeds_runtime_contract() -> None:
    source = (ROOT / "scripts/ops/vm126_dev_worker_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "kamilya-dev-worker" in source
    assert "VM_DEV_CONSUMER_READY" in source
    shell = (ROOT / "scripts/ops/vm126_dev_worker_verify.sh").read_text(encoding="utf-8")
    assert shell.count("python3 - <<'PY'\n") == 1 and shell.endswith("\nPY\n")
    embedded = shell.split("python3 - <<'PY'\n", 1)[1].removesuffix("PY\n")
    assert embedded == source.rstrip("\n") + "\n"
    assert embedded.count("EXPECTED_IDENTITY = None") == 1
    compile(embedded, "canonical_vm_worker_probe", "exec")


@pytest.mark.parametrize("reply", ["missing", "wrong_queue", "correct"])
def test_health_checks_work_under_optimized_python(reply):
    import subprocess
    import sys

    fake = """import sys,types
class Inspector:
 def ping(self): return None if REPLY=="missing" else {"kamilya-dev-worker@vm126":{"ok":"pong"}}
 def active_queues(self): return {"kamilya-dev-worker@vm126":[{"name":x} for x in (["ai"] if REPLY=="wrong_queue" else ["ai","documents","maintenance"])]}
module=types.ModuleType("app.core.celery_app")
module.celery_app=types.SimpleNamespace(control=types.SimpleNamespace(inspect=lambda **kw:Inspector()))
sys.modules["app.core.celery_app"]=module
"""
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "REPLY=" + repr(reply) + "\n" + fake + runtime.HEALTH_CODE,
        ],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (reply == "correct")
    assert ("VM_DEV_CONSUMER_READY" in result.stdout) == (reply == "correct")


def test_expected_packet_identity_is_checked_before_consumer_probe():
    source = (ROOT / "scripts/ops/vm126_dev_worker_runtime.py").read_text(
        encoding="utf-8"
    )
    assert source.index(
        'raise ValueError("expected_identity_mismatch")'
    ) < source.index("health = docker(")


def test_vm_worker_image_preserves_existing_private_converter_supervision():
    assert runtime.COMMAND[:2] == ["python", "/app/dev_private_model_runtime.py"]
    assert runtime.COMMAND[2:] == runtime.CELERY_COMMAND


def test_managed_receiver_hash_and_legacy_receiver_identity(monkeypatch):
    import hashlib

    managed_source = b"managed receiver"
    legacy_source = b"legacy receiver"
    monkeypatch.setattr(
        runtime, "RECEIVER_SHA_V3", hashlib.sha256(managed_source).hexdigest()
    )
    monkeypatch.setattr(
        runtime, "RECEIVER_SHA", hashlib.sha256(legacy_source).hexdigest()
    )
    assert runtime.receiver_identity(
        {"AI_MANAGED_LUNA_QA_DEV_ENABLED": "true"}, managed_source
    )
    assert not runtime.receiver_identity({}, legacy_source)
    with pytest.raises(ValueError, match="receiver_changed"):
        runtime.receiver_identity(
            {"AI_MANAGED_LUNA_QA_DEV_ENABLED": "true"}, managed_source + b"changed"
        )


def test_native_receiver_identity_uses_versioned_hash(monkeypatch):
    import hashlib

    native_source = b"native receiver"
    monkeypatch.setattr(
        runtime, "RECEIVER_SHA_V5", hashlib.sha256(native_source).hexdigest()
    )
    native = {
        "AI_DIRECT_LUNA_QA_DEV_ENABLED": "false",
        "AI_MANAGED_LUNA_QA_DEV_ENABLED": "false",
        "AI_QA_LUNA_DEV_ENABLED": "false",
        "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED": "false",
    }
    assert runtime.receiver_identity(native, native_source) is False
    with pytest.raises(ValueError, match="receiver_changed"):
        runtime.receiver_identity(native, native_source + b"changed")
