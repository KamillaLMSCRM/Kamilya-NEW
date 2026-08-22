"""Migration and catalog contract for the remaining immutable purge guards."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "0127_privileged_immutable_row_purge.py"
)


def test_migration_is_delete_and_exact_owner_tenant_scoped() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0127"' in source
    assert 'down_revision = "0126"' in source
    assert source.count("TG_OP = 'DELETE'") == 2
    assert source.count(
        "public.privileged_tenant_purge_authorized(OLD.tenant_id)"
    ) == 2
    assert "staff import session events are append-only" in source
    assert "Published course releases are immutable" in source
    assert "SECURITY DEFINER" not in source
    assert "GRANT " not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source
    assert "NO FORCE ROW LEVEL SECURITY" not in source
    assert "session_replication_role" not in source


@pytest.mark.asyncio
async def test_catalog_retains_triggers_with_exact_owner_delete_guard(
    db_session,
) -> None:
    functions = dict(
        (
            await db_session.execute(
                text(
                    "SELECT p.proname, p.prosrc "
                    "FROM pg_catalog.pg_proc AS p "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' "
                    "AND p.proname IN "
                    "('prevent_staff_import_session_event_mutation', "
                    "'prevent_content_release_mutation')"
                )
            )
        ).all()
    )
    assert set(functions) == {
        "prevent_staff_import_session_event_mutation",
        "prevent_content_release_mutation",
    }
    assert all("TG_OP = 'DELETE'" in body for body in functions.values())
    assert all(
        "privileged_tenant_purge_authorized(OLD.tenant_id)" in body
        for body in functions.values()
    )

    triggers = set(
        (
            await db_session.execute(
                text(
                    "SELECT c.relname, t.tgname "
                    "FROM pg_catalog.pg_trigger AS t "
                    "JOIN pg_catalog.pg_class AS c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND NOT t.tgisinternal "
                    "AND t.tgname IN "
                    "('trg_prevent_staff_import_session_event_mutation', "
                    "'content_releases_prevent_mutation')"
                )
            )
        ).all()
    )
    assert triggers == {
        (
            "staff_import_session_events",
            "trg_prevent_staff_import_session_event_mutation",
        ),
        ("content_releases", "content_releases_prevent_mutation"),
    }


async def _expect_rejected(db_session, statement: str, **params) -> None:
    savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(text(statement), params)
    finally:
        await savepoint.rollback()


@pytest.mark.asyncio
async def test_trigger_runtime_is_owner_exact_tenant_and_delete_only(
    db_session,
) -> None:
    is_database_owner = await db_session.scalar(
        text(
            "SELECT current_user = pg_catalog.pg_get_userbyid(d.datdba) "
            "FROM pg_catalog.pg_database AS d "
            "WHERE d.datname = pg_catalog.current_database()"
        )
    )
    tenant_a = uuid4()
    tenant_b = uuid4()

    for function_name in (
        "prevent_staff_import_session_event_mutation",
        "prevent_content_release_mutation",
    ):
        table_name = f"purge_trigger_probe_{uuid4().hex}"
        trigger_name = f"purge_trigger_{uuid4().hex}"
        await db_session.execute(
            text(
                f"CREATE TEMP TABLE {table_name} ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, value text NOT NULL"
                ") ON COMMIT DROP"
            )
        )
        await db_session.execute(
            text(
                f"CREATE TRIGGER {trigger_name} BEFORE UPDATE OR DELETE "
                f"ON {table_name} FOR EACH ROW EXECUTE FUNCTION "
                f"public.{function_name}()"
            )
        )
        row_a = uuid4()
        row_b = uuid4()
        await db_session.execute(
            text(
                f"INSERT INTO {table_name} (id, tenant_id, value) "
                "VALUES (:row_a, :tenant_a, 'a'), (:row_b, :tenant_b, 'b')"
            ),
            {
                "row_a": row_a,
                "tenant_a": tenant_a,
                "row_b": row_b,
                "tenant_b": tenant_b,
            },
        )

        await db_session.execute(
            text("SELECT set_config('app.privileged_tenant_purge_id', '', true)")
        )
        await _expect_rejected(
            db_session,
            f"DELETE FROM {table_name} WHERE id=:row_id",
            row_id=row_a,
        )

        await db_session.execute(
            text(
                "SELECT set_config("
                "'app.privileged_tenant_purge_id', :tenant_id, true)"
            ),
            {"tenant_id": str(uuid4())},
        )
        await _expect_rejected(
            db_session,
            f"DELETE FROM {table_name} WHERE id=:row_id",
            row_id=row_a,
        )

        await db_session.execute(
            text(
                "SELECT set_config("
                "'app.privileged_tenant_purge_id', :tenant_id, true)"
            ),
            {"tenant_id": str(tenant_a)},
        )
        await _expect_rejected(
            db_session,
            f"UPDATE {table_name} SET value='changed' WHERE id=:row_id",
            row_id=row_a,
        )
        await _expect_rejected(
            db_session,
            f"DELETE FROM {table_name} WHERE id=:row_id",
            row_id=row_b,
        )

        if is_database_owner:
            savepoint = await db_session.begin_nested()
            try:
                deleted = await db_session.execute(
                    text(f"DELETE FROM {table_name} WHERE id=:row_id"),
                    {"row_id": row_a},
                )
                assert deleted.rowcount == 1
            finally:
                await savepoint.rollback()
        else:
            await _expect_rejected(
                db_session,
                f"DELETE FROM {table_name} WHERE id=:row_id",
                row_id=row_a,
            )
