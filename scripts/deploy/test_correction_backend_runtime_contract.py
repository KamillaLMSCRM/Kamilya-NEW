"""Independent runtime-contract oracles for correction backend activation.

These tests deliberately model the host-side Compose environment merge and
exercise the controller's effective-settings readback without a database,
network, or container runtime.
"""

from __future__ import annotations

import json
import sys
import types
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts.deploy import test_correction_backend_activation as activation

plane = activation.plane
legacy = activation.legacy
PREVIOUS = activation.PREVIOUS
CANDIDATE = activation.CANDIDATE
KEYS = activation.KEYS


def _effective_env(dotenv: dict[str, str], process_override: dict[str, str]) -> dict[str, str]:
    """Model Compose's explicit process environment overriding dotenv values."""
    merged = dict(dotenv)
    merged.update(process_override)
    return merged


def test_compose_anchor_override_wins_without_runtime_file_mutation(tmp_path):
    root = Path(__file__).resolve().parents[2]
    compose = (root / "infra/compose/kamilya-release-slot.yml").read_text(
        encoding="utf-8"
    )
    assert "env_file:" in compose
    assert compose.count("<<: *app-runtime") == 4
    for key in KEYS.values():
        assert f"{key}: ${{{key}:-false}}" in compose

    dotenv = {key: "false" for key in KEYS.values()}
    dotenv["UNRELATED_SECRET"] = "sentinel-not-to-be-logged"
    override = {KEYS[key]: str(value).lower() for key, value in CANDIDATE.items()}
    merged = _effective_env(dotenv, override)
    assert {key: merged[key] for key in KEYS.values()} == override
    assert dotenv["UNRELATED_SECRET"] == "sentinel-not-to-be-logged"


@pytest.mark.parametrize("explicit", [False, True])
def test_real_subprocess_seam_neutralizes_ambient_flags_and_uses_cli_dotenv(tmp_path, monkeypatch, explicit):
    controller = _controller(tmp_path, legacy.FakeRunner())
    captured = {}
    for key in KEYS.values():
        monkeypatch.setenv(key, "false")
    monkeypatch.setenv("UNRELATED_SENTINEL", "unchanged")
    dotenv = {KEYS[key]: str(value).lower() for key, value in PREVIOUS.items()}
    flags = CANDIDATE if explicit else None
    slot_env = controller._slot_env("green", legacy.NEW_IMAGE, legacy.NEW_SHA, flags)
    command = controller._compose("green", "up", "-d", "--no-deps", "api")
    assert command[command.index("--env-file") + 1] == str(controller.config.env_file)
    def fake_run(args, **kwargs):
        captured.update(kwargs["env"])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(plane.subprocess, "run", fake_run)
    plane.SubprocessRunner().run(command, env=slot_env)
    effective = _effective_env(dotenv, {key: captured[key] for key in KEYS.values() if key in captured})
    expected = CANDIDATE if explicit else PREVIOUS
    assert {key: effective[KEYS[key]] for key in KEYS} == {key: str(value).lower() for key, value in expected.items()}
    assert captured["UNRELATED_SENTINEL"] == "unchanged"
    if not explicit:
        assert all(key not in captured for key in KEYS.values())


class ReadbackRunner(legacy.FakeRunner):
    """Minimal runner whose effective-settings output is independently controlled."""

    def __init__(self, readback: str, *, fail_token: str = ""):
        super().__init__(initial_revision="0175", fail_token=fail_token)
        self.readback = readback

    def run(self, args, *, env=None):
        call = tuple(args)
        if "ps" in call:
            self.calls.append((call, dict(env or {})))
            slot = "blue" if "kamilya-blue" in call else "green"
            return slot + ":" + call[-1]
        if "inspect" in call:
            self.calls.append((call, dict(env or {})))
            image = legacy.OLD_IMAGE if str(call[-1]).startswith("blue:") else legacy.NEW_IMAGE
            return f"{image}|running|0"
        if "exec" in call:
            self.calls.append((call, dict(env or {})))
            return self.readback
        return super().run(args, env=env)


def _readback(flags: dict[str, bool], *, unsupported: set[str] | None = None) -> str:
    unsupported = unsupported or set()
    return json.dumps(
        {
            key: {"supported": key not in unsupported, "enabled": value}
            for key, value in flags.items()
        }
    )


def _controller(tmp_path, runner):
    data = asdict(legacy.manifest())
    data.update(
        schema_version=2,
        product_version="0.11.39",
        feature_flags=CANDIDATE.copy(),
        previous_feature_flags=PREVIOUS.copy(),
        migration={
            "mode": "no-migration",
            "from_revision": None,
            "to_revision": None,
            "rollback_compatible": False,
        },
    )
    return plane.ReleasePlane(plane.ReleaseManifest.parse(data), legacy.config(tmp_path), runner, activation.FeatureHealth())


def test_feature_readback_uses_canonical_get_settings_without_raw_environment(monkeypatch, capsys):
    config_module = types.ModuleType("app.core.config")
    config_module.get_settings = lambda: types.SimpleNamespace(
        METHODOLOGIST_WORKBENCH_ENABLED=True,
        METHODOLOGIST_DOCUMENT_DRAFT_ENABLED=False,
        METHODOLOGIST_LESSON_CORRECTION_ENABLED=True,
        UNRELATED_SECRET="sentinel-not-to-be-logged",
    )
    monkeypatch.setitem(sys.modules, "app.core.config", config_module)
    exec(plane.FEATURE_READBACK, {"__name__": "__main__"})
    captured = capsys.readouterr().out
    assert "UNRELATED_SECRET" not in captured and "sentinel-not-to-be-logged" not in captured
    output = json.loads(captured)
    assert output == {
        "workbench": {"supported": True, "enabled": True},
        "document_draft": {"supported": True, "enabled": False},
        "lesson_correction": {"supported": True, "enabled": True},
    }


@pytest.mark.parametrize(
    "readback",
    [
        json.dumps({"workbench": {"supported": True, "enabled": True}}),
        '{"workbench":{"supported":true,"enabled":true},"workbench":{"supported":true,"enabled":false},"document_draft":{"supported":true,"enabled":true},"lesson_correction":{"supported":true,"enabled":true}}',
        json.dumps({"workbench": {"supported": True, "enabled": "true"}, "document_draft": {"supported": True, "enabled": True}, "lesson_correction": {"supported": True, "enabled": True}}),
        json.dumps({"workbench": {"supported": True, "enabled": True}, "document_draft": {"supported": True, "enabled": True}, "lesson_correction": {"supported": True, "enabled": True}, "extra": {"supported": True, "enabled": False}}),
    ],
)
def test_candidate_rejects_adversarial_effective_settings_readback(tmp_path, readback):
    controller = _controller(tmp_path, ReadbackRunner(readback))
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller._verify_services("green", legacy.NEW_IMAGE, legacy.NEW_SHA, CANDIDATE, ("api",))


def test_candidate_missing_false_is_not_accepted(tmp_path):
    disabled = {**CANDIDATE, "lesson_correction": False}
    readback = _readback(disabled, unsupported={"lesson_correction"})
    controller = _controller(tmp_path, ReadbackRunner(readback))
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller._verify_services("green", legacy.NEW_IMAGE, legacy.NEW_SHA, disabled, ("api",))


def test_old_image_missing_false_is_explicitly_allowed(tmp_path):
    readback = _readback(PREVIOUS, unsupported={"lesson_correction"})
    controller = _controller(tmp_path, ReadbackRunner(readback))
    controller._verify_services(
        "blue", legacy.OLD_IMAGE, legacy.OLD_SHA, PREVIOUS, ("api",), allow_unsupported_disabled=True
    )


def test_upgrade_failure_after_backup_does_not_stop_old_workers_or_leak_evidence(tmp_path):
    runner = ReadbackRunner(_readback(PREVIOUS), fail_token="upgrade 0178")
    data = asdict(legacy.manifest())
    data.update(
        schema_version=2,
        product_version="0.11.39",
        feature_flags=CANDIDATE.copy(),
        previous_feature_flags=PREVIOUS.copy(),
        migration={
            "mode": "exact",
            "from_revision": "0175",
            "to_revision": "0178",
            "rollback_compatible": True,
        },
    )
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(data), legacy.config(tmp_path), runner, activation.FeatureHealth())
    with pytest.raises(plane.ReleasePlaneError, match="synthetic_command_failure"):
        controller.execute(controller.manifest.release_id)

    commands = [" ".join(call) for call, _ in runner.calls]
    assert any("backup-gate" in command for command in commands)
    assert any("upgrade 0178" in command for command in commands)
    assert not any(" stop " in f" {command} " for command in commands)
    record = json.loads((controller.config.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert record["status"] == "FAILED"
    assert record["failure"] == "synthetic_command_failure"
    assert "UNRELATED_SECRET" not in json.dumps(record)
