from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import re
import sys
from dataclasses import asdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("release_plane.py")
SPEC = importlib.util.spec_from_file_location("release_plane", MODULE_PATH)
assert SPEC and SPEC.loader
release_plane = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_plane
SPEC.loader.exec_module(release_plane)

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
OLD_IMAGE = "ghcr.io/kamillalmscrm/kamilya-api@sha256:" + "a" * 64
NEW_IMAGE = "ghcr.io/kamillalmscrm/kamilya-api@sha256:" + "b" * 64


def test_production_slot_has_two_queue_replicas_and_only_one_beat() -> None:
    root = MODULE_PATH.parents[2]
    compose = (root / "infra" / "compose" / "kamilya-release-slot.yml").read_text(encoding="utf-8")

    def service_block(name: str) -> str:
        match = re.search(
            rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9-]+:\n|^networks:)",
            compose,
        )
        assert match is not None, f"missing release-slot service: {name}"
        return match.group(1)

    assert release_plane.SERVICES == (
        "api",
        "worker-ai",
        "worker-documents",
        "worker-ops",
        "worker-ai-replica",
        "worker-documents-replica",
    )
    assert release_plane.WORKERS == release_plane.SERVICES[1:]

    ai = service_block("worker-ai-replica")
    assert '"-Q", "ai"' in ai
    assert '"--concurrency=1"' in ai
    assert '"--hostname=ai-replica@%h"' in ai
    assert "cpus: 1.0" in ai and "mem_limit: 1g" in ai

    documents = service_block("worker-documents-replica")
    assert '"-Q", "documents"' in documents
    assert '"--concurrency=1"' in documents
    assert '"--hostname=documents-replica@%h"' in documents
    assert "cpus: 1.0" in documents and "mem_limit: 3g" in documents

    beat_services = [name for name in release_plane.SERVICES if "-B" in service_block(name)]
    assert beat_services == ["worker-ops"]


def epoch_manifest(version: str, *, migration: bool, flags: bool = True) -> dict:
    data = asdict(manifest())
    enabled = {'workbench': flags, 'document_draft': flags, 'lesson_correction': flags, 'staff_structure': flags}
    data.update(schema_version=3, product_version=version, feature_flags=enabled,
                previous_feature_flags=enabled.copy(), migration={'mode': 'exact' if migration else 'no-migration',
                'from_revision': '0183' if migration else None, 'to_revision': '0184' if migration else None,
                'rollback_compatible': migration})
    return data


def versioned_manifest(version: str, *, release_sha: str, image: str,
                       previous_release_sha: str, previous_image: str) -> release_plane.ReleaseManifest:
    data = epoch_manifest(version, migration=False)
    data.update(release_sha=release_sha, image=image,
                previous_release_sha=previous_release_sha, previous_image=previous_image)
    return release_plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize(
    "version", ["0.11.152", "0.11.153", "0.11.154", "0.11.155", "0.11.156", "0.11.157"]
)
def test_replica_topology_and_schema_epoch_are_bound_to_release(version):
    assert release_plane.services_for_product_version(None) == release_plane.LEGACY_SERVICES
    assert release_plane.services_for_product_version("0.11.151") == release_plane.LEGACY_SERVICES
    assert release_plane.services_for_product_version("0.11.152") == release_plane.SERVICES
    assert release_plane.services_for_product_version("0.11.153") == release_plane.SERVICES
    assert versioned_manifest(version, release_sha=NEW_SHA, image=NEW_IMAGE,
                              previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE).correction_revisions == (
        "0194", "0194"
    )
@pytest.mark.parametrize('flags', [True, False])
def test_version71_epoch_is_exact_even_with_features_disabled(flags):
    data = epoch_manifest('0.11.71', migration=True, flags=flags)
    assert release_plane.ReleaseManifest.parse(data).correction_revisions == ('0183', '0184')
    for source, target in [('0181', '0183'), ('0182', '0184'), ('0184', '0183'), ('0183', '0185')]:
        data['migration'].update(from_revision=source, to_revision=target)
        with pytest.raises(release_plane.ReleasePlaneError, match='v3_migration_revision_invalid'):
            release_plane.ReleaseManifest.parse(data)


def test_version70_retains_previous_staff_and_correction_epoch():
    data = epoch_manifest('0.11.70', migration=True)
    data['migration'].update(from_revision='0181', to_revision='0183')
    assert release_plane.ReleaseManifest.parse(data).correction_revisions == ('0181', '0183')


@pytest.mark.parametrize('flags', [True, False])
def test_source_editorial_epoch_admits_only_0184_to_0185(flags):
    data = epoch_manifest('0.11.74', migration=True, flags=flags)
    data['migration'].update(from_revision='0184', to_revision='0185')
    parsed = release_plane.ReleaseManifest.parse(data)
    assert parsed.correction_revisions == ('0184', '0185') and parsed.migration.rollback_compatible
    for source, target in [('0183', '0184'), ('0183', '0185'), ('0184', '0186'), ('0185', '0184')]:
        data['migration'].update(from_revision=source, to_revision=target)
        with pytest.raises(release_plane.ReleasePlaneError, match='v3_migration_revision_invalid'):
            release_plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize('revision, accepted', [('0184 (head)', False), ('0185 (head)', True)])
def test_source_editorial_no_migration_rechecks_exact_head(tmp_path, monkeypatch, revision, accepted):
    parsed = release_plane.ReleaseManifest.parse(epoch_manifest('0.11.74', migration=False, flags=False))
    cfg = config(tmp_path)
    Path(cfg.state_file).write_text(json.dumps({'schema_version': 1, 'active_slot': 'green',
        'release_sha': NEW_SHA, 'image': NEW_IMAGE}), encoding='utf-8')
    runner = FakeRunner(initial_revision=revision)
    controller = release_plane.ReleasePlane(parsed, cfg, runner, FakeHealth())
    monkeypatch.setattr(controller, '_verify_services', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, '_wait_health', lambda *args, **kwargs: None)
    if accepted:
        assert controller.execute(parsed.release_id)['status'] == 'ALREADY_DEPLOYED'
    else:
        with pytest.raises(release_plane.ReleasePlaneError, match='correction_schema_revision_mismatch'):
            controller.execute(parsed.release_id)
    assert not any('upgrade' in call or 'up' in call or 'stop' in call for call, _ in runner.calls)


@pytest.mark.parametrize('flags', [True, False])
def test_source_preparation_epoch_admits_only_0185_to_0186(flags):
    data = epoch_manifest('0.11.82', migration=False, flags=flags)
    assert release_plane.ReleaseManifest.parse(data).correction_revisions == ('0185', '0186')
    data['migration'].update(mode='exact', from_revision='0185', to_revision='0186', rollback_compatible=True)
    assert release_plane.ReleaseManifest.parse(data).migration.to_revision == '0186'
    for source, target in [('0184', '0185'), ('0184', '0186'), ('0185', '0187'), ('0186', '0185')]:
        data['migration'].update(from_revision=source, to_revision=target)
        with pytest.raises(release_plane.ReleasePlaneError, match='v3_migration_revision_invalid'):
            release_plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize('version', ['0.11.84', '0.11.85', '0.11.112', '0.11.113'])
@pytest.mark.parametrize('flags', [True, False])
def test_editorial_settings_epoch_admits_only_0186_to_0187(version, flags):
    data = epoch_manifest(version, migration=False, flags=flags)
    assert release_plane.ReleaseManifest.parse(data).correction_revisions == ('0186', '0187')
    data['migration'].update(mode='exact', from_revision='0186', to_revision='0187', rollback_compatible=True)
    assert release_plane.ReleaseManifest.parse(data).migration.to_revision == '0187'
    for source, target in [('0185', '0186'), ('0185', '0187'), ('0186', '0188'), ('0187', '0186')]:
        data['migration'].update(from_revision=source, to_revision=target)
        with pytest.raises(release_plane.ReleasePlaneError, match='v3_migration_revision_invalid'):
            release_plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize('revision, accepted', [('0186 (head)', False), ('0187 (head)', True), ('0188 (head)', False)])
def test_editorial_settings_no_migration_checks_current_head(tmp_path, monkeypatch, revision, accepted):
    parsed = release_plane.ReleaseManifest.parse(epoch_manifest('0.11.85', migration=False, flags=False))
    cfg = config(tmp_path)
    Path(cfg.state_file).write_text(json.dumps({'schema_version': 1, 'active_slot': 'green',
        'release_sha': NEW_SHA, 'image': NEW_IMAGE}), encoding='utf-8')
    runner = FakeRunner(initial_revision=revision)
    controller = release_plane.ReleasePlane(parsed, cfg, runner, FakeHealth())
    monkeypatch.setattr(controller, '_verify_services', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, '_wait_health', lambda *args, **kwargs: None)
    if accepted:
        assert controller.execute(parsed.release_id)['status'] == 'ALREADY_DEPLOYED'
    else:
        with pytest.raises(release_plane.ReleasePlaneError, match='correction_schema_revision_mismatch'):
            controller.execute(parsed.release_id)
    assert not any('upgrade' in call or 'up' in call or 'stop' in call for call, _ in runner.calls)


@pytest.mark.parametrize('flags', [True, False])
def test_knowledge_checks_epoch_requires_exact_0187_to_0188(flags):
    data = epoch_manifest('0.11.114', migration=False, flags=flags)
    assert release_plane.ReleaseManifest.parse(data).correction_revisions == ('0187', '0188')
    data['migration'].update(mode='exact', from_revision='0187', to_revision='0188', rollback_compatible=True)
    assert release_plane.ReleaseManifest.parse(data).migration.to_revision == '0188'
    for source, target in [('0186', '0187'), ('0186', '0188'), ('0187', '0189'), ('0188', '0187')]:
        data['migration'].update(from_revision=source, to_revision=target)
        with pytest.raises(release_plane.ReleasePlaneError, match='v3_migration_revision_invalid'):
            release_plane.ReleaseManifest.parse(data)


def test_current_product_epoch_matches_sole_alembic_head():
    root = MODULE_PATH.parents[2]
    gate_path = root / 'scripts' / 'ci' / 'release-contract-gate.py'
    spec = importlib.util.spec_from_file_location('release_contract_gate', gate_path)
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    gate.check_alembic_chain()
    revisions = {}
    for path in gate.MIGRATIONS_DIR.glob('*.py'):
        if path.name == '__init__.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        revisions[gate._assignment(tree, 'revision', path)] = gate._assignment(tree, 'down_revision', path)
    heads = set(revisions) - {parent for parent in revisions.values() if parent is not None}
    assert len(heads) == 1
    version = (root / 'VERSION').read_text(encoding='utf-8').strip()
    manifest = release_plane.ReleaseManifest.parse(epoch_manifest(version, migration=False, flags=False))
    assert manifest.correction_revisions[1] == heads.pop()


@pytest.mark.parametrize('flags', [True, False])
@pytest.mark.parametrize('already_deployed', [True, False])
@pytest.mark.parametrize('revision, accepted', [('0187 (head)', False), ('0188 (head)', True), ('0189 (head)', False)])
def test_knowledge_checks_no_migration_requires_0188(tmp_path, monkeypatch, flags, already_deployed, revision, accepted):
    parsed = release_plane.ReleaseManifest.parse(epoch_manifest('0.11.114', migration=False, flags=flags))
    cfg = config(tmp_path)
    if already_deployed:
        Path(cfg.state_file).write_text(json.dumps({'schema_version': 1, 'active_slot': 'green',
            'release_sha': NEW_SHA, 'image': NEW_IMAGE}), encoding='utf-8')
    runner = FakeRunner(initial_revision=revision, fail_token='' if already_deployed else 'down --remove-orphans')
    controller = release_plane.ReleasePlane(parsed, cfg, runner, FakeHealth())
    monkeypatch.setattr(controller, '_verify_services', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, '_wait_health', lambda *args, **kwargs: None)
    if accepted and already_deployed:
        assert controller.execute(parsed.release_id)['status'] == 'ALREADY_DEPLOYED'
    else:
        expected = 'synthetic_command_failure' if accepted else 'correction_schema_revision_mismatch'
        with pytest.raises(release_plane.ReleasePlaneError, match=expected):
            controller.execute(parsed.release_id)
    assert any('current' in call for call, _ in runner.calls)
    assert not any('upgrade' in call or 'up' in call or 'stop' in call for call, _ in runner.calls)


def test_version71_requires_versioned_four_flag_manifest():
    assert release_plane.feature_manifest_fields('', '', '0.11.70') == {'schema_version': 1}
    with pytest.raises(release_plane.ReleasePlaneError, match='v3_feature_flags_required'):
        release_plane.feature_manifest_fields('', '', '0.11.71')
    flags = {'workbench': True, 'document_draft': True, 'lesson_correction': True}
    with pytest.raises(release_plane.ReleasePlaneError, match='v3_feature_flags_required'):
        release_plane.feature_manifest_fields(json.dumps(flags), json.dumps(flags), '0.11.71')
    flags['staff_structure'] = True
    assert release_plane.feature_manifest_fields(json.dumps(flags), json.dumps(flags), '0.11.71')['schema_version'] == 3
    data = epoch_manifest('0.11.71', migration=False)
    data['schema_version'] = 2
    data['feature_flags'].pop('staff_structure')
    data['previous_feature_flags'].pop('staff_structure')
    with pytest.raises(release_plane.ReleasePlaneError, match='v3_requires_schema3'):
        release_plane.ReleaseManifest.parse(data)


@pytest.mark.parametrize('revision,accepted', [('0184 (head)', True), ('0183', False), ('0185', False)])
def test_version71_already_deployed_rechecks_head(tmp_path, monkeypatch, revision, accepted):
    parsed = release_plane.ReleaseManifest.parse(epoch_manifest('0.11.71', migration=False, flags=False))
    cfg = config(tmp_path)
    Path(cfg.state_file).write_text(json.dumps({'schema_version': 1, 'active_slot': 'green',
        'release_sha': NEW_SHA, 'image': NEW_IMAGE}), encoding='utf-8')
    runner = FakeRunner(initial_revision=revision)
    controller = release_plane.ReleasePlane(parsed, cfg, runner, FakeHealth())
    monkeypatch.setattr(controller, '_verify_services', lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, '_wait_health', lambda *args, **kwargs: None)
    if accepted:
        assert controller.execute(parsed.release_id)['status'] == 'ALREADY_DEPLOYED'
    else:
        with pytest.raises(release_plane.ReleasePlaneError, match='correction_schema_revision_mismatch'):
            controller.execute(parsed.release_id)
    assert any('current' in call for call, _ in runner.calls)
    assert not any('upgrade' in call or 'up' in call or 'stop' in call for call, _ in runner.calls)


@pytest.mark.parametrize('revision', ['0183', '0185', '01840'])
def test_version71_no_migration_rejects_wrong_head_even_when_flags_off(tmp_path, monkeypatch, revision):
    parsed = release_plane.ReleaseManifest.parse(epoch_manifest('0.11.71', migration=False, flags=False))
    runner = FakeRunner(initial_revision=revision)
    controller = release_plane.ReleasePlane(parsed, config(tmp_path), runner, FakeHealth())
    monkeypatch.setattr(controller, '_verify_services', lambda *args, **kwargs: None)
    with pytest.raises(release_plane.ReleasePlaneError, match='correction_schema_revision_mismatch'):
        controller.execute(parsed.release_id)
    assert not any('up' in call or 'stop' in call for call, _ in runner.calls)


def test_version71_no_migration_accepts_exact_head_before_candidate_start(tmp_path, monkeypatch):
    parsed = release_plane.ReleaseManifest.parse(epoch_manifest('0.11.71', migration=False, flags=False))
    runner = FakeRunner(initial_revision='0184 (head)', fail_token='down --remove-orphans')
    controller = release_plane.ReleasePlane(parsed, config(tmp_path), runner, FakeHealth())
    monkeypatch.setattr(controller, '_verify_services', lambda *args, **kwargs: None)
    with pytest.raises(release_plane.ReleasePlaneError, match='synthetic_command_failure'):
        controller.execute(parsed.release_id)
    assert any('current' in call for call, _ in runner.calls)
    assert not any('upgrade' in call for call, _ in runner.calls)


def test_controller_source_remains_compatible_with_vm126_python_310() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "from datetime import UTC" not in source
    assert "datetime.now(UTC)" not in source
    assert "timezone.utc" in source


def manifest(*, migration: bool = False):
    return release_plane.ReleaseManifest.parse(
        {
            "schema_version": 1,
            "release_id": "REL-20260831-RELEASE-PLANE-001",
            "release_sha": NEW_SHA,
            "image": NEW_IMAGE,
            "previous_release_sha": OLD_SHA,
            "previous_image": OLD_IMAGE,
            "expected_environment": "kz-production",
            "migration": {
                "mode": "exact" if migration else "no-migration",
                "from_revision": "0139" if migration else None,
                "to_revision": "0140" if migration else None,
                "rollback_compatible": migration,
            },
        }
    )


def config(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_slot": "blue",
                "release_sha": OLD_SHA,
                "image": OLD_IMAGE,
            }
        ),
        encoding="utf-8",
    )
    proxy = tmp_path / "upstream.conf"
    proxy.write_text("old-proxy\n", encoding="utf-8")
    return release_plane.HostConfig.parse(
        {
            "schema_version": 1,
            "environment": "kz-production",
            "compose_file": str(tmp_path / "compose.yml"),
            "env_file": str(tmp_path / "runtime.env"),
            "state_file": str(state),
            "evidence_dir": str(tmp_path / "evidence"),
            "lock_file": str(tmp_path / "release.lock"),
            "proxy_upstream_file": str(proxy),
            "proxy_upstream_name": "kamilya_api_active",
            "public_health_url": "https://api.kml.kz/health",
            "slot_ports": {"blue": 18000, "green": 18001},
            "project_prefix": "kamilya",
            "backup_gate": str(tmp_path / "backup-gate"),
            "backup_freshness_seconds": 900,
            "docker_binary": str(tmp_path / "docker"),
            "nginx_binary": str(tmp_path / "nginx"),
            "health_timeout_seconds": 30,
        }
    )


class FakeRunner:
    def __init__(self, *, fail_token: str = "", initial_revision: str = "0139") -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.fail_token = fail_token
        self.initial_revision = initial_revision
        self.container_images: dict[str, str] = {}
        self.container_settings: dict[str, dict[str, str]] = {}
        self.container_services: dict[str, str] = {}
        self.worker_bindings: dict[str, set[str]] = {
            "celery@old-worker-ai": {"ai"},
            "celery@old-worker-documents": {"documents"},
            "celery@old-worker-ops": {"maintenance", "notifications"},
        }
        self.worker_task_counts: dict[str, dict[str, int]] = {
            node: {"active": 0, "reserved": 0, "scheduled": 0}
            for node in self.worker_bindings
        }
        self.running_worker_services = set(release_plane.LEGACY_SERVICES[1:])
        self.worker_control_events: list[tuple[str, str, str]] = []

    @staticmethod
    def _queue_config(name: str) -> dict[str, object]:
        return {"exchange_name": name, "exchange_type": "direct", "routing_key": name,
                "queue_arguments": None}

    def _worker_control(self, call: tuple[str, ...]) -> str:
        start = call.index("-c")
        operation = call[start + 2]
        args = list(call[start + 3:])
        if operation == "snapshot":
            names = args
            active_queues = {
                node: [
                    {"name": queue, "exchange": {"name": queue, "type": "direct"},
                     "routing_key": queue, "queue_arguments": None}
                    for queue in sorted(queues)
                ]
                for node, queues in self.worker_bindings.items()
            }
            payload = {
                "active_queues": active_queues,
                **{field: {node: counts[field] for node, counts in self.worker_task_counts.items()}
                   for field in ("active", "reserved", "scheduled")},
                "queue_config": {name: self._queue_config(name) for name in names},
            }
            return json.dumps(payload)
        queue, node = args
        self.worker_control_events.append((operation, queue, node))
        if operation == "cancel":
            self.worker_bindings[node].discard(queue)
            ack = f"no longer consuming from {queue}"
        elif operation == "add":
            self.worker_bindings[node].add(queue)
            ack = f"now consuming from {queue}"
        else:
            raise AssertionError(f"unexpected worker control operation: {operation}")
        return json.dumps({node: {"ok": ack}})

    def _set_worker_topology(self, image: str, services: set[str]) -> None:
        self.running_worker_services = set(services)
        bindings: dict[str, set[str]] = {}
        for service in services:
            queues = {
                "worker-ai": ("ai",), "worker-documents": ("documents",),
                "worker-ops": ("maintenance", "notifications"),
                "worker-ai-replica": ("ai",), "worker-documents-replica": ("documents",),
            }[service]
            if image == OLD_IMAGE:
                node = f"celery@old-{service}"
            else:
                prefix = {
                    "worker-ai": "ai", "worker-documents": "documents", "worker-ops": "ops",
                    "worker-ai-replica": "ai-replica", "worker-documents-replica": "documents-replica",
                }[service]
                node = f"{prefix}@host-{service}"
            bindings[node] = set(queues)
        self.worker_bindings = bindings
        self.worker_task_counts = {
            node: {"active": 0, "reserved": 0, "scheduled": 0} for node in bindings
        }

    def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
        call = tuple(args)
        self.calls.append((call, dict(env or {})))
        if self.fail_token and self.fail_token in " ".join(call):
            self.fail_token = ""
            raise release_plane.ReleasePlaneError("synthetic_command_failure")
        if "compose" in call and "stop" in call:
            stopped = self.running_worker_services & set(call)
            self._set_worker_topology(str((env or {}).get("KAMILYA_API_IMAGE", NEW_IMAGE)),
                                      self.running_worker_services - stopped)
            return ""
        if "compose" in call and "up" in call and "--no-deps" in call:
            index = call.index("--no-deps") + 1
            started = set(call[index:]) & set(release_plane.WORKERS)
            if started:
                self._set_worker_topology(str((env or {}).get("KAMILYA_API_IMAGE", NEW_IMAGE)), started)
            return ""
        if len(call) > 2 and call[1] == "compose" and "exec" in call and release_plane.WORKER_CONTROL_CODE in call:
            return self._worker_control(call)
        if " current" in " " + " ".join(call):
            return (
                "0140"
                if any(" upgrade 0140" in " " + " ".join(c[0]) for c in self.calls)
                else self.initial_revision
            )
        if " ps -q " in " ".join(call):
            service = call[-1]
            if service in release_plane.WORKERS and service not in self.running_worker_services:
                return ""
            image = str((env or {}).get("KAMILYA_API_IMAGE", NEW_IMAGE))
            if image == OLD_IMAGE and service in {"worker-ai-replica", "worker-documents-replica"}:
                return ""
            container = f"{image.split('@')[-1][:6]}-{service}"
            self.container_images[container] = image
            self.container_settings[container] = dict(env or {})
            self.container_services[container] = service
            return container
        if " inspect " in " ".join(call):
            container = call[-1]
            if "{{.Config.Hostname}}|{{json .Config.Cmd}}" in call:
                service = self.container_services[container]
                command = ["celery", "-A", "app.core.celery_app:celery_app", "worker"]
                queues = {"worker-ai": "ai", "worker-documents": "documents",
                          "worker-ops": "maintenance,notifications",
                          "worker-ai-replica": "ai", "worker-documents-replica": "documents"}[service]
                command.extend(["-Q", queues])
                hostname_prefix = {"worker-ai": "ai", "worker-documents": "documents",
                                   "worker-ops": "ops", "worker-ai-replica": "ai-replica",
                                   "worker-documents-replica": "documents-replica"}[service]
                if self.container_images[container] != OLD_IMAGE:
                    command.append(f"--hostname={hostname_prefix}@%h")
                    hostname = f"host-{service}"
                else:
                    hostname = f"old-{service}"
                return f"{hostname}|{json.dumps(command)}"
            return f"{self.container_images.get(container, NEW_IMAGE)}|running|0"
        if " exec " in " ".join(call):
            container = call[2]
            names = (release_plane.STAFF_FEATURE_ENV if "staff_structure" in call[-1]
                     else release_plane.FEATURE_ENV)
            settings = self.container_settings.get(container, {})
            return json.dumps({key: {"supported": True,
                                     "enabled": settings.get(name, "false") == "true"}
                               for key, name in names.items()})
        return ""


class FakeHealth:
    def __init__(self, *, fail_public: bool = False, public_sha: str = NEW_SHA,
                 product_version: str | None = None) -> None:
        self.fail_public = fail_public
        self.public_sha = public_sha
        self.product_version = product_version

    def read(self, url: str):
        if self.fail_public and url.startswith("https://"):
            raise release_plane.ReleasePlaneError("synthetic_public_health_failure")
        sha = self.public_sha if url.startswith("https://") else (OLD_SHA if ":18000/" in url else NEW_SHA)
        return {"status": "ok", "release_sha": sha, "deployment_environment": "kz-production",
                "product_version": self.product_version}


def test_active_worker_topology_fails_closed_on_partial_replica_pair(tmp_path: Path) -> None:
    class PartialReplicaRunner(FakeRunner):
        def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
            call = tuple(args)
            if call[-2:] == ("-q", "worker-ai-replica") and (env or {}).get("KAMILYA_API_IMAGE") == OLD_IMAGE:
                return "partial-replica-container"
            return super().run(args, env=env)

    runner = PartialReplicaRunner()
    plane = release_plane.ReleasePlane(manifest(), config(tmp_path), runner, FakeHealth())

    with pytest.raises(release_plane.ReleasePlaneError, match="active_worker_topology_invalid"):
        plane._active_worker_services("blue", OLD_IMAGE, OLD_SHA)


def test_manifest_rejects_mutable_image_and_unsafe_migration() -> None:
    data = {
        "schema_version": 1,
        "release_id": "REL-20260831-RELEASE-PLANE-001",
        "release_sha": NEW_SHA,
        "image": "ghcr.io/kamillalmscrm/kamilya-api:latest",
        "previous_release_sha": OLD_SHA,
        "previous_image": OLD_IMAGE,
        "expected_environment": "kz-production",
        "migration": {
            "mode": "exact",
            "from_revision": "0139",
            "to_revision": "0140",
            "rollback_compatible": True,
        },
    }
    with pytest.raises(release_plane.ReleasePlaneError, match="immutable"):
        release_plane.ReleaseManifest.parse(data)
    data["image"] = NEW_IMAGE
    data["migration"]["rollback_compatible"] = False
    with pytest.raises(release_plane.ReleasePlaneError, match="rollback_compatibility"):
        release_plane.ReleaseManifest.parse(data)


def test_plan_is_read_only(tmp_path: Path) -> None:
    runner = FakeRunner()
    plane = release_plane.ReleasePlane(manifest(), config(tmp_path), runner, FakeHealth())
    result = plane.plan()
    assert result["status"] == "READY"
    assert result["candidate_slot"] == "green"
    assert result["mutation_attempted"] is False
    assert runner.calls == []


def test_successful_release_switches_slot_and_writes_append_only_evidence(tmp_path: Path) -> None:
    runner = FakeRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    result = plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert result["status"] == "DEPLOYED"
    state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    assert state == {
        "active_slot": "green",
        "image": NEW_IMAGE,
        "release_sha": NEW_SHA,
        "schema_version": 1,
    }
    assert "127.0.0.1:18001" in cfg.proxy_upstream_file.read_text(encoding="utf-8")
    records = (cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["status"] == "DEPLOYED"
    commands = [" ".join(call) for call, _ in runner.calls]
    assert any(" pull " in f" {command} " and NEW_IMAGE in command for command in commands)
    assert not any("backup-gate" in command for command in commands)
    stop_at = next(i for i, command in enumerate(commands)
                   if "stop --timeout 120 worker-ai worker-documents worker-ops" in command)
    candidate_workers_at = next(i for i, command in enumerate(commands) if "up -d --no-deps worker-ai worker-documents worker-ops" in command)
    assert stop_at < candidate_workers_at
    assert "worker-ai-replica" not in commands[stop_at]
    assert "worker-ai-replica" not in commands[candidate_workers_at]


def test_exact_migration_runs_backup_before_alembic_upgrade(tmp_path: Path) -> None:
    runner = FakeRunner()
    plane = release_plane.ReleasePlane(manifest(migration=True), config(tmp_path), runner, FakeHealth())
    plane.execute("REL-20260831-RELEASE-PLANE-001")
    commands = [" ".join(call) for call, _ in runner.calls]
    backup_at = next(i for i, command in enumerate(commands) if "backup-gate" in command)
    upgrade_at = next(i for i, command in enumerate(commands) if "alembic api upgrade 0140" in command)
    assert backup_at < upgrade_at
    assert "--expected-revision 0139" in commands[backup_at]
    assert "--freshness-seconds 900" in commands[backup_at]


def test_migration_retry_requires_matching_pre_migration_backup_receipt(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    runner = FakeRunner(initial_revision="0140")
    plane = release_plane.ReleasePlane(manifest(migration=True), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="matching_backup_receipt"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    receipt = cfg.evidence_dir / "migration-receipts" / "REL-20260831-RELEASE-PLANE-001.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(plane._migration_receipt()), encoding="utf-8")
    result = plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert result["status"] == "DEPLOYED"
    commands = [" ".join(call) for call, _ in runner.calls]
    assert not any("backup-gate" in command for command in commands)
    assert not any("upgrade 0140" in command for command in commands)


def test_candidate_failure_before_worker_stop_keeps_current_runtime(tmp_path: Path) -> None:
    runner = FakeRunner(fail_token="up -d --no-deps api")
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="synthetic_command_failure"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    assert state["release_sha"] == OLD_SHA
    assert cfg.proxy_upstream_file.read_text(encoding="utf-8") == "old-proxy\n"
    commands = [" ".join(call) for call, _ in runner.calls]
    assert not any("kamilya-blue" in command and " stop " in f" {command} " for command in commands)
    assert any("kamilya-green" in command and "down --remove-orphans" in command for command in commands)


def test_public_health_failure_restores_proxy_and_old_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = itertools.count()
    monkeypatch.setattr(release_plane.time, "monotonic", lambda: next(ticks) * 31.0)
    monkeypatch.setattr(release_plane.time, "sleep", lambda _seconds: None)
    runner = FakeRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth(fail_public=True))
    with pytest.raises(release_plane.ReleasePlaneError, match="health_identity_timeout"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert cfg.proxy_upstream_file.read_text(encoding="utf-8") == "old-proxy\n"
    assert json.loads(cfg.state_file.read_text(encoding="utf-8"))["release_sha"] == OLD_SHA
    commands = [" ".join(call) for call, _ in runner.calls]
    restore_at = next(i for i, command in enumerate(commands) if "kamilya-blue" in command and "up -d --no-deps worker-ai worker-documents worker-ops" in command)
    candidate_stop_at = next(i for i, command in enumerate(commands) if "kamilya-green" in command and "stop --timeout 120 worker-ai worker-documents worker-ops" in command)
    candidate_down_at = max(i for i, command in enumerate(commands) if "kamilya-green" in command and "down --remove-orphans" in command)
    assert candidate_stop_at < candidate_down_at < restore_at
    assert "worker-ai-replica" not in commands[restore_at]
    control = [(call[call.index(release_plane.WORKER_CONTROL_CODE) + 1], index)
               for index, (call, _env) in enumerate(runner.calls)
               if release_plane.WORKER_CONTROL_CODE in call]
    candidate_pause = next(index for operation, index in control
                           if operation == "cancel" and "-p kamilya-green" in commands[index])
    assert candidate_pause < candidate_stop_at
    assert any("kamilya-green" in command and "down --remove-orphans" in command for command in commands)
    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["status"] == "ROLLED_BACK"
    assert failure["rollback"] == "completed"


def test_rollback_fails_closed_when_candidate_task_cannot_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = itertools.count()
    monkeypatch.setattr(release_plane.time, "monotonic", lambda: next(ticks) * 31.0)
    monkeypatch.setattr(release_plane.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(release_plane, "WORKER_DRAIN_TIMEOUT_SECONDS", 0)

    class ActiveCandidateRunner(FakeRunner):
        def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
            result = super().run(args, env=env)
            if "compose" in args and "up" in args and "--no-deps" in args:
                for node in self.worker_task_counts:
                    if node.startswith("ai@"):
                        self.worker_task_counts[node]["active"] = 1
            return result

    runner = ActiveCandidateRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth(fail_public=True))

    with pytest.raises(release_plane.ReleasePlaneError, match="health_identity_timeout"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")

    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["status"] == "FAILED"
    assert failure["rollback"] == "blocked_worker_drain"
    assert failure["recovery_required"] is True
    assert cfg.lock_file.is_file()
    assert "release_rollback_incomplete" in cfg.lock_file.read_text(encoding="utf-8")
    assert runner.worker_task_counts["ai@host-worker-ai"]["active"] == 1
    assert {tuple(sorted(queues)) for queues in runner.worker_bindings.values()} == {
        ("ai",), ("documents",), ("maintenance", "notifications"),
    }
    commands = [" ".join(call) for call, _ in runner.calls]
    assert not any("kamilya-green" in command and "stop --timeout 120 worker-ai" in command
                   for command in commands)
    assert not any("kamilya-blue" in command and "up -d --no-deps worker-ai" in command
                   for command in commands)


def test_rollback_retains_lock_when_candidate_worker_enumeration_is_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = itertools.count()
    monkeypatch.setattr(release_plane.time, "monotonic", lambda: next(ticks) * 31.0)
    monkeypatch.setattr(release_plane.time, "sleep", lambda _seconds: None)

    class CandidateEnumerationFailureRunner(FakeRunner):
        fail_candidate_enumeration = False

        def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
            call = tuple(args)
            if (
                self.fail_candidate_enumeration and "ps" in call and "-q" in call
                and "kamilya-green" in call
                and (env or {}).get("KAMILYA_API_IMAGE") == NEW_IMAGE
            ):
                raise RuntimeError("do-not-write-this-runtime-output-to-evidence")
            return super().run(args, env=env)

    runner = CandidateEnumerationFailureRunner(initial_revision="0194")
    cfg = config(tmp_path)

    class TriggerEnumerationFailureHealth(FakeHealth):
        def read(self, url: str):
            if url.startswith("https://"):
                runner.fail_candidate_enumeration = True
            return super().read(url)

    release = versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                                 previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE)
    with pytest.raises(release_plane.ReleasePlaneError, match="health_identity_timeout"):
        release_plane.ReleasePlane(
            release, cfg, runner, TriggerEnumerationFailureHealth(
                fail_public=True, product_version="0.11.152"
            )
        ).execute(release.release_id)

    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["rollback"] == "failed"
    assert failure["recovery_required"] is True
    assert failure["rollback_error"] == "rollback_failed:RuntimeError"
    assert "do-not-write-this-runtime-output-to-evidence" not in json.dumps(failure)
    assert cfg.lock_file.is_file()
    assert "release_rollback_incomplete" in cfg.lock_file.read_text(encoding="utf-8")
    assert runner.running_worker_services == set(release_plane.WORKERS)


def test_rollback_retains_lock_when_previous_consumers_cannot_be_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = itertools.count()
    monkeypatch.setattr(release_plane.time, "monotonic", lambda: next(ticks) * 31.0)
    monkeypatch.setattr(release_plane.time, "sleep", lambda _seconds: None)

    class PreviousConsumerRestoreFailureRunner(FakeRunner):
        def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
            call = tuple(args)
            if (
                "compose" in call and "up" in call and "--no-deps" in call
                and (env or {}).get("KAMILYA_API_IMAGE") == OLD_IMAGE
            ):
                result = super().run(args, env=env)
                self.worker_bindings = {node: set() for node in self.worker_bindings}
                return result
            if (len(call) > 2 and call[1] == "compose" and "exec" in call
                and release_plane.WORKER_CONTROL_CODE in call
                and call[call.index(release_plane.WORKER_CONTROL_CODE) + 1] == "add"
                and (env or {}).get("KAMILYA_API_IMAGE") == OLD_IMAGE):
                return json.dumps({})
            return super().run(args, env=env)

    runner = PreviousConsumerRestoreFailureRunner(initial_revision="0194")
    cfg = config(tmp_path)
    release = versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                                 previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE)
    with pytest.raises(release_plane.ReleasePlaneError, match="health_identity_timeout"):
        release_plane.ReleasePlane(
            release, cfg, runner, FakeHealth(fail_public=True, product_version="0.11.152")
        ).execute(release.release_id)

    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["rollback"] == "failed"
    assert failure["recovery_required"] is True
    assert failure["rollback_error"] == "rollback_failed:ReleasePlaneError"
    assert cfg.lock_file.is_file()
    assert "release_rollback_incomplete" in cfg.lock_file.read_text(encoding="utf-8")
    assert runner.running_worker_services == set(release_plane.LEGACY_SERVICES[1:])
    assert all(not queues for queues in runner.worker_bindings.values())


def test_rollback_with_zero_candidate_workers_restores_previous_set_without_drain(tmp_path: Path) -> None:
    runner = FakeRunner(initial_revision="0194",
                        fail_token="up -d --no-deps worker-ai worker-documents worker-ops")
    cfg = config(tmp_path)
    release = versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                                 previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE)

    with pytest.raises(release_plane.ReleasePlaneError, match="synthetic_command_failure"):
        release_plane.ReleasePlane(release, cfg, runner, FakeHealth(product_version="0.11.152")).execute(
            release.release_id
        )

    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["status"] == "ROLLED_BACK" and failure["rollback"] == "completed", {
        key: failure.get(key) for key in ("status", "rollback", "recovery_required", "failure")
    }
    assert failure["recovery_required"] is False
    assert not cfg.lock_file.exists()
    commands = [" ".join(call) for call, _ in runner.calls]
    assert not any("kamilya-green" in command and "stop --timeout 120" in command for command in commands)
    assert any("kamilya-green" in command and "down --remove-orphans" in command for command in commands)
    assert any("kamilya-blue" in command and "up -d --no-deps worker-ai worker-documents worker-ops" in command
               for command in commands)


def test_rollback_with_partial_candidate_workers_drains_only_observed_set(tmp_path: Path) -> None:
    class PartialCandidateStartRunner(FakeRunner):
        def run(self, args: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
            call = tuple(args)
            if ("compose" in call and "up" in call and "--no-deps" in call
                and "kamilya-green" in call and "worker-ai" in call and "worker-documents" in call):
                index = call.index("--no-deps") + 1
                partial = (*call[:index], "worker-ai")
                super().run(partial, env=env)
                raise release_plane.ReleasePlaneError("synthetic_partial_worker_start")
            return super().run(args, env=env)

    runner = PartialCandidateStartRunner(initial_revision="0194")
    cfg = config(tmp_path)
    release = versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                                 previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE)

    with pytest.raises(release_plane.ReleasePlaneError, match="synthetic_partial_worker_start"):
        release_plane.ReleasePlane(release, cfg, runner, FakeHealth(product_version="0.11.152")).execute(
            release.release_id
        )

    failure = json.loads((cfg.evidence_dir / "release-ledger.jsonl").read_text(encoding="utf-8"))
    assert failure["status"] == "ROLLED_BACK" and failure["rollback"] == "completed", {
        key: failure.get(key) for key in ("status", "rollback", "recovery_required", "failure")
    }
    assert failure["recovery_required"] is False
    commands = [" ".join(call) for call, _ in runner.calls]
    candidate_stop = next(i for i, command in enumerate(commands)
                          if "kamilya-green" in command
                          and "stop --timeout 120 worker-ai" in command
                          and "worker-documents" not in command)
    candidate_down = max(i for i, command in enumerate(commands)
                         if "kamilya-green" in command and "down --remove-orphans" in command)
    previous_start = next(i for i, command in enumerate(commands)
                          if "kamilya-blue" in command
                          and "up -d --no-deps worker-ai worker-documents worker-ops" in command)
    pause = next(i for i, (call, _env) in enumerate(runner.calls)
                 if release_plane.WORKER_CONTROL_CODE in call
                 and call[call.index(release_plane.WORKER_CONTROL_CODE) + 1] == "cancel"
                 and call[-2] == "ai" and "kamilya-green" in call)
    assert pause < candidate_stop < candidate_down < previous_start


def test_first_replica_release_cuts_over_from_legacy_slot(tmp_path: Path) -> None:
    runner = FakeRunner(initial_revision="0194")
    cfg = config(tmp_path)
    release = versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                                 previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE)

    result = release_plane.ReleasePlane(release, cfg, runner, FakeHealth(product_version="0.11.152")).execute(release.release_id)

    assert result["status"] == "DEPLOYED"
    assert result["services"] == list(release_plane.SERVICES)
    commands = [" ".join(call) for call, _ in runner.calls]
    legacy_stop = next(i for i, command in enumerate(commands)
                       if "kamilya-blue" in command and "stop --timeout 120 worker-ai worker-documents worker-ops" in command)
    cancel_calls = [i for i, (call, _env) in enumerate(runner.calls)
                    if release_plane.WORKER_CONTROL_CODE in call
                    and call[call.index(release_plane.WORKER_CONTROL_CODE) + 1] == "cancel"]
    assert cancel_calls and max(cancel_calls) < legacy_stop
    assert {tuple(sorted(queues)) for queues in runner.worker_bindings.values()} == {
        ("ai",), ("documents",), ("maintenance", "notifications"),
    }
    assert len(runner.worker_bindings) == len(release_plane.SERVICES[1:])
    replicated_start = next(i for i, command in enumerate(commands)
                            if "kamilya-green" in command and "up -d --no-deps worker-ai worker-documents worker-ops worker-ai-replica worker-documents-replica" in command)
    assert legacy_stop < replicated_start
    assert "worker-ai-replica" not in commands[legacy_stop]


def test_protected_manifest_rollback_011152_to_011151_restores_legacy_workers(tmp_path: Path) -> None:
    runner = FakeRunner(initial_revision="0194")
    runner.worker_bindings = {
        "ai@host-worker-ai": {"ai"},
        "documents@host-worker-documents": {"documents"},
        "ops@host-worker-ops": {"maintenance", "notifications"},
        "ai-replica@host-worker-ai-replica": {"ai"},
        "documents-replica@host-worker-documents-replica": {"documents"},
    }
    runner.worker_task_counts = {node: {"active": 0, "reserved": 0, "scheduled": 0}
                                 for node in runner.worker_bindings}
    runner.running_worker_services = set(release_plane.SERVICES[1:])
    cfg = config(tmp_path)
    cfg.state_file.write_text(json.dumps({"schema_version": 1, "active_slot": "green",
                                          "release_sha": NEW_SHA, "image": NEW_IMAGE}), encoding="utf-8")
    cfg.proxy_upstream_file.write_text("new-proxy\n", encoding="utf-8")
    rollback = versioned_manifest("0.11.151", release_sha=OLD_SHA, image=OLD_IMAGE,
                                  previous_release_sha=NEW_SHA, previous_image=NEW_IMAGE)

    result = release_plane.ReleasePlane(rollback, cfg, runner,
                                        FakeHealth(public_sha=OLD_SHA, product_version="0.11.151")).execute(
        rollback.release_id
    )

    assert result["status"] == "DEPLOYED"
    assert result["services"] == list(release_plane.LEGACY_SERVICES)
    assert json.loads(cfg.state_file.read_text(encoding="utf-8"))["release_sha"] == OLD_SHA
    commands = [" ".join(call) for call, _ in runner.calls]
    new_workers_stop = next(i for i, command in enumerate(commands)
                            if "kamilya-green" in command and
                                "stop --timeout 120 worker-ai worker-documents worker-ops worker-ai-replica worker-documents-replica" in command)
    legacy_start = next(i for i, command in enumerate(commands)
                        if "kamilya-blue" in command and "up -d --no-deps worker-ai worker-documents worker-ops" in command)
    assert new_workers_stop < legacy_start
    assert "worker-ai-replica" not in commands[legacy_start]


def test_worker_drain_timeout_restores_every_original_queue_before_aborting(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    runner.worker_task_counts["celery@old-worker-ai"]["active"] = 1
    original = {node: tuple(sorted(queues)) for node, queues in runner.worker_bindings.items()}
    monkeypatch.setattr(release_plane, "WORKER_DRAIN_TIMEOUT_SECONDS", 0)
    controller = release_plane.ReleasePlane(
        versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                           previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE),
        config(tmp_path), runner, FakeHealth(product_version="0.11.152"),
    )
    env = controller._slot_env("blue", OLD_IMAGE, OLD_SHA)

    with pytest.raises(release_plane.ReleasePlaneError, match="worker_drain_timeout"):
        controller._pause_and_drain_workers("blue", env, release_plane.LEGACY_SERVICES[1:])

    assert {node: tuple(sorted(queues)) for node, queues in runner.worker_bindings.items()} == original
    assert runner.worker_task_counts["celery@old-worker-ai"]["active"] == 1
    assert any(event[0] == "cancel" for event in runner.worker_control_events)
    assert any(event[0] == "add" for event in runner.worker_control_events)


def test_partial_worker_pause_ack_restores_exact_consumers_before_aborting(tmp_path: Path) -> None:
    class MissingAckRunner(FakeRunner):
        failed = False

        def _worker_control(self, call: tuple[str, ...]) -> str:
            start = call.index("-c")
            if call[start + 2] == "cancel" and call[start + 3] == "notifications" and not self.failed:
                self.failed = True
                return json.dumps({"unexpected-node": {"ok": "no longer consuming from notifications"}})
            return super()._worker_control(call)

    runner = MissingAckRunner()
    original = {node: tuple(sorted(queues)) for node, queues in runner.worker_bindings.items()}
    controller = release_plane.ReleasePlane(
        versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                           previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE),
        config(tmp_path), runner, FakeHealth(product_version="0.11.152"),
    )

    with pytest.raises(release_plane.ReleasePlaneError, match="worker_pause_ack_missing"):
        controller._pause_and_drain_workers(
            "blue", controller._slot_env("blue", OLD_IMAGE, OLD_SHA), release_plane.LEGACY_SERVICES[1:]
        )

    assert {node: tuple(sorted(queues)) for node, queues in runner.worker_bindings.items()} == original
    restored = {(node, queue) for operation, queue, node in runner.worker_control_events if operation == "add"}
    assert restored == {(node, queue) for node, queues in original.items() for queue in queues}


@pytest.mark.parametrize("failure", ["initial_snapshot", "add_ack"])
def test_worker_restore_attempts_every_pair_and_accepts_exact_final_readback(
    tmp_path: Path, failure: str,
) -> None:
    runner = FakeRunner()
    original = {node: tuple(sorted(queues)) for node, queues in runner.worker_bindings.items()}
    # Simulate a partially paused set that must be restored.
    runner.worker_bindings["celery@old-worker-ai"].clear()
    controller = release_plane.ReleasePlane(
        versioned_manifest("0.11.152", release_sha=NEW_SHA, image=NEW_IMAGE,
                           previous_release_sha=OLD_SHA, previous_image=OLD_IMAGE),
        config(tmp_path), runner, FakeHealth(product_version="0.11.152"),
    )
    real_snapshot = controller._worker_snapshot
    snapshot_failed = False

    def snapshot_with_one_failure(slot, env, workers, **kwargs):
        nonlocal snapshot_failed
        if failure == "initial_snapshot" and not snapshot_failed:
            snapshot_failed = True
            raise release_plane.ReleasePlaneError("temporary_snapshot_failure")
        return real_snapshot(slot, env, workers, **kwargs)

    controller._worker_snapshot = snapshot_with_one_failure
    if failure == "add_ack":
        real_control = controller._worker_control
        ack_failed = False

        def control_with_lost_add_ack(slot, env, operation, *arguments, **kwargs):
            nonlocal ack_failed
            reply = real_control(slot, env, operation, *arguments, **kwargs)
            if operation == "add" and not ack_failed:
                ack_failed = True
                return {}
            return reply

        controller._worker_control = control_with_lost_add_ack

    controller._restore_worker_consumers(
        "blue", controller._slot_env("blue", OLD_IMAGE, OLD_SHA),
        release_plane.LEGACY_SERVICES[1:], original,
    )

    restored = {(node, queue) for operation, queue, node in runner.worker_control_events if operation == "add"}
    assert restored == {(node, queue) for node, queues in original.items() for queue in queues}
    assert {node: tuple(sorted(queues)) for node, queues in runner.worker_bindings.items()} == original


def test_previous_identity_and_confirmation_are_fail_closed(tmp_path: Path) -> None:
    runner = FakeRunner()
    cfg = config(tmp_path)
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="confirmation"):
        plane.execute("WRONG")
    state = json.loads(cfg.state_file.read_text(encoding="utf-8"))
    state["release_sha"] = "3" * 40
    cfg.state_file.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(release_plane.ReleasePlaneError, match="expected_previous"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert runner.calls == []


@pytest.mark.parametrize("contents", ["", "active-release"])
def test_existing_lock_blocks_before_runtime_mutation_and_is_preserved(
    tmp_path: Path, contents: str
) -> None:
    runner = FakeRunner()
    cfg = config(tmp_path)
    cfg.lock_file.write_text(contents, encoding="utf-8")
    old_state = cfg.state_file.read_bytes()
    plane = release_plane.ReleasePlane(manifest(), cfg, runner, FakeHealth())
    with pytest.raises(release_plane.ReleasePlaneError, match="release_lock_already_held"):
        plane.execute("REL-20260831-RELEASE-PLANE-001")
    assert runner.calls == []
    assert cfg.state_file.read_bytes() == old_state
    assert cfg.proxy_upstream_file.read_text(encoding="utf-8") == "old-proxy\n"
    assert cfg.lock_file.read_text(encoding="utf-8") == contents
