"""Migration and PostgreSQL catalog contract for privileged purge RLS."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "0124_privileged_tenant_purge_rls.py"
)

EXPECTED_TABLES = {
    "content_releases",
    "departments",
    "learning_path_assignments",
    "staff_import_mappings",
    "staff_import_session_events",
    "staff_import_sessions",
    "support_requests",
    "tenant_usage",
    "training_evidence_events",
    "training_evidence_signed_scans",
}


def test_migration_is_delete_only_and_preserves_force_rls() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0124"' in source
    assert 'down_revision = "0123"' in source
    assert 'POLICY_NAME = "privileged_tenant_purge_delete"' in source
    assert "FOR DELETE TO PUBLIC" in source
    assert "public.privileged_tenant_purge_authorized(tenant_id)" in source
    assert "SECURITY DEFINER" not in source
    assert "GRANT " not in source
    assert "FOR INSERT" not in source
    assert "FOR UPDATE" not in source
    assert "FOR SELECT" not in source
    assert "NO FORCE ROW LEVEL SECURITY" not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source
    assert "session_replication_role" not in source


@pytest.mark.asyncio
async def test_catalog_has_exact_delete_policies_and_force_rls(db_session) -> None:
    policies = (
        await db_session.execute(
            text(
                "SELECT tablename, cmd, roles, qual "
                "FROM pg_catalog.pg_policies "
                "WHERE schemaname = 'public' "
                "AND policyname = 'privileged_tenant_purge_delete'"
            )
        )
    ).all()

    assert {row.tablename for row in policies} == EXPECTED_TABLES
    assert all(row.cmd == "DELETE" for row in policies)
    assert all(row.roles == ["public"] for row in policies)
    assert all(
        "privileged_tenant_purge_authorized(tenant_id)" in row.qual
        for row in policies
    )

    force_rls_tables = set(
        (
            await db_session.execute(
                text(
                    "SELECT c.relname "
                    "FROM pg_catalog.pg_class AS c "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' "
                    "AND c.relname = ANY(:table_names) "
                    "AND c.relrowsecurity "
                    "AND c.relforcerowsecurity"
                ),
                {"table_names": sorted(EXPECTED_TABLES)},
            )
        ).scalars()
    )
    assert force_rls_tables == EXPECTED_TABLES

    uuid_tenant_tables = set(
        (
            await db_session.execute(
                text(
                    "SELECT c.table_name "
                    "FROM information_schema.columns AS c "
                    "WHERE c.table_schema = 'public' "
                    "AND c.column_name = 'tenant_id' "
                    "AND c.udt_name = 'uuid' "
                    "AND c.table_name = ANY(:table_names)"
                ),
                {"table_names": sorted(EXPECTED_TABLES)},
            )
        ).scalars()
    )
    assert uuid_tenant_tables == EXPECTED_TABLES
