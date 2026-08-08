import pytest
from fastapi import HTTPException

from app.core.auth import create_refresh_token
from app.modules.auth.service import (
    blacklist_refresh_token,
    issue_refresh_session,
    refresh_access_token,
)


@pytest.mark.asyncio
async def test_refresh_rotation_replay_and_logout(db_session, make_tenant, make_user):
    tenant = await make_tenant()
    user = await make_user(tenant)
    token = create_refresh_token({"sub": str(user.id), "tenant_id": str(tenant.id), "active_role": "student"})
    await issue_refresh_session(db_session, user, token)
    await db_session.commit()

    _, rotated, _ = await refresh_access_token(db_session, token)
    await db_session.commit()
    with pytest.raises(HTTPException, match="Invalid refresh token"):
        await refresh_access_token(db_session, token)

    await blacklist_refresh_token(db_session, rotated)
    await db_session.commit()
    with pytest.raises(HTTPException, match="Invalid refresh token"):
        await refresh_access_token(db_session, rotated)


@pytest.mark.asyncio
async def test_refresh_session_hash_is_tenant_scoped(db_session, make_tenant, make_user):
    first, second = await make_tenant(), await make_tenant()
    user = await make_user(first)
    token = create_refresh_token({"sub": str(user.id), "tenant_id": str(first.id), "active_role": "student"})
    await issue_refresh_session(db_session, user, token)
    await db_session.commit()

    cross_tenant_token = create_refresh_token(
        {"sub": str(user.id), "tenant_id": str(second.id), "active_role": "student"}
    )
    with pytest.raises(HTTPException, match="Invalid refresh token"):
        await refresh_access_token(db_session, cross_tenant_token)


@pytest.mark.asyncio
async def test_platform_superadmin_refresh_session_uses_platform_rls_context(db_session, make_superadmin):
    user = await make_superadmin()
    token = create_refresh_token(
        {
            "sub": str(user.id),
            "tenant_id": None,
            "active_role": "superadmin",
            "platform": True,
        }
    )
    await issue_refresh_session(db_session, user, token)
    await db_session.commit()

    _, rotated, payload = await refresh_access_token(db_session, token)
    await db_session.commit()

    assert payload["role"] == "superadmin"
    assert payload["tenant_id"] is None
    with pytest.raises(HTTPException, match="Invalid refresh token"):
        await refresh_access_token(db_session, token)

    await blacklist_refresh_token(db_session, rotated)
    await db_session.commit()
