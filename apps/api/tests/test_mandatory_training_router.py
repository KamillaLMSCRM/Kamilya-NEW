from __future__ import annotations

from inspect import getclosurevars
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from app.modules.mandatory_training import router as mandatory_training_router
from app.modules.mandatory_training.router import (
    list_mandatory_training,
    mandatory_training_summary,
)
from app.modules.mandatory_training.schemas import (
    MandatoryTrainingPage,
    MandatoryTrainingSummary,
)
from app.modules.training_responsibility.policy import ReportingScopeMode


def _empty_summary() -> MandatoryTrainingSummary:
    return MandatoryTrainingSummary(
        total=0,
        materialized=0,
        missing_enrollment=0,
        protected_assignment=0,
        stale_managed_enrollment=0,
        action_materialize=0,
        action_review_stale=0,
    )


def test_mandatory_training_routes_share_reporting_roles():
    for route in mandatory_training_router.router.routes:
        role_dependencies = [
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.call is not None and dependency.call.__name__ == "role_checker"
        ]
        assert role_dependencies, route.path
        allowed_roles = getclosurevars(role_dependencies[0]).nonlocals["allowed_roles"]
        assert allowed_roles == ("admin", "methodologist", "superadmin")


def test_application_registers_mandatory_training_routes():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/admin/mandatory-training" in paths
    assert "/api/v1/admin/mandatory-training/summary" in paths


@pytest.mark.asyncio
async def test_routes_forward_one_tenant_filter_and_disable_caching(monkeypatch):
    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="admin")
    observed = []

    async def fake_page(_db, actual_tenant_id, filters, *, limit, offset):
        assert actual_tenant_id == tenant_id
        observed.append((filters, limit, offset))
        return MandatoryTrainingPage(items=[], total=0, limit=limit, offset=offset)

    async def fake_summary(_db, actual_tenant_id, filters):
        assert actual_tenant_id == tenant_id
        observed.append(filters)
        return _empty_summary()

    monkeypatch.setattr(mandatory_training_router, "get_mandatory_training_page", fake_page)
    monkeypatch.setattr(mandatory_training_router, "get_mandatory_training_summary", fake_summary)
    common = {
        "course_id": None,
        "organization_unit_id": None,
        "position_id": None,
        "requirement_state": "missing_enrollment",
        "action_required": "materialize",
        "search": "Aida",
        "include_inactive": False,
        "db": object(),
        "user": user,
    }
    page_response = Response()
    summary_response = Response()

    await list_mandatory_training(
        response=page_response,
        limit=25,
        offset=10,
        **common,
    )
    await mandatory_training_summary(response=summary_response, **common)

    assert observed[0][0].requirement_state == "missing_enrollment"
    assert observed[0][0].action_required == "materialize"
    assert observed[0][0].search == "Aida"
    assert observed[0][1:] == (25, 10)
    assert observed[1].model_dump() == observed[0][0].model_dump()
    assert page_response.headers["Cache-Control"] == "no-store"
    assert summary_response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_routes_fail_closed_for_oversized_scope_and_empty_superadmin_context(monkeypatch):
    async def oversized(*_args, **_kwargs):
        raise ValueError("mandatory_training_scope_too_large")

    monkeypatch.setattr(mandatory_training_router, "get_mandatory_training_page", oversized)
    common = {
        "response": Response(),
        "course_id": None,
        "organization_unit_id": None,
        "position_id": None,
        "requirement_state": None,
        "action_required": None,
        "search": None,
        "include_inactive": False,
        "limit": 100,
        "offset": 0,
        "db": object(),
    }

    with pytest.raises(HTTPException) as exc:
        await list_mandatory_training(
            user=SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="admin"),
            **common,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "mandatory_training_scope_too_large"}

    empty = await list_mandatory_training(
        user=SimpleNamespace(id=uuid4(), tenant_id=None, role="superadmin"),
        **{**common, "response": Response()},
    )
    assert empty == MandatoryTrainingPage(items=[], total=0, limit=100, offset=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("responsible_user_ids", [frozenset({uuid4(), uuid4()}), frozenset()])
async def test_page_and_summary_apply_the_same_restricted_reporting_scope(
    monkeypatch,
    responsible_user_ids,
):
    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    observed = []

    async def fake_scope(*_args, **_kwargs):
        return SimpleNamespace(
            mode=ReportingScopeMode.RESTRICTED,
            user_ids=responsible_user_ids,
        )

    async def fake_page(_db, actual_tenant_id, filters, *, limit, offset):
        assert actual_tenant_id == tenant_id
        observed.append(filters.responsible_user_ids)
        return MandatoryTrainingPage(items=[], total=0, limit=limit, offset=offset)

    async def fake_summary(_db, actual_tenant_id, filters):
        assert actual_tenant_id == tenant_id
        observed.append(filters.responsible_user_ids)
        return _empty_summary()

    monkeypatch.setattr(mandatory_training_router, "resolve_reporting_scope", fake_scope)
    monkeypatch.setattr(mandatory_training_router, "get_mandatory_training_page", fake_page)
    monkeypatch.setattr(mandatory_training_router, "get_mandatory_training_summary", fake_summary)
    common = {
        "response": Response(),
        "course_id": None,
        "organization_unit_id": None,
        "position_id": None,
        "requirement_state": None,
        "action_required": None,
        "search": None,
        "include_inactive": False,
        "db": object(),
        "user": user,
    }

    page = await list_mandatory_training(limit=50, offset=0, **common)
    await mandatory_training_summary(**{**common, "response": Response()})

    assert observed == [responsible_user_ids, responsible_user_ids]
    assert page.reporting_scope == "restricted"
