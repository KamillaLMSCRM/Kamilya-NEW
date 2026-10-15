"""Independent behavioral oracles for the protected correction flag seam."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from textwrap import dedent

import pytest

from scripts.deploy import test_release_plane as legacy

plane = legacy.release_plane
PREVIOUS = {"workbench": True, "document_draft": True, "lesson_correction": False}
CANDIDATE = {**PREVIOUS, "lesson_correction": True}
KEYS = {
    "workbench": "METHODOLOGIST_WORKBENCH_ENABLED",
    "document_draft": "METHODOLOGIST_DOCUMENT_DRAFT_ENABLED",
    "lesson_correction": "METHODOLOGIST_LESSON_CORRECTION_ENABLED",
}


def payload(*, migration=True):
    data = asdict(legacy.manifest())
    data.update(schema_version=2, product_version="0.11.39", feature_flags=CANDIDATE.copy(),
                previous_feature_flags=PREVIOUS.copy())
    data["migration"] = {"mode": "exact" if migration else "no-migration",
        "from_revision": "0175" if migration else None,
        "to_revision": "0178" if migration else None, "rollback_compatible": migration}
    return data


class FeatureRunner(legacy.FakeRunner):
    def __init__(self, *, drift="", previous_drift=False, revision="0175", fail_token=""):
        super().__init__(initial_revision=revision, fail_token=fail_token)
        self.drift = drift
        self.previous_drift = previous_drift

    def run(self, args, *, env=None):
        call = tuple(args)
        if "ps" in call:
            super().run(args, env=env)
            slot = "blue" if "kamilya-blue" in call else "green"
            return slot + ":" + call[-1]
        if "inspect" in call:
            self.calls.append((call, dict(env or {})))
            slot, service = call[-1].split(":")
            if "Config.Image" in call[-2]:
                image = legacy.OLD_IMAGE if slot == "blue" else legacy.NEW_IMAGE
                return f"{image}|running|0"
        if "exec" in call:
            self.calls.append((call, dict(env or {})))
            slot, service = call[2].split(":")
            flags = PREVIOUS.copy() if slot == "blue" else CANDIDATE.copy()
            if (slot == "blue" and self.previous_drift) or (slot == "green" and service == self.drift):
                flags["lesson_correction"] = not flags["lesson_correction"]
            return json.dumps({key: {"supported": key != "lesson_correction" or slot != "blue", "enabled": value} for key, value in flags.items()})
        if "current" in call:
            self.calls.append((call, dict(env or {})))
            return "0178 (head)" if any("upgrade" in c and "0178" in c for c, _ in self.calls) else self.initial_revision
        return super().run(args, env=env)


class FeatureHealth(legacy.FakeHealth):
    def read(self, url):
        return {**super().read(url), "product_version": "0.11.39" if ":18000/" not in url else "0.11.38"}


@pytest.mark.parametrize("field", ["product_version", "feature_flags", "previous_feature_flags"])
def test_schema2_requires_explicit_fields(field):
    data = payload()
    del data[field]
    with pytest.raises(plane.ReleasePlaneError):
        plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize("object_name", ["feature_flags", "previous_feature_flags"])
@pytest.mark.parametrize("key", list(KEYS))
@pytest.mark.parametrize("value", [None, "true", 1])
def test_schema2_rejects_nonliteral_flags(object_name, key, value):
    data = payload()
    data[object_name][key] = value
    with pytest.raises(plane.ReleasePlaneError):
        plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize("drift", ["missing", "extra", "dependency", "version", "revision", "schema_bool"])
def test_schema2_rejects_shape_dependency_and_version_drift(drift):
    data = payload()
    if drift == "missing":
        del data["feature_flags"]["lesson_correction"]
    elif drift == "extra":
        data["feature_flags"]["surprise"] = False
    elif drift == "dependency":
        data["feature_flags"]["workbench"] = False
    elif drift == "version":
        data["product_version"] = "0.11.38"
    elif drift == "revision":
        data["migration"]["to_revision"] = "0177"
    else:
        data["schema_version"] = True
    with pytest.raises(plane.ReleasePlaneError):
        plane.ReleaseManifest.parse(data)


def test_duplicate_json_keys_are_refused(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version":2,"schema_version":1}', encoding="utf-8")
    with pytest.raises(plane.ReleasePlaneError, match="duplicate"):
        plane._read_json(path)


def test_candidate_all_four_flags_and_backup_order(tmp_path):
    runner = FeatureRunner()
    cfg = legacy.config(tmp_path)
    cfg.env_file.write_text("SYNTHETIC_SENTINEL=unchanged\n", encoding="utf-8")
    original = cfg.env_file.read_bytes()
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), cfg, runner, FeatureHealth())
    result = controller.execute(controller.manifest.release_id)
    assert result["status"] == "DEPLOYED" and result["feature_flags"] == CANDIDATE
    assert result["previous_feature_flags"] == PREVIOUS
    assert cfg.env_file.read_bytes() == original
    commands = [c for c, _ in runner.calls]
    backup = next(i for i, c in enumerate(commands) if "--expected-revision" in c)
    upgrade = next(i for i, c in enumerate(commands) if "upgrade" in c)
    assert backup < upgrade
    for slot, expected in (("blue", PREVIOUS), ("green", CANDIDATE)):
        for service in plane.SERVICES:
            assert any("exec" in c and c[2] == slot + ":" + service and "get_settings" in c[-1] for c in commands)
        for c, env in runner.calls:
            if "kamilya-" + slot in c:
                assert {key: env[KEYS[key]] for key in KEYS} == {key: str(value).lower() for key, value in expected.items()}


def test_previous_drift_refuses_before_pull_or_migration(tmp_path):
    runner = FeatureRunner(previous_drift=True)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), legacy.config(tmp_path), runner, FeatureHealth())
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller.execute(controller.manifest.release_id)
    assert not any("pull" in c or "upgrade" in c or "stop" in c for c, _ in runner.calls)


@pytest.mark.parametrize("service", list(plane.SERVICES))
def test_candidate_drift_rolls_back_flags_without_disabling_existing_features(tmp_path, service):
    runner = FeatureRunner(drift=service)
    cfg = legacy.config(tmp_path)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), cfg, runner, FeatureHealth())
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller.execute(controller.manifest.release_id)
    assert json.loads(cfg.state_file.read_text())["release_sha"] == legacy.OLD_SHA
    assert cfg.proxy_upstream_file.read_text() == "old-proxy\n"
    record = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text())
    assert record["status"] == "ROLLED_BACK" and record["previous_feature_flags"] == PREVIOUS
    for c, env in runner.calls:
        if "kamilya-blue" in c:
            assert env[KEYS["lesson_correction"]] == "false"
            assert env[KEYS["document_draft"]] == "true" and env[KEYS["workbench"]] == "true"
    if service == "api":
        assert not any("stop" in c for c, _ in runner.calls)


@pytest.mark.parametrize("revision", ["0175", "0177", "01780"])
def test_no_migration_correction_refuses_wrong_revision_before_candidate_start(tmp_path, revision):
    runner = FeatureRunner(revision=revision)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload(migration=False)), legacy.config(tmp_path), runner, FeatureHealth())
    with pytest.raises(plane.ReleasePlaneError, match="revision"):
        controller.execute(controller.manifest.release_id)
    assert not any("up" in c or "stop" in c for c, _ in runner.calls)


def test_target_revision_requires_same_backup_receipt_then_can_resume(tmp_path):
    runner = FeatureRunner(revision="0178")
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), legacy.config(tmp_path), runner, FeatureHealth())
    with pytest.raises(plane.ReleasePlaneError, match="matching_backup_receipt"):
        controller.execute(controller.manifest.release_id)
    controller._write_migration_receipt()
    assert controller.execute(controller.manifest.release_id)["status"] == "DEPLOYED"
    assert not any("upgrade" in c or "--expected-revision" in c for c, _ in runner.calls)


def test_already_deployed_replay_rechecks_flags(tmp_path):
    runner = FeatureRunner()
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(payload()), legacy.config(tmp_path), runner, FeatureHealth())
    controller.execute(controller.manifest.release_id)
    assert controller.execute(controller.manifest.release_id)["status"] == "ALREADY_DEPLOYED"
    runner.drift = "worker-documents"
    with pytest.raises(plane.ReleasePlaneError, match="flag"):
        controller.execute(controller.manifest.release_id)


def test_document_and_correction_independence():
    data = payload()
    data["feature_flags"]["document_draft"] = False
    assert plane.ReleaseManifest.parse(data).feature_flags["lesson_correction"] is True


def test_legacy_manifest_has_no_explicit_flag_claim(tmp_path):
    runner = legacy.FakeRunner()
    controller = plane.ReleasePlane(legacy.manifest(), legacy.config(tmp_path), runner, legacy.FakeHealth())
    result = controller.execute(controller.manifest.release_id)
    assert "feature_flags" not in result
    assert not any("get_settings" in " ".join(c) for c, _ in runner.calls)


@pytest.mark.parametrize("schema,version", [(1, "0.11.39"), (2, "0.11.39"), (2, "0.11.51")])
def test_real_workflow_manifest_producer_crosses_same_consumer(tmp_path, monkeypatch, schema, version):
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/release-kz-production.yml").read_text()
    block = workflow.split("      - name: Create strict release manifest\n", 1)[1]
    producer = dedent(block.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
    previous = CANDIDATE if version == "0.11.51" else PREVIOUS
    source, target = ("0178", "0179") if version == "0.11.51" else ("0175", "0178")
    env = {"RELEASE_ID": payload()["release_id"], "RELEASE_SHA": legacy.NEW_SHA,
           "IMAGE": legacy.NEW_IMAGE, "PREVIOUS_RELEASE_SHA": legacy.OLD_SHA,
           "PREVIOUS_IMAGE": legacy.OLD_IMAGE, "MIGRATION_MODE": "exact",
           "MIGRATION_FROM": source, "MIGRATION_TO": target, "ROLLBACK_COMPATIBLE": "true",
           "RELEASE_VERSION": version, "FEATURE_FLAGS": json.dumps(CANDIDATE) if schema == 2 else "",
           "PREVIOUS_FEATURE_FLAGS": json.dumps(previous) if schema == 2 else ""}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    exec(compile(producer, "actual_workflow_producer", "exec"), {})
    output = json.loads((tmp_path / "release-manifest.json").read_text())
    parsed = plane.ReleaseManifest.parse(output)
    assert parsed.schema_version == schema
    if schema == 2:
        assert parsed.feature_flags == CANDIDATE and parsed.previous_feature_flags == previous
    else:
        assert "feature_flags" not in output and parsed.feature_flags is None


@pytest.mark.parametrize("candidate,previous", [
    ('{"workbench":true,"workbench":false,"document_draft":true,"lesson_correction":false}', json.dumps(PREVIOUS)),
    (json.dumps(CANDIDATE), ""), ("", json.dumps(PREVIOUS)),
    ('{"workbench":"true","document_draft":true,"lesson_correction":false}', json.dumps(PREVIOUS)),
])
def test_workflow_flag_input_seam_rejects_ambiguous_configuration(candidate, previous):
    with pytest.raises(plane.ReleasePlaneError):
        plane.feature_manifest_fields(candidate, previous, "0.11.39")


def test_compose_shared_anchor_and_ci_own_explicit_flag_seam():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "infra/compose/kamilya-release-slot.yml").read_text()
    for key in KEYS.values():
        assert f"{key}: ${{{key}:-false}}" in compose
    assert compose.count("<<: *app-runtime") == 4
    assert "../../scripts/deploy/test_correction_backend_activation.py" in (root / ".github/workflows/ci.yml").read_text()


def test_selected_effective_settings_never_emit_raw_environment():
    assert "os.environ" not in plane.FEATURE_READBACK and "Config.Env" not in plane.FEATURE_READBACK
    assert "get_settings()" in plane.FEATURE_READBACK
    for key in KEYS.values():
        assert key in plane.FEATURE_READBACK


def test_real_health_producer_uses_product_version_not_invented_alias():
    import ast
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "apps/api/app/main.py").read_text(encoding="utf-8"))
    health = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_deployment_identity")
    dictionaries = [node for node in ast.walk(health) if isinstance(node, ast.Dict)]
    keys = {key.value for dictionary in dictionaries for key in dictionary.keys if isinstance(key, ast.Constant)}
    assert "product_version" in keys and "version" not in keys


def dialogue_payload(*, migration=True):
    data = payload(migration=migration)
    data.update(product_version="0.11.51", previous_feature_flags=CANDIDATE.copy())
    if migration:
        data["migration"].update(from_revision="0178", to_revision="0179")
    return data


@pytest.mark.parametrize("version,source,target,accepted", [
    ("0.11.39", "0175", "0178", True),
    ("0.11.50", "0175", "0178", True),
    ("0.11.50", "0178", "0179", False),
    ("0.11.51", "0178", "0179", True),
    ("0.11.51", "0175", "0178", False),
    ("0.11.51", "0178", "0180", False),
    ("0.11.51", "0179", "0178", False),
    ("0.11.52", "0178", "0179", True),
    ("0.11.52", "0179", "0180", False),
    ("0.11.53", "0179", "0180", True),
    ("0.11.53", "0178", "0179", False),
    ("0.11.53", "0178", "0180", False),
    ("0.11.53", "0180", "0179", False),
    ("0.11.53", "0180", "0181", False),
])
def test_correction_migration_is_version_bound(version, source, target, accepted):
    data = dialogue_payload()
    data["product_version"] = version
    data["migration"].update(from_revision=source, to_revision=target)
    if accepted:
        assert plane.ReleaseManifest.parse(data).migration.to_revision == target
    else:
        with pytest.raises(plane.ReleasePlaneError, match="correction_migration_revision_invalid"):
            plane.ReleaseManifest.parse(data)


class DialogueRunner(FeatureRunner):
    def run(self, args, *, env=None):
        call = tuple(args)
        if "current" in call:
            self.calls.append((call, dict(env or {})))
            return "0179 (head)" if any("upgrade" in c and "0179" in c for c, _ in self.calls) else self.initial_revision
        if "exec" in call:
            self.calls.append((call, dict(env or {})))
            return json.dumps({key: {"supported": True, "enabled": True} for key in KEYS})
        return super().run(args, env=env)


class DialogueHealth(FeatureHealth):
    def read(self, url):
        return {**super().read(url), "product_version": "0.11.49" if ":18000/" in url else "0.11.51"}


def test_dialogue_migration_preserves_flags_and_backup_before_upgrade(tmp_path):
    runner = DialogueRunner(revision="0178")
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(dialogue_payload()), legacy.config(tmp_path), runner, DialogueHealth())
    assert controller.execute(controller.manifest.release_id)["status"] == "DEPLOYED"
    commands = [c for c, _ in runner.calls]
    backup = next(i for i, c in enumerate(commands) if "--expected-revision" in c)
    upgrade = next(i for i, c in enumerate(commands) if "upgrade" in c)
    assert commands[backup][commands[backup].index("--expected-revision") + 1] == "0178"
    assert commands[upgrade][-1] == "0179" and backup < upgrade
    assert all(all(env[KEYS[k]] == "true" for k in KEYS) for c, env in runner.calls if "kamilya-blue" in c or "kamilya-green" in c)


@pytest.mark.parametrize("revision,accepted", [("0179", True), ("0178", False), ("0180", False), ("01790", False)])
def test_no_migration_dialogue_requires_exact_schema179(tmp_path, revision, accepted):
    runner = DialogueRunner(revision=revision)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(dialogue_payload(migration=False)), legacy.config(tmp_path), runner, DialogueHealth())
    if accepted:
        assert controller.execute(controller.manifest.release_id)["status"] == "DEPLOYED"
        assert not any("upgrade" in c or "--expected-revision" in c for c, _ in runner.calls)
    else:
        with pytest.raises(plane.ReleasePlaneError, match="correction_schema_revision_mismatch"):
            controller.execute(controller.manifest.release_id)
        assert not any("up" in c or "stop" in c for c, _ in runner.calls)


def test_dialogue_existing_target_requires_exact_backup_receipt(tmp_path):
    runner = DialogueRunner(revision="0179")
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(dialogue_payload()), legacy.config(tmp_path), runner, DialogueHealth())
    with pytest.raises(plane.ReleasePlaneError, match="matching_backup_receipt"):
        controller.execute(controller.manifest.release_id)
    assert not any("up" in c or "stop" in c for c, _ in runner.calls)
    controller._write_migration_receipt()
    assert controller.execute(controller.manifest.release_id)["status"] == "DEPLOYED"
    assert not any("upgrade" in c or "--expected-revision" in c for c, _ in runner.calls)


def test_dialogue_upgrade_failure_keeps_current_workers_and_flags(tmp_path):
    runner = DialogueRunner(revision="0178", fail_token="upgrade 0179")
    cfg = legacy.config(tmp_path)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(dialogue_payload()), cfg, runner, DialogueHealth())
    with pytest.raises(plane.ReleasePlaneError, match="synthetic_command_failure"):
        controller.execute(controller.manifest.release_id)
    assert not any("stop" in c for c, _ in runner.calls)
    assert json.loads(cfg.state_file.read_text())["release_sha"] == legacy.OLD_SHA
    assert cfg.proxy_upstream_file.read_text() == "old-proxy\n"
    record = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text())
    assert record["status"] == "FAILED"
    assert record["previous_feature_flags"] == CANDIDATE


def reserve_payload(*, migration=True):
    data = dialogue_payload(migration=migration)
    data["product_version"] = "0.11.53"
    if migration:
        data["migration"].update(from_revision="0179", to_revision="0180")
    return data


class ReserveRunner(DialogueRunner):
    def run(self, args, *, env=None):
        call = tuple(args)
        if "current" in call:
            self.calls.append((call, dict(env or {})))
            return "0180 (head)" if any("upgrade" in c and "0180" in c for c, _ in self.calls) else self.initial_revision
        return super().run(args, env=env)


class ReserveHealth(DialogueHealth):
    def read(self, url):
        return {**super().read(url), "product_version": "0.11.51" if ":18000/" in url else "0.11.53"}


def test_reserve_migration180_preserves_all_flags_and_backup_before_upgrade(tmp_path):
    runner = ReserveRunner(revision="0179")
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(reserve_payload()), legacy.config(tmp_path), runner, ReserveHealth())
    assert controller.execute(controller.manifest.release_id)["status"] == "DEPLOYED"
    commands = [c for c, _ in runner.calls]
    backup = next(i for i, c in enumerate(commands) if "--expected-revision" in c)
    upgrade = next(i for i, c in enumerate(commands) if "upgrade" in c)
    assert commands[backup][commands[backup].index("--expected-revision") + 1] == "0179"
    assert commands[upgrade][-1] == "0180" and backup < upgrade
    assert all(all(env[KEYS[k]] == "true" for k in KEYS) for c, env in runner.calls if "kamilya-blue" in c or "kamilya-green" in c)


@pytest.mark.parametrize("revision,accepted", [("0180", True), ("0179", False), ("0181", False), ("01800", False)])
def test_no_migration_reserve_requires_exact_schema180(tmp_path, revision, accepted):
    runner = ReserveRunner(revision=revision)
    controller = plane.ReleasePlane(plane.ReleaseManifest.parse(reserve_payload(migration=False)), legacy.config(tmp_path), runner, ReserveHealth())
    if accepted:
        assert controller.execute(controller.manifest.release_id)["status"] == "DEPLOYED"
        assert not any("upgrade" in c or "--expected-revision" in c for c, _ in runner.calls)
    else:
        with pytest.raises(plane.ReleasePlaneError, match="correction_schema_revision_mismatch"):
            controller.execute(controller.manifest.release_id)
        assert not any("up" in c or "stop" in c for c, _ in runner.calls)
