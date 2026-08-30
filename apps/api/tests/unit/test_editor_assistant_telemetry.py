"""Focused contracts for the AI editor assistant telemetry foundation.

Covers Step 1 acceptance: tenant separation, idempotent lifecycle recording
and collisions, invalid transitions, concurrent transition serialization,
analytics allowlisting, retention fields, per-table runtime privileges, the
same-tenancy composite FK, and absence of raw instruction text from
analytics and log surfaces.

DB-backed tests use the transactional conftest fixtures with synthetic
tenant/user rows only. No real tenant content is used anywhere.
"""

from __future__ import annotations

import ast
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.editor_assistant.analytics import (
    REQUEST_ANALYTICS_FIELDS,
    EditorMetadataValidationError,
    project_event,
    project_request,
    validate_event_metadata,
)
from app.modules.editor_assistant.models import AIEditorRequest, AIEditorRequestEvent
from app.modules.editor_assistant.repository import EditorRequestRepository
from app.modules.editor_assistant.service import (
    _MAX_INSTRUCTION_LENGTH,
    _MAX_OPERATION_CONSTRAINTS_BYTES,
    _MAX_SELECTED_SCOPE_LENGTH,
    EditorActorContext,
    EditorEventDraft,
    EditorIdempotencyCollisionError,
    EditorLifecycleTransitionError,
    EditorRequestDraft,
    EditorRequestService,
    EditorRequestServiceError,
    _validate_event_key,
    _validate_instruction_text,
    _validate_operation_constraints,
    _validate_selected_scope,
    _validated_intent,
)
from app.modules.editor_assistant.taxonomy import (
    EditorIntentCategory,
    EditorLifecycleEventType,
    EditorQualityIssueLabel,
    allowed_transitions,
    can_record_outcome,
)

# Synthetic content only — deliberately not copied from any customer request.
SYNTHETIC_INSTRUCTION = "synthetic instruction: simplify the sample wording"


def _actor(tenant, user) -> EditorActorContext:
    return EditorActorContext(tenant_id=tenant.id, actor_id=user.id)


def _draft(**overrides) -> EditorRequestDraft:
    defaults = dict(
        target_entity_type="quiz_question",
        target_entity_id=uuid4(),
        instruction_text=SYNTHETIC_INSTRUCTION,
        intent_category=EditorIntentCategory.SIMPLIFY_LANGUAGE.value,
        base_content_version="v1",
        locale="ru",
        generator_version="gen-1",
        prompt_version="prompt-1",
        model_id="synthetic-model",
        validator_version="val-1",
        instruction_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    defaults.update(overrides)
    return EditorRequestDraft(**defaults)


@pytest.fixture
async def tenant_and_user(make_tenant, make_user):
    tenant = await make_tenant(name="Synthetic Editor Tenant")
    user = await make_user(tenant, role="methodologist")
    return tenant, user


@pytest.fixture
async def editor_request(db_session, tenant_and_user):
    tenant, user = tenant_and_user
    service = EditorRequestService(db_session)
    request = await service.create_request(_actor(tenant, user), _draft())
    return service, request


# ---------------------------------------------------------------------------
# Taxonomy integrity
# ---------------------------------------------------------------------------


def test_taxonomy_values_match_plan_contract():
    assert EditorIntentCategory.OTHER.value == "other"
    assert EditorIntentCategory.REGENERATE_DISTRACTORS.value == "regenerate_distractors"
    assert EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL.value == (
        "correct_answer_length_signal"
    )
    assert EditorLifecycleEventType.REQUESTED.value == "requested"
    assert EditorLifecycleEventType.EXPIRED.value == "expired"
    assert EditorLifecycleEventType.SUPERSEDED.value == "superseded"


def test_terminal_states_have_no_outgoing_transitions():
    from app.modules.editor_assistant.taxonomy import TERMINAL_OUTCOME_STATES

    for terminal in ("published", "rejected", "expired", "superseded"):
        assert allowed_transitions(terminal) == frozenset()
        assert terminal in TERMINAL_OUTCOME_STATES
    # applied is NOT terminal: post-apply feedback remains possible.
    assert "applied" not in TERMINAL_OUTCOME_STATES


def test_applied_allows_only_post_apply_feedback():
    assert allowed_transitions("applied") == frozenset(
        {"manually_edited_after_apply", "published"}
    )


def test_first_outcome_must_be_requested():
    assert can_record_outcome(None, "requested")
    assert not can_record_outcome(None, "preview_started")


# ---------------------------------------------------------------------------
# Creation and tenant separation
# ---------------------------------------------------------------------------


async def test_create_request_derives_outcome_and_initial_event(db_session, tenant_and_user):
    tenant, user = tenant_and_user
    service = EditorRequestService(db_session)

    request = await service.create_request(_actor(tenant, user), _draft())

    assert request.outcome_state == "requested"
    repo = EditorRequestRepository(db_session)
    events = await repo.list_events(request.id, tenant.id)
    assert [event.event_type for event in events] == ["requested"]
    assert events[0].event_key == "requested"


async def test_request_rejects_unknown_intent_category(db_session, tenant_and_user):
    tenant, user = tenant_and_user
    service = EditorRequestService(db_session)
    with pytest.raises(EditorRequestServiceError):
        await service.create_request(
            _actor(tenant, user), _draft(intent_category="not_a_taxonomy_value")
        )


async def test_canonical_service_rejects_actor_from_another_tenant(
    db_session, make_tenant, make_user, tenant_and_user
):
    tenant, _ = tenant_and_user
    other_tenant = await make_tenant(name="Synthetic Actor Tenant")
    other_user = await make_user(other_tenant, role="methodologist")
    service = EditorRequestService(db_session)

    with pytest.raises(EditorRequestServiceError) as error:
        await service.create_request(
            EditorActorContext(tenant_id=tenant.id, actor_id=other_user.id), _draft()
        )

    assert str(error.value) == "Editor actor is not available in this tenant"


async def test_canonical_service_rejects_cross_tenant_actor_on_event(
    db_session, make_tenant, make_user, editor_request
):
    service, request = editor_request
    other_tenant = await make_tenant(name="Synthetic Event Actor Tenant")
    other_user = await make_user(other_tenant, role="methodologist")

    with pytest.raises(EditorRequestServiceError) as error:
        await service.record_event(
            EditorActorContext(tenant_id=request.tenant_id, actor_id=other_user.id),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_STARTED,
                event_key="cross-tenant-actor",
            ),
        )

    assert str(error.value) == "Editor actor is not available in this tenant"


async def test_request_requires_instruction_text(db_session, tenant_and_user):
    tenant, user = tenant_and_user
    service = EditorRequestService(db_session)
    with pytest.raises(EditorRequestServiceError):
        await service.create_request(_actor(tenant, user), _draft(instruction_text=""))


async def test_get_request_is_tenant_scoped(db_session, make_tenant, make_user, tenant_and_user):
    tenant, user = tenant_and_user
    other_tenant = await make_tenant(name="Synthetic Other Tenant")
    other_user = await make_user(other_tenant, role="methodologist")
    service = EditorRequestService(db_session)
    request = await service.create_request(_actor(tenant, user), _draft())

    assert await service._repo.get_request(request.id, tenant.id) is not None
    assert await service._repo.get_request(request.id, other_tenant.id) is None
    assert other_user is not None


async def test_cross_tenant_event_recording_is_denied(
    db_session, make_tenant, make_user, tenant_and_user
):
    tenant, user = tenant_and_user
    other_tenant = await make_tenant(name="Synthetic Cross Tenant")
    other_user = await make_user(other_tenant, role="methodologist")
    service = EditorRequestService(db_session)
    request = await service.create_request(_actor(tenant, user), _draft())

    with pytest.raises(EditorRequestServiceError):
        await service.record_event(
            _actor(other_tenant, other_user),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_STARTED,
                event_key="preview-1",
            ),
        )


# ---------------------------------------------------------------------------
# Idempotency, collisions, and invalid transitions
# ---------------------------------------------------------------------------


async def test_identical_event_replay_is_idempotent(db_session, editor_request):
    service, request = editor_request
    tenant_id = request.tenant_id
    user_id = request.actor_id
    context = EditorActorContext(tenant_id=tenant_id, actor_id=user_id)

    draft = EditorEventDraft(
        event_type=EditorLifecycleEventType.PREVIEW_STARTED,
        event_key="preview-attempt-1",
        metadata={"duration_ms": 500},
    )
    first_request, first_event = await service.record_event(context, request.id, draft)
    replay_request, replay_event = await service.record_event(context, request.id, draft)

    assert first_event is not None
    assert replay_event is None
    assert replay_request.outcome_state == first_request.outcome_state == "preview_started"

    repo = EditorRequestRepository(db_session)
    events = await repo.list_events(request.id, tenant_id)
    assert len(events) == 2  # requested + one preview_started
    assert [event.event_type for event in events] == ["requested", "preview_started"]


async def test_same_key_different_event_type_collides(db_session, editor_request):
    service, request = editor_request
    context = EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id)

    first, first_event = await service.record_event(
        context,
        request.id,
        EditorEventDraft(
            event_type=EditorLifecycleEventType.PREVIEW_STARTED,
            event_key="shared-key",
        ),
    )
    assert first_event is not None
    first_state = first.outcome_state

    with pytest.raises(EditorIdempotencyCollisionError):
        await service.record_event(
            context,
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_FAILED,
                event_key="shared-key",
            ),
        )

    repo = EditorRequestRepository(db_session)
    events = await repo.list_events(request.id, request.tenant_id)
    assert [event.event_type for event in events] == ["requested", "preview_started"]
    refreshed = await repo.get_request(request.id, request.tenant_id)
    assert refreshed.outcome_state == first_state


async def test_same_key_same_type_different_metadata_collides(db_session, editor_request):
    service, request = editor_request
    context = EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id)

    await service.record_event(
        context,
        request.id,
        EditorEventDraft(
            event_type=EditorLifecycleEventType.PREVIEW_STARTED,
            event_key="shared-key",
            metadata={"attempt": 1},
        ),
    )
    with pytest.raises(EditorIdempotencyCollisionError):
        await service.record_event(
            context,
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_STARTED,
                event_key="shared-key",
                metadata={"attempt": 2},
            ),
        )


def test_event_key_validation_accepts_only_ascii_allowlist():
    assert _validate_event_key("A0._:-z9") == "A0._:-z9"

    for bad_key in ("bad key", "ключ", "emoji-☃"):
        with pytest.raises(EditorRequestServiceError) as error:
            _validate_event_key(bad_key)
        assert bad_key not in str(error.value)

    with pytest.raises(EditorRequestServiceError):
        _validate_event_key("")


def test_instruction_and_scope_validation_are_bounded_without_echoing_values():
    assert _validate_instruction_text("x" * _MAX_INSTRUCTION_LENGTH) == (
        "x" * _MAX_INSTRUCTION_LENGTH
    )
    with pytest.raises(EditorRequestServiceError) as instruction_error:
        _validate_instruction_text("x" * (_MAX_INSTRUCTION_LENGTH + 1))
    assert "x" * (_MAX_INSTRUCTION_LENGTH + 1) not in str(instruction_error.value)

    assert _validate_selected_scope("  Course > Module  ") == "Course > Module"
    assert _validate_selected_scope("x" * _MAX_SELECTED_SCOPE_LENGTH) == (
        "x" * _MAX_SELECTED_SCOPE_LENGTH
    )
    with pytest.raises(EditorRequestServiceError) as scope_error:
        _validate_selected_scope("x" * (_MAX_SELECTED_SCOPE_LENGTH + 1))
    assert "x" * (_MAX_SELECTED_SCOPE_LENGTH + 1) not in str(scope_error.value)


def test_instruction_text_is_trimmed_and_bounded_without_whitespace_bypass():
    exact = "x" * _MAX_INSTRUCTION_LENGTH
    padded = f"{' ' * 256}{exact}{' ' * 256}"
    over_limit = "x" * (_MAX_INSTRUCTION_LENGTH + 1)
    padded_over_limit = f"{' ' * 128}{over_limit}{' ' * 128}"

    assert _validate_instruction_text(exact) == exact
    assert _validate_instruction_text(padded) == exact
    with pytest.raises(EditorRequestServiceError):
        _validate_instruction_text(over_limit)
    with pytest.raises(EditorRequestServiceError):
        _validate_instruction_text(padded_over_limit)


def test_operation_constraints_are_bounded_for_nested_payloads():
    nested_constraints = {"outer": {"inner": ""}}
    overhead = len(
        json.dumps(nested_constraints, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    payload = "x" * (_MAX_OPERATION_CONSTRAINTS_BYTES - overhead)
    allowed = {"outer": {"inner": payload}}
    assert _validate_operation_constraints(allowed) == allowed

    with pytest.raises(EditorRequestServiceError):
        _validate_operation_constraints({"outer": {"inner": payload + "x"}})

    for bad_number in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(EditorRequestServiceError):
            _validate_operation_constraints({"value": bad_number})

    nested = {}
    cursor = nested
    for _ in range(1500):
        child = {}
        cursor["child"] = child
        cursor = child

    with pytest.raises(EditorRequestServiceError):
        _validate_operation_constraints(nested)


def test_invalid_intent_category_does_not_echo_input():
    unsafe_intent = "not_a_taxonomy_value"
    with pytest.raises(EditorRequestServiceError) as error:
        _validated_intent(unsafe_intent)
    assert unsafe_intent not in str(error.value)


async def test_event_key_is_opaque_and_never_reflected(db_session, editor_request):
    service, request = editor_request
    unsafe_key = "person@example.com"

    with pytest.raises(EditorRequestServiceError) as error:
        await service.record_event(
            EditorActorContext(
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
            ),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_STARTED,
                event_key=unsafe_key,
            ),
        )

    assert unsafe_key not in str(error.value)


async def test_instruction_and_constraints_are_bounded(db_session, tenant_and_user):
    tenant, actor = tenant_and_user
    service = EditorRequestService(db_session)

    for instruction in ("   ", "x" * 8_001):
        with pytest.raises(EditorRequestServiceError):
            await service.create_request(
                _actor(tenant, actor),
                _draft(instruction_text=instruction),
            )

    with pytest.raises(EditorRequestServiceError):
        await service.create_request(
            _actor(tenant, actor),
            _draft(operation_constraints={"opaque": "x" * 8_193}),
        )


def test_validation_errors_do_not_reflect_untrusted_values():
    unsafe_key = "person@example.com"
    with pytest.raises(EditorMetadataValidationError) as metadata_error:
        validate_event_metadata({unsafe_key: "synthetic"})
    assert unsafe_key not in str(metadata_error.value)

    unsafe_label = "customer confidential phrase"
    with pytest.raises(EditorMetadataValidationError) as label_error:
        validate_event_metadata({"issue_labels": [unsafe_label]})
    assert unsafe_label not in str(label_error.value)


def test_project_event_fails_closed_for_invalid_metadata():
    event = _FakeEditorEvent(
        tenant_id=uuid4(),
        request_id=uuid4(),
        event_type="preview_ready",
        event_key="safe-key",
        actor_id=uuid4(),
        metadata_json={"model_id": "customer confidential phrase"},
    )

    projected = project_event(event)

    assert projected["event_type"] == "preview_ready"
    assert projected["metadata"] == {}


def test_repository_insert_methods_are_invoked_only_by_service():
    repo_path = Path(__file__).parents[2] / "app" / "modules" / "editor_assistant" / "repository.py"
    service_path = Path(__file__).parents[2] / "app" / "modules" / "editor_assistant" / "service.py"

    def calls(path: Path, method_name: str) -> list[ast.Call]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name
        ]

    assert calls(repo_path, "_create_request") == []
    assert calls(repo_path, "_append_event") == []
    assert len(calls(service_path, "_create_request")) == 1
    assert len(calls(service_path, "_append_event")) == 1


class _FakeEditorRequest:
    def __init__(self, *, tenant_id, request_id, actor_id, outcome_state):
        self.id = request_id
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.outcome_state = outcome_state
        self.updated_at = None


class _FakeEditorEvent:
    def __init__(self, *, tenant_id, request_id, event_type, event_key, actor_id, metadata_json):
        self.tenant_id = tenant_id
        self.request_id = request_id
        self.event_type = event_type
        self.event_key = event_key
        self.actor_id = actor_id
        self.metadata_json = metadata_json


class _FakeIdempotencyRepo:
    def __init__(self, request: _FakeEditorRequest, event: _FakeEditorEvent):
        self.request = request
        self.event = event
        self.history = [
            _FakeEditorEvent(
                tenant_id=request.tenant_id,
                request_id=request.id,
                event_type=EditorLifecycleEventType.REQUESTED.value,
                event_key="requested",
                actor_id=request.actor_id,
                metadata_json={},
            ),
            event,
        ]
        self.append_calls = 0
        self.refresh_calls = 0

    async def actor_exists_for_tenant(self, actor_id, tenant_id):
        return tenant_id == self.request.tenant_id

    async def get_request_for_update(self, request_id, tenant_id):
        if request_id == self.request.id and tenant_id == self.request.tenant_id:
            return self.request
        return None

    async def get_event(self, request_id, tenant_id, event_key):
        if (
            request_id == self.event.request_id
            and tenant_id == self.event.tenant_id
            and event_key == self.event.event_key
        ):
            return self.event
        return None

    async def append_event(self, event):
        self.append_calls += 1
        self.history.append(event)
        return event

    async def refresh_outcome_state(self, request, event_type):
        self.refresh_calls += 1
        request.outcome_state = event_type
        return request


async def test_same_key_replayed_by_different_actor_collides_without_db():
    tenant_id = uuid4()
    request_id = uuid4()
    first_actor_id = uuid4()
    second_actor_id = uuid4()
    request = _FakeEditorRequest(
        tenant_id=tenant_id,
        request_id=request_id,
        actor_id=first_actor_id,
        outcome_state=EditorLifecycleEventType.PREVIEW_STARTED.value,
    )
    event = _FakeEditorEvent(
        tenant_id=tenant_id,
        request_id=request_id,
        event_type=EditorLifecycleEventType.PREVIEW_STARTED.value,
        event_key="actor-bound-replay",
        actor_id=first_actor_id,
        metadata_json={"attempt": 1},
    )
    repo = _FakeIdempotencyRepo(request, event)
    service = EditorRequestService.__new__(EditorRequestService)
    service._repo = repo
    draft = EditorEventDraft(
        event_type=EditorLifecycleEventType.PREVIEW_STARTED,
        event_key="actor-bound-replay",
        metadata={"attempt": 1},
    )

    with pytest.raises(EditorIdempotencyCollisionError):
        await service.record_event(
            EditorActorContext(tenant_id=tenant_id, actor_id=second_actor_id),
            request_id,
            draft,
        )

    assert repo.append_calls == 0
    assert repo.refresh_calls == 0
    assert request.outcome_state == EditorLifecycleEventType.PREVIEW_STARTED.value
    assert [stored.actor_id for stored in repo.history] == [first_actor_id, first_actor_id]
    assert [stored.event_key for stored in repo.history] == [
        "requested",
        "actor-bound-replay",
    ]


async def test_invalid_transition_is_rejected_without_history_rewrite(db_session, editor_request):
    service, request = editor_request
    tenant_id, user_id = request.tenant_id, request.actor_id

    # requested -> applied is not a legal direct transition.
    with pytest.raises(EditorLifecycleTransitionError):
        await service.record_event(
            EditorActorContext(tenant_id=tenant_id, actor_id=user_id),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.APPLIED,
                event_key="apply-1",
            ),
        )

    repo = EditorRequestRepository(db_session)
    events = await repo.list_events(request.id, tenant_id)
    assert [event.event_type for event in events] == ["requested"]
    refreshed = await repo.get_request(request.id, tenant_id)
    assert refreshed.outcome_state == "requested"


async def test_valid_lifecycle_path_records_all_events(db_session, editor_request):
    service, request = editor_request
    tenant_id, user_id = request.tenant_id, request.actor_id

    steps = [
        EditorLifecycleEventType.PREVIEW_STARTED,
        EditorLifecycleEventType.PREVIEW_READY,
        EditorLifecycleEventType.APPLIED,
    ]
    for index, event_type in enumerate(steps):
        request, event = await service.record_event(
            EditorActorContext(tenant_id=tenant_id, actor_id=user_id),
            request.id,
            EditorEventDraft(event_type=event_type, event_key=f"key-{index}"),
        )
        assert event is not None

    assert request.outcome_state == "applied"
    repo = EditorRequestRepository(db_session)
    events = await repo.list_events(request.id, tenant_id)
    assert [event.event_type for event in events] == [
        "requested",
        "preview_started",
        "preview_ready",
        "applied",
    ]


# ---------------------------------------------------------------------------
# Analytics allowlisting and raw-instruction leakage
# ---------------------------------------------------------------------------


async def test_analytics_projection_contains_only_allowlisted_fields(db_session, editor_request):
    service, request = editor_request

    projection = await service.build_analytics_projection(
        EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
        request.id,
    )
    assert projection is not None

    request_keys = set(projection["request"].keys())
    assert request_keys == set(REQUEST_ANALYTICS_FIELDS)
    assert "instruction_text" not in request_keys
    assert "tenant_id" not in request_keys
    assert "actor_id" not in request_keys
    assert "id" not in request_keys
    assert "selected_scope" not in request_keys
    assert "source_type_summary" not in request_keys
    assert "parent_generation_trace_id" not in request_keys


async def test_raw_instruction_text_never_enters_analytics(db_session, editor_request):
    service, request = editor_request
    await service.record_event(
        EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
        request.id,
        EditorEventDraft(
            event_type=EditorLifecycleEventType.PREVIEW_STARTED,
            event_key="preview-1",
            metadata={"duration_ms": 1200},
        ),
    )

    projection = await service.build_analytics_projection(
        EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
        request.id,
    )

    serialized = repr(projection)
    assert SYNTHETIC_INSTRUCTION not in serialized
    assert "sample wording" not in serialized


def test_projection_helpers_never_emit_instruction_attribute():
    request = AIEditorRequest(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        target_entity_type="quiz_question",
        target_entity_id=uuid4(),
        intent_category="other",
        base_content_version="v1",
        locale="ru",
        instruction_text=SYNTHETIC_INSTRUCTION,
    )
    event = AIEditorRequestEvent(
        tenant_id=request.tenant_id,
        request_id=request.id,
        event_type="requested",
        event_key="requested",
        sequence_no=1,
        actor_id=request.actor_id,
    )

    assert SYNTHETIC_INSTRUCTION not in repr(project_request(request))
    assert SYNTHETIC_INSTRUCTION not in repr(project_event(event))


def test_request_projection_exposes_only_closed_taxonomy_fields():
    request = AIEditorRequest(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        target_entity_type="customer confidential phrase",
        target_entity_id=uuid4(),
        intent_category="other",
        base_content_version="v1",
        locale="person@example.com",
        instruction_text=SYNTHETIC_INSTRUCTION,
        selected_scope="private customer scope",
        source_type_summary="private source description",
        parent_generation_trace_id="private trace description",
        model_id="private customer model description",
    )

    request.outcome_state = "requested"
    assert project_request(request) == {
        "intent_category": "other",
        "outcome_state": "requested",
    }


# ---------------------------------------------------------------------------
# Event metadata is allowlist-only at persistence
# ---------------------------------------------------------------------------


def test_metadata_unknown_keys_are_rejected():
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"unrelated_free_text": "should-not-persist"})
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"instruction_text": SYNTHETIC_INSTRUCTION})
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"prompt": "raw prompt text"})


def test_metadata_issue_labels_must_be_taxonomy_values():
    valid = validate_event_metadata(
        {"issue_labels": [EditorQualityIssueLabel.IMPLAUSIBLE_DISTRACTORS.value]}
    )
    assert valid["issue_labels"] == ["implausible_distractors"]

    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"issue_labels": ["made_up_label"]})
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"issue_labels": ["a"] * 17})


def test_metadata_numerics_are_bounded_non_negative_ints():
    assert validate_event_metadata({"duration_ms": 900})["duration_ms"] == 900
    assert validate_event_metadata({"attempt": 2})["attempt"] == 2

    for bad in (True, 1.5, "900", -1, 10**10):
        with pytest.raises(EditorMetadataValidationError):
            validate_event_metadata({"duration_ms": bad})


def test_metadata_version_strings_are_bounded_and_whitespace_free():
    assert validate_event_metadata({"model_id": "model-x"})["model_id"] == "model-x"
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"model_id": "model x with spaces"})
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"model_id": ""})
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"model_id": "x" * 121})


def test_metadata_reason_code_is_a_closed_taxonomy():
    assert validate_event_metadata({"reason_code": "provider_timeout"})["reason_code"] == (
        "provider_timeout"
    )
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"reason_code": "arbitrary prose with spaces"})
    with pytest.raises(EditorMetadataValidationError):
        validate_event_metadata({"reason_code": "plausible_but_unregistered_slug"})


async def test_service_persists_only_allowlisted_metadata(db_session, editor_request):
    service, request = editor_request
    await service.record_event(
        EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
        request.id,
        EditorEventDraft(
            event_type=EditorLifecycleEventType.PREVIEW_STARTED,
            event_key="preview-ready-1-started",
        ),
    )
    _, event = await service.record_event(
        EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
        request.id,
        EditorEventDraft(
            event_type=EditorLifecycleEventType.PREVIEW_READY,
            event_key="preview-ready-1",
            metadata={
                "duration_ms": 900,
                "attempt": 2,
                "issue_labels": [EditorQualityIssueLabel.MALFORMED_QUESTION.value],
            },
        ),
    )
    assert event is not None

    from sqlalchemy import select

    stored = (
        await db_session.execute(
            select(AIEditorRequestEvent).where(AIEditorRequestEvent.id == event.id)
        )
    ).scalar_one()
    assert stored.metadata_json == {
        "duration_ms": 900,
        "attempt": 2,
        "issue_labels": ["malformed_question"],
    }

    # Unknown free-text keys are rejected before any insert happens.
    with pytest.raises(EditorMetadataValidationError):
        await service.record_event(
            EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_FAILED,
                event_key="preview-failed-free-text",
                metadata={"unrelated_free_text": SYNTHETIC_INSTRUCTION},
            ),
        )


async def test_service_rejects_unknown_metadata_before_insert(db_session, editor_request):
    service, request = editor_request
    with pytest.raises(EditorMetadataValidationError):
        await service.record_event(
            EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_FAILED,
                event_key="preview-failed-free-text",
                metadata={"free_form": SYNTHETIC_INSTRUCTION},
            ),
        )

    repo = EditorRequestRepository(db_session)
    events = await repo.list_events(request.id, request.tenant_id)
    assert [event.event_type for event in events] == ["requested"]


# ---------------------------------------------------------------------------
# Retention fields
# ---------------------------------------------------------------------------


async def test_retention_expiry_field_is_persisted_and_readable(db_session, tenant_and_user):
    tenant, user = tenant_and_user
    service = EditorRequestService(db_session)
    expires = datetime.now(UTC) + timedelta(days=7)

    request = await service.create_request(
        _actor(tenant, user), _draft(instruction_expires_at=expires)
    )

    repo = EditorRequestRepository(db_session)
    stored = await repo.get_request(request.id, tenant.id)
    assert stored.instruction_expires_at is not None
    assert stored.instruction_expires_at.replace(microsecond=0) == expires.replace(microsecond=0)


async def test_retention_expiry_is_optional(db_session, editor_request):
    _, request = editor_request
    assert request.instruction_expires_at is not None  # fixture sets 30 days
    service = EditorRequestService(db_session)
    fresh = await service.create_request(
        EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
        _draft(instruction_expires_at=None),
    )
    assert fresh.instruction_expires_at is None


# ---------------------------------------------------------------------------
# Logging hygiene
# ---------------------------------------------------------------------------


async def test_service_logs_do_not_contain_raw_instruction_text(
    db_session, editor_request, caplog: pytest.LogCaptureFixture
):
    service, request = editor_request

    with caplog.at_level(logging.INFO, logger="app.modules.editor_assistant.service"):
        await service.record_event(
            EditorActorContext(tenant_id=request.tenant_id, actor_id=request.actor_id),
            request.id,
            EditorEventDraft(
                event_type=EditorLifecycleEventType.PREVIEW_STARTED,
                event_key="preview-log-check",
            ),
        )

    assert SYNTHETIC_INSTRUCTION not in caplog.text
    assert "editor_assistant event recorded" in caplog.text


# ---------------------------------------------------------------------------
# Database-enforced contracts: privileges, same-tenant FK, CHECKs, concurrency
# ---------------------------------------------------------------------------


async def test_runtime_role_privilege_contract(db_session):
    """Exact per-table runtime privilege contract from information_schema."""

    grants = (
        await db_session.execute(
            text(
                """
                SELECT table_name, privilege_type
                FROM information_schema.role_table_grants
                WHERE table_name IN ('ai_editor_requests', 'ai_editor_request_events')
                  AND grantee = 'lms_app'
                """
            )
        )
    ).fetchall()

    by_table: dict[str, set[str]] = {}
    for row in grants:
        by_table.setdefault(row.table_name, set()).add(row.privilege_type)

    assert by_table["ai_editor_requests"] == {"SELECT", "INSERT"}
    assert by_table["ai_editor_request_events"] == {"SELECT", "INSERT"}

    column_grants = (
        await db_session.execute(
            text(
                """
                SELECT column_name, privilege_type
                FROM information_schema.role_column_grants
                WHERE table_name = 'ai_editor_requests'
                  AND grantee = 'lms_app'
                  AND privilege_type = 'UPDATE'
                """
            )
        )
    ).fetchall()
    assert {(row.column_name, row.privilege_type) for row in column_grants} == {
        ("outcome_state", "UPDATE"),
        ("updated_at", "UPDATE"),
    }


async def test_runtime_role_cannot_update_or_delete_events(db_session, make_tenant, make_user):
    """The append-only property is DB-enforced, not repository naming."""
    tenant = await make_tenant(name="Synthetic Priv Tenant")
    user = await make_user(tenant, role="methodologist")

    await db_session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant.id)})
    service = EditorRequestService(db_session)
    request = await service.create_request(_actor(tenant, user), _draft())
    await service.record_event(
        _actor(tenant, user),
        request.id,
        EditorEventDraft(
            event_type=EditorLifecycleEventType.PREVIEW_STARTED,
            event_key="preview-priv",
        ),
    )
    await db_session.commit()
    event_id = (await db_session.execute(
        text("SELECT id FROM ai_editor_request_events WHERE event_key = 'preview-priv'")
    )).scalar_one()

    # Switch to the runtime role for the negative privilege probes.
    await db_session.commit()
    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant.id)}
    )

    # Request provenance is immutable; only lifecycle state columns are writable.
    await db_session.execute(
        text("UPDATE ai_editor_requests SET updated_at = updated_at WHERE id = :rid"),
        {"rid": request.id},
    )
    with pytest.raises(Exception) as request_update_error:
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE ai_editor_requests "
                    "SET instruction_text = 'forbidden' WHERE id = :rid"
                ),
                {"rid": request.id},
            )
    assert "permission denied" in str(request_update_error.value).lower()

    # Each denied statement aborts the transaction; use savepoints so both
    # probes run independently.
    with pytest.raises(Exception) as update_error:
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE ai_editor_request_events SET event_type = 'applied' WHERE id = :eid"
                ),
                {"eid": event_id},
            )
    assert "permission denied" in str(update_error.value).lower()

    with pytest.raises(Exception) as delete_error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM ai_editor_request_events WHERE id = :eid"), {"eid": event_id}
            )
    assert "permission denied" in str(delete_error.value).lower()


async def test_same_tenant_composite_fk_rejects_cross_tenant_event(
    db_session, make_tenant, make_user, editor_request
):
    """A mismatched (tenant, request) pair violates the composite FK even
    when executed by a privileged connection without RLS tenant context."""
    service, request = editor_request

    other_tenant = await make_tenant(name="Synthetic FK Tenant")
    await make_user(other_tenant, role="methodologist")

    # Drop the RLS tenant context to simulate a privileged connection.
    await db_session.commit()
    await db_session.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    bogus = AIEditorRequestEvent(
        tenant_id=other_tenant.id,
        request_id=request.id,
        event_type=EditorLifecycleEventType.PREVIEW_STARTED.value,
        event_key="cross-tenant-probe",
        sequence_no=1,
        actor_id=request.actor_id,
        metadata_json={},
    )
    db_session.add(bogus)
    with pytest.raises(Exception) as fk_error:
        await db_session.flush()
    assert "fk_ai_editor_events_same_tenant_request" in str(fk_error.value)


async def test_check_constraints_reject_invalid_taxonomy_values(db_session, tenant_and_user):
    tenant, user = tenant_and_user
    service = EditorRequestService(db_session)
    request = await service.create_request(_actor(tenant, user), _draft())
    await db_session.commit()

    # Invalid intent_category is rejected by the DB CHECK.
    with pytest.raises(Exception) as check_error:
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE ai_editor_requests SET intent_category = 'nonsense' WHERE id = :rid"
                ),
                {"rid": request.id},
            )
    assert "ck_ai_editor_requests_intent_category" in str(check_error.value)


async def test_concurrent_transitions_cannot_both_commit_from_same_state(
    make_tenant, make_user
):
    """Two competing transitions from the same prior state: exactly one wins.

    Uses separate real sessions/transactions against the disposable local
    PostgreSQL; the row lock taken by ``record_event`` serializes them.
    """
    import asyncio

    from app.core.db import async_session_factory
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.editor_assistant.service import EditorActorContext, EditorEventDraft
    from app.modules.editor_assistant.taxonomy import EditorLifecycleEventType

    tenant_id = uuid4()

    async with async_session_factory() as setup:
        setup.add(
            Tenant(
                id=tenant_id,
                name=f"Editor concurrency {tenant_id.hex[:8]}",
                slug=f"editor-conc-{tenant_id.hex}",
                status="active",
                plan="free",
                settings={},
            )
        )
        await setup.commit()

    async with async_session_factory() as setup:
        await setup.execute(
            text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
        )
        user = User(
            id=uuid4(),
            tenant_id=tenant_id,
            email=f"editor-conc-{tenant_id.hex}@example.test",
            first_name="Concurrency",
            last_name="Test",
            role="methodologist",
            is_active=True,
        )
        setup.add(user)
        await setup.commit()
        user_id = user.id

    request_id = None
    async with async_session_factory() as setup:
        await setup.execute(
            text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
        )
        service = EditorRequestService(setup)
        draft = _draft(instruction_expires_at=None)
        request = await service.create_request(
            EditorActorContext(tenant_id=tenant_id, actor_id=user_id), draft
        )
        await setup.commit()
        request_id = request.id

    async def _compete(event_type: EditorLifecycleEventType, key: str) -> str:
        async with async_session_factory() as session:
            await session.execute(
                text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
            )
            service = EditorRequestService(session)
            try:
                await service.record_event(
                    EditorActorContext(tenant_id=tenant_id, actor_id=user_id),
                    request_id,
                    EditorEventDraft(event_type=event_type, event_key=key),
                )
                await session.commit()
                return "committed"
            except EditorLifecycleTransitionError:
                await session.rollback()
                return "transition-rejected"

    # Both events are individually valid from `requested`, but only one may
    # commit: the second must observe the first's outcome state.
    outcomes = await asyncio.gather(
        _compete(EditorLifecycleEventType.PREVIEW_STARTED, "concurrent-a"),
        _compete(EditorLifecycleEventType.REJECTED, "concurrent-b"),
    )

    # Exactly one committed; the loser saw the winner's outcome state.
    assert sorted(outcomes) == ["committed", "transition-rejected"]

    async with async_session_factory() as verify:
        await verify.execute(
            text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
        )
        events = (await verify.execute(
            text(
                "SELECT event_type FROM ai_editor_request_events WHERE request_id = :rid "
                "ORDER BY sequence_no"
            ),
            {"rid": request_id},
        )).scalars().all()
        # requested + exactly one of the two competing events.
        assert len(events) == 2
        assert events.count("requested") == 1
        assert sorted(events[1:]) == ["preview_started"] or events[1] in (
            "preview_started",
            "rejected",
        )
        final_state = (await verify.execute(
            text("SELECT outcome_state FROM ai_editor_requests WHERE id = :rid"),
            {"rid": request_id},
        )).scalar_one()
        # The persisted outcome equals the single winning event.
        assert final_state == events[1]

    # Cleanup disposable rows.
    async with async_session_factory() as cleanup:
        await cleanup.execute(
            text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
        )
        await cleanup.execute(
            text("DELETE FROM ai_editor_requests WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await cleanup.execute(
            text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await cleanup.execute(
            text("DELETE FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)}
        )
        await cleanup.commit()


# ---------------------------------------------------------------------------
# Migration contract
# ---------------------------------------------------------------------------


def test_migration_contract_is_additive_and_rls_forced():
    migration = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "0135_add_ai_editor_assistant_telemetry.py"
    ).read_text(encoding="utf-8")

    # Structural essentials only; the exact privilege contract is verified
    # against a live database in test_runtime_role_privilege_contract.
    assert "revision = \"0135\"" in migration
    assert "down_revision = \"0134\"" in migration
    assert "CREATE TABLE" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "fk_ai_editor_events_same_tenant_request" in migration
    assert "ck_ai_editor_requests_intent_category" in migration
    assert "ck_ai_editor_requests_outcome_state" in migration
    assert "ck_ai_editor_requests_instruction_length" in migration
    assert "ck_ai_editor_events_event_type" in migration
    assert "uq_ai_editor_event_tenant_request_key" in migration
    assert "uq_ai_editor_event_tenant_request_sequence" in migration
    assert "DROP TABLE IF EXISTS" in migration
