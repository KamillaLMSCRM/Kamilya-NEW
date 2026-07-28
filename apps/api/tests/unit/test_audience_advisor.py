from types import SimpleNamespace
from uuid import uuid4

from app.modules.ai.audience_advisor import (
    AudienceSnapshot,
    ScopeCandidate,
    _course_status,
    _deterministic_scopes,
    _llm_select_scopes,
    audience_prompt_reply,
)


def _snapshot(*candidates: ScopeCandidate) -> AudienceSnapshot:
    course = SimpleNamespace(status="draft", review_status="pending")
    return AudienceSnapshot(
        course=course,
        candidates=list(candidates),
        warnings=[],
        already_enrolled_count=2,
        active_student_count=10,
    )


def test_deterministic_fallback_prefers_explicit_primary_scopes():
    organization = ScopeCandidate("organization", "organization", None, "Whole organization", 10)
    position = ScopeCandidate("position_1", "position", uuid4(), "IT specialist", 3, priority="primary")

    assert _deterministic_scopes(_snapshot(organization, position)) == [position]


def test_llm_selection_discards_unknown_refs_and_keeps_real_candidate_identity():
    position_id = uuid4()
    position = ScopeCandidate("position_1", "position", position_id, "IT specialist", 3)
    snapshot = _snapshot(position)

    selected = _llm_select_scopes(
        snapshot,
        '{"selected_refs":["position_1","invented"],"primary_refs":["position_1"]}',
    )

    assert len(selected) == 1
    assert selected[0].id == position_id
    assert selected[0].name == "IT specialist"
    assert selected[0].reasons == []


def test_invalid_llm_json_returns_empty_selection_for_deterministic_fallback():
    candidate = ScopeCandidate("position_1", "position", uuid4(), "IT specialist", 3)
    assert _llm_select_scopes(_snapshot(candidate), "not json") == []


def test_course_status_is_mapped_without_exposing_review_status_in_reply():
    course = SimpleNamespace(status="draft", review_status="needs_changes")
    recommendation = SimpleNamespace(
        course_status=_course_status(course),
        matched_employee_count=3,
        already_enrolled_count=1,
    )

    assert recommendation.course_status == "review"
    reply = audience_prompt_reply(recommendation)
    assert "draft" not in reply
    assert "review_status" not in reply
    assert "3" in reply
