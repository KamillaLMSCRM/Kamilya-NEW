"""Integrated native pilot flow from persisted AI draft to training evidence.

The external LLM and embedding providers are deliberately outside this test.
Their contract is covered by pipeline/failover tests and the controlled
production smoke. This test owns the transactional product boundary after an
AI draft has been persisted: human review, release, assignment, learning,
assessment, certificate issuance, and the training log.
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_ai_draft_reaches_certificate_and_training_log_for_selected_group(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    make_document,
):
    from app.modules.quizzes.models import Question, QuizChoice

    tenant = await make_tenant(name="Pilot Tenant", slug="pilot-native-e2e")
    admin = await make_user(
        tenant,
        role="admin",
        email="admin@pilot.example",
    )
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@pilot.example",
    )
    learners = [
        await make_user(
            tenant,
            role="student",
            email=f"learner-{index}@pilot.example",
            first_name=f"Learner {index}",
        )
        for index in range(1, 4)
    ]
    document = await make_document(
        tenant,
        methodologist,
        name="approved-instruction.md",
        embedding_status="success",
    )
    course = await make_course(
        tenant,
        methodologist,
        title="AI draft based on approved instruction",
        status="draft",
    )
    course.ai_generated = True
    course.review_status = "pending"
    course.source_instruction_id = document.id

    module = await make_module(course, title="Required procedure")
    lesson = await make_lesson(
        module,
        title="Safe sequence",
        content="Follow the approved sequence and stop when a risk is found.",
    )
    quiz = await make_quiz(lesson, title="Knowledge check", pass_score=80)
    question = Question(
        quiz_id=quiz.id,
        text="What must an employee do after detecting a risk?",
        type="MCQ",
        points=1,
        order_index=0,
    )
    db_session.add(question)
    await db_session.flush()
    correct_choice = QuizChoice(
        question_id=question.id,
        text="Stop and report the risk",
        is_correct=True,
        order_index=0,
    )
    wrong_choice = QuizChoice(
        question_id=question.id,
        text="Continue without reporting",
        is_correct=False,
        order_index=1,
    )
    db_session.add_all([correct_choice, wrong_choice])
    await db_session.flush()

    methodologist_headers = auth_headers(methodologist)
    admin_headers = auth_headers(admin)

    certificate_settings = {
        "organization_name": "Pilot Tenant Learning Center",
        "signer_name": "Pilot Director",
        "signer_title": "Director",
        "validity_months": 12,
        "footer_note": "Internal training record",
        "verification_base_url": "https://example.invalid",
        "show_verification_url": True,
    }
    settings_update = await client.put(
        "/api/v1/certificates/settings",
        headers=admin_headers,
        json=certificate_settings,
    )
    assert settings_update.status_code == 200, settings_update.text
    assert (
        settings_update.json()["verification_base_url"]
        == "https://app.kml.kz/verify/certificate"
    )
    preview = await client.post(
        "/api/v1/certificates/settings/preview",
        headers=admin_headers,
        json={
            "settings": certificate_settings,
            "sample_user_name": "Preview Learner",
            "sample_course_title": "Preview Course",
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("application/pdf")
    assert preview.content.startswith(b"%PDF")

    blocked_publish = await client.post(
        f"/api/v1/courses/{course.id}/publish",
        headers=methodologist_headers,
    )
    assert blocked_publish.status_code == 409, blocked_publish.text
    assert "must be approved" in blocked_publish.json()["message"]

    review = await client.post(
        f"/api/v1/courses/{course.id}/review",
        headers=methodologist_headers,
        json={"review_status": "approved", "comment": "Checked against source"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["review_status"] == "approved"
    assert review.json()["reviewed_by"] == str(methodologist.id)

    publish = await client.post(
        f"/api/v1/courses/{course.id}/publish",
        headers=methodologist_headers,
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["status"] == "published"

    assignment = await client.post(
        f"/api/v1/courses/{course.id}/enrollments",
        headers=methodologist_headers,
        json={"user_ids": [str(learner.id) for learner in learners]},
    )
    assert assignment.status_code == 201, assignment.text
    assigned_rows = assignment.json()
    assert len(assigned_rows) == 3
    assert {row["user_id"] for row in assigned_rows} == {
        str(learner.id) for learner in learners
    }

    learner_headers = auth_headers(learners[0])
    lesson_progress = await client.put(
        f"/api/v1/progress/lessons/{lesson.id}",
        headers=learner_headers,
        json={"completed": True, "completion_percent": 100},
    )
    assert lesson_progress.status_code == 200, lesson_progress.text
    assert lesson_progress.json()["completed"] is True

    quiz_result = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        headers=learner_headers,
        json={
            "answers": [
                {
                    "question_id": str(question.id),
                    "selected_choice_ids": [str(correct_choice.id)],
                }
            ],
            "time_spent_seconds": 15,
        },
    )
    assert quiz_result.status_code == 200, quiz_result.text
    assert quiz_result.json()["passed"] is True
    assert quiz_result.json()["attempt"]["score_percent"] == 100

    completion = await client.post(
        f"/api/v1/courses/{course.id}/complete",
        headers=learner_headers,
    )
    assert completion.status_code == 200, completion.text
    completion_body = completion.json()
    assert completion_body["status"] == "completed"
    assert completion_body["certificate_number"]

    learner_certificates = await client.get(
        "/api/v1/certificates",
        headers=learner_headers,
    )
    assert learner_certificates.status_code == 200, learner_certificates.text
    assert len(learner_certificates.json()) == 1
    certificate_id = learner_certificates.json()[0]["id"]
    assert learner_certificates.json()[0]["status"] == "active"

    same_tenant_other_learner = await client.get(
        f"/api/v1/certificates/{certificate_id}",
        headers=auth_headers(learners[1]),
    )
    assert same_tenant_other_learner.status_code == 404
    methodologist_certificate = await client.get(
        f"/api/v1/certificates/{certificate_id}",
        headers=methodologist_headers,
    )
    assert methodologist_certificate.status_code == 200

    verification = await client.get(
        "/api/v1/certificates/verify/"
        + completion_body["certificate_number"],
    )
    assert verification.status_code == 200, verification.text
    assert verification.json()["valid"] is True
    assert verification.json()["status"] == "active"
    assert verification.json()["course_title"] == course.title
    assert (
        verification.json()["organization_name"]
        == "Pilot Tenant Learning Center"
    )

    training_log = await client.get(
        f"/api/v1/admin/training-log?course_id={course.id}",
        headers=methodologist_headers,
    )
    assert training_log.status_code == 200, training_log.text
    log_body = training_log.json()
    assert log_body["total"] == 3
    rows_by_user = {row["user_id"]: row for row in log_body["items"]}
    completed_row = rows_by_user[str(learners[0].id)]
    assert completed_row["computed_status"] == "completed"
    assert completed_row["progress_percent"] == 100
    assert completed_row["best_score"] == 100
    assert completed_row["quiz_attempts_count"] == 1
    assert completed_row["certificate_number"] == completion_body["certificate_number"]

    for learner in learners[1:]:
        assigned_row = rows_by_user[str(learner.id)]
        assert assigned_row["computed_status"] == "assigned"
        assert assigned_row["progress_percent"] == 0
        assert assigned_row["certificate_number"] is None

        certificates = await client.get(
            "/api/v1/certificates",
            headers=auth_headers(learner),
        )
        assert certificates.status_code == 200, certificates.text
        assert certificates.json() == []

    revocation = await client.post(
        f"/api/v1/certificates/{certificate_id}/revoke",
        headers=methodologist_headers,
        json={"reason": "Issued during integration verification"},
    )
    assert revocation.status_code == 200, revocation.text
    assert revocation.json()["status"] == "revoked"
    assert revocation.json()["valid"] is False

    revoked_verification = await client.get(
        "/api/v1/certificates/verify/"
        + completion_body["certificate_number"],
    )
    assert revoked_verification.status_code == 200
    assert revoked_verification.json()["status"] == "revoked"
    assert revoked_verification.json()["valid"] is False
