"""Synthetic V5 correction deployment contracts; no external state or secrets."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "correction_document_fixtures", Path(__file__).with_name("test_dev_document_activation.py"),
)
assert _SPEC and _SPEC.loader
_FIXTURES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURES)
controller = _FIXTURES.controller
FakeProviders = _FIXTURES.FakeProviders


def packet_data(tmp_path: Path, *, enabled: bool = False) -> dict:
    packet = _FIXTURES.packet_data(tmp_path, enabled=True)
    packet.update(schema="kamilya-dev-release-v5", lesson_correction_enabled=enabled)
    path = Path(packet["schema_evidence"]["path"])
    receipt = json.loads(path.read_bytes())
    receipt.update(current_revision="0178", expected_revision="0178")
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    packet["schema_evidence"]["sha256"] = hashlib.sha256(raw).hexdigest()
    return packet


def test_v5_accepts_explicit_disabled_correction_packet(tmp_path: Path) -> None:
    result = controller.validate_activation_packet(packet_data(tmp_path))
    assert result["lesson_correction_enabled"] is False
    assert result["document_draft_enabled"] is True


def providers_for(packet: dict, *, enabled: bool = False) -> FakeProviders:
    providers = FakeProviders()
    providers.source_ci["run_id"] = 175
    providers.flags = {"api": True, "worker": True, "frontend": True}
    _FIXTURES.add_document_methods(providers, enabled=True)
    providers.correction_flags_state = {"api": enabled, "worker": enabled, "frontend": enabled}
    providers.correction_flags = lambda _packet: dict(providers.correction_flags_state)

    def setter(_packet, value):
        providers.calls.append(("set_correction_flags", value))
        changed = [label for label, old in providers.correction_flags_state.items() if old is not value]
        providers.correction_flags_state = {"api": value, "worker": value, "frontend": value}
        return changed

    providers.set_correction_flags = setter
    providers.repo_root = Path(packet["schema_evidence"]["path"]).parents[3]
    return providers


def activation(packet: dict, providers: FakeProviders) -> controller.DevReleaseController:
    providers.repo_root = Path(packet["schema_evidence"]["path"]).parents[3]
    return controller.DevReleaseController(packet, providers)


def test_v5_prepare_enables_correction_with_observed_configuration(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet)
    result = controller.DevReleaseController(packet, providers).prepare(packet["release_id"])
    assert providers.correction_flags_state == {"api": True, "worker": True, "frontend": True}
    assert result["configuration"]["observed_correction_flags"] == {"api": True, "worker": True, "frontend": True}
    assert result["configuration"]["observed_document_flags"] == {"api": True, "worker": True, "frontend": True}
    assert set(result["correction_changed_labels"]) == {"api", "worker", "frontend"}
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


def test_live_correction_inventory_absence_is_disabled(tmp_path: Path) -> None:
    adapter = controller.LiveProviderAdapter.__new__(controller.LiveProviderAdapter)
    adapter.render_token = adapter.vercel_token = "synthetic"
    adapter._http_json = lambda url, *_args, **_kwargs: {"envs": []} if "vercel.com" in url else []
    assert adapter.correction_flags(packet_data(tmp_path)) == {"api": False, "worker": False, "frontend": False}


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda packet: packet.pop("lesson_correction_enabled"), "missing_fields"),
        (lambda packet: packet.update(extra=True), "unknown_or_missing_fields"),
        (lambda packet: packet.update(lesson_correction_enabled="false"), "lesson_correction_enabled_invalid"),
    ],
)
def test_v5_correction_flag_packet_shape_is_strict(tmp_path: Path, mutate, reason: str) -> None:
    packet = packet_data(tmp_path)
    mutate(packet)
    with pytest.raises(controller.DevReleaseBlocked, match=reason):
        controller.validate_activation_packet(packet)


def test_v5_correction_true_requires_independent_workbench_true(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    packet["workbench_enabled"] = False
    packet["document_draft_enabled"] = False
    with pytest.raises(controller.DevReleaseBlocked, match="lesson_correction_requires_workbench_enabled"):
        controller.validate_activation_packet(packet)


@pytest.mark.parametrize("revision", ["0175", "0177"])
def test_v5_wrong_schema_receipt_refuses_before_provider_calls(tmp_path: Path, revision: str) -> None:
    packet = packet_data(tmp_path)
    receipt = Path(packet["schema_evidence"]["path"])
    body = json.loads(receipt.read_text())
    body.update(current_revision=revision, expected_revision=revision)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    receipt.write_bytes(raw)
    packet["schema_evidence"]["sha256"] = hashlib.sha256(raw).hexdigest()
    providers = providers_for(packet)
    with pytest.raises(controller.DevReleaseBlocked, match="0178"):
        activation(packet, providers).prepare(packet["release_id"])
    assert providers.calls == []


@pytest.mark.parametrize("group", ["workbench", "document", "correction"])
def test_v5_any_invalid_flag_inventory_prevents_all_setters(tmp_path: Path, group: str) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet)
    providers.source_ci["run_id"] = 175
    if group == "workbench":
        providers.workbench_flags = lambda _packet: {"api": True, "worker": False, "frontend": 0}
    elif group == "document":
        providers.document_draft_flags = lambda _packet: {"api": True, "worker": False, "frontend": 0}
    else:
        providers.correction_flags = lambda _packet: {"api": True, "worker": False, "frontend": 0}
    providers.set_workbench_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("workbench setter"))
    providers.set_document_draft_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("document setter"))
    providers.set_correction_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("correction setter"))
    with pytest.raises(controller.DevReleaseBlocked, match="flag_shape"):
        activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0].startswith("set_") for call in providers.calls)


def test_v5_prepare_is_idempotent_and_never_pushes(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet)
    providers.source_ci["run_id"] = 175
    first = activation(packet, providers).prepare(packet["release_id"])
    providers.calls.clear()
    second = activation(packet, providers).prepare(packet["release_id"])
    assert first["configuration"] == second["configuration"]
    assert second["changed_labels"] == []
    assert second["document_changed_labels"] == []
    assert second["correction_changed_labels"] == []
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


def test_v5_accepts_all_three_flags_disabled_independently(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=False)
    packet["workbench_enabled"] = False
    packet["document_draft_enabled"] = False
    providers = providers_for(packet, enabled=False)
    providers.flags = {"api": False, "worker": False, "frontend": False}
    providers.document_flags = {"api": False, "worker": False, "frontend": False}
    providers.document_draft_flags = lambda _packet: dict(providers.document_flags)
    providers.source_ci["run_id"] = 175
    result = activation(packet, providers).prepare(packet["release_id"])
    assert result["changed_labels"] == []
    assert result["document_changed_labels"] == []
    assert result["correction_changed_labels"] == []


def test_v5_accepts_correction_true_with_workbench_true_and_document_false(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    packet["document_draft_enabled"] = False
    providers = providers_for(packet, enabled=False)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    providers.document_flags = {"api": False, "worker": False, "frontend": False}
    providers.document_draft_flags = lambda _packet: dict(providers.document_flags)
    providers.source_ci["run_id"] = 175
    result = activation(packet, providers).prepare(packet["release_id"])
    assert result["changed_labels"] == []
    assert result["document_changed_labels"] == []
    assert set(result["correction_changed_labels"]) == {"api", "worker", "frontend"}


def test_v5_reads_all_inventory_groups_before_first_setter(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet, enabled=False)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    providers.document_flags = {"api": False, "worker": False, "frontend": False}
    providers.document_draft_flags = lambda _packet: dict(providers.document_flags)
    events: list[str] = []
    original_workbench = providers.workbench_flags
    providers.workbench_flags = lambda value: (events.append("workbench_read"), original_workbench(value))[1]
    original_document = providers.document_draft_flags
    providers.document_draft_flags = lambda value: (events.append("document_read"), original_document(value))[1]
    original_correction = providers.correction_flags
    providers.correction_flags = lambda value: (events.append("correction_read"), original_correction(value))[1]
    original_set = providers.set_correction_flags
    providers.set_correction_flags = lambda value, enabled: (events.append("correction_set"), original_set(value, enabled))[1]
    providers.source_ci["run_id"] = 175
    activation(packet, providers).prepare(packet["release_id"])
    assert {"workbench_read", "document_read", "correction_read"}.issubset(events[:events.index("correction_set")])


def test_v5_invalid_final_correction_inventory_blocks_earlier_setters(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet, enabled=False)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    providers.document_flags = {"api": False, "worker": False, "frontend": False}
    providers.document_draft_flags = lambda _packet: dict(providers.document_flags)
    providers.correction_flags = lambda _packet: {"api": True, "worker": False, "frontend": 0}
    providers.set_workbench_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("workbench setter"))
    providers.set_document_draft_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("document setter"))
    providers.set_correction_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("correction setter"))
    providers.source_ci["run_id"] = 175
    with pytest.raises(controller.DevReleaseBlocked, match="flag_shape"):
        activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0].startswith("set_") for call in providers.calls)


@pytest.mark.parametrize("mode", ["execute", "reconcile"])
def test_v5_drift_refuses_before_push_or_deploy(tmp_path: Path, mode: str) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet, enabled=False)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    providers.correction_flags_state = {"api": False, "worker": False, "frontend": False}
    if mode == "reconcile":
        providers.branch_sha = "2" * 40
    release = activation(packet, providers)
    with pytest.raises(controller.DevReleaseBlocked, match="correction_flag_mismatch"):
        release.execute(packet["release_id"]) if mode == "execute" else release.reconcile()
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


def test_v5_prepare_paid_plan_and_ci_guards_precede_flag_writes(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet)
    providers.source_ci["run_id"] = 175
    providers.render_services["srv_api"]["plan"] = "starter"
    with pytest.raises(controller.DevReleaseBlocked, match="plan"):
        activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0].startswith("set_") for call in providers.calls)
    providers = providers_for(packet)
    providers.source_ci["run_id"] = 175
    providers.source_ci["conclusion"] = "failure"
    with pytest.raises(controller.DevReleaseBlocked, match="ci_not_successful"):
        activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0].startswith("set_") for call in providers.calls)


def test_v5_execute_previous_sha_guard_precedes_push(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = providers_for(packet)
    providers.branch_sha = "3" * 40
    with pytest.raises(controller.DevReleaseBlocked, match="expected_previous_sha_mismatch"):
        activation(packet, providers).execute(packet["release_id"])
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


@pytest.mark.parametrize("schema", [controller.PACKET_SCHEMA, controller.ACTIVATION_SCHEMA, controller.PURGE_ACTIVATION_SCHEMA, controller.DOCUMENT_ACTIVATION_SCHEMA])
def test_v1_to_v4_never_call_correction_methods(tmp_path: Path, schema: str) -> None:
    packet = packet_data(tmp_path)
    packet["schema"] = schema
    packet["release_id"] = "REL-LEGACY-20261006-001"
    if schema in {controller.ACTIVATION_SCHEMA, controller.PURGE_ACTIVATION_SCHEMA, controller.DOCUMENT_ACTIVATION_SCHEMA}:
        packet.update(workbench_enabled=True, configuration_ci_run_id=175)
        receipt = json.dumps({"current_revision": controller.ACTIVATION_REVISIONS[schema], "expected_revision": controller.ACTIVATION_REVISIONS[schema], "status": "PASS", "target": "canonical_supabase_dev_public_schema", "project_ref_sha256": controller.DEV_PROJECT_REF_SHA256}, sort_keys=True, separators=(",", ":")).encode()
        path = tmp_path / ".release-evidence" / f"schema-gate-{schema}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(receipt)
        packet["schema_evidence"] = {"path": str(path), "sha256": hashlib.sha256(receipt).hexdigest()}
    if schema == controller.DOCUMENT_ACTIVATION_SCHEMA:
        packet["document_draft_enabled"] = False
    else:
        packet.pop("document_draft_enabled", None)
    if schema in {controller.PACKET_SCHEMA, controller.ACTIVATION_SCHEMA, controller.PURGE_ACTIVATION_SCHEMA, controller.DOCUMENT_ACTIVATION_SCHEMA}:
        packet.pop("lesson_correction_enabled", None)
    if schema == controller.PACKET_SCHEMA:
        packet.pop("workbench_enabled", None)
        packet.pop("configuration_ci_run_id", None)
        packet.pop("schema_evidence", None)
    providers = _FIXTURES.FakeProviders()
    providers.source_ci["run_id"] = 175
    providers.repo_root = tmp_path
    providers.flags = {"api": True, "worker": True, "frontend": True}
    providers.correction_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("correction read"))
    providers.set_correction_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("correction write"))
    if schema == controller.DOCUMENT_ACTIVATION_SCHEMA:
        _FIXTURES.add_document_methods(providers)
    result = controller.DevReleaseController(packet, providers).execute(packet["release_id"])
    assert result["status"] == "RELEASE_OK"


def test_live_correction_adapter_uses_single_key_writes_and_skips_idempotently(tmp_path: Path) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = adapter.vercel_token = "synthetic"
    state = {"api": "false", "worker": "false", "frontend": "false"}
    calls = []
    def http(url, _token, *, method="GET", body=None):
        calls.append((url, method, body))
        if "api.render.com" in url:
            label = "api" if "/srv_api/" in url else "worker"
            if method == "PUT":
                state[label] = body["value"]
            if "&cursor=" in url:
                return []
            return [{"cursor": "last", "envVar": {"key": controller.API_CORRECTION_KEY, "value": state[label]}}]
        if method == "POST":
            state["frontend"] = body["value"]
        return {"envs": [{"key": controller.WEB_CORRECTION_KEY, "value": state["frontend"], "type": "plain", "target": ["production"]}]}
    adapter._http_json = http
    packet = _FIXTURES.packet_data(tmp_path)
    assert adapter.set_correction_flags(packet, True) == ["api", "worker", "frontend"]
    writes = [call for call in calls if call[1] in {"PUT", "POST"}]
    assert len(writes) == 3
    assert writes[0][2] == {"value": "true"} and writes[1][2] == {"value": "true"}
    assert writes[2][2] == {"key": controller.WEB_CORRECTION_KEY, "value": "true", "type": "plain", "target": ["production"]}
    calls.clear()
    assert adapter.set_correction_flags(packet, True) == []
    assert not any(call[1] in {"PUT", "POST"} for call in calls)
    assert adapter.set_correction_flags(packet, False) == ["api", "worker", "frontend"]


def test_live_correction_adapter_first_readback_failure_stops_remaining_writes(tmp_path: Path) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = adapter.vercel_token = "synthetic"
    calls = []
    def http(url, _token, *, method="GET", body=None):
        calls.append((url, method, body))
        if method == "PUT":
            return {"value": "false"}
        if "api.render.com" in url:
            if "&cursor=" in url:
                return []
            return [{"cursor": "last", "envVar": {"key": controller.API_CORRECTION_KEY, "value": "false"}}]
        return {"envs": []}
    adapter._http_json = http
    with pytest.raises(controller.DevReleaseBlocked, match="api_correction_flag_readback_mismatch"):
        adapter.set_correction_flags(_FIXTURES.packet_data(tmp_path), True)
    assert len([call for call in calls if call[1] == "PUT"]) == 1
    assert not any(call[1] == "POST" for call in calls)


@pytest.mark.parametrize("bad", [
    [[{"cursor": "first", "envVar": {"key": controller.API_CORRECTION_KEY, "value": "false"}}],
     [{"cursor": "second", "envVar": {"key": controller.API_CORRECTION_KEY, "value": "true"}}],
     []],
    [{"cursor": "first", "envVar": {"key": controller.API_CORRECTION_KEY, "value": "false"}}],
])
def test_live_correction_render_pagination_rejects_later_duplicate_or_malformed(bad) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = "synthetic"
    pages = list(bad) if isinstance(bad, list) else [bad]
    adapter._http_json = lambda *_args, **_kwargs: pages.pop(0)
    with pytest.raises(controller.DevReleaseBlocked, match="duplicate|inventory"):
        adapter._render_feature_value("srv_api", controller.API_CORRECTION_KEY, "correction")


@pytest.mark.parametrize("rows", [
    [{"key": controller.WEB_CORRECTION_KEY, "value": "yes", "type": "plain", "target": ["production"]}],
    [{"key": controller.WEB_CORRECTION_KEY, "value": "true", "type": "plain", "target": ["production", "preview"]}],
])
def test_live_correction_frontend_rejects_nonliteral_or_shared_target(tmp_path: Path, rows) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.vercel_token = "synthetic"
    adapter._http_json = lambda *_args, **_kwargs: {"envs": rows}
    with pytest.raises(controller.DevReleaseBlocked, match="literal|scope"):
        adapter._vercel_feature_value(_FIXTURES.packet_data(tmp_path), controller.WEB_CORRECTION_KEY, "correction")
