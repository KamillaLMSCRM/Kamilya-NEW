from pathlib import Path

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
