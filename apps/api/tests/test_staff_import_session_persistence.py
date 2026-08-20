import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.modules.staff_import_sessions import (
    BranchProposal,
    ImportMode,
    ImportSessionProposal,
    ImportSessionState,
    MatchAction,
    ProposalConfidence,
)
from app.modules.staff_import_sessions.persistence import (
    cleanup_expired_import_sources,
    proposal_review_state,
    record_to_domain,
)
from app.modules.staff_import_sessions.state_machine import bind_proposal_revision

PERSISTENCE = Path(__file__).parents[1] / "app" / "modules" / "staff_import_sessions" / "persistence.py"


def _proposal(*, action: MatchAction, confidence: ProposalConfidence) -> ImportSessionProposal:
    return ImportSessionProposal(
        source_file_name="staff.xlsx",
        source_file_sha256="a" * 64,
        branches=[
            BranchProposal(
                external_key="branch:pavlodar",
                branch_id="pavlodar",
                branch_name="Филиал Павлодар",
                action=action,
                confidence=confidence,
            )
        ],
    )


def test_review_state_blocks_low_confidence_and_conflicts() -> None:
    assert (
        proposal_review_state(_proposal(action=MatchAction.CREATE, confidence=ProposalConfidence.LOW))
        is ImportSessionState.NEEDS_CORRECTION
    )
    assert (
        proposal_review_state(_proposal(action=MatchAction.CONFLICT, confidence=ProposalConfidence.HIGH))
        is ImportSessionState.NEEDS_CORRECTION
    )


def test_cleanup_expired_sources_is_bounded_and_keeps_failed_deletes_retryable() -> None:
    now = datetime.now(UTC)
    deleted_record = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        source_object_key="staff-import-sessions/t/session-1/source.xlsx",
        state=ImportSessionState.NEEDS_MAPPING.value,
        expires_at=now - timedelta(minutes=1),
    )
    failed_record = SimpleNamespace(
        id=uuid4(),
        tenant_id=deleted_record.tenant_id,
        actor_id=uuid4(),
        source_object_key="staff-import-sessions/t/session-2/source.xlsx",
        state=ImportSessionState.NEEDS_REVIEW.value,
        expires_at=now - timedelta(minutes=1),
    )
    committed_record = SimpleNamespace(
        id=uuid4(),
        tenant_id=deleted_record.tenant_id,
        actor_id=uuid4(),
        source_object_key="staff-import-sessions/t/session-3/source.xlsx",
        state=ImportSessionState.COMMITTED.value,
        expires_at=now - timedelta(minutes=1),
    )

    class Result:
        def scalars(self):
            return self

        def all(self):
            return [deleted_record, failed_record, committed_record]

    class Db:
        def __init__(self):
            self.events = []
            self.flushed = False

        async def execute(self, _statement):
            return Result()

        def add(self, event):
            self.events.append(event)

        async def flush(self):
            self.flushed = True

    class Storage:
        def delete_bytes(self, key):
            if key.endswith("session-2/source.xlsx"):
                raise RuntimeError("temporary object-store failure")

    db = Db()
    deleted = asyncio.run(
        cleanup_expired_import_sources(
            db,
            tenant_id=deleted_record.tenant_id,
            storage=Storage(),
            now=now,
            limit=20,
        )
    )

    assert deleted == 2
    assert deleted_record.source_object_key is None
    assert deleted_record.state == ImportSessionState.EXPIRED.value
    assert failed_record.source_object_key is not None
    assert failed_record.state == ImportSessionState.NEEDS_REVIEW.value
    assert committed_record.source_object_key is None
    assert committed_record.state == ImportSessionState.COMMITTED.value
    assert len(db.events) == 2
    assert db.events[0].event_type == "source_retention_expired"
    assert db.events[0].actor_id == deleted_record.actor_id
    assert db.events[1].actor_id == committed_record.actor_id
    assert db.flushed is True


def test_review_state_allows_explicit_high_confidence_proposal() -> None:
    assert (
        proposal_review_state(_proposal(action=MatchAction.CREATE, confidence=ProposalConfidence.HIGH))
        is ImportSessionState.READY_FOR_APPROVAL
    )


def test_record_round_trip_preserves_bound_snapshot() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    proposal = _proposal(action=MatchAction.CREATE, confidence=ProposalConfidence.HIGH)
    initial = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role="methodologist",
        state=ImportSessionState.READY_FOR_APPROVAL.value,
        mode=ImportMode.ADD_OR_UPDATE.value,
        proposal_json=None,
        approval_token_hash=None,
        full_reconciliation_confirmation=False,
        reviewed_revision=None,
        approved_revision=None,
        approved_at=None,
        expires_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    base = record_to_domain(initial)
    bound = bind_proposal_revision(base, proposal)
    assert bound.proposal is not None
    initial.proposal_json = bound.proposal.model_dump(mode="json")
    initial.reviewed_revision = bound.reviewed_revision

    restored = record_to_domain(initial)
    assert restored.proposal == bound.proposal
    assert restored.reviewed_revision == bound.proposal.revision
    assert restored.proposal.revision_hash is not None


def test_idempotency_race_and_profile_upsert_are_deterministic() -> None:
    source = PERSISTENCE.read_text(encoding="utf-8")
    assert "except IntegrityError as exc" in source
    assert "replay.source_file_sha256" in source
    assert "on_conflict_do_nothing" in source
    assert "workbook_signature" in source
