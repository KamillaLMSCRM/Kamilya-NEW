from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.modules.source_actuality import router
from app.modules.source_actuality.schemas import SourcePolicyUpdate


class _Db:
    async def commit(self) -> None:
        return None


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/v1/admin/source-actuality/source/policy",
            "headers": [],
            "client": ("127.0.0.1", 43210),
        }
    )


@pytest.mark.asyncio
async def test_policy_update_under_impersonation_separates_domain_and_audit_actors(monkeypatch) -> None:
    tenant_id = uuid4()
    platform_superadmin_id = uuid4()
    source_family_id = uuid4()
    captured: dict[str, UUID | None] = {}
    now = datetime.now(UTC)

    async def fake_upsert_policy(_db, **kwargs):
        captured["domain_actor_id"] = kwargs["actor_id"]
        return SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            source_family_id=source_family_id,
            owner_id=None,
            reviewed_at=None,
            next_review_at=None,
            created_at=now,
            updated_at=now,
        )

    async def fake_log_action(_db, _tenant_id, _action, _resource_type, **kwargs):
        captured["audit_actor_id"] = kwargs["user_id"]

    monkeypatch.setattr(router, "upsert_policy", fake_upsert_policy)
    monkeypatch.setattr(router, "log_action", fake_log_action)

    impersonated = SimpleNamespace(
        id=platform_superadmin_id,
        tenant_id=tenant_id,
        role="methodologist",
        is_impersonating=True,
    )

    await router.put_source_policy(
        source_family_id,
        SourcePolicyUpdate(),
        _request(),
        Response(),
        db=_Db(),
        user=impersonated,
    )

    assert captured == {
        "domain_actor_id": None,
        "audit_actor_id": platform_superadmin_id,
    }


@pytest.mark.asyncio
async def test_policy_update_by_methodologist_uses_same_domain_and_audit_actor(monkeypatch) -> None:
    tenant_id = uuid4()
    methodologist_id = uuid4()
    source_family_id = uuid4()
    captured: dict[str, UUID | None] = {}
    now = datetime.now(UTC)

    async def fake_upsert_policy(_db, **kwargs):
        captured["domain_actor_id"] = kwargs["actor_id"]
        return SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            source_family_id=source_family_id,
            owner_id=None,
            reviewed_at=None,
            next_review_at=None,
            created_at=now,
            updated_at=now,
        )

    async def fake_log_action(_db, _tenant_id, _action, _resource_type, **kwargs):
        captured["audit_actor_id"] = kwargs["user_id"]

    monkeypatch.setattr(router, "upsert_policy", fake_upsert_policy)
    monkeypatch.setattr(router, "log_action", fake_log_action)

    methodologist = SimpleNamespace(
        id=methodologist_id,
        tenant_id=tenant_id,
        role="methodologist",
        is_impersonating=False,
    )

    await router.put_source_policy(
        source_family_id,
        SourcePolicyUpdate(),
        _request(),
        Response(),
        db=_Db(),
        user=methodologist,
    )

    assert captured == {
        "domain_actor_id": methodologist_id,
        "audit_actor_id": methodologist_id,
    }
