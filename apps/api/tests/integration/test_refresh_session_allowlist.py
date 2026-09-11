import pytest
from fastapi import HTTPException

from app.core.auth import create_refresh_token, decode_token
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

    access, rotated, _ = await refresh_access_token(db_session, token)
    await db_session.commit()
    original_payload = decode_token(token)
    access_payload = decode_token(access)
    rotated_payload = decode_token(rotated)
    assert access_payload["auth_time"] == original_payload["auth_time"]
    assert access_payload["session_exp"] == original_payload["exp"]
    assert rotated_payload["auth_time"] == original_payload["auth_time"]
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
