from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core.auth import create_access_token
from app.models.user_roles import UserRole
from app.modules.admin.superadmin.schemas import AdminCreate
from app.modules.admin.superadmin.service import SuperadminService
from app.modules.audit.models import AuditLog

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
    )

    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
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


async def test_superadmin_admin_endpoint_commits_user_role_and_audit_together(
    client,
    db_session,
    make_superadmin,
    make_tenant,
) -> None:
    operator = await make_superadmin()
    tenant = await make_tenant(name="Atomic admin endpoint", slug=f"sa-{uuid4().hex[:8]}")
    token = create_access_token(
        {
            "sub": str(operator.id),
            "tenant_id": None,
            "roles": ["superadmin"],
        }
    )

    response = await client.post(
        f"/api/v1/admin/super/tenants/{tenant.id}/admins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": f"methodologist-{uuid4().hex[:8]}@example.com",
            "first_name": "Test",
            "last_name": "Methodologist",
            "role": "methodologist",
            "is_active": True,
            "send_invite": False,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
    )
    role_count = (
        await db_session.execute(
            select(UserRole).where(
                UserRole.user_id == body["id"],
                UserRole.tenant_id == tenant.id,
                UserRole.role == "methodologist",
            )
        )
    ).scalar_one()
    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action == "superadmin.admin.created",
                AuditLog.resource_id == body["id"],
            )
        )
    ).scalar_one()

    assert role_count.tenant_id == tenant.id
    assert audit.user_id == operator.id
    assert audit.resource_id == body["id"]
