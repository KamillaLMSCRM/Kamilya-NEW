from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

SERVICE = Path(__file__).parents[1] / "app" / "modules" / "staff_import_sessions" / "commit_service.py"


def test_commit_rechecks_approved_revision_hash_and_locks_session() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "for_update=True" in source
    assert "approved proposal revision mismatch" in source
    assert "approved proposal hash mismatch" in source
    assert "compute_proposal_hash" in source


def test_commit_is_additive_atomic_and_preserves_legacy_roots() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "LEGACY_ROOT_EXTERNAL_KEY" in source
    assert '"deleted": 0' in source
    assert "db.commit" not in source
    assert "MatchAction.SKIP" in source
    assert "MatchAction.CONFLICT" in source
    assert '"rules_recompute_state": "pending"' in source
    assert "apply_rules_for_users" in source


def test_commit_reclassifies_approved_legacy_branch_without_replacing_id() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert 'unit.unit_type = "branch"' in source
    assert "unit.legacy_root = False" in source
    assert "proposal_key = normalize_import_key(proposal.external_key)" in source
    assert "units_by_external[proposal_key] = unit" in source


def test_position_lock_excludes_nullable_eager_join() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert ".with_for_update(of=Position)" in source
    assert "select(Position).where(Position.tenant_id == tenant_id).with_for_update()" not in source


@pytest.mark.parametrize("existing", [False, True], ids=["created", "updated"])
async def test_generic_commit_reports_branch_and_department_counters(monkeypatch, existing):
    from unittest.mock import Mock

    from app.modules.organization_units import workspace_config
    from app.modules.staff_import_sessions import commit_service as service
    from app.modules.staff_import_sessions.schemas import ImportSessionState

    tenant_id, session_id = uuid4(), uuid4()
    branch_id, department_id = uuid4(), uuid4()
    branch = SimpleNamespace(
        id=branch_id, slug="branch", name="Existing branch", normalized_name="existing branch",
        unit_type="branch", external_key="branch-1", parent_id=None, is_active=True,
        is_head_office=False, legacy_root=False, source_metadata={},
    )
    department = SimpleNamespace(
        id=department_id, slug="department", name="Existing department", normalized_name="existing department",
        unit_type="department", external_key="department-1", parent_id=branch_id, is_active=True,
        is_head_office=False, legacy_root=False, source_metadata={},
    )
    branch_proposal = SimpleNamespace(
        name="Created branch" if not existing else "Renamed branch", unit_type=SimpleNamespace(value="branch"),
        external_key="branch-1", parent_external_key=None, is_head_office=False, action="update",
    )
    department_proposal = SimpleNamespace(
        name="Created department" if not existing else "Renamed department", unit_type=SimpleNamespace(value="department"),
        external_key="department-1", parent_external_key="branch-1", is_head_office=False, action="update",
    )
    proposal = SimpleNamespace(
        organization_units=[branch_proposal, department_proposal], branches=[], departments=[], positions=[], staff=[],
        revision="r", revision_hash="hash",
    )
    record = SimpleNamespace(id=session_id, state="approved", approved_revision="r")
    domain = SimpleNamespace(state=ImportSessionState.APPROVED, proposal=proposal, approved_revision="r")
    plan = (
        service.GenericUnitCommitPlanItem(branch_proposal, branch if existing else None),
        service.GenericUnitCommitPlanItem(department_proposal, department if existing else None),
    )

    class Result:
        def scalars(self):
            return self

        def all(self):
            return []

        def scalar_one_or_none(self):
            return None

    db = SimpleNamespace(add=Mock(), flush=AsyncMock(), execute=AsyncMock(return_value=Result()))
    monkeypatch.setattr(service, "get_import_session", AsyncMock(return_value=record))
    monkeypatch.setattr(service, "record_to_domain", lambda _: domain)
    monkeypatch.setattr(service, "compute_proposal_hash", lambda _: "hash")
    monkeypatch.setattr(service, "_lock_and_reject_inactive_staff_matches", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_tenant_units", AsyncMock(return_value=[branch, department] if existing else []))
    monkeypatch.setattr(service, "build_generic_unit_commit_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(workspace_config, "staff_workspace_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "apply_transition",
        lambda current, target, **kwargs: SimpleNamespace(state=target),
    )

    result = await service.commit_approved_import_session(
        db, tenant_id=tenant_id, session_id=session_id, actor_id=uuid4(), revision="r"
    )

    assert result.result_summary["organization_units_created" if not existing else "organization_units_updated"] == 2
    assert result.result_summary["branches_created" if not existing else "branches_updated"] == 1
    assert result.result_summary["departments_created" if not existing else "departments_updated"] == 1


@pytest.mark.parametrize("action", ["update", "move"])
async def test_workspace_import_preflight_allows_safe_update_to_locked_validation(monkeypatch, action):
    from app.modules.organization_units import workspace_config
    from app.modules.staff_import_sessions import commit_service as service
    from app.modules.staff_import_sessions.schemas import ImportSessionState
    class ReachedLockedValidationError(Exception):
        pass
    proposal = SimpleNamespace(revision="r", revision_hash="hash", organization_units=[],
        branches=[SimpleNamespace(action=action)], departments=[], positions=[], staff=[])
    record = SimpleNamespace(state="approved", approved_revision="r")
    monkeypatch.setattr(service, "get_import_session", AsyncMock(return_value=record))
    monkeypatch.setattr(service, "record_to_domain", lambda _: SimpleNamespace(
        state=ImportSessionState.APPROVED, proposal=proposal, approved_revision="r"))
    monkeypatch.setattr(service, "compute_proposal_hash", lambda _: "hash")
    monkeypatch.setattr(workspace_config, "staff_workspace_enabled", lambda: True)
    locked = AsyncMock(return_value={})
    monkeypatch.setattr(service, "_lock_and_reject_inactive_staff_matches", locked)
    units = AsyncMock(side_effect=ReachedLockedValidationError())
    monkeypatch.setattr(service, "_tenant_units", units)
    expected = service.ImportCommitConflictError if action == "move" else ReachedLockedValidationError
    with pytest.raises(expected):
        await service.commit_approved_import_session(SimpleNamespace(), tenant_id=uuid4(),
            session_id=uuid4(), actor_id=uuid4(), revision="r")
    assert locked.await_count == units.await_count == (0 if action == "move" else 1)


@pytest.mark.parametrize("change", ["parent", "head_office", "reactivation", "hr"])
async def test_update_locked_unit_guards_reject_placement_and_hr_before_field_writes(monkeypatch, change):
    from copy import deepcopy

    from app.modules.organization_units import workspace_config
    from app.modules.staff_import_sessions import commit_service as service
    from app.modules.staff_import_sessions.schemas import ImportSessionState

    parent = SimpleNamespace(id=uuid4(), slug="parent", external_key="parent")
    unit = SimpleNamespace(id=uuid4(), name="Existing", parent_id=None, unit_type="department",
        external_key="unit", is_head_office=False, legacy_root=False, is_active=change != "reactivation",
        source_metadata={"origin": "1c"} if change == "hr" else {})
    before = deepcopy(vars(unit))
    incoming = SimpleNamespace(action="update", parent_external_key="parent" if change == "parent" else None,
        name="Renamed", unit_type=SimpleNamespace(value="department"), external_key="unit",
        is_head_office=change == "head_office")
    proposal = SimpleNamespace(revision="r", revision_hash="hash", organization_units=[incoming],
        branches=[], departments=[], positions=[], staff=[])
    record = SimpleNamespace(id=uuid4(), state="approved", approved_revision="r")
    monkeypatch.setattr(service, "get_import_session", AsyncMock(return_value=record))
    monkeypatch.setattr(service, "record_to_domain", lambda _: SimpleNamespace(
        state=ImportSessionState.APPROVED, proposal=proposal, approved_revision="r"))
    monkeypatch.setattr(service, "compute_proposal_hash", lambda _: "hash")
    monkeypatch.setattr(workspace_config, "staff_workspace_enabled", lambda: True)
    monkeypatch.setattr(service, "_lock_and_reject_inactive_staff_matches", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_tenant_units", AsyncMock(return_value=[parent, unit]))
    monkeypatch.setattr(service, "build_generic_unit_commit_plan", lambda *args, **kwargs: (
        service.GenericUnitCommitPlanItem(proposal=incoming, existing=unit),))
    monkeypatch.setattr(service, "apply_transition", lambda *args, **kwargs: SimpleNamespace(state=ImportSessionState.COMMITTING))
    from unittest.mock import Mock

    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    with pytest.raises(ValueError, match="hr_managed" if change == "hr" else "placement_requires_reviewed_transfer"):
        await service.commit_approved_import_session(db, tenant_id=uuid4(), session_id=record.id,
            actor_id=uuid4(), revision="r")
    assert vars(unit) == before
    # No organization write or training recompute occurred. The surrounding
    # router owns rollback of the pending COMMITTING event/session transition.
    assert db.add.call_count == 1
    assert db.flush.await_count == 1
