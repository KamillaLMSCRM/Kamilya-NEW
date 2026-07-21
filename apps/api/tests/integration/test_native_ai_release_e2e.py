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

    verification = await client.get(
        "/api/v1/certificates/verify/"
        + completion_body["certificate_number"],
    )
    assert verification.status_code == 200, verification.text
    assert verification.json()["valid"] is True
    assert verification.json()["course_title"] == course.title

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
