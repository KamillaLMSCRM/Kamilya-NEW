"""Real runtime-role RLS coverage; run only against the isolated DEV gate."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def _set_runtime_role(db_session) -> None:
    attributes = (
        await db_session.execute(
            text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname='lms_app'")
        )
    ).one_or_none()
    assert attributes == (False, False), "lms_app must be a non-superuser NOBYPASSRLS role"
    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    assert await db_session.scalar(text("SELECT current_user")) == "lms_app"


async def _set_tenant_context(db_session, tenant_id: uuid.UUID | None) -> None:
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": "" if tenant_id is None else str(tenant_id)},
    )


@pytest.mark.asyncio
async def test_runtime_lms_app_force_rls_blocks_missing_and_cross_tenant_crud(
    db_session,
    make_tenant,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="BYOK RLS A")
    tenant_b = await make_tenant(name="BYOK RLS B")
    provider_id = uuid.uuid4()

    await set_current_tenant(tenant_a)
    await db_session.execute(
        text("""
            INSERT INTO tenant_ai_providers (id, tenant_id, purpose, provider, model, encrypted_key)
            VALUES (:id, :tenant_id, 'embedding', 'voyage', 'voyage-4-lite', 'synthetic-ciphertext')
        """),
        {"id": provider_id, "tenant_id": tenant_a.id},
    )
    await _set_runtime_role(db_session)

    await _set_tenant_context(db_session, None)
    assert await db_session.scalar(text("SELECT count(*) FROM tenant_ai_providers")) == 0

    await _set_tenant_context(db_session, tenant_b.id)
    assert await db_session.scalar(text("SELECT count(*) FROM tenant_ai_providers")) == 0
    assert (await db_session.execute(
        text("UPDATE tenant_ai_providers SET enabled=false WHERE id=:id"), {"id": provider_id}
    )).rowcount == 0
    assert (await db_session.execute(
        text("DELETE FROM tenant_ai_providers WHERE id=:id"), {"id": provider_id}
    )).rowcount == 0

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("""
                    INSERT INTO tenant_ai_providers (id, tenant_id, purpose, provider, model, encrypted_key)
                    VALUES (:id, :tenant_id, 'generation', 'deepseek', 'deepseek-v4-flash', 'synthetic-ciphertext')
                """),
                {"id": uuid.uuid4(), "tenant_id": tenant_a.id},
            )

    await _set_tenant_context(db_session, tenant_a.id)
    assert await db_session.scalar(text("SELECT count(*) FROM tenant_ai_providers")) == 1
    assert (await db_session.execute(
        text("UPDATE tenant_ai_providers SET enabled=false WHERE id=:id"), {"id": provider_id}
    )).rowcount == 1
    assert (await db_session.execute(
        text("DELETE FROM tenant_ai_providers WHERE id=:id"), {"id": provider_id}
    )).rowcount == 1
