"""Static security contract for the bounded immutable-release purge."""

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0141_superadmin_content_release_purge.py"
)


def _upgrade_source() -> str:
    source = MIGRATION.read_text(encoding="utf-8")
    return source.split("def downgrade()", maxsplit=1)[0]


def test_purge_helper_is_bounded_and_not_public() -> None:
    source = _upgrade_source()

    assert "SECURITY DEFINER" in source
    assert "REVOKE ALL ON FUNCTION" in source
    assert "GRANT EXECUTE ON FUNCTION" in source
    assert "TO lms_app" in source
    assert "app.is_superadmin" in source
    assert "persisted_slug IS DISTINCT FROM p_confirm_slug" in source
    assert "persisted_slug = 'kamilya'" in source
    assert "WHERE tenant_id = p_tenant_id" in source


def test_purge_authorization_requires_owner_execution_and_exact_tenant_guc() -> None:
    source = _upgrade_source()

    assert "app.privileged_tenant_purge_id" in source
    assert "= p_tenant_id::text" in source
    assert "current_user = database_owner" in source
    assert "UPDATE public.courses" in source
    assert "SET current_release_id = NULL" in source
    assert "DELETE FROM public.content_releases" in source
