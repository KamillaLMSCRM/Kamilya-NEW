"""Transactional Supabase DEV journey for source actuality and controlled drafts."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from direct_source_fixtures import seed_direct_source_documents
from sqlalchemy import select

from app.models.enrollment import Enrollment
from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.courses.localizations import POLICY_KEY, read_policy, save_edition, source_fields
from app.modules.courses.models import Course
from app.modules.courses.release_service import create_course_release
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
    original_rule = "Verify identity before payment"
    unchanged_rule = "Review payments above 100000 tenge"
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        [previous, current],
        texts={
            previous.id: (
                "# Cash handling\n\n"
                "| Role | Requirement |\n|---|---|\n"
                f"| Cashier | {original_rule} |\n"
                f"| Supervisor | {unchanged_rule} |\n"
            ),
            current.id: (
                "# Cash handling\n\n"
                "| Role | Requirement |\n|---|---|\n"
                "| Cashier | Verify identity and record the document number before payment |\n"
                f"| Supervisor | {unchanged_rule} |\n"
            ),
        },
    )

    course = await make_course(tenant, methodologist, title="Cash handling", status="published")
    course.source_document_ids = [str(previous.id)]
    course.source_instruction_id = previous.id
    course.source_analysis = {POLICY_KEY: {"primary": "ru", "requested": ["ru", "kk"]}}
    module = await make_module(course)
    lesson = await make_lesson(module, title="Payment verification")
    retained_lesson = await make_lesson(module, title="Supervisor verification")
    original_source = (await build_direct_source_corpus([previous], tenant_id=tenant.id)).documents[0]
    working = original_source.source_text
    assert working is not None
    for item, quote in ((lesson, original_rule), (retained_lesson, unchanged_rule)):
        start = working.index(quote)
        item.source_document_ids = [str(previous.id)]
        item.source_references = [{
            "kind": "working_text_span_v1", "doc_id": str(previous.id),
            "source_revision": original_source.source_revision,
            "source_text_sha256": sha256(working.encode()).hexdigest(),
            "start": start, "end": start + len(quote),
            "span_sha256": sha256(quote.encode()).hexdigest(),
        }]
        item.source_validation_status = "verified"
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
    baseline = await create_course_release(db_session, course, published_by=methodologist.id)
    baseline_sha = baseline.snapshot_sha256
    language_sha, fields = source_fields(baseline.snapshot)
    policy = read_policy(course)
    assert policy is not None
    assert await save_edition(db_session, course, policy, language_sha, "kk", fields, approve=True)
    learner = await make_user(tenant, role="student")
    enrollment = Enrollment(tenant_id=tenant.id, course_id=course.id, user_id=learner.id,
                            content_release_id=baseline.id, status="completed")
    db_session.add(enrollment)
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
        select(Lesson).join(Module).where(Module.course_id == draft_id, Lesson.title == lesson.title)
    )
    draft_quiz = await db_session.scalar(
        select(Quiz).join(Lesson).join(Module).where(Module.course_id == draft_id)
    )
    assert draft is not None
    assert draft.status == "draft"
    assert draft.review_status == "pending"
    assert draft.current_release_id is None
    assert read_policy(draft).requested == ["ru", "kk"]
    assert draft.source_analysis["source_actuality"]["previous_release_id"] == str(baseline.id)
    assert draft_lesson is not None
    assert draft_lesson.source_validation_status == "needs_review"
    assert draft_lesson.source_references[0]["doc_id"] == str(current.id)
    carried_lesson = await db_session.scalar(
        select(Lesson).join(Module).where(Module.course_id == draft_id, Lesson.title == retained_lesson.title)
    )
    assert carried_lesson is not None
    assert carried_lesson.source_validation_status == "verified"
    assert carried_lesson.source_references[0]["doc_id"] == str(current.id)
    assert draft_quiz is not None
    assert draft_quiz.review_status == "needs_review"
    assert decision["decision_snapshot"]["draft_courses"][0]["lessons"] == [
        {"lesson_id": str(draft_lesson.id), "title": "Payment verification"}
    ]
    languages = await client.get(f"/api/v1/courses/{draft_id}/languages/editor", headers=headers)
    assert languages.status_code == 200, languages.text
    edition = languages.json()["editions"]["kk"]
    assert edition["approved"] is False
    assert edition["content"][f"lesson.{draft_lesson.id}.title"] == lesson.title
    await db_session.refresh(enrollment)
    await db_session.refresh(baseline)
    assert enrollment.status == "completed" and enrollment.content_release_id == baseline.id
    assert baseline.snapshot_sha256 == baseline_sha

    outsider_tenant = await make_tenant(name="Other", slug=f"other-{uuid4().hex[:8]}")
    outsider = await make_user(outsider_tenant, role="methodologist")
    hidden = await client.get(
        f"/api/v1/admin/source-actuality/reviews/{review_id}",
        headers=auth_headers(outsider),
    )
    assert hidden.status_code == 404
