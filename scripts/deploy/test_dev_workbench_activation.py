"""RED-first contract tests for the DEV workbench activation controller.

These tests deliberately use only synthetic packet/receipt/provider state.  They
must not contact GitHub, Render, Vercel, Supabase, a database, or load .env.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("dev_release_controller.py")
SPEC = importlib.util.spec_from_file_location("dev_release_controller_activation", MODULE_PATH)
assert SPEC and SPEC.loader
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)

PREVIOUS = "1" * 40
RELEASE = "2" * 40


def packet_data() -> dict:
    """Return a valid V2 packet shape without provider or environment data."""
    return {
        "schema": "kamilya-dev-release-v2",
        "release_id": "REL-DEV-WORKBENCH-20261002-001",
        "release_sha": RELEASE,
        "expected_previous_sha": PREVIOUS,
        "repository": "KamillaLMSCRM/Kamilya-NEW",
        "branch": "dev",
        "migration_scope": "none",
        "github": {"workflow": "CI"},
        "vercel": {
            "project_id": "prj_test",
            "project_name": "kamilya-lms-dev",
            "team_id": "team_test",
            "expected_plan": "hobby",
            "public_url": "https://dev.example.test/login",
        },
        "render": {
            "api_service_id": "srv_api",
            "worker_service_id": "srv_worker",
            "expected_plan": "free",
            "api_auto_deploy": "yes",
            "worker_auto_deploy": "no",
            "api_health_url": "https://api.example.test/api/v1/health",
            "worker_health_url": "https://worker.example.test/",
        },
        "workbench_enabled": True,
        "configuration_ci_run_id": 172,
        "schema_evidence": {
            "path": ".release-evidence/dev/REL-DEV-WORKBENCH-20261002-001/schema-gate.json",
            "sha256": "" + "a" * 64,
        },
    }


def _receipt() -> bytes:
    return json.dumps(
        {
            "current_revision": "0172",
            "expected_revision": "0172",
            "status": "PASS",
            "target": "canonical_supabase_dev_public_schema",
            "project_ref_sha256": controller.DEV_PROJECT_REF_SHA256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class FakeProviders:
    """Provider double that records every read/write and exposes exact flags."""

    def __init__(self, *, branch_sha: str = PREVIOUS) -> None:
        self.branch_sha = branch_sha
        self.calls: list[tuple] = []
        self.ci = {"status": "completed", "conclusion": "success", "run_id": 73}
        self.source_ci = {
            "status": "completed",
            "conclusion": "success",
            "run_id": 172,
            "branch": "master",
            "event": "push",
            "release_sha": RELEASE,
            "sha": RELEASE,
        }
        self.vercel = {"status": "READY", "deployment_id": "dpl_1", "release_sha": RELEASE, "plan": "hobby"}
        self.vercel_project_data = {
            "project_id": "prj_test", "project_name": "kamilya-lms-dev", "branch": "dev", "plan": "hobby"
        }
        self.render_services = {
            "srv_api": {"plan": "free", "branch": "dev", "auto_deploy": "yes"},
            "srv_worker": {"plan": "free", "branch": "dev", "auto_deploy": "no"},
        }
        self.render_deploys = {
            "srv_api": {"status": "live", "deployment_id": "dep_api", "release_sha": RELEASE},
            "srv_worker": {"status": "live", "deployment_id": "dep_worker", "release_sha": RELEASE},
        }
        self.flags = {"api": False, "worker": False, "frontend": False}
        self.health = {
            "https://api.example.test/api/v1/health": {"status": "ok", "deployment_environment": "render-development", "release_sha": RELEASE},
            "https://worker.example.test/": "ok",
            "https://dev.example.test/login": {"http_status": 200},
        }

    def remote_branch_sha(self, repository: str, branch: str) -> str:
        self.calls.append(("remote_branch_sha", repository, branch))
        return RELEASE if branch == "master" else self.branch_sha

    def push_exact_sha(self, repository: str, branch: str, release_sha: str) -> None:
        self.calls.append(("push_exact_sha", repository, branch, release_sha))
        self.branch_sha = release_sha

    def wait_github_ci(self, repository: str, workflow: str, release_sha: str) -> dict:
        self.calls.append(("wait_github_ci", repository, workflow, release_sha))
        return self.ci

    def verify_source_ci(self, run_id: int, release_sha: str, repository: str) -> dict:
        self.calls.append(("verify_source_ci", run_id, release_sha, repository))
        return self.source_ci

    def wait_vercel(self, project_id: str, team_id: str, release_sha: str) -> dict:
        self.calls.append(("wait_vercel", project_id, team_id, release_sha))
        return self.vercel

    def vercel_project(self, project_id: str, team_id: str) -> dict:
        self.calls.append(("vercel_project", project_id, team_id))
        return self.vercel_project_data

    def render_service(self, service_id: str) -> dict:
        self.calls.append(("render_service", service_id))
        return self.render_services[service_id]

    def trigger_render(self, service_id: str, release_sha: str) -> str:
        self.calls.append(("trigger_render", service_id, release_sha))
        return self.render_deploys[service_id]["deployment_id"]

    def find_render(self, service_id: str, release_sha: str):
        self.calls.append(("find_render", service_id, release_sha))
        return None

    def wait_render(self, service_id: str, deployment_id: str, release_sha: str) -> dict:
        self.calls.append(("wait_render", service_id, deployment_id, release_sha))
        return self.render_deploys[service_id]

    def read_health(self, url: str):
        self.calls.append(("read_health", url))
        return self.health[url]

    def workbench_flags(self, packet: dict) -> dict:
        self.calls.append(("workbench_flags", packet["release_id"]))
        return dict(self.flags)

    def set_workbench_flags(self, packet: dict, enabled: bool) -> list[str]:
        self.calls.append(("set_workbench_flags", packet["release_id"], enabled))
        changed = [label for label, value in self.flags.items() if value is not enabled]
        for label in changed:
            self.flags[label] = enabled
        return changed


def _write_packet(tmp_path: Path, *, mutate=None, receipt: bytes | None = None) -> tuple[dict, Path]:
    packet = packet_data()
    receipt_path = tmp_path / ".release-evidence" / "dev" / packet["release_id"] / "schema-gate.json"
    receipt_path.parent.mkdir(parents=True)
    body = _receipt() if receipt is None else receipt
    receipt_path.write_bytes(body)
    packet["schema_evidence"]["path"] = str(receipt_path)
    packet["schema_evidence"]["sha256"] = hashlib.sha256(body).hexdigest()
    if mutate:
        mutate(packet)
    return packet, receipt_path


def _activation(packet: dict, providers: FakeProviders):
    evidence_path = Path(packet["schema_evidence"]["path"])
    providers.repo_root = evidence_path.parents[3]
    return controller.DevReleaseController(packet, providers)


def test_v2_packet_accepts_exact_typed_fields_and_rejects_unknown_fields(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    assert controller.validate_activation_packet(packet)["workbench_enabled"] is True
    with pytest.raises(controller.DevReleaseBlocked, match="unknown"):
        controller.validate_activation_packet({**packet, "unexpected": 1})


@pytest.mark.parametrize("value", [1, 0, "true", "false", None])
def test_v2_packet_rejects_non_boolean_workbench_flag(tmp_path: Path, value: object) -> None:
    packet, _ = _write_packet(tmp_path, mutate=lambda p: p.update(workbench_enabled=value))
    with pytest.raises(controller.DevReleaseBlocked, match="workbench_enabled"):
        controller.validate_activation_packet(packet)


def test_v1_packet_is_not_accepted_by_activation_seam(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path, mutate=lambda p: p.update(schema="kamilya-dev-release-v1"))
    with pytest.raises(controller.DevReleaseBlocked, match="unknown_or_missing_fields"):
        _activation(packet, FakeProviders())


def test_schema_receipt_digest_and_0172_pass_are_checked_before_any_provider_call(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    packet["schema_evidence"]["sha256"] = "b" * 64
    providers = FakeProviders()
    with pytest.raises(controller.DevReleaseBlocked, match="schema.*digest"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert providers.calls == []


def test_schema_receipt_must_be_canonical_regular_and_bounded(tmp_path: Path) -> None:
    packet, receipt = _write_packet(tmp_path, receipt=b'{"schema_revision":"0169","status":"PASS"}')
    providers = FakeProviders()
    with pytest.raises(controller.DevReleaseBlocked, match="0172"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert providers.calls == []
    receipt.write_bytes(b"x" * 4097)
    packet["schema_evidence"]["sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    with pytest.raises(controller.DevReleaseBlocked, match="bounded|size"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert providers.calls == []


def test_prepare_requires_confirmation_and_checks_master_source_ci_and_dev_branch_before_setters(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders()
    with pytest.raises(controller.DevReleaseBlocked, match="confirmation"):
        _activation(packet, providers).prepare("WRONG")
    assert providers.calls == []
    providers.source_ci["branch"] = "dev"
    with pytest.raises(controller.DevReleaseBlocked, match="source.*branch|master"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0] == "set_workbench_flags" for call in providers.calls)


def test_prepare_rejects_paid_or_unknown_plans_before_setters(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders()
    providers.render_services["srv_api"]["plan"] = "starter"
    with pytest.raises(controller.DevReleaseBlocked, match="plan"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert not any(call[0] == "set_workbench_flags" for call in providers.calls)


def test_prepare_is_idempotent_and_changes_only_three_exact_flag_labels(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders()
    first = _activation(packet, providers).prepare(packet["release_id"])
    assert first["status"] == "CONFIGURATION_READY"
    assert set(first["changed_labels"]) == {"api", "worker", "frontend"}
    providers.calls.clear()
    second = _activation(packet, providers).prepare(packet["release_id"])
    assert second["changed_labels"] == []
    assert not any(call[0] == "set_workbench_flags" for call in providers.calls)


def test_prepare_stops_after_flag_update_readback_failure_without_continuing(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders()
    providers.workbench_flags = lambda _packet: {"api": True, "worker": False, "frontend": False}
    with pytest.raises(controller.DevReleaseBlocked, match="readback|flag"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert [call[0] for call in providers.calls].count("set_workbench_flags") <= 1


def test_legacy_controller_never_calls_workbench_flag_methods() -> None:
    providers = FakeProviders()
    legacy_packet = packet_data()
    legacy_packet["schema"] = "kamilya-dev-release-v1"
    for key in ("workbench_enabled", "configuration_ci_run_id", "schema_evidence"):
        legacy_packet.pop(key)
    legacy = controller.DevReleaseController(legacy_packet, providers)
    result = legacy.execute("REL-DEV-WORKBENCH-20261002-001")
    assert result["status"] == "RELEASE_OK"
    assert not any(call[0] in {"workbench_flags", "set_workbench_flags"} for call in providers.calls)


def test_v2_execute_denies_flag_drift_before_push_or_deploy(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders()
    providers.flags["api"] = False
    with pytest.raises(controller.DevReleaseBlocked, match="flag.*mismatch|prepare"):
        _activation(packet, providers).execute(packet["release_id"])
    assert not any(call[0] in {"push_exact_sha", "trigger_render"} for call in providers.calls)


def test_v2_reconcile_denies_flag_drift_without_repair(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders(branch_sha=RELEASE)
    with pytest.raises(controller.DevReleaseBlocked, match="flag.*mismatch|prepare"):
        _activation(packet, providers).reconcile()
    assert not any(call[0] == "set_workbench_flags" for call in providers.calls)


def test_v2_execute_observes_configuration_separately_from_live_product_go(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders()
    providers.flags = {"api": True, "worker": True, "frontend": True}
    result = _activation(packet, providers).execute(packet["release_id"])
    assert result["status"] == "RELEASE_OK"
    assert result["configuration"]["observed_flags"] == providers.flags
    assert result["configuration"]["requested_workbench_enabled"] is True
    assert result["product_go"] == "NOT_VERIFIED_UNTIL_EXACT_DEPLOY_AND_LIVE_TEST"


def test_v2_reconcile_observes_terminal_flags_after_read_only_health(tmp_path: Path) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders(branch_sha=RELEASE)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    result = _activation(packet, providers).reconcile()
    assert result["status"] == "RECONCILED"
    assert result["configuration"]["observed_flags"] == providers.flags
    assert result["product_go"] == "NOT_VERIFIED_UNTIL_EXACT_DEPLOY_AND_LIVE_TEST"


@pytest.mark.parametrize("mode", ["execute", "reconcile"])
def test_terminal_flag_drift_is_not_reported_as_release_success(tmp_path: Path, mode: str) -> None:
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders(branch_sha=RELEASE if mode == "reconcile" else PREVIOUS)
    providers.flags = {"api": True, "worker": True, "frontend": True}
    original_health = providers.read_health

    def health_then_drift(url):
        result = original_health(url)
        if url == packet["vercel"]["public_url"]:
            providers.flags["frontend"] = False
        return result

    providers.read_health = health_then_drift
    release = _activation(packet, providers)
    with pytest.raises(controller.DevReleaseBlocked, match="flag_mismatch"):
        release.execute(packet["release_id"]) if mode == "execute" else release.reconcile()
    assert not any(call[0] == "set_workbench_flags" for call in providers.calls)


@pytest.mark.parametrize("change", [
    {"current_revision": "0169"}, {"expected_revision": "0169"},
    {"target": "another_project"}, {"status": "NOT_VERIFIED"},
    {"project_ref_sha256": "b" * 64},
])
def test_foreign_or_unproven_receipt_stops_before_provider_reads(tmp_path, change):
    receipt = json.loads(_receipt())
    receipt.update(change)
    packet, _ = _write_packet(tmp_path, receipt=json.dumps(receipt).encode())
    providers = FakeProviders()
    with pytest.raises(controller.DevReleaseBlocked, match="0172_pass_required"):
        _activation(packet, providers).prepare(packet["release_id"])
    assert providers.calls == []


def _live_adapter_double():
    adapter = object.__new__(controller.LiveProviderAdapter)
    adapter.render_token = "synthetic-render-token"
    adapter.vercel_token = "synthetic-vercel-token"
    flags = {"api": "false", "worker": "false", "frontend": "false"}
    calls = []

    def http(url, token, *, method="GET", body=None):
        calls.append((url, method, body))
        if "api.render.com" in url:
            label = "api" if "/srv_api/" in url else "worker"
            if method == "PUT":
                flags[label] = body["value"]
            return {"key": controller.API_WORKBENCH_KEY, "value": flags[label]}
        if method == "POST":
            flags["frontend"] = body["value"]
        return {"envs": [
            {"key": controller.WEB_WORKBENCH_KEY, "value": flags["frontend"], "type": "plain", "target": ["production"]},
            {"key": "UNRELATED_SECRET", "value": "not-exposed", "type": "encrypted", "target": ["production"]},
        ]}

    adapter._http_json = http
    return adapter, flags, calls


def test_adapter_updates_only_named_keys_and_preserves_unrelated_targets():
    adapter, flags, calls = _live_adapter_double()
    assert adapter.set_workbench_flags(packet_data(), True) == ["api", "worker", "frontend"]
    writes = [call for call in calls if call[1] != "GET"]
    assert len(writes) == 3
    assert all(call[0].endswith("/env-vars/METHODOLOGIST_WORKBENCH_ENABLED") and call[2] == {"value": "true"} for call in writes[:2])
    assert writes[2][1:] == ("POST", {"key": controller.WEB_WORKBENCH_KEY, "value": "true", "type": "plain", "target": ["production"]})
    assert flags == {"api": "true", "worker": "true", "frontend": "true"}
    calls.clear()
    assert adapter.set_workbench_flags(packet_data(), True) == []
    assert all(call[1] == "GET" for call in calls)


def test_adapter_partial_readback_failure_stops_remaining_writes():
    adapter, flags, calls = _live_adapter_double()
    original = adapter._http_json

    def mismatch(url, token, **kwargs):
        result = original(url, token, **kwargs)
        if "/srv_api/" in url and kwargs.get("method", "GET") == "GET":
            return {"key": controller.API_WORKBENCH_KEY, "value": "false"}
        return result

    adapter._http_json = mismatch
    with pytest.raises(controller.DevReleaseBlocked, match="api_flag_readback_mismatch"):
        adapter.set_workbench_flags(packet_data(), True)
    writes = [call for call in calls if call[1] != "GET"]
    assert len(writes) == 1
    assert flags["worker"] == flags["frontend"] == "false"


@pytest.mark.parametrize("mode", ["execute", "reconcile"])
def test_wrong_provider_identity_prevents_flag_inventory(tmp_path, mode):
    packet, _ = _write_packet(tmp_path)
    providers = FakeProviders(branch_sha=RELEASE if mode == "reconcile" else PREVIOUS)
    providers.vercel_project_data["project_name"] = "another-project"
    with pytest.raises(controller.DevReleaseBlocked, match="project_name_mismatch"):
        release = _activation(packet, providers)
        release.execute(packet["release_id"]) if mode == "execute" else release.reconcile()
    assert not any(call[0] in {"workbench_flags", "set_workbench_flags", "push_exact_sha", "trigger_render"} for call in providers.calls)
