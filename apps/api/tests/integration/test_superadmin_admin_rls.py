from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.models.user_roles import UserRole
from app.modules.admin.superadmin.schemas import AdminCreate
from app.modules.admin.superadmin.service import SuperadminService

pytestmark = pytest.mark.asyncio


async def test_platform_superadmin_sets_target_tenant_before_user_role_write(
    db_session,
    make_superadmin,
    make_tenant,
) -> None:
    """A platform session must be able to add a second tenant system user.

    The HTTP auth dependency sets only ``app.is_superadmin`` for a platform
    operator.  ``user_roles`` intentionally has tenant-only FORCE RLS, so the
    service must bind the target tenant before reading or writing that table.
    """

    operator = await make_superadmin()
    tenant = await make_tenant(name="Superadmin role write", slug=f"sa-{uuid4().hex[:8]}")
    await db_session.execute(text("SELECT reset_tenant()"))

    user, invite = await SuperadminService(db_session).create_admin(
        tenant.id,
        AdminCreate(
            email=f"methodologist-{uuid4().hex[:8]}@example.com",
            first_name="Test",
            last_name="Methodologist",
            role="methodologist",
            is_active=True,
            send_invite=False,
        ),
        superadmin_id=operator.id,
        commit=False,
    )

    role = (
        await db_session.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.tenant_id == tenant.id,
                UserRole.role == "methodologist",
            )
        )
    ).scalar_one()

    assert invite is None
    assert user.tenant_id == tenant.id
    assert user.role == "methodologist"
    assert role.tenant_id == tenant.id
