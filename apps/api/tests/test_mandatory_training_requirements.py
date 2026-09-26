"""Contracts for the explainable mandatory-training requirement resolver."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.mandatory_training.requirements import (
    EnrollmentAssignment,
    merge_effective_requirements,
    project_mandatory_training,
    resolve_effective_requirements,
    resolve_effective_requirements_for_users,
)


def _result(rows):
    result = MagicMock()
    result.all.return_value = rows
    result.scalar_one_or_none.return_value = rows[0][0] if rows else None
    return result


def test_requirement_precedence_preserves_exact_winning_source_reference():
    shared_course = uuid4()
    organization_rule_id = uuid4()
    department_id = uuid4()
    position_id = uuid4()

    requirements = merge_effective_requirements(
        organization_rules=[(shared_course, organization_rule_id)],
        department_rules=[(shared_course, department_id)],
        position_rules=[(shared_course, position_id)],
    )

    assert requirements[shared_course].source == "position"
    assert requirements[shared_course].source_ref_id == position_id


def test_closest_department_rule_wins_within_root_to_leaf_path():
    shared_course = uuid4()
    root_department_id = uuid4()
    leaf_department_id = uuid4()

    requirements = merge_effective_requirements(
        organization_rules=[],
        department_rules=[
            (shared_course, root_department_id),
            (shared_course, leaf_department_id),
        ],
        position_rules=[],
        department_scope_path=(root_department_id, leaf_department_id),
    )

    requirement = requirements[shared_course]
    assert requirement.source == "department"
    assert requirement.source_ref_id == leaf_department_id
    assert requirement.scope_path == (root_department_id, leaf_department_id)


def test_distinct_courses_keep_distinct_effective_sources():
    organization_course = uuid4()
    department_course = uuid4()
    position_course = uuid4()

    requirements = merge_effective_requirements(
        organization_rules=[(organization_course, uuid4())],
        department_rules=[(department_course, uuid4())],
        position_rules=[(position_course, uuid4())],
    )

    assert requirements[organization_course].source == "organization"
    assert requirements[department_course].source == "department"
    assert requirements[position_course].source == "position"


def test_projection_exposes_missing_enrollment_instead_of_hiding_the_requirement():
    course_id = uuid4()
    requirements = merge_effective_requirements(
        organization_rules=[(course_id, uuid4())],
        department_rules=[],
        position_rules=[],
    )

    rows = project_mandatory_training(requirements=requirements, enrollments=[])

    assert len(rows) == 1
    assert rows[0].course_id == course_id
    assert rows[0].requirement_state == "missing_enrollment"
    assert rows[0].assignment_reason_source == "organization"
    assert rows[0].action_required == "materialize"


def test_projection_preserves_manual_assignment_over_an_effective_rule():
    course_id = uuid4()
    enrollment_id = uuid4()
    requirements = merge_effective_requirements(
        organization_rules=[],
        department_rules=[],
        position_rules=[(course_id, uuid4())],
    )

    rows = project_mandatory_training(
        requirements=requirements,
        enrollments=[EnrollmentAssignment(
            enrollment_id=enrollment_id,
            course_id=course_id,
            source="manual",
            status="enrolled",
        )],
    )

    assert rows[0].requirement_state == "protected_assignment"
    assert rows[0].assignment_reason_source == "manual"
    assert rows[0].requirement is requirements[course_id]
    assert rows[0].enrollment_id == enrollment_id
    assert rows[0].action_required == "none"


def test_projection_marks_orphaned_managed_enrollment_for_review():
    course_id = uuid4()

    rows = project_mandatory_training(
        requirements={},
        enrollments=[EnrollmentAssignment(
            enrollment_id=uuid4(),
            course_id=course_id,
            source="department",
            status="enrolled",
        )],
    )

    assert rows[0].requirement_state == "stale_managed_enrollment"
    assert rows[0].assignment_reason_source == "department"
    assert rows[0].action_required == "review_stale"


def test_projection_rejects_ambiguous_current_enrollments_for_one_course():
    course_id = uuid4()
    duplicate_rows = [
        EnrollmentAssignment(uuid4(), course_id, "manual", "enrolled"),
        EnrollmentAssignment(uuid4(), course_id, "position", "enrolled"),
    ]

    with pytest.raises(ValueError, match="duplicate_current_enrollment"):
        project_mandatory_training(requirements={}, enrollments=duplicate_rows)


@pytest.mark.asyncio
async def test_resolver_preserves_nearest_department_and_exact_rule_provenance():
    tenant_id = uuid4()
    root_id, leaf_id = uuid4(), uuid4()
    organization_course, shared_course = uuid4(), uuid4()
    organization_rule_id = uuid4()
    position_id = uuid4()
    user = MagicMock(
        tenant_id=tenant_id,
        position_id=position_id,
        organization_unit_id=leaf_id,
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _result([(shared_course,)]),
        _result([(shared_course, root_id), (shared_course, leaf_id)]),
        _result([(organization_course, organization_rule_id)]),
    ])

    with patch(
        "app.modules.mandatory_training.requirements.resolve_ancestor_path",
        new=AsyncMock(return_value=[root_id, leaf_id]),
    ):
        requirements = await resolve_effective_requirements(db, user)

    shared = requirements[shared_course]
    assert shared.source == "position"
    assert shared.source_ref_id == position_id
    assert requirements[organization_course].source_ref_id == organization_rule_id


@pytest.mark.asyncio
async def test_resolver_uses_tenant_safe_legacy_position_unit_fallback():
    tenant_id = uuid4()
    legacy_unit_id, ancestor_id = uuid4(), uuid4()
    course_id = uuid4()
    user = MagicMock(
        tenant_id=tenant_id,
        position_id=uuid4(),
        organization_unit_id=None,
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _result([]),
        _result([(legacy_unit_id,)]),
        _result([(course_id, ancestor_id)]),
        _result([]),
    ])

    with patch(
        "app.modules.mandatory_training.requirements.resolve_ancestor_path",
        new=AsyncMock(return_value=[ancestor_id, legacy_unit_id]),
    ):
        requirements = await resolve_effective_requirements(db, user)

    requirement = requirements[course_id]
    assert requirement.source == "department"
    assert requirement.source_ref_id == ancestor_id
    assert requirement.scope_path == (ancestor_id, legacy_unit_id)


@pytest.mark.asyncio
async def test_batch_resolver_reads_rules_once_and_keeps_per_user_precedence():
    tenant_id = uuid4()
    root_id, leaf_id = uuid4(), uuid4()
    position_id = uuid4()
    organization_course, department_course, shared_course = uuid4(), uuid4(), uuid4()
    organization_rule_id = uuid4()
    first_user = MagicMock(
        id=uuid4(),
        tenant_id=tenant_id,
        position_id=position_id,
        organization_unit_id=leaf_id,
    )
    second_user = MagicMock(
        id=uuid4(),
        tenant_id=tenant_id,
        position_id=None,
        organization_unit_id=root_id,
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _result([(position_id, leaf_id)]),
        _result([(position_id, shared_course)]),
        _result([(root_id, department_course), (leaf_id, shared_course)]),
        _result([(organization_course, organization_rule_id)]),
    ])

    with patch(
        "app.modules.mandatory_training.requirements.resolve_ancestor_paths",
        new=AsyncMock(return_value={leaf_id: [root_id, leaf_id], root_id: [root_id]}),
    ):
        resolved = await resolve_effective_requirements_for_users(
            db,
            [first_user, second_user],
        )

    assert db.execute.await_count == 4
    assert resolved[first_user.id][shared_course].source == "position"
    assert resolved[first_user.id][shared_course].source_ref_id == position_id
    assert resolved[first_user.id][department_course].source_ref_id == root_id
    assert resolved[second_user.id][department_course].source == "department"
    assert shared_course not in resolved[second_user.id]
    assert resolved[second_user.id][organization_course].source_ref_id == organization_rule_id
