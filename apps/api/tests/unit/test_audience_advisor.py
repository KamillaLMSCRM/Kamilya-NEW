from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.modules.ai.audience_advisor import (
    AudienceSnapshot,
    ScopeCandidate,
    _course_status,
    _deterministic_scopes,
    _llm_select_scopes,
    _load_departments,
    _unit_membership_clause,
    audience_prompt_reply,
    is_audience_recommendation_question,
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


def test_llm_cannot_hide_or_downgrade_explicit_primary_scope():
    required = ScopeCandidate(
        "position_required",
        "position",
        uuid4(),
        "Required position",
        2,
        priority="primary",
    )
    optional = ScopeCandidate(
        "position_optional",
        "position",
        uuid4(),
        "Optional position",
        3,
    )

    selected = _llm_select_scopes(
        _snapshot(required, optional),
        '{"selected_refs":["position_optional"],"secondary_refs":["position_optional"]}',
    )

    assert selected[0] is required
    assert required.priority == "primary"
    assert optional in selected


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
    assert "опубликуйте курс" in reply


def test_typed_audience_question_is_detected_without_explicit_intent():
    assert is_audience_recommendation_question(
        "Кому его назначить? Посмотри по моей структуре"
    )
    assert is_audience_recommendation_question("Which departments should take this course?")
    assert not is_audience_recommendation_question("Перепиши второй урок")


def test_audience_membership_clause_prefers_explicit_unit_over_legacy_position():
    """The SQL contract must not let a stale position department override placement."""
    from app.models.users import User
    from app.modules.positions.models import Position
    # This is the same predicate shape used by _matched_count; compiling it
    # keeps this database-free test focused on the tenant/NULL fallback seam.
    unit_id = uuid4()
    statement = select(User.id).select_from(User).outerjoin(Position, Position.id == User.position_id).where(
        _unit_membership_clause({unit_id}, uuid4()),
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "organization_unit_id" in sql
    assert "IS NULL" in sql


def test_scope_candidate_can_represent_nested_unit_without_new_public_type():
    unit = ScopeCandidate("department_1", "department", uuid4(), "Sector", 4)
    unit.semantic_context["unit_type"] = "sector"
    assert unit.type == "department"
    assert unit.semantic_context["unit_type"] == "sector"


@pytest.mark.asyncio
async def test_department_candidates_roll_up_employee_counts_with_one_bulk_path_resolution():
    tenant_id = uuid4()
    root = SimpleNamespace(
        id=uuid4(), name="Central", description="", unit_type="organization"
    )
    leaf = SimpleNamespace(
        id=uuid4(), name="Sector", description="", unit_type="sector"
    )
    units_result = MagicMock()
    units_result.scalars.return_value.all.return_value = [root, leaf]
    members_result = MagicMock()
    members_result.all.return_value = [
        (uuid4(), leaf.id, uuid4()),
        (uuid4(), None, leaf.id),
    ]
    db = AsyncMock()
    db.execute.side_effect = [units_result, members_result]

    with patch(
        "app.modules.ai.audience_advisor.resolve_ancestor_paths",
        new=AsyncMock(return_value={leaf.id: [root.id, leaf.id]}),
    ) as resolver:
        candidates = await _load_departments(db, tenant_id)

    assert [candidate.employee_count for candidate in candidates] == [2, 2]
    resolver.assert_awaited_once_with(db, tenant_id, {leaf.id})
    db.scalar.assert_not_awaited()
