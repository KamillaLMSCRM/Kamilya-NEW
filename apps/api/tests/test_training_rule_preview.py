"""Read-only preview behavior for organization and department training rules."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.positions.assignment_service import RuleChangePreview, preview_rule_change
from app.modules.training_rules.router import (
    RulePreviewRequest,
    preview_training_rule_change,
)


def _rows(*, users=None, current=None):
    result = MagicMock()
    result.scalars.return_value.all.return_value = users or []
    result.first.return_value = current
    return result


@pytest.mark.asyncio
async def test_organization_attach_preview_counts_adds_and_protected_sources_without_mutation():
    tenant_id = uuid4()
    course_id = uuid4()
    user_a = MagicMock(id=uuid4())
    user_b = MagicMock(id=uuid4())
    user_c = MagicMock(id=uuid4())
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _rows(users=[user_a, user_b, user_c]),
            _rows(current=None),
            _rows(current=("manual", "enrolled")),
            _rows(current=("cohort", "enrolled")),
        ]
    )
    db.add = MagicMock()
    db.delete = AsyncMock()
    with patch(
        "app.modules.positions.assignment_service._rule_course_sets",
        AsyncMock(return_value=(set(), set(), set())),
    ):
        impact = await preview_rule_change(
            db,
            tenant_id=tenant_id,
            scope="organization",
            operation="attach",
            course_id=course_id,
        )

    assert impact == RuleChangePreview(
        affected_employees=3,
        enrollments_to_add=1,
        protected_other_sources=2,
    )
    db.add.assert_not_called()
    db.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_organization_detach_preview_counts_in_progress_and_completed_protection():
    tenant_id = uuid4()
    course_id = uuid4()
    user_a = MagicMock(id=uuid4())
    user_b = MagicMock(id=uuid4())
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _rows(users=[user_a, user_b]),
            _rows(current=("organization", "enrolled")),
            _rows(current=("organization", "completed")),
        ]
    )
    with patch(
        "app.modules.positions.assignment_service._rule_course_sets",
        AsyncMock(return_value=(set(), set(), {course_id})),
    ):
        impact = await preview_rule_change(
            db,
            tenant_id=tenant_id,
            scope="organization",
            operation="detach",
            course_id=course_id,
        )

    assert impact.in_progress_to_remove == 1
    assert impact.protected_completed == 1


@pytest.mark.asyncio
async def test_preview_endpoint_is_methodologist_contract_and_never_mutates():
    tenant_id = uuid4()
    course_id = uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[MagicMock(), None])
    db.add = MagicMock()
    db.delete = AsyncMock()
    user = MagicMock(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    with patch(
        "app.modules.training_rules.router.preview_rule_change",
        AsyncMock(return_value=RuleChangePreview(affected_employees=4, enrollments_to_add=4)),
    ) as preview:
        response = await preview_training_rule_change(
            RulePreviewRequest(scope="organization", operation="attach", course_id=course_id),
            db,
            user,
        )

    assert response.affected_employees == 4
    assert response.enrollments_to_add == 4
    preview.assert_awaited_once()
    db.add.assert_not_called()
    db.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_department_preview_requires_department_without_creating_one():
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    user = MagicMock(id=uuid4(), tenant_id=uuid4(), role="methodologist")
    with pytest.raises(Exception) as caught:
        await preview_training_rule_change(
            RulePreviewRequest(scope="department", operation="attach", course_id=uuid4()),
            db,
            user,
        )

    assert getattr(caught.value, "status_code", None) == 422
    db.add.assert_not_called()
    db.delete.assert_not_awaited()
