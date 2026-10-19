"""Production staff delivery: strict flags, schema, old-image and rollback seams."""
import json
from pathlib import Path
from textwrap import dedent

import pytest

from scripts.deploy import test_correction_backend_activation as correction

plane = correction.plane
legacy = correction.legacy
PREVIOUS = {**correction.CANDIDATE, "staff_structure": False}
CANDIDATE = {**PREVIOUS, "staff_structure": True}


def test_ci_runs_staff_delivery_contracts():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text()
    block = workflow.split("      - name: Render-like release-plane contract tests\n", 1)[1]
    run = block.split("        run:", 1)[1].split("\n\n", 1)[0]
    assert "../../scripts/deploy/test_staff_backend_activation.py" in run


def payload(*, migration=True):
    data = correction.payload(migration=migration)
    data.update(schema_version=3, product_version="0.11.63",
                feature_flags=CANDIDATE.copy(), previous_feature_flags=PREVIOUS.copy())
    if migration:
        data["migration"].update(from_revision="0181", to_revision="0183")
    return data


def test_staff_manifest_and_workflow_producer_use_same_closed_schema():
    fields = plane.feature_manifest_fields(json.dumps(CANDIDATE), json.dumps(PREVIOUS), "0.11.63")
    assert fields["schema_version"] == 3
    data = payload() | fields
    parsed = plane.ReleaseManifest.parse(data)
    assert parsed.feature_flags == CANDIDATE and parsed.previous_feature_flags == PREVIOUS
    assert parsed.correction_revisions == ("0181", "0183")


def test_actual_workflow_producer_roundtrips_schema3(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/release-kz-production.yml").read_text()
    block = workflow.split("      - name: Create strict release manifest\n", 1)[1]
    producer = dedent(block.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
    values = {
        "RELEASE_ID": payload()["release_id"], "RELEASE_SHA": legacy.NEW_SHA,
        "IMAGE": legacy.NEW_IMAGE, "PREVIOUS_RELEASE_SHA": legacy.OLD_SHA,
        "PREVIOUS_IMAGE": legacy.OLD_IMAGE, "MIGRATION_MODE": "exact",
        "MIGRATION_FROM": "0181", "MIGRATION_TO": "0183", "ROLLBACK_COMPATIBLE": "true",
        "RELEASE_VERSION": "0.11.63", "FEATURE_FLAGS": json.dumps(CANDIDATE),
        "PREVIOUS_FEATURE_FLAGS": json.dumps(PREVIOUS),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    exec(compile(producer, "actual_workflow_staff_producer", "exec"), {})
    parsed = plane.ReleaseManifest.parse(json.loads((tmp_path / "release-manifest.json").read_text()))
    assert parsed.schema_version == 3 and parsed.feature_flags == CANDIDATE
    assert parsed.previous_feature_flags == PREVIOUS


@pytest.mark.parametrize("object_name", ["feature_flags", "previous_feature_flags"])
@pytest.mark.parametrize("value", [None, "true", 1])
def test_staff_flag_is_explicit_literal_boolean(object_name, value):
    data = payload()
    data[object_name]["staff_structure"] = value
    with pytest.raises(plane.ReleasePlaneError):
        plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize("fault", ["missing", "extra", "old_schema", "old_version", "wrong_from", "wrong_to"])
def test_staff_manifest_rejects_protocol_and_epoch_drift(fault):
    data = payload()
    if fault == "missing":
        del data["previous_feature_flags"]["staff_structure"]
    elif fault == "extra":
        data["feature_flags"]["arbitrary"] = True
    elif fault == "old_schema":
        data["schema_version"] = 2
    elif fault == "old_version":
        data["product_version"] = "0.11.62"
    elif fault == "wrong_from":
        data["migration"]["from_revision"] = "0180"
    else:
        data["migration"]["to_revision"] = "0182"
    with pytest.raises(plane.ReleasePlaneError):
        plane.ReleaseManifest.parse(data)


class StaffRunner(correction.FeatureRunner):
    def __init__(self, *, revision="0181", drift="", previous_drift=False):
        super().__init__(revision=revision)
        self.staff_drift = drift
        self.staff_previous_drift = previous_drift

    def run(self, args, *, env=None):
        call = tuple(args)
        if "exec" in call:
            self.calls.append((call, dict(env or {})))
            slot, service = call[2].split(":")
            flags = PREVIOUS.copy() if slot == "blue" else CANDIDATE.copy()
            if (slot == "blue" and self.staff_previous_drift) or (slot == "green" and service == self.staff_drift):
                flags["staff_structure"] = not flags["staff_structure"]
            return json.dumps({key: {"supported": key != "staff_structure" or slot != "blue", "enabled": value}
                               for key, value in flags.items()})
        if "current" in call:
            self.calls.append((call, dict(env or {})))
            return "0183 (head)" if any("upgrade" in c and "0183" in c for c, _ in self.calls) else self.initial_revision
        return super().run(args, env=env)


class StaffHealth(legacy.FakeHealth):
    def read(self, url):
        return {**super().read(url), "product_version": "0.11.62" if ":18000/" in url else "0.11.63"}


def test_staff_all_services_flag_backup_before_upgrade_and_legacy_false_support(tmp_path):
    cfg = legacy.config(tmp_path)
    cfg.env_file.write_text("SYNTHETIC_SENTINEL=unchanged\n", encoding="utf8")
    original = cfg.env_file.read_bytes()
    runner = StaffRunner()
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), cfg, runner, StaffHealth())
    receipt = controller.execute(controller.manifest.release_id)
    assert receipt["status"] == "DEPLOYED" and receipt["feature_flags"] == CANDIDATE
    assert cfg.env_file.read_bytes() == original
    commands = [c for c, _ in runner.calls]
    assert next(i for i, c in enumerate(commands) if "--expected-revision" in c) < next(i for i, c in enumerate(commands) if "upgrade" in c)
    for service in plane.SERVICES:
        assert any("exec" in c and c[2] == "green:" + service and "STAFF_STRUCTURE_V3_ENABLED" in c[-1] for c in commands)
    for c, env in runner.calls:
        if "kamilya-green" in c:
            assert env["STAFF_STRUCTURE_V3_ENABLED"] == "true"
        elif "kamilya-blue" in c:
            assert env["STAFF_STRUCTURE_V3_ENABLED"] == "false"


@pytest.mark.parametrize("service", list(plane.SERVICES))
def test_staff_candidate_drift_rolls_back_and_preserves_old_flags(tmp_path, service):
    runner = StaffRunner(drift=service)
    cfg = legacy.config(tmp_path)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), cfg, runner, StaffHealth())
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller.execute(controller.manifest.release_id)
    assert json.loads(cfg.state_file.read_text())["release_sha"] == legacy.OLD_SHA
    assert cfg.proxy_upstream_file.read_text() == "old-proxy\n"
    for c, env in runner.calls:
        if "kamilya-blue" in c:
            assert env["STAFF_STRUCTURE_V3_ENABLED"] == "false"
            assert all(env[value] == "true" for value in correction.KEYS.values())


def test_staff_previous_drift_stops_before_pull(tmp_path):
    runner = StaffRunner(previous_drift=True)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), legacy.config(tmp_path), runner, StaffHealth())
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller.execute(controller.manifest.release_id)
    assert not any("pull" in c or "upgrade" in c or "stop" in c for c, _ in runner.calls)


def test_staff_no_migration_checks_0183_even_without_correction(tmp_path):
    data = payload(migration=False)
    data["feature_flags"] = {"workbench": False, "document_draft": False, "lesson_correction": False, "staff_structure": True}
    runner = StaffRunner(revision="0181")
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(data), legacy.config(tmp_path), runner, StaffHealth())
    with pytest.raises(plane.ReleasePlaneError, match="revision"):
        controller.execute(controller.manifest.release_id)
    assert not any("up" in c or "stop" in c for c, _ in runner.calls)
