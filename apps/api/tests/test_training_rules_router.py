"""Router contracts for methodologist-owned organization training rules."""
from datetime import datetime, timezone
from inspect import getclosurevars
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.positions.batch_service import BatchResult
from app.modules.training_rules.models import OrganizationCourseRule
from app.modules.training_rules.router import (
    OrganizationCourseRuleRequest,
    attach_organization_course_rule,
    detach_organization_course_rule,
    list_organization_course_rules,
    router,
)


def _user(tenant_id=None):
    return MagicMock(id=uuid4(), tenant_id=tenant_id or uuid4(), role="methodologist")


def _rule(tenant_id, course_id):
    return OrganizationCourseRule(
        id=uuid4(),
        tenant_id=tenant_id,
        course_id=course_id,
        required=True,
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_attach_creates_rule_and_recomputes_all_tenant_users():
    tenant_id = uuid4()
    course_id = uuid4()
    user = _user(tenant_id)
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[MagicMock(), None])
    db.flush = AsyncMock()

    def add_rule(rule):
        rule.id = uuid4()
        rule.created_at = datetime.now(timezone.utc)
        rule.updated_at = rule.created_at

    db.add = MagicMock(side_effect=add_rule)
    with patch(
        "app.modules.training_rules.router.recompute_tenant_members",
        AsyncMock(return_value=BatchResult(users_processed=2, added=2)),
    ) as recompute:
        response = await attach_organization_course_rule(
            OrganizationCourseRuleRequest(course_id=course_id), db, user
        )

    assert response.course_id == course_id
    assert response.enrollments_added == 2
    assert db.add.call_count == 1
    recompute.assert_awaited_once_with(db, tenant_id)


@pytest.mark.asyncio
async def test_attach_is_idempotent_and_updates_required_without_duplicate():
    tenant_id = uuid4()
    course_id = uuid4()
    existing = _rule(tenant_id, course_id)
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[MagicMock(), existing])
    db.flush = AsyncMock()
    db.add = MagicMock()
    with patch(
        "app.modules.training_rules.router.recompute_tenant_members",
        AsyncMock(return_value=BatchResult()),
    ):
        response = await attach_organization_course_rule(
            OrganizationCourseRuleRequest(course_id=course_id, required=False), db, _user(tenant_id)
        )

    assert response.required is False
    assert existing.required is False
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_attach_rejects_cross_tenant_or_unpublished_course_without_writing():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.flush = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await attach_organization_course_rule(
            OrganizationCourseRuleRequest(course_id=uuid4()), db, _user()
        )

    assert exc.value.status_code == 404
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_detach_removes_rule_and_recomputes_in_progress_but_not_completed():
    tenant_id = uuid4()
    course_id = uuid4()
    rule = _rule(tenant_id, course_id)
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=rule)
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    with patch(
        "app.modules.training_rules.router.recompute_tenant_members",
        AsyncMock(return_value=BatchResult(removed=1, protected_completed=1)),
    ):
        response = await detach_organization_course_rule(course_id, db, _user(tenant_id))

    assert response.enrollments_removed == 1
    db.delete.assert_awaited_once_with(rule)


@pytest.mark.asyncio
async def test_list_is_tenant_scoped():
    tenant_id = uuid4()
    rule = _rule(tenant_id, uuid4())
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [rule]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=rows)

    response = await list_organization_course_rules(db, _user(tenant_id))

    assert [item.id for item in response.rules] == [rule.id]
    statement = db.execute.await_args.args[0]
    assert "organization_course_rules.tenant_id" in str(statement)


def test_training_rule_and_department_course_routes_are_methodologist_only():
    protected_routes = [
        *router.routes,
    ]
    from app.modules.departments.router import router as departments_router

    protected_routes.extend(
        route
        for route in departments_router.routes
        if route.path in {"/{department_id}/courses", "/attach-courses-all", "/detach-courses-all", ""}
    )
    for route in protected_routes:
        role_dependencies = [
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.call is not None and dependency.call.__name__ == "role_checker"
        ]
        assert role_dependencies, route.path
        allowed_roles = getclosurevars(role_dependencies[0]).nonlocals["allowed_roles"]
        assert allowed_roles == ("methodologist",), route.path


def test_legacy_batch_department_routes_are_explicitly_deprecated():
    from app.modules.departments.router import router as departments_router

    legacy_routes = {
        route.path.rsplit("/", 1)[-1]: route
        for route in departments_router.routes
        if route.path.endswith(("/attach-courses-all", "/detach-courses-all"))
    }
    assert legacy_routes["attach-courses-all"].deprecated is True
    assert legacy_routes["detach-courses-all"].deprecated is True
