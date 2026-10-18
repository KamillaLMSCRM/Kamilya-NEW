from pathlib import Path
from types import SimpleNamespace
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
