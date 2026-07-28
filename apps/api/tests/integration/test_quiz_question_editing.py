from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_methodologist_updates_question_and_choices_atomically(
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
    from app.modules.quizzes.models import Question, QuizChoice

    tenant = await make_tenant(name="Question editor", slug="question-editor")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@question-editor.example",
    )
    course = await make_course(tenant, methodologist)
    module = await make_module(course)
    lesson = await make_lesson(module)
    quiz = await make_quiz(lesson)
    question = Question(
        quiz_id=quiz.id,
        text="Old question",
        type="MCQ",
        points=1,
        order_index=0,
    )
    db_session.add(question)
    await db_session.flush()
    correct_choice = QuizChoice(
        question_id=question.id,
        text="Old correct",
        is_correct=True,
        order_index=0,
    )
    wrong_choice = QuizChoice(
        question_id=question.id,
        text="Old wrong",
        is_correct=False,
        order_index=1,
    )
    db_session.add_all([correct_choice, wrong_choice])
    await db_session.flush()

    response = await client.put(
        f"/api/v1/quizzes/{quiz.id}/questions/{question.id}",
        headers=auth_headers(methodologist),
        json={
            "text": "Updated question",
            "type": "MCQ",
            "points": 3,
            "explanation": "Updated explanation",
            "order_index": 0,
            "choices": [
                {
                    "id": str(wrong_choice.id),
                    "text": "New wrong",
                    "is_correct": False,
                    "order_index": 0,
                },
                {
                    "id": str(correct_choice.id),
                    "text": "New correct",
                    "is_correct": True,
                    "order_index": 1,
                },
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["questions"][0]["text"] == "Updated question"
    assert payload["questions"][0]["points"] == 3
    assert payload["questions"][0]["explanation"] == "Updated explanation"
    assert [(choice["id"], choice["text"], choice["is_correct"]) for choice in payload["questions"][0]["choices"]] == [
        (str(wrong_choice.id), "New wrong", False),
        (str(correct_choice.id), "New correct", True),
    ]

    clear_response = await client.put(
        f"/api/v1/quizzes/{quiz.id}/questions/{question.id}",
        headers=auth_headers(methodologist),
        json={
            "explanation": None,
            "choices": [
                payload["questions"][0]["choices"][1],
                {
                    "text": "Replacement wrong",
                    "is_correct": False,
                    "order_index": 1,
                },
            ],
        },
    )
    assert clear_response.status_code == 200, clear_response.text
    cleared_question = clear_response.json()["questions"][0]
    assert cleared_question["explanation"] is None
    cleared_choices = cleared_question["choices"]
    assert [choice["text"] for choice in cleared_choices] == [
        "New correct",
        "Replacement wrong",
    ]
    assert cleared_choices[0]["id"] == str(correct_choice.id)
    assert all(choice["id"] != str(wrong_choice.id) for choice in cleared_choices)


@pytest.mark.asyncio
async def test_other_tenant_cannot_update_question(
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
    from app.modules.quizzes.models import Question

    owner_tenant = await make_tenant(name="Quiz owner", slug="quiz-owner")
    owner = await make_user(owner_tenant, role="methodologist")
    course = await make_course(owner_tenant, owner)
    module = await make_module(course)
    lesson = await make_lesson(module)
    quiz = await make_quiz(lesson)
    question = Question(
        quiz_id=quiz.id,
        text="Private question",
        type="MCQ",
        points=1,
        order_index=0,
    )
    db_session.add(question)
    await db_session.flush()

    other_tenant = await make_tenant(name="Other tenant", slug="other-tenant")
    outsider = await make_user(other_tenant, role="methodologist")
    response = await client.put(
        f"/api/v1/quizzes/{quiz.id}/questions/{question.id}",
        headers=auth_headers(outsider),
        json={"text": "Tampered"},
    )

    assert response.status_code == 404
    await db_session.refresh(question)
    assert question.text == "Private question"


@pytest.mark.asyncio
async def test_question_with_existing_attempt_cannot_be_changed(
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
    from app.modules.quizzes.models import Question, QuizAttempt

    tenant = await make_tenant(name="Attempt history", slug="attempt-history")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@attempt-history.example",
    )
    learner = await make_user(
        tenant,
        role="student",
        email="learner@attempt-history.example",
    )
    course = await make_course(tenant, methodologist)
    module = await make_module(course)
    lesson = await make_lesson(module)
    quiz = await make_quiz(lesson)
    question = Question(
        quiz_id=quiz.id,
        text="Historical question",
        type="MCQ",
        points=1,
        order_index=0,
    )
    db_session.add(question)
    await db_session.flush()
    db_session.add(
        QuizAttempt(
            quiz_id=quiz.id,
            user_id=learner.id,
            tenant_id=tenant.id,
            score_percent=100,
            total_points=1,
            earned_points=1,
            passed=True,
            answers=[],
        )
    )
    await db_session.flush()

    response = await client.put(
        f"/api/v1/quizzes/{quiz.id}/questions/{question.id}",
        headers=auth_headers(methodologist),
        json={"text": "Changed after attempt"},
    )

    assert response.status_code == 409
    assert "новую версию" in response.json()["message"]
    await db_session.refresh(question)
    assert question.text == "Historical question"
