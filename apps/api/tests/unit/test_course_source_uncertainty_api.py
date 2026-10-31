"""Comprehensive HTTP/ASGI and audit integration tests for course source uncertainty resolution endpoint."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_active_user, get_current_user
from app.core.db import get_db
from app.modules.courses.router import router
from app.modules.courses.source_uncertainty import SOURCE_UNCERTAINTY_KEY


def _make_user(role: str = "methodologist", tenant_id: UUID | None = None, user_id: UUID | None = None):
    return SimpleNamespace(
        id=user_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        role=role,
        is_active=True,
    )


def _make_course(
    course_id: UUID,
    tenant_id: UUID,
    source_analysis: dict | None = None,
    review_status: str = "pending",
    status: str = "draft",
    ai_generated: bool = True,
):
    course = SimpleNamespace(
        id=course_id,
        tenant_id=tenant_id,
        title="Тестовый регламентный курс",
        description="Описание курса",
        status=status,
        delivery_type="native",
        thumbnail_url=None,
        created_by=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        published_at=None,
        current_release_id=None,
        ai_generated=ai_generated,
        source_instruction_id=None,
        source_instruction_version_at=None,
        source_document_ids=[],
        source_strategy="single_topic",
        source_combination_goal=None,
        source_analysis=source_analysis or {SOURCE_UNCERTAINTY_KEY: {"status": "review_required"}},
        review_status=review_status,
        reviewed_by=None,
        reviewed_at=None,
        review_comment=None,
        modules=[],
        reviewer=None,
    )
    return course


def _build_test_app(course: SimpleNamespace | None, user: SimpleNamespace, audit_recorder: list[dict]):
    app = FastAPI()
    app.include_router(router)

    async def override_user():
        return user

    async def mock_log_action(db, tenant_id, action, resource_type, resource_id=None, user_id=None, details=None, ip_address=None, user_agent=None):
        audit_recorder.append({
            "tenant_id": tenant_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "user_id": user_id,
            "details": details,
        })

    class MockAsyncSession:
        def __init__(self):
            self.committed = False
            self.flushed = False
            self.refreshed = False
            self.query_had_lock = False

        async def execute(self, statement):
            statement_str = str(statement).upper()
            if "FOR UPDATE" in statement_str:
                self.query_had_lock = True
            matched = course if (course and course.tenant_id == user.tenant_id) else None
            return SimpleNamespace(scalar_one_or_none=lambda: matched)

        async def scalar(self, statement):
            statement_str = str(statement).upper()
            if "COURSE_APPROVAL_POLICIES" in statement_str:
                return None
            if "WORKFLOW_IDEMPOTENCY_KEYS" in statement_str:
                return None
            if "QUIZZES" in statement_str:
                return None
            if "COURSES" in statement_str:
                return course if (course and course.tenant_id == user.tenant_id) else None
            return None

        async def flush(self):
            self.flushed = True

        async def refresh(self, instance):
            self.refreshed = True

        async def commit(self):
            self.committed = True

    session = MockAsyncSession()

    async def override_db():
        yield session

    app.dependency_overrides[get_current_active_user] = override_user
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db

    # Monkeypatch log_action in courses router
    import app.modules.courses.router as courses_router
    courses_router.log_action = mock_log_action

    return app, session


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_methodologist_success_records_audit():
    """Verify authorized methodologist call succeeds, locks row, clears hold, and writes audit record."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "Методист проверил первоисточник и подтвердил соответствие регламенту"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(course_id)

    # Invariants:
    # 1. DB lock was acquired
    assert session.query_had_lock is True
    # 2. Commit was executed
    assert session.committed is True
    # 3. Source uncertainty hold marker removed from source_analysis
    assert SOURCE_UNCERTAINTY_KEY not in course.source_analysis
    # 4. Resolution metadata recorded
    res = course.source_analysis["source_uncertainty_resolution"]
    assert res["status"] == "resolved"
    assert res["resolved_by"] == str(user.id)
    assert "Методист проверил" in res["reason"]
    assert "content_hash" in res
    # 5. Audit log was written
    assert len(audit_log) == 1
    assert audit_log[0]["action"] == "resolve_source_uncertainty"
    assert audit_log[0]["resource_id"] == str(course_id)
    assert audit_log[0]["user_id"] == user.id
    assert audit_log[0]["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_superadmin_success():
    """Verify superadmin role is also authorized to resolve source hold."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="superadmin", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "Суперадминистратор утвердил снятие блокировки по запросу службы безопасности"},
        )

    assert resp.status_code == 200
    assert len(audit_log) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden_role", ["admin", "student"])
async def test_resolve_source_uncertainty_forbidden_roles(forbidden_role):
    """Verify unauthorized roles (admin, student) receive HTTP 403 Forbidden."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role=forbidden_role, tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "Попытка несанкционированного снятия блокировки"},
        )

    assert resp.status_code == 403
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_tenant_isolation():
    """Verify tenant isolation: course belonging to a different tenant is not found (404)."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_a)
    audit_log: list[dict] = []

    # Course exists in tenant_b, query for tenant_a will return None due to tenant isolation
    course_in_tenant_b = _make_course(course_id, tenant_b)
    app, _ = _build_test_app(course_in_tenant_b, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "Попытка межтенантного доступа к курсу"},
        )

    assert resp.status_code == 404
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_short_or_empty_reason():
    """Verify reason < 10 characters is rejected with 422 Unprocessable Entity."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "коротко"},
        )

    assert resp.status_code == 422
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_content_hash_mismatch():
    """Verify that expected_content_hash mismatch returns 409 Conflict."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист выполнил сверку регламента",
                "expected_content_hash": "stale-content-hash-000000000000000000000000000000",
            },
        )

    assert resp.status_code == 409
    err = resp.json()["detail"]
    assert err["code"] == "source_uncertainty_resolution_rejected"
    assert "Несоответствие версии содержания" in err["message"]
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_unacknowledged_defects():
    """Verify that resolving a course with active semantic violations without acknowledging them fails with 409."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    source_analysis = {
        SOURCE_UNCERTAINTY_KEY: {"status": "review_required"},
        "evidence_v3": {
            "violations": ["Критическое противоречие: в источнике закрыть дверь, в уроке открыть"],
        },
    }
    course = _make_course(course_id, tenant_id, source_analysis=source_analysis)
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log)

    # 1. Attempt without acknowledged_defects -> 409
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "Методист попытался закрыть без признания замечания"},
        )
    assert resp.status_code == 409
    assert "обнаружены неисправленные замечания" in resp.json()["detail"]["message"]

    # 2. Now call with acknowledged_defects matching the violation -> 200 OK
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp_ok = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист подтвердил формулировку как специальное исключение для регламента",
                "acknowledged_defects": ["Критическое противоречие: в источнике закрыть дверь, в уроке открыть"],
            },
        )
    assert resp_ok.status_code == 200
    res_data = course.source_analysis["source_uncertainty_resolution"]
    assert res_data["acknowledged_defects"] == ["Критическое противоречие: в источнике закрыть дверь, в уроке открыть"]


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_preserves_independent_publication_block():
    """Verify that resolving source uncertainty DOES NOT clear course review_status or allow publication."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    # Course with review_status="pending"
    course = _make_course(course_id, tenant_id, review_status="pending", status="draft")
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Step 1: Resolve source uncertainty
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={"reason": "Методист подтвердил соответствие регламента"},
        )
        assert resp.status_code == 200

        # Step 2: Course review_status must STILL be pending
        assert course.review_status == "pending"

        # Step 3: Attempting to publish without methodologist review approval still fails with 409
        pub_resp = await ac.post(f"/courses/{course_id}/publish")
        assert pub_resp.status_code == 409
        assert pub_resp.json()["detail"]["code"] == "course_review_required"
