"""Exercise registered FastAPI dependencies, not just direct handler functions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.modules.knowledge_checks.router import router


@pytest.mark.parametrize("role,path", [
    ("admin", "/knowledge-checks/"),
    ("student", "/knowledge-checks/"),
    ("methodologist", "/knowledge-checks/my"),
    ("admin", "/knowledge-checks/my"),
])
def test_wrong_active_role_rejected_before_query(role, path):
    db = AsyncMock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role, id=uuid4(), tenant_id=uuid4())
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get(path).status_code == 403
    db.scalar.assert_not_awaited()
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()


def test_course_personal_link_cannot_open_independent_assessments():
    db = AsyncMock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        role="student", id=uuid4(), tenant_id=uuid4(), assignment_access_enrollment_id=uuid4(),
    )
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/knowledge-checks/my").status_code == 403
        assert client.post(f"/knowledge-checks/assignments/{uuid4()}/start").status_code == 403
    db.scalar.assert_not_awaited()
    db.scalars.assert_not_awaited()


def test_platform_without_tenant_cannot_create_check():
    db = AsyncMock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role="superadmin", id=uuid4(), tenant_id=None)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/knowledge-checks/").status_code == 403
    db.scalars.assert_not_awaited()
