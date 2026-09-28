from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.source_actuality import service as source_actuality_service
from app.modules.source_actuality.service import (
    _clone_course,
    _without_document_reference,
    bounded_fact_diff,
    decide_review,
    derive_actuality_state,
    process_review,
    request_analysis,
)


def test_bounded_fact_diff_normalizes_and_orders_changes_deterministically():
    previous = [
        SourceFact("old-limit", "Cashier", "Limit", "100", "doc=old;row=4"),
        SourceFact("old-frequency", "Auditor", "Frequency", "Monthly", "doc=old;row=5"),
    ]
    current = [
        SourceFact("new-limit", "cashier", "limit", "200", "doc=new;row=4"),
        SourceFact("new-frequency", "Auditor", "Frequency", "Monthly", "doc=new;row=5"),
        SourceFact("new-review", "Manager", "Review", "Weekly", "doc=new;row=6"),
    ]

    changes = bounded_fact_diff(previous, current, limit=10)

    assert changes["added"] == [
        {"change_kind": "added", "subject": "cashier", "attribute": "limit", "new_value": "200", "new_locator": "doc=new;row=4"},
        {"change_kind": "added", "subject": "Manager", "attribute": "Review", "new_value": "Weekly", "new_locator": "doc=new;row=6"},
    ]
    assert changes["removed"] == [
        {"change_kind": "removed", "subject": "Cashier", "attribute": "Limit", "old_value": "100", "old_locator": "doc=old;row=4"}
    ]
    assert changes["unchanged_count"] == 1
    assert changes["truncated"] is False


def test_fact_diff_reports_uncertainty_change_without_rewriting_value():
    previous = [SourceFact("old", "Rule", "Requirement", "Sign", "doc=old", 1.0, "")]
    current = [SourceFact("new", "Rule", "Requirement", "Sign", "doc=new", 0.6, "ocr_uncertain")]

    changes = bounded_fact_diff(previous, current)

    assert changes["changed_count"] == 1
    assert changes["unchanged_count"] == 0
    assert changes["changed"] == [
        {
            "change_kind": "metadata_changed",
            "subject": "Rule",
            "attribute": "Requirement",
            "old_value": "Sign",
            "new_value": "Sign",
            "old_locator": "doc=old",
            "new_locator": "doc=new",
            "old_confidence": 1.0,
            "new_confidence": 0.6,
            "old_uncertainty": "",
            "new_uncertainty": "ocr_uncertain",
        }
    ]


def test_actuality_state_never_treats_missing_policy_as_current():
    assert derive_actuality_state(None, None) == "unassigned"


def test_source_reference_cleanup_preserves_unrelated_evidence():
    predecessor = uuid4()
    replacement = uuid4()
    references = [
        {"document_id": str(predecessor), "quote": "old"},
        {"document_id": str(replacement), "quote": "other"},
    ]

    assert _without_document_reference(references, predecessor) == [references[1]]


@pytest.mark.asyncio
async def test_analysis_rejects_a_superseded_active_revision():
    tenant_id = uuid4()
    family_id = uuid4()
    new_document = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        source_family_id=family_id,
        version=2,
    )
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[new_document, 3]))

    with pytest.raises(HTTPException) as exc_info:
        await request_analysis(db, tenant_id=tenant_id, new_document_id=new_document.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only the latest active source revision can be analyzed"


@pytest.mark.asyncio
async def test_processing_marks_a_review_failed_when_revision_was_superseded():
    tenant_id = uuid4()
    family_id = uuid4()
    previous_id = uuid4()
    new_id = uuid4()
    review = SimpleNamespace(
        status="pending",
        previous_document_id=previous_id,
        new_document_id=new_id,
        analysis_error_code=None,
        analysis_error_message=None,
    )
    previous = SimpleNamespace(
        id=previous_id,
        source_family_id=family_id,
        version=1,
        lifecycle_status="active",
        index_status="ready",
        content_sha256="a" * 64,
    )
    new = SimpleNamespace(
        id=new_id,
        source_family_id=family_id,
        version=2,
        lifecycle_status="active",
        index_status="ready",
        content_sha256="b" * 64,
    )

    class Rows:
        def scalars(self):
            return self

        def __iter__(self):
            return iter((previous, new))

    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[review, 3]),
        execute=AsyncMock(return_value=Rows()),
        flush=AsyncMock(),
    )

    result = await process_review(db, tenant_id=tenant_id, review_id=uuid4())

    assert result.status == "failed"
    assert result.analysis_error_code == "source_revision_superseded"


@pytest.mark.asyncio
async def test_clone_marks_reported_course_level_lessons_and_quizzes_for_review():
    tenant_id = uuid4()
    predecessor_id = uuid4()
    replacement_id = uuid4()
    lesson_id = uuid4()
    course = SimpleNamespace(
        id=uuid4(),
        title="Legacy course",
        description="",
        thumbnail_url=None,
        ai_generated=True,
        source_instruction_id=predecessor_id,
        source_document_ids=[str(predecessor_id)],
        source_strategy="single_topic",
        source_combination_goal=None,
    )
    module = SimpleNamespace(
        id=uuid4(), title="Module", description="", order_index=0, ai_generated=True
    )
    lesson = SimpleNamespace(
        id=lesson_id,
        title="Legacy lesson",
        content_type="text",
        content="Content",
        duration_seconds=60,
        order_index=0,
        ai_generated=True,
        source_document_ids=[],
        source_references=[],
        source_validation_status="verified",
    )
    quiz = SimpleNamespace(
        id=uuid4(),
        title="Quiz",
        pass_score=80,
        time_limit=None,
        attempt_limit=3,
        deferral_days=7,
        review_status="approved",
    )

    class Rows:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class FakeDb:
        def __init__(self):
            self.results = iter((Rows([module]), Rows([lesson]), Rows([]), Rows([quiz]), Rows([])))
            self.added = []

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = uuid4()
            self.added.append(value)

        def add_all(self, values):
            for value in values:
                self.add(value)

        async def flush(self):
            return None

        async def execute(self, _query):
            return next(self.results)

    db = FakeDb()

    await _clone_course(
        db,
        course=course,
        tenant_id=tenant_id,
        actor_id=uuid4(),
        predecessor_id=predecessor_id,
        replacement_id=replacement_id,
        impacted_lesson_ids={lesson_id},
    )

    cloned_lesson = next(value for value in db.added if value.__class__.__name__ == "Lesson")
    cloned_quiz = next(value for value in db.added if value.__class__.__name__ == "Quiz")
    assert cloned_lesson.source_validation_status == "needs_review"
    assert cloned_quiz.review_status == "needs_review"


@pytest.mark.asyncio
async def test_resolved_decision_is_idempotent_only_for_the_exact_same_command():
    tenant_id = uuid4()
    review_id = uuid4()
    actor_id = uuid4()
    due_at = datetime.now(UTC)
    review = SimpleNamespace(
        status="resolved",
        decision="update_and_retrain",
        decision_reason="The revised rule requires a new controlled course draft.",
        decision_snapshot={"retraining_due_at": due_at.isoformat()},
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=review))

    result = await decide_review(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        review_id=review_id,
        decision="update_and_retrain",
        reason=review.decision_reason,
        retraining_due_at=due_at,
    )
    assert result is review

    with pytest.raises(HTTPException) as exc_info:
        await decide_review(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            review_id=review_id,
            decision="no_learning_impact",
            reason="A conflicting command must not rewrite the recorded decision.",
            retraining_due_at=None,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_course_level_impact_marks_every_reported_lesson_for_review(
    monkeypatch: pytest.MonkeyPatch,
):
    tenant_id = uuid4()
    actor_id = uuid4()
    review_id = uuid4()
    predecessor_id = uuid4()
    replacement_id = uuid4()
    course_id = uuid4()
    lesson_ids = {uuid4(), uuid4()}
    draft_id = uuid4()
    review = SimpleNamespace(
        status="ready",
        impact_snapshot={
            "impacted_courses": [
                {
                    "course_id": str(course_id),
                    "impacted_lesson_ids": [str(value) for value in lesson_ids],
                }
            ]
        },
        previous_document_id=predecessor_id,
        new_document_id=replacement_id,
    )
    course = SimpleNamespace(id=course_id, delivery_type="native")
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[review, course]), flush=AsyncMock())
    clone = AsyncMock(return_value=draft_id)
    monkeypatch.setattr(source_actuality_service, "_clone_course", clone)

    result = await decide_review(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        review_id=review_id,
        decision="update_future",
        reason="The source changed and every dependent lesson needs a controlled review.",
        retraining_due_at=None,
    )

    assert result.decision_snapshot["draft_course_ids"] == [str(draft_id)]
    assert clone.await_args.kwargs["impacted_lesson_ids"] == lesson_ids


def test_router_exposes_only_the_required_source_actuality_contract():
    from app.modules.source_actuality.router import router

    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert {
        ("/admin/source-actuality", ("GET",)),
        ("/admin/source-actuality/{source_family_id}/policy", ("PUT",)),
        ("/admin/source-actuality/documents/{new_document_id}/analyze", ("POST",)),
        ("/admin/source-actuality/reviews/{review_id}", ("GET",)),
        ("/admin/source-actuality/reviews/{review_id}/decision", ("POST",)),
    } <= routes
