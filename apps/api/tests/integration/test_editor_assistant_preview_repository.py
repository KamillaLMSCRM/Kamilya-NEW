"""Behavioral contract for durable editor-assistant preview claims."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.core.db import async_session_factory
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.editor_assistant.models import AIEditorRequest
from app.modules.editor_assistant.patch_contract import (
    PatchContractError,
    PatchIdempotencyCollisionError,
)
from app.modules.editor_assistant.repository import EditorRequestRepository

pytestmark = pytest.mark.asyncio

_FINGERPRINT = "a" * 64
_OTHER_FINGERPRINT = "b" * 64


async def _set_tenant(session, tenant_id: UUID, *, runtime_role: bool = False) -> None:
    if runtime_role:
        await session.execute(text("SET LOCAL ROLE lms_app"))
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def _seed_request() -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    actor_id = uuid4()
    request_id = uuid4()
    async with async_session_factory() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name="Synthetic Preview Tenant",
                slug=f"preview-{tenant_id.hex}",
                status="active",
                plan="free",
                is_demo=True,
                settings={},
            )
        )
        await session.flush()
        await _set_tenant(session, tenant_id)
        session.add(
            User(
                id=actor_id,
                tenant_id=tenant_id,
                email=f"preview-{actor_id.hex}@example.test",
                first_name="Synthetic",
                last_name="Methodologist",
                role="methodologist",
                is_active=True,
            )
        )
        session.add(
            AIEditorRequest(
                id=request_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                target_entity_type="question",
                target_entity_id=uuid4(),
                intent_category="rewrite_wording",
                selected_scope="question.text",
                operation_constraints={},
                base_content_version="synthetic-v1",
                locale="ru",
                instruction_text="Synthetic instruction",
                outcome_state="requested",
            )
        )
        await session.commit()
    return tenant_id, request_id


async def _claim(
    tenant_id: UUID,
    request_id: UUID,
    *,
    preview_key: str = "preview-key",
    fingerprint: str = _FINGERPRINT,
):
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        result = await EditorRequestRepository(session).claim_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
        )
        await session.commit()
        return result


async def test_first_claim_is_only_owner_and_public_record_hides_digest() -> None:
    tenant_id, request_id = await _seed_request()

    owner = await _claim(tenant_id, request_id)
    observer = await _claim(tenant_id, request_id)

    assert owner is not None
    assert owner.state == "pending"
    assert owner.owns_claim is True
    assert isinstance(owner.claim_token, str) and len(owner.claim_token) >= 32
    assert not hasattr(owner, "claim_token_sha256")
    assert observer is not None
    assert observer.id == owner.id
    assert observer.state == "pending"
    assert observer.owns_claim is False
    assert observer.claim_token is None
    with pytest.raises(FrozenInstanceError):
        owner.state = "failed"


async def test_key_collision_is_safe_and_does_not_reflect_payload() -> None:
    tenant_id, request_id = await _seed_request()
    await _claim(tenant_id, request_id)

    with pytest.raises(PatchIdempotencyCollisionError) as error:
        await _claim(tenant_id, request_id, fingerprint=_OTHER_FINGERPRINT)

    message = str(error.value)
    assert message == "Editor preview idempotency collision"
    assert _FINGERPRINT not in message
    assert _OTHER_FINGERPRINT not in message


async def test_complete_is_owner_only_immutable_and_returns_canonical_result() -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id)
    assert owner is not None and owner.claim_token is not None
    result = {"operations": [{"field": "question.text", "value": "Synthetic"}]}

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        repository = EditorRequestRepository(session)
        wrong = await repository.complete_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
            claim_token="wrong-token-that-never-owned-the-preview",
            completed_result=result,
        )
        completed = await repository.complete_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            completed_result=result,
        )
        await session.commit()

    assert wrong is None
    assert completed is not None
    assert completed.state == "completed"
    assert completed.owns_claim is False
    assert completed.claim_token is None
    assert isinstance(completed.completed_result, Mapping)
    assert completed.completed_result == result
    assert completed.completed_at is not None
    with pytest.raises(TypeError):
        completed.completed_result["new"] = "forbidden"

    retry = await _claim(tenant_id, request_id)
    assert retry is not None
    assert retry.id == completed.id
    assert retry.completed_result == completed.completed_result

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        overwrite = await EditorRequestRepository(session).complete_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            completed_result={"operations": []},
        )
        assert overwrite is None


async def test_fail_normalizes_unsafe_code_and_requires_explicit_reclaim() -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id)
    assert owner is not None and owner.claim_token is not None

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        failed = await EditorRequestRepository(session).fail_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            failure_code="Traceback: tenant content must never persist",
        )
        await session.commit()

    assert failed is not None
    assert failed.state == "failed"
    assert failed.failure_code == "internal_error"
    assert failed.failed_at is not None
    assert failed.claim_token is None
    observed = await _claim(tenant_id, request_id)
    assert observed is not None
    assert observed.state == "failed"
    assert observed.owns_claim is False

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        reclaimed = await EditorRequestRepository(session).reclaim_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
        )
        await session.commit()
    assert reclaimed is not None
    assert reclaimed.state == "pending"
    assert reclaimed.owns_claim is True
    assert reclaimed.claim_token is not None
    assert reclaimed.claim_token != owner.claim_token


async def test_wrong_or_stale_token_cannot_fail_reclaimed_preview() -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id)
    assert owner is not None and owner.claim_token is not None
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        repository = EditorRequestRepository(session)
        await repository.fail_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            failure_code="provider_timeout",
        )
        await session.commit()
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        reclaimed = await EditorRequestRepository(session).reclaim_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
        )
        await session.commit()
    assert reclaimed is not None and reclaimed.claim_token is not None

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        stale = await EditorRequestRepository(session).fail_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            failure_code="provider_unavailable",
        )
        current = await EditorRequestRepository(session).read_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
        )
    assert stale is None
    assert current is not None and current.state == "pending"


async def test_absent_and_cross_tenant_requests_are_non_enumerating() -> None:
    tenant_id, request_id = await _seed_request()
    other_tenant_id, _ = await _seed_request()

    assert await _claim(tenant_id, uuid4(), preview_key="absent-request") is None
    assert await _claim(other_tenant_id, request_id, preview_key="cross-tenant") is None
    async with async_session_factory() as session:
        await _set_tenant(session, other_tenant_id, runtime_role=True)
        missing = await EditorRequestRepository(session).read_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="preview-key",
        )
    assert missing is None


@pytest.mark.parametrize(
    ("preview_key", "fingerprint"),
    [
        ("", _FINGERPRINT),
        ("contains whitespace", _FINGERPRINT),
        ("x" * 121, _FINGERPRINT),
        ("valid-key", "A" * 64),
        ("valid-key", "a" * 63),
    ],
)
async def test_invalid_identity_is_rejected_before_persistence(
    preview_key: str, fingerprint: str
) -> None:
    tenant_id, request_id = await _seed_request()
    with pytest.raises(PatchContractError) as error:
        await _claim(
            tenant_id,
            request_id,
            preview_key=preview_key,
            fingerprint=fingerprint,
        )
    assert str(error.value) == "Invalid editor preview identity"


async def test_completion_accepts_only_bounded_json_mapping() -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id)
    assert owner is not None and owner.claim_token is not None
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        repository = EditorRequestRepository(session)
        with pytest.raises(PatchContractError, match="Invalid editor preview result"):
            await repository.complete_preview(
                tenant_id=tenant_id,
                request_id=request_id,
                preview_key="preview-key",
                payload_fingerprint=_FINGERPRINT,
                claim_token=owner.claim_token,
                completed_result=["not", "a", "mapping"],
            )
        with pytest.raises(PatchContractError, match="Invalid editor preview result"):
            await repository.complete_preview(
                tenant_id=tenant_id,
                request_id=request_id,
                preview_key="preview-key",
                payload_fingerprint=_FINGERPRINT,
                claim_token=owner.claim_token,
                completed_result={"value": "x" * 70_000},
            )


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "raw_instruction",
        "INSTRUCTION_TEXT",
        "Raw_Provider_Response",
        "provider_response",
        "source_excerpt",
        "SOURCE_EXCERPTS",
        "exception_text",
        "TraceBack",
    ],
)
async def test_completion_rejects_forbidden_nested_content_without_transition(
    forbidden_key: str,
) -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(
        tenant_id,
        request_id,
        preview_key=f"forbidden-{forbidden_key.casefold()}",
    )
    assert owner is not None and owner.claim_token is not None
    reflected_content = "synthetic reflected content must not appear"
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        repository = EditorRequestRepository(session)
        with pytest.raises(PatchContractError) as error:
            await repository.complete_preview(
                tenant_id=tenant_id,
                request_id=request_id,
                preview_key=f"forbidden-{forbidden_key.casefold()}",
                payload_fingerprint=_FINGERPRINT,
                claim_token=owner.claim_token,
                completed_result={
                    "patch": {
                        "operations": [
                            {forbidden_key: reflected_content},
                        ]
                    }
                },
            )
        current = await repository.read_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key=f"forbidden-{forbidden_key.casefold()}",
        )
    assert str(error.value) == "Invalid editor preview result"
    assert reflected_content not in str(error.value)
    assert forbidden_key not in str(error.value)
    assert current is not None and current.state == "pending"


@pytest.mark.parametrize(
    "invalid_token",
    ["", "short", "contains whitespace", "contains/slash", "x" * 129, None],
)
async def test_malformed_claim_token_cannot_complete_or_fail(
    invalid_token,
) -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id, preview_key="invalid-token")
    assert owner is not None and owner.claim_token is not None
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        repository = EditorRequestRepository(session)
        assert (
            await repository.complete_preview(
                tenant_id=tenant_id,
                request_id=request_id,
                preview_key="invalid-token",
                payload_fingerprint=_FINGERPRINT,
                claim_token=invalid_token,
                completed_result={"operations": []},
            )
            is None
        )
        assert (
            await repository.fail_preview(
                tenant_id=tenant_id,
                request_id=request_id,
                preview_key="invalid-token",
                payload_fingerprint=_FINGERPRINT,
                claim_token=invalid_token,
                failure_code="provider_timeout",
            )
            is None
        )
        current = await repository.read_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="invalid-token",
        )
    assert current is not None and current.state == "pending"


async def test_unhashable_failure_code_normalizes_to_internal_error() -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id, preview_key="unhashable-failure")
    assert owner is not None and owner.claim_token is not None
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        failed = await EditorRequestRepository(session).fail_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="unhashable-failure",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            failure_code=["not", "hashable"],
        )
        await session.commit()
    assert failed is not None
    assert failed.state == "failed"
    assert failed.failure_code == "internal_error"


async def test_concurrent_first_claim_has_exactly_one_owner() -> None:
    tenant_id, request_id = await _seed_request()

    owners = await asyncio.gather(
        *[_claim(tenant_id, request_id, preview_key="concurrent-first") for _ in range(6)]
    )

    assert sum(item is not None and item.owns_claim for item in owners) == 1
    assert len({item.id for item in owners if item is not None}) == 1
    assert sum(item is not None and item.claim_token is not None for item in owners) == 1


async def test_concurrent_reclaim_has_exactly_one_owner() -> None:
    tenant_id, request_id = await _seed_request()
    owner = await _claim(tenant_id, request_id, preview_key="concurrent-reclaim")
    assert owner is not None and owner.claim_token is not None
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id, runtime_role=True)
        await EditorRequestRepository(session).fail_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key="concurrent-reclaim",
            payload_fingerprint=_FINGERPRINT,
            claim_token=owner.claim_token,
            failure_code="provider_timeout",
        )
        await session.commit()

    async def compete():
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id, runtime_role=True)
            result = await EditorRequestRepository(session).reclaim_preview(
                tenant_id=tenant_id,
                request_id=request_id,
                preview_key="concurrent-reclaim",
                payload_fingerprint=_FINGERPRINT,
            )
            await session.commit()
            return result

    outcomes = await asyncio.gather(*[compete() for _ in range(6)])
    assert sum(item is not None and item.owns_claim for item in outcomes) == 1
    assert len({item.id for item in outcomes if item is not None}) == 1
    assert sum(item is not None and item.claim_token is not None for item in outcomes) == 1
