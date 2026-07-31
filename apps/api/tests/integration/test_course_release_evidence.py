from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError


async def _curriculum(
    db_session,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    tenant,
    author,
):
    from app.modules.quizzes.models import Question, QuizChoice

    course = await make_course(
        tenant,
        author,
        title="Internal evidence course",
        status="draft",
    )
    module = await make_module(course, title="Evidence module")
    lesson = await make_lesson(module, title="Evidence lesson", content="Exact policy text")
    quiz = await make_quiz(lesson, title="Evidence quiz", pass_score=80)
    first = Question(
        quiz_id=quiz.id,
        text="First question?",
        type="MCQ",
        points=1,
        order_index=0,
    )
    second = Question(
        quiz_id=quiz.id,
        text="Second question?",
        type="MCQ",
        points=1,
        order_index=1,
    )
    db_session.add_all([first, second])
    await db_session.flush()
    choices = [
        QuizChoice(
            question_id=first.id,
            text="First correct",
            is_correct=True,
            order_index=0,
        ),
        QuizChoice(
            question_id=first.id,
            text="First wrong",
            is_correct=False,
            order_index=1,
        ),
        QuizChoice(
            question_id=second.id,
            text="Second correct",
            is_correct=True,
            order_index=0,
        ),
        QuizChoice(
            question_id=second.id,
            text="Second wrong",
            is_correct=False,
            order_index=1,
        ),
    ]
    db_session.add_all(choices)
    await db_session.flush()
    return course, quiz, (first, second), choices


@pytest.mark.asyncio
async def test_publish_binds_enrollment_and_attempt_to_immutable_release(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    from app.models.enrollment import Enrollment
    from app.modules.courses.release_models import ContentRelease
    from app.modules.courses.release_service import canonical_json_sha256
    from app.modules.quizzes.models import QuizAttempt

    tenant = await make_tenant(name="Evidence tenant")
    author = await make_user(
        tenant,
        role="methodologist",
        email="author@evidence.example",
    )
    learner = await make_user(
        tenant,
        role="student",
        email="learner@evidence.example",
    )
    course, quiz, questions, choices = await _curriculum(
        db_session,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
        tenant,
        author,
    )

    published = await client.post(
        f"/api/v1/courses/{course.id}/publish",
        headers=auth_headers(author),
    )
    assert published.status_code == 200, published.text
    release_id = published.json()["current_release_id"]
    assert release_id

    release = await db_session.scalar(
        select(ContentRelease).where(ContentRelease.id == release_id)
    )
    assert release is not None
    assert release.version == 1
    assert release.snapshot_sha256 == canonical_json_sha256(release.snapshot)
    assert release.snapshot["course"]["title"] == "Internal evidence course"
    assert release.snapshot["modules"][0]["lessons"][0]["quizzes"][0]["questions"]

    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        status="in_progress",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()
    await db_session.refresh(enrollment)
    assert str(enrollment.content_release_id) == release_id

    submitted = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        headers=auth_headers(learner),
        json={
            "answers": [
                {
                    "question_id": str(questions[0].id),
                    "selected_choice_ids": [str(choices[0].id)],
                },
                {
                    "question_id": str(questions[1].id),
                    "selected_choice_ids": [str(choices[2].id)],
                },
            ],
            "time_spent_seconds": 45,
        },
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["attempt"]["score_percent"] == 100
    assert body["attempt"]["content_release_id"] == release_id
    assert len(body["attempt"]["evidence_sha256"]) == 64

    attempt = await db_session.scalar(
        select(QuizAttempt).where(QuizAttempt.id == body["attempt"]["id"])
    )
    assert attempt is not None
    assert attempt.evidence_sha256 == canonical_json_sha256(attempt.evidence_snapshot)
    assert attempt.evidence_snapshot["attempt"]["content_release_sha256"] == (
        release.snapshot_sha256
    )
    assert len(attempt.evidence_snapshot["quiz"]["questions"]) == 2

    release_savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(
                update(ContentRelease)
                .where(ContentRelease.id == release.id)
                .values(snapshot_sha256="0" * 64)
            )
            await db_session.flush()
    finally:
        await release_savepoint.rollback()

    attempt_savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(
                update(QuizAttempt)
                .where(QuizAttempt.id == attempt.id)
                .values(score_percent=0)
            )
            await db_session.flush()
    finally:
        await attempt_savepoint.rollback()


@pytest.mark.asyncio
async def test_legacy_published_course_is_bound_to_release_before_assignment_and_quiz(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    """Published pre-release courses must not fail at the first real quiz."""
    from app.models.enrollment import Enrollment
    from app.modules.courses.release_models import ContentRelease

    tenant = await make_tenant(name="Legacy release tenant")
    author = await make_user(
        tenant,
        role="methodologist",
        email="author@legacy-release.example",
    )
    learner = await make_user(
        tenant,
        role="student",
        email="learner@legacy-release.example",
    )
    course, quiz, questions, choices = await _curriculum(
        db_session,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
        tenant,
        author,
    )
    course.status = "published"
    course.current_release_id = None
    await db_session.flush()

    assigned = await client.post(
        f"/api/v1/courses/{course.id}/enrollments",
        headers=auth_headers(author),
        json={"user_ids": [str(learner.id)]},
    )
    assert assigned.status_code == 201, assigned.text
    await db_session.refresh(course)
    assert course.current_release_id is not None

    release = await db_session.scalar(
        select(ContentRelease).where(ContentRelease.id == course.current_release_id)
    )
    enrollment = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.course_id == course.id,
            Enrollment.user_id == learner.id,
        )
    )
    assert release is not None
    assert enrollment is not None
    assert enrollment.content_release_id == release.id

    submitted = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        headers=auth_headers(learner),
        json={
            "answers": [
                {
                    "question_id": str(questions[0].id),
                    "selected_choice_ids": [str(choices[0].id)],
                },
                {
                    "question_id": str(questions[1].id),
                    "selected_choice_ids": [str(choices[2].id)],
                },
            ],
            "time_spent_seconds": 15,
        },
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["passed"] is True
    assert body["attempt"]["content_release_id"] == str(release.id)
    assert body["training_evidence_event_id"]


@pytest.mark.asyncio
async def test_quiz_submission_rejects_partial_and_cross_question_answers(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    from app.models.enrollment import Enrollment
    from app.modules.quizzes.models import QuizAttempt

    tenant = await make_tenant(name="Strict quiz tenant")
    author = await make_user(
        tenant,
        role="methodologist",
        email="author@strict-quiz.example",
    )
    learner = await make_user(
        tenant,
        role="student",
        email="learner@strict-quiz.example",
    )
    course, quiz, questions, choices = await _curriculum(
        db_session,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
        tenant,
        author,
    )
    published = await client.post(
        f"/api/v1/courses/{course.id}/publish",
        headers=auth_headers(author),
    )
    assert published.status_code == 200, published.text
    db_session.add(
        Enrollment(
            tenant_id=tenant.id,
            course_id=course.id,
            user_id=learner.id,
            status="in_progress",
            source="manual",
        )
    )
    await db_session.flush()

    partial = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        headers=auth_headers(learner),
        json={
            "answers": [
                {
                    "question_id": str(questions[0].id),
                    "selected_choice_ids": [str(choices[0].id)],
                }
            ]
        },
    )
    assert partial.status_code == 400
    assert "Submit every quiz question" in partial.json()["message"]

    cross_question = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        headers=auth_headers(learner),
        json={
            "answers": [
                {
                    "question_id": str(questions[0].id),
                    "selected_choice_ids": [str(choices[2].id)],
                },
                {
                    "question_id": str(questions[1].id),
                    "selected_choice_ids": [str(choices[2].id)],
                },
            ]
        },
    )
    assert cross_question.status_code == 400
    assert "does not belong" in cross_question.json()["message"]
    assert (
        await db_session.scalar(
            select(QuizAttempt.id).where(
                QuizAttempt.tenant_id == tenant.id,
                QuizAttempt.user_id == learner.id,
            )
        )
        is None
    )
