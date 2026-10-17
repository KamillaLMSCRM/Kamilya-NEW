"""Synthetic V6 staff-structure activation contracts; no external state."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "correction_activation_fixtures", Path(__file__).with_name("test_dev_correction_activation.py"),
)
assert _SPEC and _SPEC.loader
_FIXTURES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURES)
controller = _FIXTURES.controller
RELEASE = "2" * 40
PREVIOUS = "1" * 40
SOURCE_BRANCH = "codex/staff-structure-dev-20261017"


def packet_data(tmp_path: Path, *, enabled: bool = True) -> dict:
    packet = _FIXTURES.packet_data(tmp_path, enabled=True)
    packet.update(
        schema=controller.STAFF_ACTIVATION_SCHEMA,
        release_id="REL-DEV-STAFF-20261017-001",
        lesson_correction_enabled=True,
        staff_structure_enabled=enabled,
        configuration_source_branch=SOURCE_BRANCH,
    )
    path = Path(packet["schema_evidence"]["path"])
    receipt = json.loads(path.read_bytes())
    receipt.update(current_revision="0183", expected_revision="0183")
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    packet["schema_evidence"]["sha256"] = hashlib.sha256(raw).hexdigest()
    return packet


def providers_for(packet: dict, *, staff_enabled: bool = False):
    providers = _FIXTURES.providers_for(packet, enabled=False)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    providers.document_flags = {"api": True, "worker": True, "frontend": True}
    providers.document_draft_flags = lambda _packet: dict(providers.document_flags)
    providers.correction_flags_state = {"api": True, "worker": True, "frontend": True}
    providers.correction_flags = lambda _packet: dict(providers.correction_flags_state)
    providers.staff_flags_state = {"api": staff_enabled, "worker": staff_enabled, "frontend": staff_enabled}
    providers.staff_flags = lambda _packet: dict(providers.staff_flags_state)

    def set_staff_flags(_packet, enabled):
        providers.calls.append(("set_staff_flags", enabled))
        changed = [key for key, old in providers.staff_flags_state.items() if old is not enabled]
        providers.staff_flags_state = {key: enabled for key in ("api", "worker", "frontend")}
        return changed

    providers.set_staff_flags = set_staff_flags
    providers.source_ci.update(
        run_id=182,
        branch=SOURCE_BRANCH,
        event="pull_request",
        base_branch="dev",
        same_repository_pr=True,
        release_sha=RELEASE,
        status="completed",
        conclusion="success",
    )
    packet["configuration_ci_run_id"] = 182
    remote_reads: list[str] = []

    def remote_branch_sha(repository: str, branch: str) -> str:
        remote_reads.append(branch)
        if repository != "KamillaLMSCRM/Kamilya-NEW":
            raise AssertionError("unexpected repository")
        if branch == SOURCE_BRANCH:
            return RELEASE
        if branch == "dev":
            return PREVIOUS
        raise AssertionError(f"unexpected branch read: {branch}")

    providers.remote_branch_sha = remote_branch_sha
    providers.remote_reads = remote_reads
    providers.repo_root = Path(packet["schema_evidence"]["path"]).parents[3]
    return providers


def activation(packet: dict, providers) -> controller.DevReleaseController:
    providers.repo_root = Path(packet["schema_evidence"]["path"]).parents[3]
    return controller.DevReleaseController(packet, providers)


def test_v6_exact_packet_binds_0183_and_feature_source_branch(tmp_path: Path) -> None:
    packet = packet_data(tmp_path)
    validated = controller.validate_activation_packet(packet)
    assert validated["schema"] == "kamilya-dev-release-v6"
    assert validated["staff_structure_enabled"] is True
    assert validated["configuration_source_branch"] == SOURCE_BRANCH


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda packet: packet.pop("staff_structure_enabled"), "unknown_or_missing_fields"),
        (lambda packet: packet.update(unreviewed=True), "unknown_or_missing_fields"),
        (lambda packet: packet.update(staff_structure_enabled="true"), "staff_structure_enabled_invalid"),
        (lambda packet: packet.update(configuration_source_branch="master"), "feature_branch_required"),
        (lambda packet: packet.update(configuration_source_branch="codex/../dev"), "feature_branch_required"),
        (lambda packet: packet.update(schema="kamilya-dev-release-v5"), "unknown_or_missing_fields"),
    ],
)
def test_v6_packet_rejects_missing_extra_nonboolean_or_wrong_branch_fields(tmp_path: Path, mutate, reason: str) -> None:
    packet = packet_data(tmp_path)
    mutate(packet)
    with pytest.raises(controller.DevReleaseBlocked, match=reason):
        controller.validate_activation_packet(packet)


def test_v6_prepare_uses_same_repository_dev_pr_and_sets_only_staff_flags(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet)

    result = activation(packet, providers).prepare(packet["release_id"])

    assert providers.remote_reads == [SOURCE_BRANCH, "dev"]
    assert providers.staff_flags_state == {"api": True, "worker": True, "frontend": True}
    assert result["configuration"]["observed_staff_flags"] == providers.staff_flags_state
    assert set(result["staff_changed_labels"]) == {"api", "worker", "frontend"}
    assert [call[0] for call in providers.calls if call[0].startswith("set_")] == ["set_staff_flags"]
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("branch", "codex/other-source", "same_repository_dev_pr_required"),
        ("event", "push", "same_repository_dev_pr_required"),
        ("base_branch", "master", "same_repository_dev_pr_required"),
        ("same_repository_pr", False, "same_repository_dev_pr_required"),
        ("release_sha", "3" * 40, "ci_not_successful"),
    ],
)
def test_v6_ci_mismatch_stops_before_any_setter(tmp_path: Path, field: str, value, reason: str) -> None:
    packet = packet_data(tmp_path)
    providers = providers_for(packet)
    providers.source_ci[field] = value

    with pytest.raises(controller.DevReleaseBlocked, match=reason):
        activation(packet, providers).prepare(packet["release_id"])

    assert not any(call[0].startswith("set_") for call in providers.calls)


@pytest.mark.parametrize("failure", ["source_sha", "dev_sha"])
def test_v6_branch_readback_mismatch_stops_before_all_setters(tmp_path: Path, failure: str) -> None:
    packet = packet_data(tmp_path)
    providers = providers_for(packet)
    if failure == "source_sha":
        providers.remote_branch_sha = lambda _repository, _branch: "3" * 40
        reason = "configuration_source_branch_sha_mismatch"
    else:
        original = providers.remote_branch_sha
        providers.remote_branch_sha = lambda repository, branch: "3" * 40 if branch == "dev" else original(repository, branch)
        reason = "configuration_dev_previous_sha_mismatch"

    with pytest.raises(controller.DevReleaseBlocked, match=reason):
        activation(packet, providers).prepare(packet["release_id"])

    assert not any(call[0].startswith("set_") for call in providers.calls)


@pytest.mark.parametrize("group", ["workbench", "document", "correction"])
def test_v6_existing_flag_drift_blocks_staff_setter(tmp_path: Path, group: str) -> None:
    packet = packet_data(tmp_path)
    providers = providers_for(packet)
    if group == "workbench":
        providers.flags = {"api": True, "worker": False, "frontend": True}
    elif group == "document":
        providers.document_draft_flags = lambda _packet: {"api": True, "worker": False, "frontend": True}
    else:
        providers.correction_flags = lambda _packet: {"api": True, "worker": False, "frontend": True}

    with pytest.raises(controller.DevReleaseBlocked, match="preserve_existing_feature_flags"):
        activation(packet, providers).prepare(packet["release_id"])

    assert not any(call[0].startswith("set_") for call in providers.calls)


@pytest.mark.parametrize(
    "bad_inventory",
    [
        {"api": True},
        {"api": True, "worker": False, "frontend": 0},
    ],
)
def test_v6_invalid_staff_inventory_prevents_all_setters(tmp_path: Path, bad_inventory: dict) -> None:
    packet = packet_data(tmp_path)
    providers = providers_for(packet)
    providers.staff_flags = lambda _packet: bad_inventory

    with pytest.raises(controller.DevReleaseBlocked, match="staff_flag_shape"):
        activation(packet, providers).prepare(packet["release_id"])

    assert not any(call[0].startswith("set_") for call in providers.calls)


def test_v6_live_inventory_absence_is_false_and_staff_setter_reads_back_exact_keys(tmp_path: Path) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = adapter.vercel_token = "synthetic"
    packet = packet_data(tmp_path)
    state: dict[str, bool] = {}
    calls: list[tuple[str, str, dict | None]] = []

    def http(url: str, _token: str, *, method: str = "GET", body: dict | None = None):
        calls.append((url, method, body))
        if "api.render.com" in url:
            service = "api" if "/srv_api/" in url else "worker"
            if method == "PUT":
                state[service] = body["value"] == "true"
                return {"value": body["value"]}
            if "&cursor=" in url:
                return []
            key = controller.API_STAFF_KEY
            return [] if service not in state else [{"cursor": "last", "envVar": {"key": key, "value": str(state[service]).lower()}}]
        if method == "POST":
            state["frontend"] = body["value"] == "true"
            return {}
        rows = [] if "frontend" not in state else [{
            "key": controller.WEB_STAFF_KEY,
            "value": str(state["frontend"]).lower(),
            "type": "plain",
            "target": ["production"],
        }]
        return {"envs": rows}

    adapter._http_json = http
    assert adapter.staff_flags(packet) == {"api": False, "worker": False, "frontend": False}
    assert adapter.set_staff_flags(packet, True) == ["api", "worker", "frontend"]
    assert adapter.staff_flags(packet) == {"api": True, "worker": True, "frontend": True}
    writes = [(url, method, body) for url, method, body in calls if method in {"PUT", "POST"}]
    assert len(writes) == 3
    assert all(body is not None and body.get("key", controller.API_STAFF_KEY) == controller.API_STAFF_KEY for _, method, body in writes if method == "PUT")
    assert writes[-1][2] == {
        "key": controller.WEB_STAFF_KEY,
        "value": "true",
        "type": "plain",
        "target": ["production"],
    }
    assert all(controller.API_WORKBENCH_KEY not in url for url, _, _ in writes)
    assert all(controller.API_DOCUMENT_DRAFT_KEY not in url for url, _, _ in writes)
    assert all(controller.API_CORRECTION_KEY not in url for url, _, _ in writes)


def test_live_source_ci_readback_reports_same_repository_pr_and_target_branch() -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter._gh = lambda _args: {
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "head_sha": RELEASE,
        "head_branch": SOURCE_BRANCH,
        "event": "pull_request",
        "id": 182,
        "repository": {"id": 100},
        "pull_requests": [{
            "head": {"repo": {"id": 100}},
            "base": {"ref": "dev", "repo": {"id": 100}},
        }],
    }

    result = adapter.verify_source_ci(182, RELEASE, "KamillaLMSCRM/Kamilya-NEW")

    assert result == {
        "status": "completed",
        "conclusion": "success",
        "release_sha": RELEASE,
        "branch": SOURCE_BRANCH,
        "event": "pull_request",
        "run_id": 182,
        "base_branch": "dev",
        "same_repository_pr": True,
    }


def test_v5_packet_rejects_v6_staff_fields(tmp_path: Path) -> None:
    packet = _FIXTURES.packet_data(tmp_path, enabled=True)
    packet["staff_structure_enabled"] = True
    packet["configuration_source_branch"] = SOURCE_BRANCH

    with pytest.raises(controller.DevReleaseBlocked, match="unknown_or_missing_fields"):
        controller.validate_activation_packet(packet)


@pytest.mark.parametrize("change", ["failed_ci", "foreign_pr", "source_moved"])
def test_v6_direct_execute_cannot_bypass_source_gate_with_matching_flags(tmp_path: Path, change: str) -> None:
    packet = packet_data(tmp_path)
    providers = providers_for(packet, staff_enabled=True)
    if change == "failed_ci":
        providers.source_ci["conclusion"] = "failure"
    elif change == "foreign_pr":
        providers.source_ci["same_repository_pr"] = False
    else:
        providers.remote_branch_sha = lambda _repo, branch: PREVIOUS if branch == "dev" else "3" * 40
    with pytest.raises(controller.DevReleaseBlocked):
        activation(packet, providers).execute(packet["release_id"])
    assert not any(call[0] in {"push_exact_sha", "trigger_render", "wait_vercel"} for call in providers.calls)
