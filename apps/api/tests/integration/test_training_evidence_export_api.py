"""Integration coverage for server-built training-evidence downloads."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from pypdf import PdfReader

from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.training_evidence.service import add_legal_hold, confirm_step_up, record_event

pytestmark = pytest.mark.asyncio


async def _make_complete_event(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    *,
    tenant_name: str = "Export tenant",
    procedure_type: str = "knowledge_check",
    with_confirmation: bool = True,
    answer_marker: str = "a",
):
    from app.models.enrollment import Enrollment
    from app.modules.quizzes.models import QuizAttempt

    tenant = await make_tenant(name=tenant_name)
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email=f"methodologist-{uuid4().hex[:8]}@evidence.example",
        first_name="Method",
        last_name="Ologist",
    )
    learner = await make_user(
        tenant,
        role="student",
        email=f"learner-{uuid4().hex[:8]}@evidence.example",
        first_name="Aliya",
        last_name="Akhmetova",
        personnel_number="EMP-007",
    )
    course = await make_course(tenant, methodologist, title="Internal microcredit rules")
    module = await make_module(course, title="Rules")
    lesson = await make_lesson(module, title="Knowledge check")
    quiz = await make_quiz(lesson, title="Microcredit quiz", pass_score=80)

    release_snapshot = {
        "schema_version": 1,
        "course": {"id": str(course.id), "title": course.title},
        "modules": [{"id": str(module.id), "lessons": [{"id": str(lesson.id)}]}],
    }
    release = ContentRelease(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot=release_snapshot,
        snapshot_sha256=canonical_json_sha256(release_snapshot),
        published_by=methodologist.id,
        published_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    course.current_release_id = release.id
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        content_release_id=release.id,
        status="enrolled",
        source="position",
        enrolled_at=datetime.now(UTC),
    )
    db_session.add(enrollment)
    await db_session.flush()

    attempt_id = uuid4()
    completed_at = datetime.now(UTC)
    graded_answers = [{"question_id": "q-1", "answer": answer_marker, "is_correct": True}]
    attempt_snapshot = {
        "schema_version": 1,
        "attempt": {
            "id": str(attempt_id),
            "tenant_id": str(tenant.id),
            "user_id": str(learner.id),
            "enrollment_id": str(enrollment.id),
            "content_release_id": str(release.id),
            "quiz_id": str(quiz.id),
        },
        "quiz": {"id": str(quiz.id), "title": quiz.title, "pass_score": quiz.pass_score},
        "graded_answers": graded_answers,
    }
    attempt = QuizAttempt(
        id=attempt_id,
        tenant_id=tenant.id,
        user_id=learner.id,
        quiz_id=quiz.id,
        enrollment_id=enrollment.id,
        content_release_id=release.id,
        score_percent=100,
        total_points=1,
        earned_points=1,
        passed=True,
        answers=graded_answers,
        evidence_snapshot=attempt_snapshot,
        evidence_sha256=canonical_json_sha256(attempt_snapshot),
        started_at=completed_at - timedelta(minutes=10),
        completed_at=completed_at,
        time_spent_seconds=600,
    )
    db_session.add(attempt)
    await db_session.flush()

    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner.id,
        procedure_type=procedure_type,
        enrollment_id=enrollment.id,
        content_release_id=release.id,
        payload_snapshot={
            "procedure": {
                "title": "Проверка знаний правил предоставления микрокредитов",
                "code": "MICRO-2025",
                "version": "1.0",
            }
        },
    )
    if with_confirmation:
        await confirm_step_up(
            db_session,
            tenant_id=tenant.id,
            event_id=event.id,
            user_id=learner.id,
            action_text="Подтверждаю результат проверки знаний, версия 1.0",
            object_version="content-release:v1",
            reauth_method="email_otp",
            ip_address="192.0.2.10",
            user_agent="evidence-test/1.0",
        )
    await db_session.flush()
    return tenant, methodologist, learner, event, release, enrollment


async def test_individual_export_builds_server_owned_zip_and_state(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    auth_headers,
):
    tenant, methodologist, learner, event, _, _ = await _make_complete_event(
        db_session, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz
    )
    await add_legal_hold(
        db_session,
        tenant_id=tenant.id,
        event_id=event.id,
        actor_user_id=methodologist.id,
        action="placed",
        reason="Проверка комплаенса",
    )
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="kamilya-')
    assert all(ord(char) < 128 for char in disposition)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["employee"]["id"] == str(learner.id)
    assert manifest["course"]["release_id"]
    assert manifest["attempts"][0]["answers"]
    assert manifest["state"]["legal_hold_active"] is True
    assert manifest["confirmation"]["method"] == "otp"

    repeated = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(methodologist),
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.content == response.content

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        pdf_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(archive.read("individual-act.pdf"))).pages
        )
    assert "Состояние доказательства" in pdf_text
    assert "Юридическое удержание: Активно" in pdf_text


async def test_pdf_format_is_streamed_without_public_mode(client, complete_event, auth_headers):
    _, methodologist, _, event, _, _ = complete_event
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export?format=pdf",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
    assert "public" not in response.headers["content-disposition"].lower()


async def test_learner_owned_pdf_hides_answers_and_audit_only_data(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    auth_headers,
):
    tenant, methodologist, learner, event, _, _ = await _make_complete_event(
        db_session,
        make_tenant,
        make_user,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
        with_confirmation=False,
        answer_marker="SECRET-CORRECT-ANSWER-MUST-NOT-LEAK",
    )

    response = await client.get(
        f"/api/v1/training-evidence/events/mine/{event.id}/export",
        headers=auth_headers(learner),
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages)
    assert "SECRET-CORRECT-ANSWER-MUST-NOT-LEAK" not in pdf_text
    assert "Ответы" not in pdf_text
    assert "Состояние доказательства" not in pdf_text
    assert "Хэш публикации SHA-256" not in pdf_text
    assert "Подтверждение" not in pdf_text
    assert methodologist.email not in pdf_text


async def test_learner_owned_pdf_returns_indistinguishable_404_for_foreign_event(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    auth_headers,
):
    tenant, _, learner, own_event, _, _ = await _make_complete_event(
        db_session, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz
    )
    _, _, other_learner, foreign_event, _, _ = await _make_complete_event(
        db_session,
        make_tenant,
        make_user,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
        tenant_name="Other learner event tenant",
    )
    assert tenant.id != other_learner.tenant_id
    foreign = await client.get(
        f"/api/v1/training-evidence/events/mine/{foreign_event.id}/export",
        headers=auth_headers(learner),
    )
    missing = await client.get(
        f"/api/v1/training-evidence/events/mine/{uuid4()}/export",
        headers=auth_headers(learner),
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert own_event.id != foreign_event.id


async def test_methodologist_uploads_signed_copy_and_cross_tenant_cannot_read_it(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    auth_headers,
    monkeypatch,
):
    from app.modules.training_evidence import signed_scan_service

    tenant, methodologist, _, event, _, _ = await _make_complete_event(
        db_session,
        make_tenant,
        make_user,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
        with_confirmation=False,
    )

    class StorageStub:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def put_bytes(self, key, content, content_type):
            assert content_type == "application/pdf"
            self.objects[key] = content
            return key

        def delete_bytes(self, key):
            self.objects.pop(key, None)
            return True

    storage = StorageStub()
    monkeypatch.setattr(signed_scan_service, "get_storage", lambda: storage)

    initial = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/signed-scans",
        headers=auth_headers(methodologist),
    )
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "event_id": str(event.id),
        "status": "awaiting_signed_copy",
        "scans": [],
    }

    uploaded = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/signed-scans",
        headers=auth_headers(methodologist),
        files={"file": ("signed-result.pdf", b"%PDF-1.7\nhand-signed", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["event_id"] == str(event.id)
    assert body["status"] == "received"
    assert body["original_filename"] == "signed-result.pdf"
    assert "storage_key" not in body
    assert list(storage.objects.values()) == [b"%PDF-1.7\nhand-signed"]

    ledger = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/signed-scans",
        headers=auth_headers(methodologist),
    )
    assert ledger.status_code == 200, ledger.text
    assert ledger.json()["status"] == "received"
    assert len(ledger.json()["scans"]) == 1

    other_tenant = await make_tenant(name="Signed scan outsider")
    outsider = await make_user(other_tenant, role="methodologist")
    forbidden = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/signed-scans",
        headers=auth_headers(outsider),
    )
    assert forbidden.status_code == 404
    assert tenant.id != other_tenant.id


async def test_missing_mandatory_evidence_returns_409(client, db_session, make_tenant, make_user, auth_headers):
    tenant = await make_tenant(name="Incomplete export")
    methodologist = await make_user(tenant, role="methodologist", email="incomplete-method@evidence.example")
    learner = await make_user(tenant, role="student", email="incomplete-learner@evidence.example")
    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner.id,
        procedure_type="knowledge_check",
        payload_snapshot={"procedure": {"title": "Incomplete"}},
    )
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 409
    assert response.json()["details"]["code"] == "evidence_incomplete"
    assert "enrollment" in response.json()["details"]["missing"]


async def test_cross_tenant_admin_and_student_are_rejected(
    client,
    complete_event,
    make_tenant,
    make_user,
    auth_headers,
):
    tenant, methodologist, learner, event, _, _ = complete_event
    other_tenant = await make_tenant(name="Other export tenant")
    other_methodologist = await make_user(other_tenant, role="methodologist", email="other-method@evidence.example")
    admin = await make_user(tenant, role="admin", email="export-admin@evidence.example")

    cross_tenant = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(other_methodologist),
    )
    assert cross_tenant.status_code == 404
    assert (
        await client.get(
            f"/api/v1/training-evidence/events/{event.id}/export",
            headers=auth_headers(admin),
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/training-evidence/events/{event.id}/export",
            headers=auth_headers(learner),
        )
    ).status_code == 403
    assert methodologist.role == "methodologist"


async def test_group_export_rejects_duplicate_and_oversized_requests(client, complete_event, auth_headers):
    _, methodologist, _, event, _, _ = complete_event
    duplicate = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": [str(event.id), str(event.id)]},
    )
    assert duplicate.status_code == 422
    oversized = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": [str(uuid4()) for _ in range(201)]},
    )
    assert oversized.status_code == 422


async def test_group_export_rejects_malformed_event_id(client, complete_event, auth_headers):
    _, methodologist, _, _, _, _ = complete_event
    response = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": ["not-a-uuid"]},
    )
    assert response.status_code == 422


async def test_group_export_cannot_claim_decision_via_generic_correction(client, complete_event, auth_headers):
    tenant, methodologist, learner, event, _, _ = complete_event
    correction = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/corrections",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(learner.id),
            "procedure_type": "knowledge_check",
            "payload_snapshot": {"decision": {"outcome": "admitted"}},
            "reason": "Attempt to manufacture an admission decision",
        },
    )
    assert correction.status_code == 422, correction.text
    assert correction.json()["details"]["code"] == "system_evidence_workflow_required"

    response = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": [str(event.id)]},
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert "group-protocol.pdf" in archive.namelist()
    assert manifest.get("decision") is None
    assert all("decision" not in record for record in manifest["records"])


@pytest_asyncio.fixture
async def complete_event(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    return await _make_complete_event(
        db_session,
        make_tenant,
        make_user,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
    )
