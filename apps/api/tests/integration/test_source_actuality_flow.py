"""Transactional Supabase DEV journey for source actuality and controlled drafts."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from direct_source_fixtures import seed_direct_source_documents
from sqlalchemy import select

from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.source_actuality import router as source_actuality_router
from app.modules.source_actuality import service as source_actuality_service
from app.modules.source_actuality.service import process_review


@pytest.mark.asyncio
async def test_methodologist_reviews_latest_revision_and_creates_only_a_reviewable_draft(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_document,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    set_current_tenant,
    monkeypatch,
):
    tenant = await make_tenant(name="Source Actuality", slug=f"source-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    family_id = uuid4()
    previous = await make_document(
        tenant,
        methodologist,
        title="Cash handling policy",
        source_family_id=family_id,
        version=1,
        lifecycle_status="active",
        index_status="ready",
    )
    current = await make_document(
        tenant,
        methodologist,
        title="Cash handling policy",
        source_family_id=family_id,
        version=2,
        lifecycle_status="active",
        index_status="ready",
    )
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        [previous, current],
        texts={
            previous.id: (
                "# Cash handling\n\n"
                "| Role | Requirement |\n|---|---|\n"
                "| Cashier | Verify identity before payment |\n"
            ),
            current.id: (
                "# Cash handling\n\n"
                "| Role | Requirement |\n|---|---|\n"
                "| Cashier | Verify identity and record the document number before payment |\n"
                "| Supervisor | Review payments above 100000 tenge |\n"
            ),
        },
    )

    course = await make_course(tenant, methodologist, title="Cash handling", status="published")
    course.source_document_ids = [str(previous.id)]
    course.source_instruction_id = previous.id
    module = await make_module(course)
    lesson = await make_lesson(module, title="Payment verification")
    lesson.source_document_ids = []
    lesson.source_references = []
    lesson.source_validation_status = "verified"
    quiz = await make_quiz(lesson)
    question = Question(
        quiz_id=quiz.id,
        text="What must a cashier verify before payment?",
        type="single_choice",
        points=1,
        order_index=0,
    )
    db_session.add(question)
    await db_session.flush()
    db_session.add_all(
        [
            QuizChoice(question_id=question.id, text="Customer identity", is_correct=True, order_index=0),
            QuizChoice(question_id=question.id, text="Desk color", is_correct=False, order_index=1),
        ]
    )
    await db_session.flush()

    headers = auth_headers(methodologist)
    policy = await client.put(
        f"/api/v1/admin/source-actuality/{family_id}/policy",
        json={"owner_id": str(methodologist.id), "reviewed_at": None, "next_review_at": None},
        headers=headers,
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["owner_id"] == str(methodologist.id)
    assert policy.json()["reviewed_at"] is None

    monkeypatch.setattr(source_actuality_router.analyze_review_task, "apply_async", lambda *args, **kwargs: None)
    admitted = await client.post(
        f"/api/v1/admin/source-actuality/documents/{current.id}/analyze",
        headers=headers,
    )
    assert admitted.status_code == 202, admitted.text
    review_id = admitted.json()["id"]

    async def transactional_loader(document_ids, *, tenant_id, check_cancelled=None):
        assert document_ids == [str(previous.id), str(current.id)]
        assert tenant_id == tenant.id
        return await build_direct_source_corpus(
            [previous, current],
            tenant_id=tenant_id,
            check_cancelled=check_cancelled,
        )

    monkeypatch.setattr(source_actuality_service, "load_direct_source_corpus", transactional_loader)
    await set_current_tenant(tenant)
    await process_review(db_session, tenant_id=tenant.id, review_id=UUID(review_id))
    review = await client.get(f"/api/v1/admin/source-actuality/reviews/{review_id}", headers=headers)
    assert review.status_code == 200, review.text
    payload = review.json()
    assert payload["status"] == "ready", (
        payload.get("analysis_error_code"),
        payload.get("analysis_error_message"),
    )
    assert payload["added_fact_count"] + payload["removed_fact_count"] + payload["changed_fact_count"] > 0
    assert payload["impacted_course_count"] == 1
    assert payload["impacted_lesson_count"] == 1
    assert payload["assessment_questions_requiring_review"] == 1

    decided = await client.post(
        f"/api/v1/admin/source-actuality/reviews/{review_id}/decision",
        json={
            "decision": "update_future",
            "reason": "The new source changes the payment verification rule and requires review.",
        },
        headers=headers,
    )
    assert decided.status_code == 200, decided.text
    decision = decided.json()
    assert decision["status"] == "resolved"
    assert decision["decision_snapshot"]["automatic_reassignment"] is False
    assert len(decision["decision_snapshot"]["draft_course_ids"]) == 1

    draft_id = UUID(decision["decision_snapshot"]["draft_course_ids"][0])
    draft = await db_session.scalar(select(Course).where(Course.id == draft_id))
    draft_lesson = await db_session.scalar(
        select(Lesson).join(Module).where(Module.course_id == draft_id)
    )
    draft_quiz = await db_session.scalar(
        select(Quiz).join(Lesson).join(Module).where(Module.course_id == draft_id)
    )
    assert draft is not None
    assert draft.status == "draft"
    assert draft.review_status == "pending"
    assert draft.current_release_id is None
    assert draft_lesson is not None
    assert draft_lesson.source_validation_status == "needs_review"
    assert draft_quiz is not None
    assert draft_quiz.review_status == "needs_review"

    outsider_tenant = await make_tenant(name="Other", slug=f"other-{uuid4().hex[:8]}")
    outsider = await make_user(outsider_tenant, role="methodologist")
    hidden = await client.get(
        f"/api/v1/admin/source-actuality/reviews/{review_id}",
        headers=auth_headers(outsider),
    )
    assert hidden.status_code == 404
