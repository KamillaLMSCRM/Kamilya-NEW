"""Migration and catalog contract for owner-only purge visibility."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "0126_privileged_tenant_purge_visibility.py"
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


def test_migration_adds_only_owner_authorized_select_visibility() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0126"' in source
    assert 'down_revision = "0125"' in source
    assert 'POLICY_NAME = "privileged_tenant_purge_select"' in source
    assert "FOR SELECT TO PUBLIC" in source
    assert "public.privileged_tenant_purge_authorized(tenant_id)" in source
    assert "SECURITY DEFINER" not in source
    assert "GRANT " not in source
    assert "FOR INSERT" not in source
    assert "FOR UPDATE" not in source
    assert "NO FORCE ROW LEVEL SECURITY" not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source
    assert "session_replication_role" not in source


@pytest.mark.asyncio
async def test_catalog_has_matching_select_and_delete_policies(db_session) -> None:
    policies = (
        await db_session.execute(
            text(
                "SELECT policyname, tablename, cmd, roles, qual "
                "FROM pg_catalog.pg_policies "
                "WHERE schemaname = 'public' "
                "AND policyname IN "
                "('privileged_tenant_purge_delete', "
                "'privileged_tenant_purge_select')"
            )
        )
    ).all()

    select_policies = {
        row.tablename: row for row in policies if row.cmd == "SELECT"
    }
    delete_policies = {
        row.tablename: row for row in policies if row.cmd == "DELETE"
    }
    assert set(select_policies) == EXPECTED_TABLES
    assert set(delete_policies) == EXPECTED_TABLES
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


@pytest.mark.asyncio
async def test_visibility_is_owner_exact_tenant_only(
    db_session,
    set_current_tenant,
) -> None:
    is_database_owner = await db_session.scalar(
        text(
            "SELECT current_user = pg_catalog.pg_get_userbyid(d.datdba) "
            "FROM pg_catalog.pg_database AS d "
            "WHERE d.datname = pg_catalog.current_database()"
        )
    )
    role_bypasses_rls = await db_session.scalar(
        text(
            "SELECT rolsuper OR rolbypassrls "
            "FROM pg_catalog.pg_roles WHERE rolname = current_user"
        )
    )
    if is_database_owner and role_bypasses_rls:
        pytest.skip("owner visibility contract requires a non-bypass owner")

    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    for tenant_id, name, slug in (
        (tenant_a_id, "Purge visibility tenant A", f"purge-a-{uuid4().hex[:8]}"),
        (tenant_b_id, "Purge visibility tenant B", f"purge-b-{uuid4().hex[:8]}"),
    ):
        await db_session.execute(
            text(
                "INSERT INTO tenants "
                "(id, name, slug, status, plan, is_demo, settings) "
                "VALUES (:id, :name, :slug, 'active', 'free', false, '{}'::jsonb)"
            ),
            {"id": tenant_id, "name": name, "slug": slug},
        )

    await set_current_tenant(tenant_a_id)
    department_a_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO departments "
            "(id, tenant_id, name, slug, unit_type, normalized_name, "
            "is_active, source_metadata, legacy_root, description) "
            "VALUES (:id, :tenant_id, :name, :slug, 'department', '', "
            "true, '{}'::jsonb, true, '')"
        ),
        {
            "id": department_a_id,
            "tenant_id": tenant_a_id,
            "name": "Synthetic department A",
            "slug": f"purge-a-{uuid4().hex[:8]}",
        },
    )

    await set_current_tenant(tenant_b_id)
    department_b_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO departments "
            "(id, tenant_id, name, slug, unit_type, normalized_name, "
            "is_active, source_metadata, legacy_root, description) "
            "VALUES (:id, :tenant_id, :name, :slug, 'department', '', "
            "true, '{}'::jsonb, true, '')"
        ),
        {
            "id": department_b_id,
            "tenant_id": tenant_b_id,
            "name": "Synthetic department B",
            "slug": f"purge-b-{uuid4().hex[:8]}",
        },
    )

    neutral_tenant_id = uuid4()
    await set_current_tenant(neutral_tenant_id)

    async def visible_department_ids() -> set:
        return set(
            (
                await db_session.execute(
                    text(
                        "SELECT id FROM departments "
                        "WHERE id = ANY(:department_ids)"
                    ),
                    {"department_ids": [department_a_id, department_b_id]},
                )
            ).scalars()
        )

    await db_session.execute(
        text("SELECT set_config('app.privileged_tenant_purge_id', '', true)")
    )
    assert await visible_department_ids() == set()

    await db_session.execute(
        text(
            "SELECT set_config("
            "'app.privileged_tenant_purge_id', :tenant_id, true)"
        ),
        {"tenant_id": str(tenant_a_id)},
    )
    if not is_database_owner:
        assert await visible_department_ids() == set()
        return

    assert await visible_department_ids() == {department_a_id}

    await db_session.execute(
        text(
            "SELECT set_config("
            "'app.privileged_tenant_purge_id', :tenant_id, true)"
        ),
        {"tenant_id": str(uuid4())},
    )
    assert await visible_department_ids() == set()

    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    await db_session.execute(
        text(
            "SELECT set_config("
            "'app.privileged_tenant_purge_id', :tenant_id, true)"
        ),
        {"tenant_id": str(tenant_a_id)},
    )
    assert await visible_department_ids() == set()
