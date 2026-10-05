"""Nonempty all-column learner history oracle, with no database/network."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def history(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/ops/workbench_correction_history_dev_checks.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("history_proof_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows():
    return {
        "enrollments": [{"status": "completed", "completed_at": "fixed", "content_release_id": "release"}],
        "quiz_attempts": [{"completed_at": "fixed", "passed": True, "answers": [{"answer": "steel"}], "evidence_snapshot": {"answer": "steel"}, "evidence_sha256": "a" * 64, "content_release_id": "release", "enrollment_id": "enrollment", "score_percent": 100, "total_points": 1, "earned_points": 1}],
        "certificates": [{"enrollment_id": "enrollment", "metadata": {"course_title": "Fixed"}, "pdf_sha256": "b" * 64, "revoked_at": None}],
        "content_releases": [{"id": "release", "snapshot": {"history": "release"}, "snapshot_sha256": "c" * 64}],
        "current_release_id": "release",
    }


@pytest.fixture
def application_gate(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/ops/workbench_correction_application_dev_gate.py"
    spec = importlib.util.spec_from_file_location("history_application_gate_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nonempty_all_column_history_snapshot_is_stable(history):
    value = rows()
    sealed = history.history_fingerprint(value)
    assert len(sealed) == 64
    assert history.history_fingerprint(deepcopy(value)) == sealed
    for key in ("enrollments", "quiz_attempts", "certificates", "content_releases"):
        empty = deepcopy(value)
        empty[key] = []
        with pytest.raises(history.GateBlocked):
            history.history_fingerprint(empty)
    for key, column, replacement in (
        ("quiz_attempts", "answers", [{"answer": "wood"}]),
        ("certificates", "metadata", {"course_title": "Changed"}),
        ("content_releases", "snapshot", {"history": "changed"}),
    ):
        changed = deepcopy(value)
        changed[key][0][column] = replacement
        assert history.history_fingerprint(changed) != sealed
    changed = deepcopy(value)
    changed["current_release_id"] = "different"
    with pytest.raises(history.GateBlocked):
        history.history_fingerprint(changed)


def test_history_fingerprint_rejects_missing_or_extra_top_level_keys(history):
    value = rows()
    missing = deepcopy(value)
    del missing["certificates"]
    with pytest.raises(history.GateBlocked, match="history_shape_invalid"):
        history.history_fingerprint(missing)
    extra = deepcopy(value)
    extra["unowned_table"] = []
    with pytest.raises(history.GateBlocked, match="history_shape_invalid"):
        history.history_fingerprint(extra)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["enrollments"][0].update(status="enrolled"),
        lambda value: value["enrollments"][0].update(completed_at=None),
        lambda value: value["quiz_attempts"][0].update(completed_at=None),
        lambda value: value["quiz_attempts"][0].update(passed=False),
        lambda value: value["quiz_attempts"][0].update(score_percent=99),
        lambda value: value["quiz_attempts"][0].update(total_points=2),
        lambda value: value["quiz_attempts"][0].update(earned_points=0),
        lambda value: value["quiz_attempts"][0].update(answers=[]),
        lambda value: value["quiz_attempts"][0].update(evidence_snapshot=None),
        lambda value: value["quiz_attempts"][0].update(evidence_sha256=None),
        lambda value: value["quiz_attempts"][0].update(enrollment_id=None),
        lambda value: value["certificates"][0].update(enrollment_id=None),
        lambda value: value["certificates"][0].update(metadata=None),
        lambda value: value["certificates"][0].update(pdf_sha256=None),
        lambda value: value["certificates"][0].update(revoked_at="fixed"),
        lambda value: value["content_releases"][0].update(snapshot={}),
        lambda value: value["content_releases"][0].update(snapshot_sha256=None),
        lambda value: value.update(current_release_id=None),
    ],
)
def test_history_fingerprint_rejects_incomplete_required_evidence(history, mutate):
    value = rows()
    mutate(value)
    with pytest.raises(history.GateBlocked, match="history_evidence_incomplete"):
        history.history_fingerprint(value)


@pytest.mark.parametrize("table", ["enrollments", "quiz_attempts", "certificates", "content_releases"])
def test_history_fingerprint_covers_arbitrary_populated_immutable_columns(history, table):
    value = rows()
    value[table][0]["immutable_metadata"] = {"marker": "before"}
    sealed = history.history_fingerprint(value)
    value[table][0]["immutable_metadata"] = {"marker": "after"}
    assert history.history_fingerprint(value) != sealed


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_scope", [None, 1, "true"])
async def test_opt_in_scope_invalid_type_refuses_before_engine_creation(application_gate, monkeypatch, bad_scope):
    monkeypatch.setattr(application_gate, "create_async_engine", lambda *_a, **_k: pytest.fail("engine created"))
    with pytest.raises(application_gate.GateBlocked, match="learner_history_scope_invalid"):
        await application_gate.run_gate("unused", "unused", "unused", "workbench_0123456789ab", learner_history=bad_scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [
    "learner_history_fixture",
    "learner_history_apply",
    "learner_history_replay",
    "learner_history_refusal",
])
async def test_opt_in_scope_requires_all_four_history_checks_before_engine_creation(application_gate, monkeypatch, missing):
    monkeypatch.setattr(application_gate, "create_async_engine", lambda *_a, **_k: pytest.fail("engine created"))
    required = set(application_gate.REQUIRED_CHECKS) | {
        "learner_history_fixture",
        "learner_history_apply",
        "learner_history_replay",
        "learner_history_refusal",
    }
    required.remove(missing)
    with pytest.raises(application_gate.GateBlocked, match="learner_history_scope_invalid"):
        await application_gate.run_gate("unused", "unused", "unused", "workbench_0123456789ab", learner_history=True, required_checks=required)
