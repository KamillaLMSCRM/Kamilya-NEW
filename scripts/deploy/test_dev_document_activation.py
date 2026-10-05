"""Synthetic V4 document-draft activation tests; no provider or DB access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_BASE = Path(__file__).with_name("test_dev_workbench_activation.py")
_SPEC = importlib.util.spec_from_file_location("workbench_activation_fixtures", _BASE)
assert _SPEC and _SPEC.loader
_FIXTURES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURES)
controller = _FIXTURES.controller
FakeProviders = _FIXTURES.FakeProviders


def packet_data(tmp_path: Path, *, enabled: bool = False) -> dict:
    packet = _FIXTURES.packet_data()
    packet["schema"] = controller.DOCUMENT_ACTIVATION_SCHEMA
    packet["release_id"] = "REL-DEV-DOCUMENT-20261005-001"
    packet["configuration_ci_run_id"] = 175
    packet["document_draft_enabled"] = enabled
    receipt = json.dumps(
        {
            "current_revision": "0175", "expected_revision": "0175",
            "status": "PASS", "target": "canonical_supabase_dev_public_schema",
            "project_ref_sha256": controller.DEV_PROJECT_REF_SHA256,
        }, sort_keys=True, separators=(",", ":")
    ).encode()
    path = tmp_path / ".release-evidence" / "dev" / packet["release_id"] / "schema-gate.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(receipt)
    packet["schema_evidence"] = {"path": str(path), "sha256": hashlib.sha256(receipt).hexdigest()}
    return packet


def activation(packet: dict, providers: FakeProviders) -> controller.DevReleaseController:
    providers.repo_root = Path(packet["schema_evidence"]["path"]).parents[3]
    return controller.DevReleaseController(packet, providers)


def add_document_methods(providers: FakeProviders, *, enabled: bool = False) -> None:
    providers.document_flags = {"api": enabled, "worker": enabled, "frontend": enabled}
    providers.document_draft_flags = lambda _packet: dict(providers.document_flags)

    def setter(_packet, value):
        providers.calls.append(("set_document_draft_flags", value))
        changed = [key for key, old in providers.document_flags.items() if old is not value]
        for key in changed:
            providers.document_flags[key] = value
        return changed

    providers.set_document_draft_flags = setter


def test_v4_exact_shape_and_document_default_off(tmp_path: Path) -> None:
    packet = packet_data(tmp_path)
    assert controller.validate_activation_packet(packet)["document_draft_enabled"] is False
    with pytest.raises(controller.DevReleaseBlocked, match="unknown"):
        controller.validate_activation_packet({**packet, "extra": 1})
    with pytest.raises(controller.DevReleaseBlocked, match="document_draft_enabled"):
        controller.validate_activation_packet({**packet, "document_draft_enabled": "false"})


def test_v4_document_true_requires_old_workbench_true(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    packet["workbench_enabled"] = False
    with pytest.raises(controller.DevReleaseBlocked, match="requires_workbench"):
        controller.validate_activation_packet(packet)


def test_v4_rejects_0174_receipt_before_provider_calls(tmp_path: Path) -> None:
    packet = packet_data(tmp_path)
    receipt = Path(packet["schema_evidence"]["path"])
    body = json.loads(receipt.read_text())
    body["current_revision"] = body["expected_revision"] = "0174"
    receipt.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")))
    packet["schema_evidence"]["sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    providers = FakeProviders()
    add_document_methods(providers)
    with pytest.raises(controller.DevReleaseBlocked, match="0175"):
        activation(packet, providers).prepare(packet["release_id"])
    assert providers.calls == []


def test_v4_prepare_updates_document_flags_only_when_drifted(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = FakeProviders()
    providers.source_ci["run_id"] = 175
    add_document_methods(providers)
    result = activation(packet, providers).prepare(packet["release_id"])
    assert set(result["document_changed_labels"]) == {"api", "worker", "frontend"}
    assert providers.document_flags == {"api": True, "worker": True, "frontend": True}
    assert any(call[0] == "set_workbench_flags" for call in providers.calls)
    assert any(call[0] == "set_document_draft_flags" for call in providers.calls)
    providers.calls.clear()
    second = activation(packet, providers).prepare(packet["release_id"])
    assert second["document_changed_labels"] == []
    assert not any(call[0] == "set_document_draft_flags" for call in providers.calls)


def test_v4_execute_denies_document_drift_before_push(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = FakeProviders()
    providers.flags = {"api": True, "worker": True, "frontend": True}
    add_document_methods(providers, enabled=False)
    with pytest.raises(controller.DevReleaseBlocked, match="document_flag_mismatch"):
        activation(packet, providers).execute(packet["release_id"])
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


@pytest.mark.parametrize("bad", [{"api": True}, {"api": True, "worker": False, "frontend": 0}])
def test_invalid_document_inventory_prevents_all_flag_writes(tmp_path: Path, bad: dict) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = FakeProviders()
    providers.source_ci["run_id"] = 175
    providers.document_draft_flags = lambda _packet: bad
    providers.set_document_draft_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("write"))
    with pytest.raises(controller.DevReleaseBlocked, match="document_flag_shape"):
        activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0] in {"set_workbench_flags", "set_document_draft_flags"} for call in providers.calls)


def test_paid_plan_denial_precedes_document_inventory_or_writes(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = FakeProviders()
    providers.source_ci["run_id"] = 175
    providers.render_services["srv_api"]["plan"] = "starter"
    providers.document_draft_flags = lambda _packet: (_ for _ in ()).throw(AssertionError("inventory"))
    with pytest.raises(controller.DevReleaseBlocked, match="plan"):
        activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0] in {"set_workbench_flags", "set_document_draft_flags"} for call in providers.calls)


def test_v4_reconcile_denies_document_drift_without_push_or_deploy(tmp_path: Path) -> None:
    packet = packet_data(tmp_path, enabled=True)
    providers = FakeProviders(branch_sha=_FIXTURES.RELEASE)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    add_document_methods(providers, enabled=False)
    with pytest.raises(controller.DevReleaseBlocked, match="document_flag_mismatch"):
        activation(packet, providers).reconcile()
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


def test_old_v3_prepare_and_execute_never_call_document_methods(tmp_path: Path) -> None:
    packet = packet_data(tmp_path)
    packet["schema"] = controller.PURGE_ACTIVATION_SCHEMA
    packet["workbench_enabled"] = False
    packet.pop("document_draft_enabled")
    receipt = Path(packet["schema_evidence"]["path"])
    body = json.loads(receipt.read_text())
    body["current_revision"] = body["expected_revision"] = "0173"
    receipt.write_text(json.dumps(body, sort_keys=True, separators=(",", ":")))
    packet["schema_evidence"]["sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    providers = FakeProviders()
    providers.source_ci["run_id"] = 175
    providers.document_draft_flags = lambda _packet: (_ for _ in ()).throw(AssertionError("called"))
    providers.set_document_draft_flags = lambda *_args: (_ for _ in ()).throw(AssertionError("called"))
    result = activation(packet, providers).prepare(packet["release_id"])
    assert result["status"] == "CONFIGURATION_READY"
    providers.calls.clear()
    result = activation(packet, providers).execute(packet["release_id"])
    assert result["status"] == "RELEASE_OK"


def test_live_adapter_document_inventory_absence_is_off_and_partial_readback_stops() -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = "synthetic"
    adapter.vercel_token = "synthetic"
    state = {"api": "false", "worker": "false", "frontend": "false"}
    calls = []

    def http(url, _token, *, method="GET", body=None):
        calls.append((url, method, body))
        if "api.render.com" in url:
            label = "api" if "/srv_api/" in url else "worker"
            if method == "PUT":
                state[label] = body["value"]
                return {"value": state[label]}
            return [] if state[label] == "false" or "&cursor=" in url else [{"cursor": "last", "envVar": {"key": controller.API_DOCUMENT_DRAFT_KEY, "value": state[label]}}]
        if method == "POST":
            state["frontend"] = body["value"]
        return {"envs": [] if state["frontend"] == "false" else [{"key": controller.WEB_DOCUMENT_DRAFT_KEY, "value": state["frontend"], "type": "plain", "target": ["production"]}]}

    adapter._http_json = http
    packet = _FIXTURES.packet_data()
    assert adapter.document_draft_flags(packet) == {"api": False, "worker": False, "frontend": False}
    assert adapter.set_document_draft_flags(packet, True) == ["api", "worker", "frontend"]
    assert all(controller.API_WORKBENCH_KEY not in call[0] for call in calls if call[1] == "PUT")


def test_live_adapter_first_document_readback_failure_stops_remaining_writes(tmp_path: Path) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = "synthetic"
    adapter.vercel_token = "synthetic"
    calls = []

    def http(url, _token, *, method="GET", body=None):
        calls.append((url, method, body))
        if method == "PUT":
            return {"value": "false"}
        if "api.render.com" in url:
            return [] if "&cursor=" in url else [{"cursor": "last", "envVar": {"key": controller.API_DOCUMENT_DRAFT_KEY, "value": "false"}}]
        return {"envs": []}

    adapter._http_json = http
    with pytest.raises(controller.DevReleaseBlocked, match="api_document_flag_readback_mismatch"):
        adapter.set_document_draft_flags(packet_data(tmp_path), True)
    writes = [call for call in calls if call[1] == "PUT"]
    assert len(writes) == 1


def test_render_inventory_uses_last_cursor_and_proves_completion() -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = "synthetic"
    calls = []
    pages = [
        [{"cursor": "first", "envVar": {"key": "OTHER", "value": "x"}},
         {"cursor": "last", "envVar": {"key": "OTHER2", "value": "y"}}],
        [{"cursor": "final", "envVar": {"key": controller.API_DOCUMENT_DRAFT_KEY, "value": "true"}}],
        [],
    ]
    def http(url, _token):
        calls.append(url)
        return pages.pop(0)
    adapter._http_json = http
    assert adapter._render_document_value({}, "srv_api") is True
    assert "cursor=last" in calls[1]
    assert "cursor=final" in calls[2]


@pytest.mark.parametrize("rows", [[{}], [{"envVar": {}}], [{"envVar": {"key": "OTHER"}, "cursor": 1}]])
def test_render_malformed_nonempty_inventory_cannot_mean_flag_absent(rows) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = "synthetic"
    adapter._http_json = lambda *_args: rows
    with pytest.raises(controller.DevReleaseBlocked, match="inventory"):
        adapter._render_document_value({}, "srv_api")


@pytest.mark.parametrize("rows", [[None], [{"key": "OTHER", "target": None}],
                                  [{"key": controller.WEB_DOCUMENT_DRAFT_KEY, "target": "production"}]])
def test_vercel_malformed_inventory_cannot_mean_flag_absent(rows) -> None:
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.vercel_token = "synthetic"
    adapter._http_json = lambda *_args: {"envs": rows}
    with pytest.raises(controller.DevReleaseBlocked, match="inventory"):
        adapter._vercel_document_value(_FIXTURES.packet_data())
