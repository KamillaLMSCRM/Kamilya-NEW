"""RBAC tests for course assignment access.

Direct user→course assignment belongs to methodologist, not tenant
administration. Students must NOT be able to enroll/remove/list arbitrary
enrollments — they keep the self-enrollment path (`POST /v1/courses/{id}/enroll`)
instead.

These tests verify role gating on:
  - POST   /v1/courses/{id}/enrollments  (bulk enroll by manager)
  - GET    /v1/courses/{id}/enrollments  (list)
  - DELETE /v1/courses/enrollments/{id}  (remove)
  - GET    /v1/admin/export/enrollments  (CSV export)

Methodologists can use these endpoints. Tenant admins and students
must get 403.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _bulk_enroll_payload(user_ids: list[str]) -> dict:
    return {"user_ids": user_ids}


class TestEnrollmentRoleGating:
    """Enrollments are methodologist-owned, not tenant-admin-owned."""

    async def test_methodologist_can_bulk_enroll(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant = await make_tenant(name="Tenant T")
        methodologist = await make_user(tenant, role="methodologist")
        student = await make_user(tenant, role="student")
        course = await make_course(
            tenant, methodologist, title="T's Course", status="published"
        )

        r = await client.post(
            f"/api/v1/courses/{course.id}/enrollments",
            json=_bulk_enroll_payload([str(student.id)]),
            headers=auth_headers(methodologist),
        )

        assert r.status_code == 201, (
            f"Methodologist must be able to bulk-enroll. Got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert len(body) == 1
        assert body[0]["user_id"] == str(student.id)

    async def test_admin_cannot_bulk_enroll(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant = await make_tenant(name="Tenant A")
        admin = await make_user(tenant, role="admin")
        student = await make_user(tenant, role="student")
        course = await make_course(tenant, admin, title="A's Course")

        r = await client.post(
            f"/api/v1/courses/{course.id}/enrollments",
            json=_bulk_enroll_payload([str(student.id)]),
            headers=auth_headers(admin),
        )

        assert r.status_code == 403, (
            f"Tenant admin must NOT bulk-enroll learners. Got {r.status_code}: {r.text}"
        )

    async def test_admin_cannot_list_enrollments(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant = await make_tenant(name="Tenant AL")
        admin = await make_user(tenant, role="admin")
        course = await make_course(tenant, admin, title="AL's Course")

        r = await client.get(
            f"/api/v1/courses/{course.id}/enrollments",
            headers=auth_headers(admin),
        )

        assert r.status_code == 403, (
            f"Tenant admin must NOT list learner assignments. Got {r.status_code}: {r.text}"
        )

    async def test_student_cannot_bulk_enroll(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant = await make_tenant(name="Tenant S")
        student_a = await make_user(tenant, role="student")
        student_b = await make_user(tenant, role="student")
        course = await make_course(tenant, student_a, title="S's Course")

        r = await client.post(
            f"/api/v1/courses/{course.id}/enrollments",
            json=_bulk_enroll_payload([str(student_b.id)]),
            headers=auth_headers(student_a),
        )

        assert r.status_code == 403, (
            f"Student must NOT be able to bulk-enroll others. "
            f"Got {r.status_code}: {r.text}"
        )

    async def test_methodologist_can_list_enrollments(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant = await make_tenant(name="Tenant L")
        methodologist = await make_user(tenant, role="methodologist")
        course = await make_course(tenant, methodologist, title="L's Course")

        r = await client.get(
            f"/api/v1/courses/{course.id}/enrollments",
            headers=auth_headers(methodologist),
        )

        # 200 + empty list is acceptable. Anything other than 403/401/200 is wrong.
        assert r.status_code == 200, (
            f"Methodologist must be able to list enrollments. Got {r.status_code}: {r.text}"
        )

    async def test_student_cannot_list_enrollments(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        """Regression: list was open to all auth'd users before this fix.
        Student must NOT see the full enrollment roster of a course."""
        tenant = await make_tenant(name="Tenant LS")
        student = await make_user(tenant, role="student")
        course = await make_course(tenant, student, title="LS's Course")

        r = await client.get(
            f"/api/v1/courses/{course.id}/enrollments",
            headers=auth_headers(student),
        )

        assert r.status_code == 403, (
            f"Student must NOT list enrollments. Got {r.status_code}: {r.text}"
        )

    async def test_student_cannot_unenroll(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        """Regression: DELETE was open to all auth'd users before this fix.
        Student must NOT be able to unenroll anyone."""
        from uuid import uuid4

        tenant = await make_tenant(name="Tenant UD")
        student = await make_user(tenant, role="student")
        course = await make_course(tenant, student, title="UD's Course")

        # Random enrollment_id; backend should reject on role before reaching service
        r = await client.delete(
            f"/api/v1/courses/enrollments/{uuid4()}",
            headers=auth_headers(student),
        )

        assert r.status_code == 403, (
            f"Student must NOT unenroll. Got {r.status_code}: {r.text}"
        )

    async def test_admin_cannot_export_enrollments_csv(
        self, client, make_tenant, make_user, auth_headers
    ):
        tenant = await make_tenant(name="Tenant EA")
        admin = await make_user(tenant, role="admin")

        r = await client.get(
            "/api/v1/admin/export/enrollments",
            headers=auth_headers(admin),
        )

        assert r.status_code == 403, (
            f"Tenant admin must NOT export enrollments CSV. Got {r.status_code}: {r.text}"
        )

    async def test_methodologist_can_export_enrollments_csv(
        self, client, make_tenant, make_user, auth_headers
    ):
        tenant = await make_tenant(name="Tenant E")
        methodologist = await make_user(tenant, role="methodologist")

        r = await client.get(
            "/api/v1/admin/export/enrollments",
            headers=auth_headers(methodologist),
        )

        assert r.status_code == 200, (
            f"Methodologist must be able to export enrollments CSV. "
            f"Got {r.status_code}: {r.text}"
        )
        assert "text/csv" in r.headers.get("content-type", "")

    async def test_student_cannot_export_enrollments_csv(
        self, client, make_tenant, make_user, auth_headers
    ):
        tenant = await make_tenant(name="Tenant ES")
        student = await make_user(tenant, role="student")

        r = await client.get(
            "/api/v1/admin/export/enrollments",
            headers=auth_headers(student),
        )

        assert r.status_code == 403, (
            f"Student must NOT export enrollments CSV. "
            f"Got {r.status_code}: {r.text}"
        )
