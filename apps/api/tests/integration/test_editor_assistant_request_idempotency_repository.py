from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.editor_assistant.models import AIEditorRequest, AIEditorRequestEvent
from app.modules.editor_assistant.service import (
    EditorActorContext,
    EditorIdempotencyCollisionError,
    EditorRequestDraft,
    EditorRequestService,
)


def _draft(**overrides: object) -> EditorRequestDraft:
    values = {
        "target_entity_type": "quiz_question",
        "target_entity_id": uuid4(),
        "instruction_text": "Rewrite this question clearly.",
        "intent_category": "rewrite_wording",
        "base_content_version": "a" * 64,
        "locale": "ru",
        "selected_scope": "question",
        "operation_constraints": {"maximum_operations": 3},
    }
    values.update(overrides)
    return EditorRequestDraft(**values)


def _actor(tenant, user) -> EditorActorContext:
    return EditorActorContext(tenant_id=tenant.id, actor_id=user.id)


async def test_repository_primary_key_claim_reuses_one_request_and_requested_event(
    db_session, make_tenant, make_user, set_current_tenant
):
    tenant = await make_tenant(name="Request Idempotency Tenant")
    user = await make_user(tenant, role="methodologist")
    await set_current_tenant(tenant)
    service = EditorRequestService(db_session)
    draft = _draft()

    first = await service.create_or_reuse_request(
        _actor(tenant, user), draft, request_key="integration-request-1"
    )
    second = await service.create_or_reuse_request(
        _actor(tenant, user), draft, request_key="integration-request-1"
    )

    assert second.id == first.id
    assert first.request_fingerprint_sha256 is not None
    assert len(first.request_fingerprint_sha256) == 64
    assert first.operation_constraints == {"maximum_operations": 3}
    request_count = await db_session.scalar(
        select(func.count())
        .select_from(AIEditorRequest)
        .where(AIEditorRequest.id == first.id, AIEditorRequest.tenant_id == tenant.id)
    )
    event_count = await db_session.scalar(
        select(func.count())
        .select_from(AIEditorRequestEvent)
        .where(
            AIEditorRequestEvent.request_id == first.id,
            AIEditorRequestEvent.tenant_id == tenant.id,
            AIEditorRequestEvent.event_key == "requested",
        )
    )
    assert event_count == 1
    assert request_count == 1


async def test_retry_preserves_first_creator_expiry(
    db_session, make_tenant, make_user, set_current_tenant
):
    from datetime import UTC, datetime, timedelta, timezone

    tenant = await make_tenant(name="Request Expiry Tenant")
    user = await make_user(tenant, role="methodologist")
    await set_current_tenant(tenant)
    service = EditorRequestService(db_session)
    first_expiry = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    draft = _draft(instruction_expires_at=first_expiry)

    first = await service.create_or_reuse_request(
        _actor(tenant, user), draft, request_key="integration-expiry"
    )
    second = await service.create_or_reuse_request(
        _actor(tenant, user),
        replace(
            draft,
            instruction_expires_at=first_expiry.astimezone(
                timezone(timedelta(hours=5))
            ),
        ),
        request_key="integration-expiry",
    )

    assert second.id == first.id
    assert second.instruction_expires_at == first.instruction_expires_at


async def test_repository_claim_rejects_mismatch_without_second_row(
    db_session, make_tenant, make_user, set_current_tenant
):
    tenant = await make_tenant(name="Request Conflict Tenant")
    user = await make_user(tenant, role="methodologist")
    await set_current_tenant(tenant)
    service = EditorRequestService(db_session)
    draft = _draft()
    first = await service.create_or_reuse_request(
        _actor(tenant, user), draft, request_key="integration-request-2"
    )

    with pytest.raises(EditorIdempotencyCollisionError) as error:
        await service.create_or_reuse_request(
            _actor(tenant, user),
            replace(draft, instruction_text="A different private instruction."),
            request_key="integration-request-2",
        )

    assert str(error.value) == "Editor request idempotency collision"
    request_count = await db_session.scalar(
        select(func.count())
        .select_from(AIEditorRequest)
        .where(AIEditorRequest.id == first.id, AIEditorRequest.tenant_id == tenant.id)
    )
    assert request_count == 1


async def test_same_request_key_is_independent_across_tenants(
    db_session, make_tenant, make_user, set_current_tenant
):
    first_tenant = await make_tenant(name="Request Tenant One")
    first_user = await make_user(first_tenant, role="methodologist")
    second_tenant = await make_tenant(name="Request Tenant Two")
    second_user = await make_user(second_tenant, role="methodologist")
    service = EditorRequestService(db_session)
    draft = _draft()

    await set_current_tenant(first_tenant)
    first = await service.create_or_reuse_request(
        _actor(first_tenant, first_user), draft, request_key="shared-integration-key"
    )
    await set_current_tenant(second_tenant)
    second = await service.create_or_reuse_request(
        _actor(second_tenant, second_user), draft, request_key="shared-integration-key"
    )

    assert first.id != second.id
    assert first.tenant_id == first_tenant.id
    assert second.tenant_id == second_tenant.id
