from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.modules.editor_assistant.service import (
    _MAX_OPERATION_CONSTRAINTS_BYTES,
    EditorActorContext,
    EditorIdempotencyCollisionError,
    EditorRequestDraft,
    EditorRequestService,
    EditorRequestServiceError,
)


class FakeRepository:
    def __init__(self) -> None:
        self.requests: dict[UUID, object] = {}
        self.events: list[object] = []
        self.claim_calls = 0
        self.allowed_actors: set[tuple[object, object]] = set()

    async def actor_exists_for_tenant(self, actor_id: object, tenant_id: object) -> bool:
        return (tenant_id, actor_id) in self.allowed_actors

    async def claim_request(self, request: object) -> tuple[object, bool]:
        self.claim_calls += 1
        request_id = request.id
        existing = self.requests.get(request_id)
        if existing is not None:
            return existing, False
        self.requests[request_id] = request
        return request, True

    async def _create_request(self, request: object) -> object:
        self.requests[request.id] = request
        return request

    async def next_event_sequence(self, request_id: object, tenant_id: object) -> int:
        del request_id, tenant_id
        return len(self.events) + 1

    async def _append_event(self, event: object) -> object:
        self.events.append(event)
        return event


def _service(repo: FakeRepository) -> EditorRequestService:
    service = object.__new__(EditorRequestService)
    service._repo = repo
    return service


def _actor(*, tenant_id: UUID | None = None, actor_id: UUID | None = None):
    return EditorActorContext(
        tenant_id=tenant_id or uuid4(),
        actor_id=actor_id or uuid4(),
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


async def test_same_tenant_key_and_fingerprint_reuses_one_request_and_event():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    draft = _draft()

    first = await service.create_or_reuse_request(actor, draft, request_key="request-1")
    second = await service.create_or_reuse_request(actor, draft, request_key="request-1")

    assert second is first
    assert len(repo.requests) == 1
    assert len(repo.events) == 1
    assert repo.claim_calls == 2


async def test_legacy_create_request_remains_source_compatible_with_null_fingerprint():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))

    request = await service.create_request(actor, _draft())

    assert request.request_fingerprint_sha256 is None
    assert request.operation_constraints == {"maximum_operations": 3}
    assert len(repo.requests) == 1
    assert len(repo.events) == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"intent_category": "simplify_language"},
        {"target_entity_id": uuid4()},
        {"base_content_version": "b" * 64},
        {"instruction_text": "Do not reflect this changed instruction."},
    ],
)
async def test_same_key_with_changed_canonical_request_is_bounded_conflict(changed):
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    original = _draft()
    await service.create_or_reuse_request(actor, original, request_key="request-2")

    with pytest.raises(EditorIdempotencyCollisionError) as error:
        await service.create_or_reuse_request(
            actor,
            replace(original, **changed),
            request_key="request-2",
        )

    assert str(error.value) == "Editor request idempotency collision"
    assert all(str(value) not in str(error.value) for value in changed.values())
    assert len(repo.requests) == 1
    assert len(repo.events) == 1


async def test_same_key_is_independent_between_tenants():
    repo = FakeRepository()
    service = _service(repo)
    first_actor = _actor()
    second_actor = _actor()
    repo.allowed_actors.update(
        {
            (first_actor.tenant_id, first_actor.actor_id),
            (second_actor.tenant_id, second_actor.actor_id),
        }
    )
    target_id = uuid4()
    draft = _draft(target_entity_id=target_id)

    first = await service.create_or_reuse_request(
        first_actor, draft, request_key="shared-key"
    )
    second = await service.create_or_reuse_request(
        second_actor, draft, request_key="shared-key"
    )

    assert first.id != second.id
    assert len(repo.requests) == 2
    assert len(repo.events) == 2


async def test_actor_authority_is_checked_before_repository_claim():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()

    with pytest.raises(EditorRequestServiceError) as error:
        await service.create_or_reuse_request(actor, _draft(), request_key="request-3")

    assert str(error.value) == "Editor actor is not available in this tenant"
    assert repo.claim_calls == 0


async def test_only_canonical_instruction_and_bounded_hash_are_stored():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    instruction = "  Cafe\u0301: rewrite without a second copy.  "

    request = await service.create_or_reuse_request(
        actor,
        _draft(instruction_text=instruction),
        request_key="opaque-request-4",
    )

    assert request.instruction_text == "Caf\u00e9: rewrite without a second copy."
    assert request.operation_constraints == {"maximum_operations": 3}
    fingerprint = request.request_fingerprint_sha256
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")
    assert instruction.strip() not in repr(request.operation_constraints)
    assert "opaque-request-4" not in repr(request.operation_constraints)


async def test_decomposed_and_precomposed_instruction_reuse_the_same_request():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    draft = _draft(instruction_text="  Cafe\u0301  ")

    first = await service.create_or_reuse_request(actor, draft, request_key="nfc-key")
    second = await service.create_or_reuse_request(
        actor,
        replace(draft, instruction_text="Caf\u00e9"),
        request_key="nfc-key",
    )

    assert second is first
    assert first.instruction_text == "Caf\u00e9"


async def test_uuid_object_and_uppercase_uuid_string_are_the_same_request_key():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    draft = _draft()
    key = uuid4()

    first = await service.create_or_reuse_request(actor, draft, request_key=key)
    second = await service.create_or_reuse_request(
        actor,
        draft,
        request_key=str(key).upper(),
    )

    assert second is first
    assert len(repo.requests) == 1


async def test_non_uuid_opaque_request_keys_remain_case_sensitive():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    draft = _draft()

    first = await service.create_or_reuse_request(actor, draft, request_key="CaseKey")
    second = await service.create_or_reuse_request(actor, draft, request_key="casekey")

    assert first.id != second.id
    assert len(repo.requests) == 2


async def test_retry_expiry_is_not_fingerprinted_and_first_expiry_is_preserved():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    first_expiry = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    equivalent_offset = first_expiry.astimezone(timezone(timedelta(hours=5)))
    draft = _draft(instruction_expires_at=first_expiry)

    first = await service.create_or_reuse_request(actor, draft, request_key="expiry-key")
    second = await service.create_or_reuse_request(
        actor,
        replace(draft, instruction_expires_at=equivalent_offset),
        request_key="expiry-key",
    )

    assert second is first
    assert first.instruction_expires_at is first_expiry


async def test_naive_instruction_expiry_is_rejected_before_claim():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))

    with pytest.raises(EditorRequestServiceError) as error:
        await service.create_or_reuse_request(
            actor,
            _draft(instruction_expires_at=datetime(2026, 9, 1, 8, 0)),
            request_key="naive-expiry",
        )

    assert str(error.value) == "Invalid editor instruction expiry"
    assert repo.claim_calls == 0


async def test_different_actor_reusing_key_receives_bounded_conflict():
    repo = FakeRepository()
    service = _service(repo)
    tenant_id = uuid4()
    first_actor = _actor(tenant_id=tenant_id)
    second_actor = _actor(tenant_id=tenant_id)
    repo.allowed_actors.update(
        {
            (tenant_id, first_actor.actor_id),
            (tenant_id, second_actor.actor_id),
        }
    )
    draft = _draft()
    await service.create_or_reuse_request(first_actor, draft, request_key="actor-key")

    with pytest.raises(EditorIdempotencyCollisionError) as error:
        await service.create_or_reuse_request(
            second_actor,
            draft,
            request_key="actor-key",
        )

    assert str(error.value) == "Editor request idempotency collision"
    assert str(second_actor.actor_id) not in str(error.value)


async def test_maximum_business_constraints_are_preserved_without_internal_projection():
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))
    template = {"business_rule": ""}
    overhead = len(
        json.dumps(template, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    maximum_constraints = {
        "business_rule": "x" * (_MAX_OPERATION_CONSTRAINTS_BYTES - overhead)
    }

    request = await service.create_or_reuse_request(
        actor,
        _draft(
            operation_constraints=maximum_constraints,
            model_id="provider-model-must-not-project",
        ),
        request_key="maximum-constraints",
    )

    assert request.operation_constraints == maximum_constraints
    assert "request_fingerprint_sha256" not in request.operation_constraints
    assert "provider" not in repr(request.operation_constraints)
    assert "model" not in repr(request.operation_constraints)


@pytest.mark.parametrize("request_key", ["", "bad key", "x" * 121, "ключ"])
async def test_request_key_validation_is_bounded_and_non_reflecting(request_key):
    repo = FakeRepository()
    service = _service(repo)
    actor = _actor()
    repo.allowed_actors.add((actor.tenant_id, actor.actor_id))

    with pytest.raises(EditorRequestServiceError) as error:
        await service.create_or_reuse_request(actor, _draft(), request_key=request_key)

    assert str(error.value) == "Invalid editor request key"
    if request_key:
        assert request_key not in str(error.value)
    assert repo.claim_calls == 0
