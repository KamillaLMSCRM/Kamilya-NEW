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
from app.modules.courses import router as courses_router
from app.modules.courses.router import router
from app.modules.courses.source_uncertainty import (
    SOURCE_UNCERTAINTY_KEY,
    compute_course_content_snapshot_hash,
    get_active_source_defects,
)


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
    modules: list | None = None,
):
    if modules is None:
        m1 = SimpleNamespace(
            id=uuid4(),
            course_id=course_id,
            tenant_id=tenant_id,
            title="Основной регламентный модуль",
            description="Описание модуля",
            order_index=0,
            lessons=[],
        )
        l1 = SimpleNamespace(
            id=uuid4(),
            module_id=m1.id,
            tenant_id=tenant_id,
            title="Урок регламента безопасности",
            description="Описание урока",
            content_type="text",
            content="Содержание регламентного урока для проверки целостности хэша снимка.",
            duration_seconds=600,
            order_index=0,
            source_document_ids=[],
            source_references=[],
            source_validation_status="needs_review",
            blocks=[],
        )
        m1.lessons = [l1]
        modules = [m1]

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
        modules=modules,
        reviewer=None,
    )
    return course


def _build_test_app(
    course: SimpleNamespace | None,
    user: SimpleNamespace,
    audit_recorder: list[dict],
    monkeypatch: pytest.MonkeyPatch,
):
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

    # Clean monkeypatch isolated to test execution lifecycle
    monkeypatch.setattr(courses_router, "log_action", mock_log_action)

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

            def get_scalars_all():
                if not matched:
                    return []
                if "FROM MODULES" in statement_str:
                    return list(getattr(matched, "modules", []))
                if "FROM LESSONS" in statement_str:
                    return [les for m in getattr(matched, "modules", []) for les in getattr(m, "lessons", [])]
                if "FROM CONTENT_BLOCKS" in statement_str:
                    return [blk for m in getattr(matched, "modules", []) for les in getattr(m, "lessons", []) for blk in getattr(les, "blocks", [])]
                return []

            return SimpleNamespace(
                scalar_one_or_none=lambda: matched if ("COURSES" in statement_str or "FOR UPDATE" in statement_str) else None,
                scalars=lambda: SimpleNamespace(all=get_scalars_all),
            )

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

    return app, session


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_methodologist_success_records_audit(monkeypatch: pytest.MonkeyPatch):
    """Verify authorized methodologist call succeeds, locks row, clears hold, and writes audit record."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)

    actual_hash = await compute_course_content_snapshot_hash(session, course)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист проверил первоисточник и подтвердил соответствие регламенту",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-2026-qa1",
                "defect_resolutions": [],
            },
        )

    assert resp.status_code == 200, resp.text
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
    assert res["content_hash"] == actual_hash
    assert res["verified_revision"] == "rev-2026-qa1"
    # 5. Audit log was written
    assert len(audit_log) == 1
    assert audit_log[0]["action"] == "resolve_source_uncertainty"
    assert audit_log[0]["resource_id"] == str(course_id)
    assert audit_log[0]["user_id"] == user.id
    assert audit_log[0]["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_superadmin_success(monkeypatch: pytest.MonkeyPatch):
    """Verify superadmin role is also authorized to resolve source hold."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="superadmin", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Суперадминистратор утвердил снятие блокировки по запросу службы безопасности",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-superadmin-sec-check",
            },
        )

    assert resp.status_code == 200, resp.text
    assert len(audit_log) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden_role", ["admin", "student"])
async def test_resolve_source_uncertainty_forbidden_roles(forbidden_role: str, monkeypatch: pytest.MonkeyPatch):
    """Verify unauthorized roles (admin, student) receive HTTP 403 Forbidden."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role=forbidden_role, tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Попытка несанкционированного снятия блокировки",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-forbidden-test",
            },
        )

    assert resp.status_code == 403
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_tenant_isolation(monkeypatch: pytest.MonkeyPatch):
    """Verify tenant isolation: course belonging to a different tenant is not found (404)."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_a)
    audit_log: list[dict] = []

    # Course exists in tenant_b, query for tenant_a will return None due to tenant isolation
    course_in_tenant_b = _make_course(course_id, tenant_b)
    app, session = _build_test_app(course_in_tenant_b, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course_in_tenant_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Попытка межтенантного доступа к курсу",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-tenant-b",
            },
        )

    assert resp.status_code == 404
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_short_or_empty_reason(monkeypatch: pytest.MonkeyPatch):
    """Verify reason < 10 characters is rejected with 422 Unprocessable Entity."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "коротко",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-valid-test",
            },
        )

    assert resp.status_code == 422
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_missing_hash_or_revision(monkeypatch: pytest.MonkeyPatch):
    """Verify that omitting mandatory expected_content_hash or verified_revision yields 422."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    # Missing expected_content_hash
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp1 = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист выполнил проверку регламента",
                "verified_revision": "rev-valid-test",
            },
        )
    assert resp1.status_code == 422

    # Missing verified_revision
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp2 = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист выполнил проверку регламента",
                "expected_content_hash": actual_hash,
            },
        )
    assert resp2.status_code == 422
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_content_hash_mismatch(monkeypatch: pytest.MonkeyPatch):
    """Verify that expected_content_hash mismatch returns 409 Conflict."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, _ = _build_test_app(course, user, audit_log, monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист выполнил сверку регламента",
                "expected_content_hash": "stale-content-hash-000000000000000000000000000000",
                "verified_revision": "rev-any",
            },
        )

    assert resp.status_code == 409
    err = resp.json()["detail"]
    assert err["code"] == "source_uncertainty_resolution_rejected"
    assert "Несоответствие версии содержания" in err["message"]
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_revision_mismatch(monkeypatch: pytest.MonkeyPatch):
    """Verify that specifying a revision that conflicts with authoritative sources returns 409."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    source_analysis = {
        SOURCE_UNCERTAINTY_KEY: {"status": "review_required"},
        "source_revision": "rev-authoritative-v1",
    }
    course = _make_course(course_id, tenant_id, source_analysis=source_analysis)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист попытался привязать непроверенную ревизию",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-forged-999",
            },
        )

    assert resp.status_code == 409
    err = resp.json()["detail"]
    assert err["code"] == "source_uncertainty_resolution_rejected"
    assert "не совпадает с авторитетными ревизиями" in err["message"]
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_rejects_unacknowledged_defects_and_substring_matching(
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify strict exact defect_id matching: empty resolutions or arbitrary substrings fail with 409."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    violation_text = "Критическое противоречие: в источнике закрыть дверь, в уроке открыть"
    source_analysis = {
        SOURCE_UNCERTAINTY_KEY: {"status": "review_required"},
        "evidence_v3": {
            "violations": [violation_text],
        },
    }
    course = _make_course(course_id, tenant_id, source_analysis=source_analysis)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    active_defects = get_active_source_defects(course.source_analysis)
    assert len(active_defects) == 1
    expected_defect_id = active_defects[0]["defect_id"]
    assert expected_defect_id.startswith("defect-")

    # 1. Attempt without defect_resolutions -> 409
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp1 = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист попытался закрыть без списка решений дефектов",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-defects-test",
                "defect_resolutions": [],
            },
        )
    assert resp1.status_code == 409
    assert "обнаружены активные дефекты курса" in resp1.json()["detail"]["message"]

    # 2. Attempt with arbitrary substring defect_id (e.g. single character 'a' or substring 'defect-') -> 409
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp2 = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист передал поддельный неполный идентификатор дефекта",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-defects-test",
                "defect_resolutions": [
                    {
                        "defect_id": "defect-",
                        "action": "documented_exception",
                        "rationale": "Достаточно длинное обоснование исключения для проверки подделки",
                    }
                ],
            },
        )
    assert resp2.status_code == 409
    assert "отсутствуют решения для идентификаторов" in resp2.json()["detail"]["message"]

    # 3. Attempt with exact defect_id but rationale too short -> 422 (schema min_length=10)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp3 = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист передал слишком короткое обоснование",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-defects-test",
                "defect_resolutions": [
                    {
                        "defect_id": expected_defect_id,
                        "action": "documented_exception",
                        "rationale": "коротко",
                    }
                ],
            },
        )
    assert resp3.status_code == 422

    # 4. Now call with exact matching defect_id, valid action, and valid rationale -> 200 OK
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp_ok = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист подтвердил формулировку как специальное регламентное исключение",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-defects-test",
                "defect_resolutions": [
                    {
                        "defect_id": expected_defect_id,
                        "action": "documented_exception",
                        "rationale": "Исключение согласовано главным инженером регламента безопасности.",
                    }
                ],
            },
        )
    assert resp_ok.status_code == 200
    res_data = course.source_analysis["source_uncertainty_resolution"]
    assert len(res_data["defect_resolutions"]) == 1
    assert res_data["defect_resolutions"][0]["defect_id"] == expected_defect_id


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_concurrent_edit_conflict(monkeypatch: pytest.MonkeyPatch):
    """Verify concurrency safety: modifying a lesson/content between review and submission alters the hash and causes 409."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    course = _make_course(course_id, tenant_id)
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)

    # 1. Methodologist reviews the course and captures snapshot hash H1
    h1 = await compute_course_content_snapshot_hash(session, course)

    # 2. Concurrently, another author modifies a lesson in the course (e.g. content or title)
    lesson = course.modules[0].lessons[0]
    lesson.content = "Конкурентное изменение содержания урока после завершения методической сверки!"

    # 3. Methodologist submits resolution using the stale hash H1
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист согласовал курс по ранее зафиксированному снимку H1",
                "expected_content_hash": h1,
                "verified_revision": "rev-v1",
                "defect_resolutions": [],
            },
        )

    # 4. Under with_for_update() lock, the server re-computes authoritative snapshot hash H2
    # and rejects the submission with 409 Conflict due to hash mismatch.
    assert resp.status_code == 409
    err = resp.json()["detail"]
    assert err["code"] == "source_uncertainty_resolution_rejected"
    assert "Несоответствие версии содержания курса" in err["message"]
    assert "Курс был изменен после проверки" in err["message"]
    assert len(audit_log) == 0


@pytest.mark.asyncio
async def test_resolve_source_uncertainty_preserves_independent_publication_block(monkeypatch: pytest.MonkeyPatch):
    """Verify that resolving source uncertainty DOES NOT clear course review_status or allow publication."""
    tenant_id = uuid4()
    course_id = uuid4()
    user = _make_user(role="methodologist", tenant_id=tenant_id)
    # Course with review_status="pending"
    course = _make_course(course_id, tenant_id, review_status="pending", status="draft")
    audit_log: list[dict] = []

    app, session = _build_test_app(course, user, audit_log, monkeypatch)
    actual_hash = await compute_course_content_snapshot_hash(session, course)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Step 1: Resolve source uncertainty
        resp = await ac.post(
            f"/courses/{course_id}/resolve-source-uncertainty",
            json={
                "reason": "Методист подтвердил соответствие регламента",
                "expected_content_hash": actual_hash,
                "verified_revision": "rev-independent-block",
                "defect_resolutions": [],
            },
        )
        assert resp.status_code == 200

        # Step 2: Course review_status must STILL be pending
        assert course.review_status == "pending"

        # Step 3: Attempting to publish without methodologist review approval still fails with 409
        pub_resp = await ac.post(f"/courses/{course_id}/publish")
        assert pub_resp.status_code == 409
        assert pub_resp.json()["detail"]["code"] == "course_review_required"
