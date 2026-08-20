from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0113_staff_import_sessions.py"


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_0113_is_linear_and_creates_audited_tenant_scoped_tables() -> None:
    source = _source()
    assert 'revision = "0113"' in source
    assert 'down_revision = "0112"' in source
    assert '"staff_import_sessions"' in source
    assert '"staff_import_session_events"' in source
    assert '"workbook_analysis"' in source
    assert '"mapping_json"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source


def test_0113_enforces_ownership_immutability_and_closed_grants() -> None:
    source = _source()
    assert "staff import actor tenant mismatch" in source
    assert "staff import mapping tenant mismatch" in source
    assert "staff import event tenant mismatch" in source
    assert "approved staff import proposal is immutable" in source
    assert "invalid staff import session state transition" in source
    assert "staff import session events are append-only" in source
    assert "GRANT SELECT, INSERT, UPDATE ON staff_import_sessions TO lms_app" in source
    assert "GRANT SELECT, INSERT ON staff_import_session_events TO lms_app" in source
    assert "GRANT DELETE" not in source


def test_0113_guards_snapshot_state_and_downgrade() -> None:
    source = _source()
    assert "ck_staff_import_sessions_proposal_snapshot" in source
    assert "ck_staff_import_sessions_approval_state" in source
    assert "ck_staff_import_sessions_commit_state" in source
    assert "source_format IN ('xlsx','xls','csv')" in source
    assert "0113 downgrade refused" in source
