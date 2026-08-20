from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0114_position_import_identity.py"


def test_0114_adds_stable_tenant_position_identity() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0114"' in source
    assert 'down_revision = "0113"' in source
    assert '"normalized_name"' in source
    assert '"external_key"' in source
    assert "uq_positions_tenant_external_key" in source
    assert "position organization unit tenant mismatch" in source
    assert "0114 downgrade refused" in source
