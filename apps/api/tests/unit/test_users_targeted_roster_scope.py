from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.training_responsibility.scope import ReportingScope, ReportingScopeMode
from app.modules.users import router as users_router


@pytest.mark.asyncio
async def test_targeted_roster_ids_outside_methodologist_scope_return_no_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    requested_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    observed: list[object] = []

    async def fake_scope(*_args, **_kwargs):
        return ReportingScope(ReportingScopeMode.RESTRICTED, frozenset())

    async def fake_list_users(*args):
        observed.append(args)
        return [], 0

    monkeypatch.setattr(users_router, "resolve_reporting_scope", fake_scope)
    monkeypatch.setattr(users_router, "list_users", fake_list_users)

    response = await users_router.list_all_users(
        page=1,
        per_page=50,
        search=None,
        role="student",
        is_active=True,
        user_ids=[requested_id],
        include_students=False,
        db=object(),
        user=user,
    )

    assert response.users == []
    assert response.total == 0
    assert observed == []


@pytest.mark.asyncio
async def test_untargeted_roster_keeps_existing_role_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    observed: list[tuple[object, ...]] = []

    async def unexpected_scope(*_args, **_kwargs):
        raise AssertionError("untargeted roster must not resolve a reporting scope")

    async def fake_list_users(*args):
        observed.append(args)
        return [], 0

    async def fake_role_map(*_args):
        return {}

    monkeypatch.setattr(users_router, "resolve_reporting_scope", unexpected_scope)
    monkeypatch.setattr(users_router, "list_users", fake_list_users)
    monkeypatch.setattr(users_router, "get_role_map", fake_role_map)

    response = await users_router.list_all_users(
        page=1,
        per_page=500,
        search=None,
        role="student",
        is_active=True,
        user_ids=[],
        include_students=False,
        db=object(),
        user=user,
    )

    assert response.users == []
    assert response.total == 0
    assert observed and observed[0][-1] == []
