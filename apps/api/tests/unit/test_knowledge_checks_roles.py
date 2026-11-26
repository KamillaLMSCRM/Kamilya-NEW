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
from app.modules.knowledge_checks.service import digest
from app.modules.training_responsibility.scope import ReportingScope, ReportingScopeMode


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


@pytest.mark.parametrize("suffix", ["assignments", "attempts/" + str(uuid4())])
def test_employee_review_refuses_another_reporting_audience(monkeypatch, suffix):
    db = AsyncMock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        role="methodologist", id=uuid4(), tenant_id=uuid4(),
    )
    app.dependency_overrides[get_db] = lambda: db
    resolve = AsyncMock(return_value=ReportingScope(ReportingScopeMode.RESTRICTED, frozenset({uuid4()})))
    monkeypatch.setattr("app.modules.knowledge_checks.router.resolve_reporting_scope", resolve)
    with TestClient(app) as client:
        assert client.get(f"/knowledge-checks/employees/{uuid4()}/{suffix}").status_code == 404
    resolve.assert_awaited_once()
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


@pytest.mark.parametrize("corrupt_field", [None, "snapshot_sha256", "submission_sha256"])
def test_employee_attempt_verifies_saved_evidence(monkeypatch, corrupt_field):
    db = AsyncMock()
    app = FastAPI()
    app.include_router(router)
    employee_id, tenant_id = uuid4(), uuid4()
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        role="methodologist", id=uuid4(), tenant_id=tenant_id,
    )
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(
        "app.modules.knowledge_checks.router.resolve_reporting_scope",
        AsyncMock(return_value=ReportingScope(ReportingScopeMode.RESTRICTED, frozenset({employee_id}))),
    )
    snapshot = {"questions": [{"id": str(uuid4()), "choices": [{"text": "Saved answer", "is_correct": True}]}]}
    answers = []
    attempt = SimpleNamespace(
        id=uuid4(), assignment_id=uuid4(), number=1, status="expired", started_at=None,
        deadline_at=None, completed_at=None, score_percent=0, passed=False, earned_points=0,
        total_points=1, answers=answers, snapshot=snapshot, snapshot_sha256=digest(snapshot),
        submission_sha256=digest(answers),
    )
    if corrupt_field:
        setattr(attempt, corrupt_field, "0" * 64)
    db.scalar.side_effect = [employee_id, attempt]
    with TestClient(app) as client:
        response = client.get(f"/knowledge-checks/employees/{employee_id}/attempts/{attempt.id}")
    if corrupt_field:
        assert response.status_code == 409
        assert "Saved answer" not in response.text
    else:
        assert response.status_code == 200
        assert response.json()["snapshot"] == snapshot
