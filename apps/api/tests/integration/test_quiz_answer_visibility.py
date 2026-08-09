from __future__ import annotations

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected_correct"),
    [
        ("student", [False, False]),
        ("methodologist", [True, False]),
    ],
)
async def test_quiz_answers_are_hidden_from_learners(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    role,
    expected_correct,
):
    from app.modules.quizzes.models import Question, QuizChoice

    tenant = await make_tenant(name="Quiz visibility", slug=f"quiz-visibility-{role}")
    author = await make_user(
        tenant,
        role="methodologist",
        email=f"author-{role}@quiz-visibility.example",
    )
    viewer = (
        author
        if role == "methodologist"
        else await make_user(
            tenant,
            role="student",
            email="learner@quiz-visibility.example",
        )
    )
    course = await make_course(tenant, author, status="published")
    module = await make_module(course)
    lesson = await make_lesson(module)
    quiz = await make_quiz(lesson)
    question = Question(
        quiz_id=quiz.id,
        text="Which choice is correct?",
        type="MCQ",
        points=1,
        explanation="Only authors may read this explanation.",
        order_index=0,
    )
    db_session.add(question)
    await db_session.flush()
    db_session.add_all(
        [
            QuizChoice(
                question_id=question.id,
                text="Correct",
                is_correct=True,
                order_index=0,
            ),
            QuizChoice(
                question_id=question.id,
                text="Wrong",
                is_correct=False,
                order_index=1,
            ),
        ]
    )
    await db_session.flush()

    if role == "student":
        from app.models.enrollment import Enrollment

        db_session.add(
            Enrollment(
                tenant_id=tenant.id,
                course_id=course.id,
                user_id=viewer.id,
                status="in_progress",
                source="manual",
            )
        )
        await db_session.flush()

    for path in (
        f"/api/v1/quizzes/{quiz.id}",
        f"/api/v1/quizzes/by-lesson/{lesson.id}",
    ):
        response = await client.get(path, headers=auth_headers(viewer))
        assert response.status_code == 200, response.text
        choices = response.json()["questions"][0]["choices"]
        assert [choice["is_correct"] for choice in choices] == expected_correct
        explanation = response.json()["questions"][0]["explanation"]
        assert explanation == ("Only authors may read this explanation." if role == "methodologist" else None)
