from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.candidate_assessments import service


def test_candidate_access_token_carries_only_routing_prefix_and_random_secret() -> None:
    tenant_id = uuid4()
    first = service.issue_access_token(tenant_id)
    second = service.issue_access_token(tenant_id)

    assert first.startswith(f"{tenant_id}.")
    assert service.tenant_from_access_token(first) == tenant_id
    assert first != second
    assert service.token_hash(first) != service.token_hash(second)


@pytest.mark.parametrize("token", ["", "opaque-only", ".missing-prefix", "not-a-uuid.secret"])
@pytest.mark.asyncio
async def test_malformed_candidate_token_fails_before_database_context(token: str) -> None:
    db = AsyncMock()

    assert await service.establish_context(db, token) is None
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_context_is_set_before_hash_lookup() -> None:
    tenant_id = uuid4()
    token = service.issue_access_token(tenant_id)
    db = AsyncMock()
    db.scalar.return_value = tenant_id

    assert await service.establish_context(db, token) == tenant_id
    db.execute.assert_awaited_once()
    db.scalar.assert_awaited_once()
    assert db.execute.await_args_list[0].args[1] == {"tid": str(tenant_id)}


@pytest.mark.asyncio
async def test_candidate_context_rejects_hash_not_found_inside_claimed_tenant() -> None:
    tenant_id = uuid4()
    db = AsyncMock()
    db.scalar.return_value = None

    assert await service.establish_context(db, service.issue_access_token(tenant_id)) is None
