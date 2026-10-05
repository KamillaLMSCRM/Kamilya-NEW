"""Public safety seam of the disposable application driver, database-free."""

import importlib.util
import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location(
        "correction_apply_gate_test",
        ROOT / "scripts/ops/workbench_correction_application_dev_gate.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_foreign_key_rebinding_is_exact_and_fail_closed(gate):
    assert (
        gate.rebind_fk(
            "FOREIGN KEY (course_id) REFERENCES public.courses(id) ON DELETE CASCADE",
            "courses",
            "workbench_0123456789ab",
        )
        == 'FOREIGN KEY (course_id) REFERENCES "workbench_0123456789ab".courses(id) ON DELETE CASCADE'
    )
    for definition in (
        "FOREIGN KEY (course_id) REFERENCES other.courses(id)",
        "FOREIGN KEY (course_id) REFERENCES public.users(id)",
        "FOREIGN KEY (course_id) REFERENCES public.courses(id); DROP TABLE public.users",
    ):
        with pytest.raises(gate.GateBlocked):
            gate.rebind_fk(definition, "courses", "workbench_0123456789ab")


def test_complete_unique_application_matrix_required(gate):
    complete = list(gate.REQUIRED_CHECKS)
    gate.validate_checks(complete)
    for checks in ([], complete[:-1], complete + [complete[0]]):
        with pytest.raises(gate.GateBlocked):
            gate.validate_checks(checks)


@pytest.mark.asyncio
async def test_concurrent_failure_drains_peer_before_cleanup(gate):
    import workbench_correction_application_dev_checks as checks

    finished = []

    async def failure():
        raise ValueError("private SQL parameters")

    async def peer():
        await asyncio.sleep(0)
        finished.append(True)
        return "committed"

    with pytest.raises(ValueError):
        await checks.drain_concurrent(failure(), peer())
    assert finished == [True]


@pytest.mark.asyncio
async def test_unlock_failure_never_masks_original_probe_and_drains_task(gate):
    import workbench_correction_application_dev_checks as checks

    finished = []
    original = gate.GateBlocked("original_probe_failure")

    async def unlock():
        raise ValueError("cleanup failure")

    async def peer():
        await asyncio.sleep(0)
        finished.append(True)
        return "receipt"

    with pytest.raises(gate.GateBlocked) as caught:
        await checks.release_and_drain(unlock(), asyncio.create_task(peer()), original)
    assert caught.value is original and finished == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("application_fails", [False, True])
async def test_cleanup_surfaces_application_error_before_unlock_error(
    gate, application_fails
):
    import workbench_correction_application_dev_checks as checks

    unlock_error, application_error = (
        ValueError("unlock failed"),
        RuntimeError("apply failed"),
    )

    async def unlock():
        raise unlock_error

    async def peer():
        if application_fails:
            raise application_error
        return "receipt"

    with pytest.raises((ValueError, RuntimeError)) as caught:
        await checks.release_and_drain(unlock(), asyncio.create_task(peer()))
    assert caught.value is (application_error if application_fails else unlock_error)


@pytest.mark.asyncio
async def test_concurrent_exact_busy_outcome_does_not_mask_other_failures(gate):
    import workbench_correction_application_dev_checks as checks

    class WorkbenchConflict(Exception):
        pass

    async def busy(code):
        raise WorkbenchConflict(code)

    async def completed():
        return "receipt"

    results = await checks.drain_concurrent(
        completed(), busy("correction_application_busy"), busy_type=WorkbenchConflict
    )
    assert results[0] == "receipt" and isinstance(results[1], WorkbenchConflict)
    with pytest.raises(WorkbenchConflict, match="wrong_seal"):
        await checks.drain_concurrent(
            completed(), busy("wrong_seal"), busy_type=WorkbenchConflict
        )


def test_failure_detail_is_safe_and_locates_application_owner(gate):
    namespace = {}
    path = (
        gate.ROOT
        / "apps/api/app/modules/methodologist_workbench/correction_application.py"
    )
    try:
        exec(
            compile("raise ValueError('secret SQL parameters')", str(path), "exec"),
            namespace,
        )
    except ValueError as exc:
        detail = gate.failure_detail(exc)
    assert detail == {
        "file": "apps/api/app/modules/methodologist_workbench/correction_application.py",
        "line": 1,
    }
    assert "secret" not in str(detail)


def test_wrapped_database_failure_keeps_only_safe_sqlstate(gate):
    from types import SimpleNamespace

    cause = RuntimeError("private SQL parameters")
    cause.orig = SimpleNamespace(sqlstate="55P03")
    outer = ValueError("private outer message")
    outer.__cause__ = cause
    assert gate.failure_detail(outer) == {"state": "55P03"}


def test_probe_error_context_keeps_only_safe_sqlstate(gate):
    from types import SimpleNamespace

    database_error = RuntimeError("private SQL parameters")
    database_error.orig = SimpleNamespace(sqlstate="23505")
    outer = ValueError("private probe message")
    outer.__context__ = database_error
    assert gate.failure_detail(outer) == {"state": "23505"}


@pytest.mark.asyncio
async def test_invalid_schema_never_opens_engine(gate, monkeypatch):
    monkeypatch.setattr(
        gate, "create_async_engine", lambda *_a, **_k: pytest.fail("engine created")
    )
    with pytest.raises(gate.GateBlocked, match="unsafe_schema_name"):
        await gate.run_gate("unused", "unused", "unused", "public")


@pytest.mark.asyncio
async def test_collision_never_drops_preexisting_schema(gate, monkeypatch):
    from test_workbench_correction_dev_gate import mock_engines

    owner, runtime = mock_engines(gate, monkeypatch, exists=True)
    monkeypatch.setattr(gate.event, "listen", lambda *_: None)
    monkeypatch.setattr(
        gate, "cleanup", lambda *_a: pytest.fail("preexisting schema dropped")
    )
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED" and result["failure"] == "schema_collision"
    assert not any("CREATE SCHEMA" in call for call in owner.connection.calls)
    assert owner.disposed and runtime.disposed


@pytest.mark.asyncio
async def test_partial_creation_failure_cleans_and_verifies_public(gate, monkeypatch):
    from test_workbench_correction_dev_gate import mock_engines

    owner, runtime = mock_engines(gate, monkeypatch)
    monkeypatch.setattr(gate.event, "listen", lambda *_: None)
    cleaned = []

    async def broken(*_):
        raise RuntimeError("private raw data")

    async def cleanup(*_):
        cleaned.append(True)
        return True

    monkeypatch.setattr(gate, "clone_application_tables", broken)
    monkeypatch.setattr(gate, "cleanup", cleanup)
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED" and result["failure"] == "RuntimeError"
    assert result["cleanup"] and result["public_schema_neutral"] and cleaned == [True]
    assert "private raw data" not in str(result)
    assert owner.disposed and runtime.disposed
