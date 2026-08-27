"""Release-environment contract for the PostgreSQL tenant-isolation gate."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.asyncio

CRITICAL_TENANT_TABLES = {
    "ai_jobs",
    "courses",
    "departments",
    "documents",
    "enrollments",
    "staff_import_sessions",
    "training_evidence_events",
    "training_evidence_shares",
    "users",
}


async def test_release_database_is_postgresql_17_with_pgvector_and_current_schema(
    db_session,
) -> None:
    server_version = int(
        await db_session.scalar(text("SELECT current_setting('server_version_num')"))
    )
    assert 170000 <= server_version < 180000
    assert await db_session.scalar(
        text("SELECT count(*) FROM pg_extension WHERE extname='vector'")
    ) == 1
    assert await db_session.scalar(text("SELECT version_num FROM alembic_version")) == "0133"


async def test_runtime_role_cannot_bypass_rls_or_administer_cluster(db_session) -> None:
    role = (
        await db_session.execute(
            text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolinherit, rolbypassrls "
                "FROM pg_roles WHERE rolname='lms_app'"
            )
        )
    ).one()
    assert tuple(role) == (False, False, False, False, False)


async def test_critical_tenant_tables_have_rls_and_force_rls(db_session) -> None:
    rows = (
        await db_session.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname IN "
                "('ai_jobs','courses','departments','documents','enrollments',"
                "'staff_import_sessions','training_evidence_events',"
                "'training_evidence_shares','users')"
            )
        )
    ).all()
    assert {row.relname for row in rows} == CRITICAL_TENANT_TABLES
    assert all(row.relrowsecurity and row.relforcerowsecurity for row in rows)


async def test_runtime_role_can_set_only_tenant_context(db_session) -> None:
    execute_granted = await db_session.scalar(
        text(
            "SELECT has_function_privilege('lms_app', "
            "'set_current_tenant(uuid)', 'EXECUTE')"
        )
    )
    assert execute_granted is True


async def test_runtime_role_denies_cross_tenant_course_crud(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
) -> None:
    tenant_a = await make_tenant(name="RLS CRUD tenant A")
    tenant_b = await make_tenant(name="RLS CRUD tenant B")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    course_a = await make_course(tenant_a, methodologist_a, title="Tenant A secret")

    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    await set_current_tenant(tenant_b)

    assert await db_session.scalar(
        text("SELECT title FROM courses WHERE id=:course_id"),
        {"course_id": course_a.id},
    ) is None
    update_result = await db_session.execute(
        text("UPDATE courses SET title='cross-tenant update' WHERE id=:course_id"),
        {"course_id": course_a.id},
    )
    assert update_result.rowcount == 0
    delete_result = await db_session.execute(
        text("DELETE FROM courses WHERE id=:course_id"),
        {"course_id": course_a.id},
    )
    assert delete_result.rowcount == 0

    savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(
                text(
                    "INSERT INTO courses "
                    "(id,tenant_id,title,description,status,delivery_type,ai_generated,"
                    "source_document_ids,source_strategy,source_analysis,review_status) "
                    "VALUES (:id,:tenant_id,'forbidden','', 'draft','native',false,"
                    "'[]'::jsonb,'single_topic','{}'::jsonb,'pending')"
                ),
                {"id": uuid4(), "tenant_id": tenant_a.id},
            )
    finally:
        await savepoint.rollback()
