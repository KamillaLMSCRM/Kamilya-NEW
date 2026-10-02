from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.deploy import release_runner_bridge as bridge
from scripts.ops import ct137_native_release as release
from scripts.ops import test_ct137_native_release as native_fixtures


SHA = native_fixtures.SHA
CURRENT = native_fixtures.CURRENT
ROLLBACK = native_fixtures.ROLLBACK


def _packet(*, schema_version: int = 2, workbench_enabled: bool = False) -> release.ReleasePacket:
    raw = native_fixtures._packet().to_mapping()
    raw["schema_version"] = schema_version
    if schema_version == 2:
        raw["workbench_enabled"] = workbench_enabled
    return release.ReleasePacket.from_mapping(raw)


def _write_bound_config(root: Path, *, enabled: bool) -> Path:
    manifest = root / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    path = root / "build-config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_sha": payload["release_sha"],
                "product_version": payload["product_version"],
                "sha256": payload["sha256"],
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "workbench_enabled": enabled,
            }
        ),
        encoding="utf-8",
    )
    return path


def _true28_artifact(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    native_fixtures._artifact(root, product_version="0.11.28")
    _write_bound_config(root, enabled=True)
    return root


def _false27_artifact(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    native_fixtures._artifact(root, product_version="0.11.27")
    _write_bound_config(root, enabled=False)
    return root


def _orchestrator(host: native_fixtures.FakeHost | None = None) -> release.NativeReleaseOrchestrator:
    return release.NativeReleaseOrchestrator(
        repository=native_fixtures.FakeRepository(),
        github=native_fixtures.FakeGithub(),
        host=host or native_fixtures.FakeHost(),
        public=native_fixtures.FakePublic(),
    )


def test_packet_schema_one_is_legacy_off_and_omits_new_field() -> None:
    packet = native_fixtures._packet()

    assert packet.workbench_enabled is False
    assert "workbench_enabled" not in packet.to_mapping()


@pytest.mark.parametrize(
    "mutator, reason",
    [
        (lambda raw: raw.update(workbench_enabled=True), "release_packet_fields_invalid"),
        (lambda raw: raw.update(schema_version=2), "release_packet_fields_invalid"),
    ],
)
def test_schema_one_rejects_new_or_mismatched_fields(mutator, reason: str) -> None:
    raw = native_fixtures._packet().to_mapping()
    mutator(raw)

    with pytest.raises(release.ReleaseBlocked, match=reason):
        release.ReleasePacket.from_mapping(raw)


@pytest.mark.parametrize(
    "raw_update",
    [
        {},
        {"workbench_enabled": 1},
        {"workbench_enabled": "true"},
        {"workbench_enabled": None},
        {"workbench_enabled": False, "unknown": False},
    ],
)
def test_schema_two_requires_exact_boolean_and_no_unknown_fields(raw_update: dict[str, object]) -> None:
    raw = native_fixtures._packet().to_mapping()
    raw["schema_version"] = 2
    raw.update(raw_update)

    if raw_update == {"workbench_enabled": False}:
        packet = release.ReleasePacket.from_mapping(raw)
        assert packet.workbench_enabled is False
    else:
        with pytest.raises(release.ReleaseBlocked):
            release.ReleasePacket.from_mapping(raw)


def test_schema_two_preserves_explicit_false() -> None:
    packet = _packet(workbench_enabled=False)

    assert packet.workbench_enabled is False
    assert packet.to_mapping()["workbench_enabled"] is False


def test_true_28_artifact_is_accepted_and_false_27_is_preserved(tmp_path: Path) -> None:
    _true28_artifact(tmp_path / "true28")
    enabled = release.inspect_native_artifact(tmp_path / "true28", SHA)
    assert enabled.workbench_enabled is True

    _false27_artifact(tmp_path / "false27")
    disabled = release.inspect_native_artifact(tmp_path / "false27", SHA)
    assert disabled.workbench_enabled is False


def test_true_27_artifact_is_rejected(tmp_path: Path) -> None:
    native_fixtures._artifact(tmp_path, product_version="0.11.27")
    _write_bound_config(tmp_path, enabled=True)

    with pytest.raises(release.ReleaseBlocked, match="artifact_build_config_invalid"):
        release.inspect_native_artifact(tmp_path, SHA)


@pytest.mark.parametrize("packet_factory", [lambda: native_fixtures._packet(), lambda: _packet(workbench_enabled=False)])
def test_enabled_artifact_is_denied_for_off_packet_before_staging(tmp_path: Path, packet_factory) -> None:
    _true28_artifact(tmp_path)
    host = native_fixtures.FakeHost()
    orchestrator = _orchestrator(host)

    with pytest.raises(release.ReleaseBlocked):
        orchestrator.preflight(packet_factory(), tmp_path)

    assert not any(call[0] in {"stage", "deploy"} for call in host.calls)


def test_legacy_artifact_unknown_flag_is_denied_for_schema_two(tmp_path: Path) -> None:
    native_fixtures._artifact(tmp_path, product_version="0.11.1")

    with pytest.raises(release.ReleaseBlocked):
        _orchestrator().preflight(_packet(workbench_enabled=True), tmp_path)


def test_matching_true_schema_two_execute_stages_only_archive_manifest_and_reports_true(tmp_path: Path) -> None:
    _true28_artifact(tmp_path)
    host = native_fixtures.FakeHost()

    result = _orchestrator(host).execute(_packet(workbench_enabled=True), tmp_path)

    stages = [call for call in host.calls if call[0] == "stage"]
    assert [stage[1] for stage in stages] == [
        f"frontend-native-{SHA}.tar.gz",
        f"frontend-native-{SHA}.manifest.json",
    ]
    assert sum(call[0] == "deploy" for call in host.calls) == 1
    assert result["preflight"]["workbench_enabled"] is True
    assert result["preflight"]["artifact"]["workbench_enabled"] is True
    assert result["technical_readback"]["workbench_enabled"] is True
    assert result["technical_readback"]["workbench_flag_evidence"] == "immutable_build_config"
    assert result["technical_readback"]["runtime_feature_acceptance"] == "SEPARATE_TEST_RUNNER_REQUIRED"
    assert result["workbench_enabled"] is True


def test_true_to_false_drift_between_preflight_and_execute_stops_before_staging(tmp_path: Path) -> None:
    _true28_artifact(tmp_path)
    config = tmp_path / "build-config.json"

    class MutatingHost(native_fixtures.FakeHost):
        def boundary(self, rollback_sha: str) -> dict[str, object]:
            result = super().boundary(rollback_sha)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["workbench_enabled"] = False
            config.write_text(json.dumps(payload), encoding="utf-8")
            return result

    host = MutatingHost()
    with pytest.raises(release.ReleaseBlocked):
        _orchestrator(host).execute(_packet(workbench_enabled=True), tmp_path)

    assert not any(call[0] in {"stage", "deploy"} for call in host.calls)


def _bridge_packet_payload(*, workbench_enabled: bool) -> dict[str, object]:
    raw = native_fixtures._packet().to_mapping()
    raw["schema_version"] = 2
    raw["workbench_enabled"] = workbench_enabled
    return raw


def test_bridge_binds_technical_flag_to_frozen_packet(tmp_path: Path) -> None:
    packet_path = tmp_path / "release-packet.json"
    content = (json.dumps(_bridge_packet_payload(workbench_enabled=True), sort_keys=True) + "\n").encode()
    packet_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    plan = bridge.plan_release(
        packet_path=packet_path,
        packet_sha256=digest,
        repo_root=Path(__file__).resolve().parents[2],
        evidence_root=Path(__file__).resolve().parents[2] / ".release-evidence",
    )

    assert plan["workbench_enabled"] is True
    technical = {
        "status": "READY",
        "release_id": plan["release_id"],
        "release_sha": plan["release_sha"],
        "workbench_enabled": True,
    }
    bridge._bind_technical_evidence(plan, technical)

    with pytest.raises(bridge.BridgeBlocked):
        bridge._bind_technical_evidence(plan, {**technical, "workbench_enabled": False})


@pytest.mark.parametrize("enabled", [False, True])
def test_schema_two_bridge_requires_explicit_typed_flag(enabled: bool) -> None:
    plan = {"schema_version": 2, "release_id": "test", "release_sha": SHA, "workbench_enabled": enabled}
    evidence = {"release_id": "test", "release_sha": SHA}
    with pytest.raises(bridge.BridgeBlocked, match="flag_missing"):
        bridge._bind_technical_evidence(plan, evidence)
    for bad in (None, 0, 1, "false", "true"):
        with pytest.raises(bridge.BridgeBlocked, match="flag_mismatch"):
            bridge._bind_technical_evidence(plan, {**evidence, "workbench_enabled": bad})


def test_packet_boolean_schema_is_not_integer_one() -> None:
    raw = native_fixtures._packet().to_mapping()
    raw["schema_version"] = True
    with pytest.raises(release.ReleaseBlocked, match="schema_invalid"):
        release.ReleasePacket.from_mapping(raw)
