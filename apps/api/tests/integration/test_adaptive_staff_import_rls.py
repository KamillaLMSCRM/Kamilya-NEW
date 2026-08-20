"""PostgreSQL integration checks for adaptive-import tenant isolation."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.models.department import Department
from app.models.staff_import_mapping import StaffImportMapping  # noqa: F401
from app.models.staff_import_session import StaffImportSession


@pytest.mark.asyncio
async def test_runtime_role_cannot_see_other_tenant_units_or_import_sessions(
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="Adaptive import RLS A")
    tenant_b = await make_tenant(name="Adaptive import RLS B")
    actor_a = await make_user(tenant_a, role="methodologist")

    await set_current_tenant(tenant_a)
    unit_a = Department(
        tenant_id=tenant_a.id,
        name="RLS Branch A",
        slug=f"rls-branch-{uuid4().hex[:8]}",
        unit_type="branch",
        legacy_root=False,
        source_metadata={"origin": "integration_test"},
    )
    session_a = StaffImportSession(
        tenant_id=tenant_a.id,
        actor_id=actor_a.id,
        actor_role="methodologist",
        state="uploaded",
        mode="ADD_OR_UPDATE",
        idempotency_key=f"rls-{uuid4().hex}",
        source_file_name="synthetic.xlsx",
        source_file_sha256=hashlib.sha256(b"synthetic workbook").hexdigest(),
        source_format="xlsx",
        source_size_bytes=18,
        parser_version="adaptive-v1",
    )
    db_session.add_all([unit_a, session_a])
    await db_session.flush()

    # Fixtures use the migration owner. Switch to the actual restricted
    # production role before asserting FORCE RLS behavior.
    role_probe = await db_session.begin_nested()
    try:
        await db_session.execute(text("SET LOCAL ROLE lms_app"))
    except ProgrammingError:
        await role_probe.rollback()
        pytest.skip("configured migration owner cannot SET ROLE lms_app")
    else:
        await role_probe.commit()
    await set_current_tenant(tenant_b)

    assert await db_session.scalar(select(Department).where(Department.id == unit_a.id)) is None
    assert (
        await db_session.scalar(
            select(StaffImportSession).where(StaffImportSession.id == session_a.id)
        )
        is None
    )
