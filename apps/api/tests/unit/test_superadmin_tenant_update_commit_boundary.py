"""Database-free regression tests for the superadmin tenant update boundary."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import InvalidRequestError

from app.modules.admin.superadmin import router
from app.modules.admin.superadmin.schemas import TenantResponse, TenantUpdate

TENANT_ID = UUID("83552ce6-8058-4561-abe3-cfbda14e030a")


class _Session:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.committed = False
        self.commit_calls = 0
        self.refresh_calls = 0
        self.commit_error = commit_error

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    async def refresh(self, _tenant) -> None:
        self.refresh_calls += 1
        if self.committed:
            raise InvalidRequestError("refresh must not run after the update commit")


class _Service:
    def __init__(self, db: _Session) -> None:
        self.db = db
        self.tenant = SimpleNamespace(id=TENANT_ID, is_demo=False)

    async def update_tenant(self, tenant_id, payload):
        assert tenant_id == TENANT_ID
        assert payload.model_dump(exclude_none=True) == {"is_demo": False}
        return self.tenant


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "unit-test"},
    )


@pytest.mark.asyncio
async def test_update_tenant_assembles_response_and_refreshes_before_commit(
    monkeypatch,
):
    db = _Session()
    svc = _Service(db)
    events: list[str] = []

    async def fake_log_action(*args, **kwargs):
        assert db.committed is False
        assert kwargs["details"] == {"is_demo": False}
        events.append("audit")

    async def fake_response(_svc, tenant):
        assert db.committed is False
        assert tenant.is_demo is False
        events.append("response")
        return {"id": str(tenant.id), "is_demo": tenant.is_demo}

    monkeypatch.setattr(router, "log_action", fake_log_action)
    monkeypatch.setattr(router, "_tenant_response", fake_response)

    result = await router.update_tenant(
        TENANT_ID,
        TenantUpdate(is_demo=False),
        _request(),
        user=SimpleNamespace(id=uuid4()),
        svc=svc,
    )

    assert result == {"id": str(TENANT_ID), "is_demo": False}
    assert events == ["audit", "response"]
    assert db.commit_calls == 1
    assert db.refresh_calls == 1


@pytest.mark.asyncio
async def test_update_tenant_response_failure_prevents_commit(monkeypatch):
    db = _Session()
    svc = _Service(db)
    audit_called = False

    async def fake_log_action(*args, **kwargs):
        nonlocal audit_called
        audit_called = True

    async def fail_response(*args, **kwargs):
        raise RuntimeError("response assembly failed")

    monkeypatch.setattr(router, "log_action", fake_log_action)
    monkeypatch.setattr(router, "_tenant_response", fail_response)

    with pytest.raises(RuntimeError, match="response assembly failed"):
        await router.update_tenant(
            TENANT_ID,
            TenantUpdate(is_demo=False),
            _request(),
            user=SimpleNamespace(id=uuid4()),
            svc=svc,
        )

    assert audit_called is True
    assert db.commit_calls == 0
    assert db.refresh_calls == 1


@pytest.mark.asyncio
async def test_update_tenant_commit_failure_propagates_after_response_assembly(monkeypatch):
    db = _Session(commit_error=RuntimeError("commit failed"))
    svc = _Service(db)
    response_called = False

    async def fake_log_action(*args, **kwargs):
        return None

    async def fake_response(_svc, tenant):
        nonlocal response_called
        response_called = True
        assert tenant.is_demo is False
        return TenantResponse.model_construct(id=tenant.id, is_demo=False)

    monkeypatch.setattr(router, "log_action", fake_log_action)
    monkeypatch.setattr(router, "_tenant_response", fake_response)

    with pytest.raises(RuntimeError, match="commit failed"):
        await router.update_tenant(
            TENANT_ID,
            TenantUpdate(is_demo=False),
            _request(),
            user=SimpleNamespace(id=uuid4()),
            svc=svc,
        )

    assert response_called is True
    assert db.commit_calls == 1
    assert db.refresh_calls == 1
