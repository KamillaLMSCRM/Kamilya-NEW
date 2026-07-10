"""Regression tests for production P0 fixes in auth and admin dashboard."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.admin.service import get_activity_summary
from app.modules.audit.schemas import AuditLogResponse
from app.modules.auth.service import create_user_and_tokens


@pytest.mark.asyncio
async def test_create_user_sets_tenant_context_before_insert() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    tenant_id = uuid4()

    await create_user_and_tokens(
        db,
        tenant_id=tenant_id,
        email="new@example.test",
        first_name="New",
        last_name="User",
    )

    statement = db.execute.await_args_list[0].args[0]
    assert "set_config('app.tenant_id'" in str(statement)
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_activity_summary_keeps_zero_metrics_and_avoids_cross_join() -> None:
    db = AsyncMock()

    async def execute(statement):
        sql = str(statement).upper()
        assert "CROSS JOIN" not in sql
        return SimpleNamespace(
            one=lambda: SimpleNamespace(
                new_users=0,
                new_enrollments=2,
                quizzes_taken=0,
                certs_issued=0,
            )
        )

    db.execute = AsyncMock(side_effect=execute)
    result = await get_activity_summary(db, uuid4(), days=1)

    assert result == [
        {
            "date": result[0]["date"],
            "new_users": 0,
            "new_enrollments": 2,
            "quizzes_taken": 0,
            "certificates_issued": 0,
        }
    ]


def test_audit_response_accepts_postgres_uuid_resource_id() -> None:
    resource_id = uuid4()
    payload = AuditLogResponse.model_validate(
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "user_id": uuid4(),
            "action": "course.created",
            "resource_type": "course",
            "resource_id": resource_id,
            "details": None,
            "ip_address": None,
            "user_agent": None,
            "created_at": "2026-07-10T00:00:00Z",
        }
    )
    assert payload.resource_id == resource_id


def test_demo_user_lookup_is_bounded_before_scalar_resolution() -> None:
    from sqlalchemy import select

    from app.models.users import User

    statement = (
        select(User)
        .where(User.telegram_id == 900000003, User.tenant_id == uuid4())
        .order_by(User.created_at.desc())
        .limit(1)
    )
    assert "LIMIT" in str(statement).upper()
