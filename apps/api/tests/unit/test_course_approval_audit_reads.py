"""HTTP seam contracts; database-boundary fake, not a PostgreSQL/RLS proof."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.modules.course_approval.router import require_course_approval_enabled, router


class ReadOnlyDB:
    def __init__(self):
        self.statements = []
        self.catalog = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [])

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: self.catalog)


def audit_app(role="admin", tenant_id=None, *, without_tenant=False):
    db = ReadOnlyDB()
    user = SimpleNamespace(id=uuid4(), tenant_id=None if without_tenant else tenant_id or uuid4(), role=role, is_active=True, roles=["admin", "methodologist"])
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    async def principal():
        return user

    async def database():
        yield db

    app.dependency_overrides[get_current_active_user] = principal
    app.dependency_overrides[get_db] = database
    return app, db, user


@pytest.mark.asyncio
async def test_admin_can_read_approval_history_without_receiving_request_permission():
    app, db, user = audit_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/course-approval-requests")
    assert response.status_code == 200
    assert response.json() == []
    assert len(db.statements) == 1
    query = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "course_approval_requests.tenant_id" in query
    assert str(user.tenant_id).replace("-", "") in query.replace("-", "")


@pytest.mark.asyncio
async def test_selected_course_request_filter_joins_tenant_bound_revisions():
    app, db, user = audit_app("methodologist")
    course_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/course-approval-requests?course_id={course_id}")
    assert response.status_code == 200
    query = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN course_approval_revisions" in query
    assert "course_approval_revisions.course_id" in query
    assert str(course_id).replace("-", "") in query.replace("-", "")
    assert "course_approval_requests.tenant_id" in query
    assert "course_approval_revisions.tenant_id" in query
    assert str(user.tenant_id).replace("-", "") in query.replace("-", "")


@pytest.mark.asyncio
async def test_invalid_course_request_filter_is_rejected_before_query():
    app, db, _ = audit_app("methodologist")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/course-approval-requests?course_id=not-a-uuid")
    assert response.status_code == 422
    assert db.statements == []


@pytest.mark.asyncio
async def test_admin_catalog_returns_only_approval_configuration_metadata():
    app, db, user = audit_app()
    course_id = uuid4()
    db.catalog = [SimpleNamespace(id=course_id, title="Synthetic policy course", requires_approval=False)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/course-approval-courses?page=2&per_page=20")
    assert response.status_code == 200
    assert response.json() == [{"id": str(course_id), "title": "Synthetic policy course", "requires_approval": False}]
    statement = db.statements[0]
    assert list(statement.selected_columns.keys()) == ["id", "title", "requires_approval"]
    query = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "courses.tenant_id" in query
    assert str(user.tenant_id).replace("-", "") in query.replace("-", "")
    assert "course_approval_policies.tenant_id = courses.tenant_id" in query
    assert "LIMIT 20" in query and "OFFSET 20" in query


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["student", "superadmin", "org_admin", "teacher"])
@pytest.mark.parametrize("path", ["/v1/course-approval-courses", "/v1/course-approval-requests"])
async def test_audit_reads_use_active_role_not_assigned_role_union(role, path):
    app, db, _ = audit_app(role)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 403
    assert db.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/course-approval-courses", "/v1/course-approval-requests"])
async def test_audit_reads_require_tenant_and_preserve_methodologist_access(path):
    app, db, _ = audit_app("methodologist", without_tenant=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 403
    assert db.statements == []
    app, _, _ = audit_app("methodologist")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["courses/{id}/approval-revisions", "course-approval-revisions/{id}/requests", "course-approval-requests/{id}/cancel", "course-approval-requests/{id}/revoke", "course-approval-requests/{id}/resend"])
async def test_admin_audit_does_not_grant_requester_mutations(suffix):
    app, db, _ = audit_app()
    async def enabled():
        return None
    app.dependency_overrides[require_course_approval_enabled] = enabled
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/" + suffix.format(id=uuid4()), json={})
    assert response.status_code == 403
    assert db.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101", "page=not-a-number"])
async def test_metadata_catalog_bounds_are_validated_before_query(query):
    app, db, _ = audit_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/course-approval-courses?" + query)
    assert response.status_code == 422
    assert db.statements == []

