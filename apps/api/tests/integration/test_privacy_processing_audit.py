from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.modules.audit.models import AuditLog
from app.modules.users import router as users_router

pytestmark = pytest.mark.asyncio


async def _privacy_entry(db_session, *, tenant_id, action: str, resource_id: str):
    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant_id)},
    )
    return (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == action,
                AuditLog.resource_id == resource_id,
            )
        )
    ).scalar_one()


async def test_employee_update_and_privacy_record_commit_together(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
) -> None:
    tenant = await make_tenant(name=f"Privacy update {uuid4().hex[:8]}")
    admin = await make_user(tenant, role="admin")
    employee = await make_user(tenant, role="student")

    response = await client.patch(
        f"/api/v1/users/{employee.id}",
        headers=auth_headers(admin),
        json={"first_name": "Updated"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["first_name"] == "Updated"
    entry = await _privacy_entry(
        db_session,
        tenant_id=tenant.id,
        action="privacy.processing.team_member.update",
        resource_id=str(employee.id),
    )
    assert entry.user_id == admin.id
    assert entry.details["outcome"] == "full"
    assert entry.details["field_names"] == [
        "email",
        "first_name",
        "is_active",
        "last_name",
    ]


async def test_employee_export_records_value_free_processing_metadata(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
) -> None:
    tenant = await make_tenant(name=f"Privacy export {uuid4().hex[:8]}")
    admin = await make_user(tenant, role="admin")
    employee = await make_user(tenant, role="student")

    response = await client.get(
        "/api/v1/admin/export/users",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200, response.text
    entry = await _privacy_entry(
        db_session,
        tenant_id=tenant.id,
        action="privacy.processing.employee.export",
        resource_id="tenant-users",
    )
    assert entry.user_id == admin.id
    assert employee.email not in repr(entry.details)
    assert entry.details["data_classes"] == [
        "contact_identifier",
        "employment",
        "identity",
        "internal_identifier",
        "online_identifier",
    ]


async def test_team_member_mutations_emit_complete_processing_audit(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        users_router.EmailService,
        "delivery_ready",
        staticmethod(lambda: False),
    )
    tenant = await make_tenant(name=f"Privacy mutations {uuid4().hex[:8]}")
    admin = await make_user(tenant, role="admin")
    employee_for_role = await make_user(tenant, role="student")
    employee_for_reset = await make_user(tenant, role="student")
    employee_for_deactivate = await make_user(tenant, role="student")

    create_response = await client.post(
        "/api/v1/users",
        headers=auth_headers(admin),
        json={
            "email": f"team-{uuid4().hex[:8]}@example.com",
            "first_name": "Team",
            "last_name": "Member",
            "role": "methodologist",
            "is_active": True,
        },
    )
    assert create_response.status_code == 201, create_response.text
    created_id = create_response.json()["id"]

    add_role_response = await client.post(
        f"/api/v1/users/{employee_for_role.id}/roles",
        headers=auth_headers(admin),
        json={"role": "methodologist"},
    )
    assert add_role_response.status_code == 200, add_role_response.text

    reset_response = await client.post(
        f"/api/v1/users/{employee_for_reset.id}/reset-password",
        headers=auth_headers(admin),
        json={"new_password": "synthetic-password-2026"},
    )
    assert reset_response.status_code == 200, reset_response.text

    deactivate_response = await client.delete(
        f"/api/v1/users/{employee_for_deactivate.id}",
        headers=auth_headers(admin),
    )
    assert deactivate_response.status_code == 204, deactivate_response.text

    change_role_response = await client.post(
        f"/api/v1/users/{created_id}/role?role=admin",
        headers=auth_headers(admin),
    )
    assert change_role_response.status_code == 200, change_role_response.text

    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
    )
    actions = set(
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.action.like("privacy.processing.team_member.%"),
                )
            )
        ).scalars()
    )
    assert actions == {
        "privacy.processing.team_member.assign_role",
        "privacy.processing.team_member.change_role",
        "privacy.processing.team_member.create",
        "privacy.processing.team_member.deactivate",
        "privacy.processing.team_member.reset_password",
    }


async def test_training_exports_emit_processing_audit(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
) -> None:
    tenant = await make_tenant(name=f"Privacy reports {uuid4().hex[:8]}")
    admin = await make_user(tenant, role="admin")
    methodologist = await make_user(tenant, role="methodologist")

    enrollment_response = await client.get(
        "/api/v1/admin/export/enrollments",
        headers=auth_headers(methodologist),
    )
    quiz_response = await client.get(
        "/api/v1/admin/export/quiz-results",
        headers=auth_headers(admin),
    )

    assert enrollment_response.status_code == 200, enrollment_response.text
    assert quiz_response.status_code == 200, quiz_response.text
    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
    )
    actions = set(
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.action.in_(
                        (
                            "privacy.processing.enrollment.export",
                            "privacy.processing.quiz_result.export",
                        )
                    ),
                )
            )
        ).scalars()
    )
    assert actions == {
        "privacy.processing.enrollment.export",
        "privacy.processing.quiz_result.export",
    }


async def test_methodologist_employee_update_and_termination_are_recorded(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
) -> None:
    tenant = await make_tenant(name=f"Privacy staff {uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    employee_to_update = await make_user(tenant, role="student")
    employee_to_update.personnel_number = f"PN-{uuid4().hex[:8]}"
    employee_to_terminate = await make_user(tenant, role="student")
    employee_to_terminate.personnel_number = f"PN-{uuid4().hex[:8]}"
    await db_session.flush()

    update_response = await client.patch(
        f"/api/v1/admin/staff/manual/{employee_to_update.id}",
        headers=auth_headers(methodologist),
        json={
            "personnel_number": employee_to_update.personnel_number,
            "first_name": "Updated",
            "last_name": "Employee",
            "email": employee_to_update.email,
            "phone": "+7 700 000 00 00",
        },
    )
    terminate_response = await client.post(
        f"/api/v1/admin/staff/manual/{employee_to_terminate.id}/terminate",
        headers=auth_headers(methodologist),
        json={"reason": "Synthetic integration test"},
    )

    assert update_response.status_code == 200, update_response.text
    assert terminate_response.status_code == 200, terminate_response.text
    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
    )
    entries = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action.in_(
                    (
                        "privacy.processing.employee.update",
                        "privacy.processing.employee.terminate",
                    )
                ),
            )
        )
    ).scalars().all()
    assert {entry.action for entry in entries} == {
        "privacy.processing.employee.update",
        "privacy.processing.employee.terminate",
    }
    assert all("Synthetic integration test" not in repr(entry.details) for entry in entries)


async def test_methodologist_employee_create_preview_and_import_are_recorded(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
) -> None:
    tenant = await make_tenant(name=f"Privacy import {uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    manual_email = f"manual-{uuid4().hex[:8]}@example.com"

    create_response = await client.post(
        "/api/v1/admin/staff/manual",
        headers=auth_headers(methodologist),
        json={
            "personnel_number": f"MAN-{uuid4().hex[:8]}",
            "first_name": "Synthetic",
            "last_name": "Manual",
            "position": "Privacy test role",
            "email": manual_email,
        },
    )
    assert create_response.status_code == 201, create_response.text

    imported_email = f"import-{uuid4().hex[:8]}@example.com"
    csv_content = (
        "personnel_number,first_name,last_name,department,position,email,hire_date\n"
        f"IMP-{uuid4().hex[:8]},Synthetic,Imported,Test,Analyst,{imported_email},2026-09-29\n"
    ).encode()
    upload = {"file": ("staff.csv", csv_content, "text/csv")}

    preview_response = await client.post(
        "/api/v1/admin/staff/import/preview",
        headers=auth_headers(methodologist),
        files=upload,
    )
    assert preview_response.status_code == 200, preview_response.text
    assert preview_response.json()["missing_required_columns"] == []

    commit_response = await client.post(
        "/api/v1/admin/staff/import/commit",
        headers=auth_headers(methodologist),
        files={"file": ("staff.csv", csv_content, "text/csv")},
    )
    assert commit_response.status_code == 200, commit_response.text
    assert commit_response.json()["created"] == 1

    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
    )
    entries = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action.in_(
                    (
                        "privacy.processing.employee.create",
                        "privacy.processing.employee.import_preview",
                        "privacy.processing.employee.import",
                    )
                ),
            )
        )
    ).scalars().all()
    assert {entry.action for entry in entries} == {
        "privacy.processing.employee.create",
        "privacy.processing.employee.import_preview",
        "privacy.processing.employee.import",
    }
    serialized = repr([entry.details for entry in entries])
    assert manual_email not in serialized
    assert imported_email not in serialized
