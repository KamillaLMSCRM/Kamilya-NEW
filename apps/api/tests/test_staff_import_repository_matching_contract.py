from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.staff_import_legacy_adapter import LegacyStaffRow, adapt_legacy_rows
from app.modules.staff_import_sessions import MatchAction
from app.modules.staff_import_sessions.repository_matching import reconcile_proposal_with_database

ADAPTER = Path(__file__).parents[1] / "app" / "modules" / "staff_import_sessions" / "repository_matching.py"
ROUTER = Path(__file__).parents[1] / "app" / "modules" / "staff_import_sessions" / "router.py"


def test_repository_adapter_reads_only_current_tenant_before_pure_matching() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    assert "Department.tenant_id == tenant_id" in source
    assert "Position.tenant_id == tenant_id" in source
    assert "User.tenant_id == tenant_id" in source
    assert "build_import_diff(" in source
    assert "db.commit" not in source
    assert "db.add" not in source
    assert "existing_unit_keys.get(parent.id)" in source


def test_analyze_route_reconciles_before_persisting_proposal() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    reconcile_index = source.index("reconcile_proposal_with_database(")
    save_index = source.index("return await save_proposal(")
    assert reconcile_index < save_index


@pytest.mark.asyncio
async def test_existing_staff_preview_uses_matcher_external_key_not_personnel_lookup():
    from app.modules.staff_import_legacy_adapter import LegacyStaffRow, adapt_legacy_rows
    from app.modules.staff_import_sessions.repository_matching import reconcile_proposal_with_database
    from app.modules.staff_import_sessions.schemas import MatchAction

    tenant_id, unit_id, position_id = uuid4(), uuid4(), uuid4()
    proposal = adapt_legacy_rows(
        tenant_id=tenant_id,
        source_file_name="same.csv",
        source_file_sha256="a" * 64,
        rows=[
            LegacyStaffRow(
                row_number=2,
                personnel_number="QA-010",
                first_name="QA",
                last_name="Employee",
                department="QA Dept",
                position="QA Position",
            )
        ],
    )
    unit = SimpleNamespace(
        id=unit_id,
        tenant_id=tenant_id,
        name="QA Dept",
        unit_type="department",
        legacy_root=False,
        external_key=proposal.departments[0].external_key,
        parent_id=None,
        source_metadata={},
    )
    position = SimpleNamespace(
        id=position_id,
        tenant_id=tenant_id,
        name="QA Position",
        department_id=unit_id,
        external_key=proposal.positions[0].external_key,
        source_metadata={},
    )
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        personnel_number="QA-010",
        first_name="QA",
        last_name="Employee",
        email=None,
        phone=None,
        position_id=position_id,
        is_active=True,
    )

    def result(rows):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    db = SimpleNamespace(execute=AsyncMock(side_effect=[result([unit]), result([position]), result([user])]))
    reconciled = await reconcile_proposal_with_database(db, tenant_id=tenant_id, proposal=proposal)
    assert reconciled.staff[0].external_key != reconciled.staff[0].personnel_number
    assert reconciled.staff[0].action is MatchAction.UNCHANGED
    assert any(e.evidence_code for e in reconciled.staff[0].evidence)


@pytest.mark.asyncio
async def test_repeat_file_generic_and_legacy_unit_actions_use_the_same_reconciliation():
    tenant_id = uuid4()
    proposal = adapt_legacy_rows(
        tenant_id=tenant_id,
        source_file_name="repeat.xlsx",
        source_file_sha256="f" * 64,
        rows=[
            LegacyStaffRow(
                row_number=2,
                personnel_number="001",
                first_name="First",
                last_name="Testov",
                branch="Branch A",
                department="Dept A",
                position="Operator",
            )
        ],
    )
    branch_id, department_id = uuid4(), uuid4()
    units = [
        SimpleNamespace(
            id=branch_id,
            tenant_id=tenant_id,
            name="Branch A",
            unit_type="branch",
            parent_id=None,
            external_key=proposal.branches[0].external_key,
            is_active=True,
            legacy_root=False,
            source_metadata={},
        ),
        SimpleNamespace(
            id=department_id,
            tenant_id=tenant_id,
            name="Dept A",
            unit_type="department",
            parent_id=branch_id,
            external_key=proposal.departments[0].external_key,
            is_active=True,
            legacy_root=False,
            source_metadata={},
        ),
    ]

    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class Session:
        def __init__(self):
            self.results = [units, [], []]

        async def execute(self, statement):
            return Result(self.results.pop(0))

    result = await reconcile_proposal_with_database(Session(), tenant_id=tenant_id, proposal=proposal)
    assert result.branches[0].action is MatchAction.UNCHANGED
    assert result.departments[0].action is MatchAction.UNCHANGED
    assert all(unit.action is MatchAction.UNCHANGED for unit in result.organization_units)
