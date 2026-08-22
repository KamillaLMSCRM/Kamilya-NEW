"""PostgreSQL contract checks for the owner-only tenant purge guard."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.learning_paths.models import LearningPath, LearningPathCourse

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "0123_privileged_tenant_purge_guard.py"
)


def test_migration_exposes_no_application_purge_entry_point() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0123"' in source
    assert 'down_revision = "0122"' in source
    assert "SECURITY DEFINER" not in source
    assert "GRANT EXECUTE" not in source
    assert "session_user = database_owner" in source
    assert "current_user = database_owner" in source
    assert "TG_OP = 'DELETE'" in source
    assert "OLD.tenant_id" in source
    assert "path_tenant_id" in source
    assert "SET search_path = pg_catalog, pg_temp" in source
    assert "Published learning-program versions are immutable" in source
    assert "Published learning-program curriculum is immutable" in source


async def _expect_rejected(db_session, statement: str, **params) -> None:
    savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(text(statement), params)
    finally:
        await savepoint.rollback()


@pytest.mark.asyncio
async def test_runtime_role_cannot_spoof_purge_guard(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
) -> None:
    is_database_owner = await db_session.scalar(
        text(
            "SELECT current_user = pg_catalog.pg_get_userbyid(d.datdba) "
            "FROM pg_catalog.pg_database AS d "
            "WHERE d.datname = pg_catalog.current_database()"
        )
    )
    if is_database_owner:
        pytest.skip("runtime-role contract requires the lms_app connection")

    tenant = await make_tenant(name="Runtime purge guard")
    creator = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, creator, title="Runtime purge guard course")
    path = LearningPath(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=uuid4(),
        version=1,
        title="Runtime published purge guard",
        description="",
        status="draft",
        sequencing_mode="linear",
        created_by=creator.id,
    )
    step = LearningPathCourse(
        id=uuid4(),
        path_id=path.id,
        course_id=course.id,
        order_index=0,
        required=True,
    )
    await set_current_tenant(tenant)
    db_session.add_all([path, step])
    await db_session.flush()
    path.status = "published"
    await db_session.flush()

    await db_session.execute(
        text(
            "SELECT set_config('app.privileged_tenant_purge_id', "
            ":tenant_id, true)"
        ),
        {"tenant_id": str(tenant.id)},
    )
    assert not await db_session.scalar(
        text("SELECT public.privileged_tenant_purge_authorized(:tenant_id)"),
        {"tenant_id": tenant.id},
    )
    await _expect_rejected(
        db_session,
        "DELETE FROM public.learning_path_courses WHERE id = :row_id",
        row_id=step.id,
    )
    await _expect_rejected(
        db_session,
        "DELETE FROM public.learning_paths WHERE id = :row_id",
        row_id=path.id,
    )


@pytest.mark.asyncio
async def test_guard_is_owner_tenant_and_delete_scoped(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
) -> None:
    is_database_owner = await db_session.scalar(
        text(
            "SELECT current_user = pg_catalog.pg_get_userbyid(d.datdba) "
            "FROM pg_catalog.pg_database AS d "
            "WHERE d.datname = pg_catalog.current_database()"
        )
    )
    if not is_database_owner:
        pytest.skip("owner contract requires the migration-owner connection")

    tenant_a = await make_tenant(name="Purge guard A")
    tenant_b = await make_tenant(name="Purge guard B")
    creator_a = await make_user(tenant_a, role="methodologist")
    creator_b = await make_user(tenant_b, role="methodologist")
    course_a = await make_course(tenant_a, creator_a, title="Purge guard course A")
    course_b = await make_course(tenant_b, creator_b, title="Purge guard course B")

    path_a = LearningPath(
        id=uuid4(),
        tenant_id=tenant_a.id,
        family_id=uuid4(),
        version=1,
        title="Published purge guard A",
        description="",
        status="draft",
        sequencing_mode="linear",
        created_by=creator_a.id,
    )
    path_b = LearningPath(
        id=uuid4(),
        tenant_id=tenant_b.id,
        family_id=uuid4(),
        version=1,
        title="Published purge guard B",
        description="",
        status="draft",
        sequencing_mode="linear",
        created_by=creator_b.id,
    )
    step_a = LearningPathCourse(
        id=uuid4(),
        path_id=path_a.id,
        course_id=course_a.id,
        order_index=0,
        required=True,
    )
    step_b = LearningPathCourse(
        id=uuid4(),
        path_id=path_b.id,
        course_id=course_b.id,
        order_index=0,
        required=True,
    )
    await set_current_tenant(tenant_a)
    db_session.add_all([path_a, step_a])
    await db_session.flush()
    path_a.status = "published"
    await db_session.flush()

    await set_current_tenant(tenant_b)
    db_session.add_all([path_b, step_b])
    await db_session.flush()
    path_b.status = "published"
    await db_session.flush()

    await set_current_tenant(tenant_a)
    await db_session.execute(
        text("SELECT set_config('app.privileged_tenant_purge_id', '', true)")
    )
    assert not await db_session.scalar(
        text("SELECT public.privileged_tenant_purge_authorized(:tenant_id)"),
        {"tenant_id": tenant_a.id},
    )
    await _expect_rejected(
        db_session,
        "DELETE FROM public.learning_path_courses WHERE id = :row_id",
        row_id=step_a.id,
    )

    await db_session.execute(
        text(
            "SELECT set_config('app.privileged_tenant_purge_id', "
            ":tenant_id, true)"
        ),
        {"tenant_id": str(tenant_a.id)},
    )
    assert await db_session.scalar(
        text("SELECT public.privileged_tenant_purge_authorized(:tenant_id)"),
        {"tenant_id": tenant_a.id},
    )
    assert not await db_session.scalar(
        text("SELECT public.privileged_tenant_purge_authorized(:tenant_id)"),
        {"tenant_id": tenant_b.id},
    )

    await _expect_rejected(
        db_session,
        "UPDATE public.learning_paths SET title = title || ' changed' WHERE id = :row_id",
        row_id=path_a.id,
    )

    await set_current_tenant(tenant_b)
    await _expect_rejected(
        db_session,
        "DELETE FROM public.learning_path_courses WHERE id = :row_id",
        row_id=step_b.id,
    )
    await _expect_rejected(
        db_session,
        "DELETE FROM public.learning_paths WHERE id = :row_id",
        row_id=path_b.id,
    )

    await set_current_tenant(tenant_a)
    await db_session.execute(
        text(
            "SELECT set_config('app.privileged_tenant_purge_id', "
            ":tenant_id, true)"
        ),
        {"tenant_id": str(tenant_a.id)},
    )
    purge_savepoint = await db_session.begin_nested()
    try:
        deleted_steps = await db_session.execute(
            text("DELETE FROM public.learning_path_courses WHERE id = :row_id"),
            {"row_id": step_a.id},
        )
        deleted_paths = await db_session.execute(
            text("DELETE FROM public.learning_paths WHERE id = :row_id"),
            {"row_id": path_a.id},
        )
        assert deleted_steps.rowcount == 1
        assert deleted_paths.rowcount == 1
    finally:
        await purge_savepoint.rollback()
