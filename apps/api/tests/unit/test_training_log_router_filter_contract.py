from inspect import signature
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.modules.training_log import router as training_log_router
from app.modules.training_log.router import list_training_log, training_log_summary
from app.modules.training_log.schemas import TrainingLogPage, TrainingLogSummary
from app.modules.training_responsibility.policy import ReportingScopeMode


def test_training_log_routes_expose_exact_enrollment_filter() -> None:
    assert "enrollment_id" in signature(list_training_log).parameters
    assert "enrollment_id" in signature(training_log_summary).parameters


@pytest.mark.asyncio
async def test_training_log_routes_forward_exact_enrollment_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    enrollment_id = uuid4()
    tenant_id = uuid4()
    observed: list[object] = []

    async def fake_summary(_db, actual_tenant_id, filters):
        assert actual_tenant_id == tenant_id
        observed.append(filters.enrollment_id)
        return TrainingLogSummary(total=0, assigned=0, in_progress=0, completed=0)

    async def fake_page(_db, actual_tenant_id, filters, *, limit, offset):
        assert actual_tenant_id == tenant_id
        assert (limit, offset) == (100, 0)
        observed.append(filters.enrollment_id)
        return TrainingLogPage(items=[], total=0, limit=limit, offset=offset)

    monkeypatch.setattr(training_log_router, "get_training_log_summary", fake_summary)
    monkeypatch.setattr(training_log_router, "get_training_log_page", fake_page)
    common = {
        "enrollment_id": enrollment_id,
        "course_id": None,
        "department_id": None,
        "position_id": None,
        "status": None,
        "history": False,
        "delivery_type": None,
        "date_from": None,
        "date_to": None,
        "search": None,
        "db": object(),
        "user": SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="admin"),
    }

    await training_log_summary(response=Response(), **common)
    await list_training_log(
        request=Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}),
        response=Response(),
        limit=100,
        offset=0,
        format="json",
        lang="ru",
        **common,
    )

    assert observed == [enrollment_id, enrollment_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("responsible_user_ids", [frozenset({uuid4(), uuid4()}), frozenset()])
async def test_training_log_json_summary_and_csv_share_restricted_scope(
    monkeypatch: pytest.MonkeyPatch,
    responsible_user_ids,
) -> None:
    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    observed: list[tuple[str, object]] = []

    async def fake_scope(*_args, **_kwargs):
        return SimpleNamespace(
            mode=ReportingScopeMode.RESTRICTED,
            user_ids=responsible_user_ids,
        )

    async def fake_summary(_db, actual_tenant_id, filters):
        assert actual_tenant_id == tenant_id
        observed.append(("summary", filters.responsible_user_ids))
        return TrainingLogSummary(total=0, assigned=0, in_progress=0, completed=0)

    async def fake_page(_db, actual_tenant_id, filters, *, limit, offset):
        assert actual_tenant_id == tenant_id
        assert (limit, offset) == (100, 0)
        observed.append(("json", filters.responsible_user_ids))
        return TrainingLogPage(items=[], total=0, limit=limit, offset=offset)

    def fake_csv(_db, actual_tenant_id, filters, *, lang):
        assert actual_tenant_id == tenant_id
        assert lang == "ru"
        observed.append(("csv", filters.responsible_user_ids))

        async def chunks():
            yield b""

        return chunks()

    monkeypatch.setattr(training_log_router, "resolve_reporting_scope", fake_scope)
    monkeypatch.setattr(training_log_router, "get_training_log_summary", fake_summary)
    monkeypatch.setattr(training_log_router, "get_training_log_page", fake_page)
    monkeypatch.setattr(training_log_router, "stream_training_log_as_csv", fake_csv)
    common = {
        "enrollment_id": None,
        "course_id": None,
        "department_id": None,
        "position_id": None,
        "status": None,
        "history": False,
        "delivery_type": None,
        "date_from": None,
        "date_to": None,
        "search": None,
        "db": object(),
        "user": user,
    }

    await training_log_summary(response=Response(), **common)
    page = await list_training_log(
        request=Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}),
        response=Response(),
        limit=100,
        offset=0,
        format="json",
        lang="ru",
        **common,
    )
    await list_training_log(
        request=Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}),
        response=Response(),
        limit=100,
        offset=0,
        format="csv",
        lang="ru",
        **common,
    )

    assert observed == [
        ("summary", responsible_user_ids),
        ("json", responsible_user_ids),
        ("csv", responsible_user_ids),
    ]
    assert page.reporting_scope == "restricted"
