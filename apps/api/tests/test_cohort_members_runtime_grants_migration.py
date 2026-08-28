"""Static contract tests for migration 0134."""

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0134_grant_cohort_members_runtime_access.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("migration_0134", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_0134_after_0133() -> None:
    module = _module()
    assert module.revision == "0134"
    assert module.down_revision == "0133"


def test_runtime_role_receives_only_cohort_membership_privileges() -> None:
    module = _module()
    statements: list[str] = []
    module.op.execute = statements.append

    module.upgrade()

    assert statements == [
        "GRANT SELECT, INSERT, DELETE ON TABLE cohort_members TO lms_app"
    ]
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "GRANT UPDATE" not in source
    assert "GRANT TRUNCATE" not in source
    assert "BYPASSRLS" not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source


def test_downgrade_preserves_the_predecessor_privilege_contract() -> None:
    module = _module()
    statements: list[str] = []
    module.op.execute = statements.append

    module.downgrade()

    assert statements == []
