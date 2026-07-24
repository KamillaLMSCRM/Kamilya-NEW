"""Cross-tenant isolation tests.

Per AGENTS.md §Testing rules:
    "Cross-tenant test (MANDATORY для data-access endpoints)
     Tenant A создаёт ресурс → Tenant B пытается его прочитать → expect 404 (не 403).
     Тест ДОЛЖЕН быть в PR, иначе review rejection."

These tests cover the four primary data domains: courses, documents,
quizzes, enrollments. Each test follows the pattern:

    1. Create tenant_A with admin user_A
    2. Create tenant_B with admin user_B
    3. Create resource in tenant_A
    4. Attempt to read/mutate it as user_B
    5. Assert 404 (not 403, not 200)

Tests run inside a transactional rollback (see conftest.db_session) so
they don't pollute each other or the real DB.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


# ===========================================================================
# Courses
# ===========================================================================


class TestCoursesCrossTenant:
    """Tenant B must NOT be able to read, modify, or delete tenant A's courses."""

    async def test_get_course_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant_a = await make_tenant(name="Tenant A")
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a, title="A's Course")

        tenant_b = await make_tenant(name="Tenant B")
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/courses/{course.id}",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404, (
            f"Tenant B must not see tenant A's course. Got {r.status_code}: {r.text}"
        )

    async def test_patch_course_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.patch(
            f"/api/v1/courses/{course.id}",
            headers=auth_headers(user_b),
            json={"title": "Hacked"},
        )

        assert r.status_code == 404

    async def test_delete_course_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.delete(
            f"/api/v1/courses/{course.id}",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404

    async def test_list_courses_excludes_other_tenant(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        await make_course(tenant_a, user_a, title="A-Course-1")
        await make_course(tenant_a, user_a, title="A-Course-2")

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")
        b_course = await make_course(tenant_b, user_b, title="B-Course-1")

        r = await client.get(
            "/api/v1/courses",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 200
        body = r.json()
        titles = [c["title"] for c in body]
        assert "B-Course-1" in titles, "Tenant B must see its own course"
        assert "A-Course-1" not in titles, "Tenant B must NOT see tenant A's course"
        assert "A-Course-2" not in titles
        assert len(body) == 1

    async def test_preview_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/courses/{course.id}/preview",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404


# ===========================================================================
# Documents
# ===========================================================================


class TestDocumentsCrossTenant:
    """Tenant B must NOT see tenant A's documents."""

    async def test_get_document_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_document, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        doc = await make_document(tenant_a, user_a, name="a-secret.md")

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/documents/{doc.id}",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404

    async def test_delete_document_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_document, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        doc = await make_document(tenant_a, user_a)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.delete(
            f"/api/v1/documents/{doc.id}",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404

    async def test_list_documents_excludes_other_tenant(
        self, client, make_tenant, make_user, make_document, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        await make_document(tenant_a, user_a, name="a-1.md")
        await make_document(tenant_a, user_a, name="a-2.md")

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")
        await make_document(tenant_b, user_b, name="b-1.md")

        r = await client.get(
            "/api/v1/documents",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 200
        body = r.json()
        names = [d["filename"] for d in body]
        assert "b-1.md" in names
        assert "a-1.md" not in names
        assert "a-2.md" not in names


# ===========================================================================
# Quizzes
# ===========================================================================


class TestQuizzesCrossTenant:
    """Tenant B must NOT see tenant A's quizzes."""

    async def test_get_quiz_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)
        mod = await make_module(course)
        lesson = await make_lesson(mod)
        quiz = await make_quiz(lesson)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/quizzes/{quiz.id}",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404

    async def test_get_quiz_by_lesson_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)
        mod = await make_module(course)
        lesson = await make_lesson(mod)
        await make_quiz(lesson, title="A's Quiz")

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/quizzes/by-lesson/{lesson.id}",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404

    async def test_quiz_attempts_returns_404_for_other_tenant(
        self, client, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)
        mod = await make_module(course)
        lesson = await make_lesson(mod)
        quiz = await make_quiz(lesson)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/quizzes/{quiz.id}/attempts",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404


# ===========================================================================
# Enrollments
# ===========================================================================


class TestEnrollmentsCrossTenant:
    """Tenant B's methodologist must NOT see tenant A's enrollment lists."""

    async def test_list_enrollments_returns_404_for_other_tenant_course(
        self, client, make_tenant, make_user, make_course, auth_headers
    ):
        tenant_a = await make_tenant()
        user_a = await make_user(tenant_a, role="methodologist")
        course = await make_course(tenant_a, user_a)

        tenant_b = await make_tenant()
        user_b = await make_user(tenant_b, role="methodologist")

        r = await client.get(
            f"/api/v1/courses/{course.id}/enrollments",
            headers=auth_headers(user_b),
        )

        assert r.status_code == 404, (
            f"Cross-tenant course lookup must be hidden as 404. Got {r.status_code}: {r.text}"
        )


# ===========================================================================
# Unauthenticated access
# ===========================================================================


class TestUnauthenticatedAccess:
    """Endpoints must reject anonymous callers regardless of any payload."""

    async def test_get_course_without_token_returns_401(self, client):
        r = await client.get("/api/v1/courses")
        assert r.status_code == 401

    async def test_get_course_with_invalid_token_returns_401(self, client):
        r = await client.get(
            "/api/v1/courses",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code == 401


# ===========================================================================
# Cross-tenant smoke: superadmin sanity
# ===========================================================================
# A superadmin (tenant_id=None) is NOT a tenant user. They must NOT be able
# to read tenant data through tenant-scoped endpoints — they have separate
# /v1/admin/* endpoints for that purpose.


class TestSuperadminTenantIsolation:
    """Superadmin tokens must be rejected by tenant-scoped endpoints.

    The require_tenant_user() dependency should bounce superadmin (tenant_id=None)
    to a 403, so they must use dedicated /v1/admin/* routes.
    """

    async def test_superadmin_blocked_from_tenant_courses_list(
        self, client, make_superadmin, auth_headers
    ):
        superadmin = await make_superadmin()
        r = await client.get(
            "/api/v1/courses",
            headers=auth_headers(superadmin),
        )
        # 403 = forbidden (not 404 because superadmin identity is known to the app).
        assert r.status_code in (401, 403), (
            f"Superadmin must not access tenant courses endpoint. Got {r.status_code}"
        )
