"""Pure transition and validation rules for staff import sessions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256

from .schemas import (
    CanonicalProposalBase,
    ImportMode,
    ImportSession,
    ImportSessionConflict,
    ImportSessionProposal,
    ImportSessionState,
    MatchAction,
    ProposalConfidence,
    SourceCellRef,
)


def _canonical_dict(value):
    if isinstance(value, dict):
        return {k: _canonical_dict(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return sorted(
            (_canonical_dict(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)
        )
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, CanonicalProposalBase):
        return _canonical_dict(value.model_dump())
    if isinstance(value, ImportSessionProposal):
        return _canonical_dict(value.model_dump(exclude={"revision", "revision_hash", "generated_at"}))
    return value


def canonicalize_session_payload(payload: ImportSessionProposal) -> dict:
    """Build a deterministic dict used for hashing and replay-safe comparisons."""

    return _canonical_dict(payload)


def compute_proposal_hash(payload: ImportSessionProposal) -> str:
    """Compute immutable hash for a proposal snapshot."""

    canonical = canonicalize_session_payload(payload)
    payload_text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload_text.encode("utf-8")).hexdigest()


def compute_proposal_revision(payload: ImportSessionProposal) -> str:
    """Revision is hash-derived and stable for the same canonical snapshot."""

    digest = compute_proposal_hash(payload)
    return f"rev-{digest[:16]}"


_TRANSITIONS: dict[ImportSessionState, set[ImportSessionState]] = {
    ImportSessionState.UPLOADED: {
        ImportSessionState.INSPECTING,
        ImportSessionState.FAILED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.INSPECTING: {
        ImportSessionState.NEEDS_MAPPING,
        ImportSessionState.FAILED,
        ImportSessionState.REJECTED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.NEEDS_MAPPING: {
        ImportSessionState.NEEDS_REVIEW,
        ImportSessionState.NEEDS_CORRECTION,
        ImportSessionState.FAILED,
        ImportSessionState.REJECTED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.NEEDS_REVIEW: {
        ImportSessionState.READY_FOR_APPROVAL,
        ImportSessionState.NEEDS_CORRECTION,
        ImportSessionState.REJECTED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.NEEDS_CORRECTION: {
        ImportSessionState.NEEDS_REVIEW,
        ImportSessionState.READY_FOR_APPROVAL,
        ImportSessionState.REJECTED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.READY_FOR_APPROVAL: {
        ImportSessionState.APPROVED,
        ImportSessionState.NEEDS_CORRECTION,
        ImportSessionState.REJECTED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.APPROVED: {
        ImportSessionState.COMMITTING,
        ImportSessionState.REJECTED,
        ImportSessionState.EXPIRED,
    },
    ImportSessionState.COMMITTING: {
        ImportSessionState.COMMITTED,
        ImportSessionState.FAILED,
    },
    ImportSessionState.COMMITTED: set(),
    ImportSessionState.REJECTED: set(),
    ImportSessionState.EXPIRED: set(),
    ImportSessionState.FAILED: set(),
}


def next_states(state: ImportSessionState) -> list[ImportSessionState]:
    """Expose legal public next states for API contract docs and tests."""

    return sorted(_TRANSITIONS.get(state, set()), key=lambda s: s.value)


def can_transition(current: ImportSessionState, target: ImportSessionState) -> bool:
    return target in _TRANSITIONS.get(current, set())


class SessionStateError(ValueError):
    """Raised when a transition violates the session state machine."""


class ApprovalBlockedError(ValueError):
    """Raised when session approval is not allowed by rule violations."""


class StaleProposalError(ValueError):
    """Raised when approval references a non-current proposal revision."""


def assert_transition_allowed(current: ImportSessionState, target: ImportSessionState) -> None:
    if not can_transition(current, target):
        raise SessionStateError(f"Cannot transition from {current.value} to {target.value}")


def _blocking_conflicts(conflicts: Iterable[ImportSessionConflict]) -> list[ImportSessionConflict]:
    return [c for c in conflicts if c.blocking]


def _has_blocking_conflicts(session: ImportSession) -> bool:
    if not session.proposal:
        return False
    return len(_blocking_conflicts(session.proposal.conflicts)) > 0


def _has_unresolved_proposals(proposal: ImportSessionProposal) -> bool:
    proposed_items = (
        *proposal.branches,
        *proposal.departments,
        *proposal.positions,
        *proposal.staff,
    )
    return any(
        item.action is MatchAction.CONFLICT
        or (item.confidence is ProposalConfidence.LOW and item.action is not MatchAction.SKIP)
        for item in proposed_items
    )


def _proposal_revision_is_current(proposal: ImportSessionProposal) -> bool:
    if proposal.revision is None or proposal.revision_hash is None:
        return False
    current_hash = compute_proposal_hash(proposal)
    return proposal.revision_hash == current_hash and proposal.revision == f"rev-{current_hash[:16]}"


def _full_reconciliation_confirmed(session: ImportSession) -> bool:
    if session.mode != ImportMode.FULL_RECONCILIATION:
        return True
    return bool(session.full_reconciliation_confirmation)


def can_approve_session(session: ImportSession, revision: str, *, now: datetime | None = None) -> bool:
    """Return whether session can move to APPROVED at `now`."

    Rules:
    - session must be in READY_FOR_APPROVAL
    - proposal hash/revision must exist
    - caller revision must equal proposal.revision
    - no blocking conflicts
    - mode FULL_RECONCILIATION requires explicit confirmation
    """
    if session.state != ImportSessionState.READY_FOR_APPROVAL:
        return False
    if not session.proposal or not _proposal_revision_is_current(session.proposal):
        return False
    if session.proposal.revision != revision:
        return False
    if session.reviewed_revision != revision:
        return False
    if _has_blocking_conflicts(session):
        return False
    if _has_unresolved_proposals(session.proposal):
        return False
    if not _full_reconciliation_confirmed(session):
        return False
    if session.expires_at is not None:
        current = now or datetime.now(UTC)
        if current > session.expires_at:
            return False
    return True


def bind_proposal_revision(session: ImportSession, proposal: ImportSessionProposal) -> ImportSession:
    """Return copy with proposal revision/hash persisted immutably."""
    digest = compute_proposal_hash(proposal)
    revision = compute_proposal_revision(proposal)
    locked = proposal.model_copy(update={"revision": revision, "revision_hash": digest})
    return session.model_copy(update={"proposal": locked, "mode": proposal.mode, "reviewed_revision": revision})


def apply_transition(
    session: ImportSession,
    target: ImportSessionState,
    *,
    now: datetime | None = None,
    approval_revision: str | None = None,
    approval_token_hash: str | None = None,
) -> ImportSession:
    """Pure transition function for all state and metadata changes."""
    assert_transition_allowed(session.state, target)
    current = now or datetime.now(UTC)

    if target == ImportSessionState.APPROVED:
        if approval_revision is None:
            raise ApprovalBlockedError("approve requires revision")
        if not can_approve_session(session, approval_revision, now=current):
            raise ApprovalBlockedError("session is not currently approvable")
        if session.approval_token_hash and approval_token_hash != session.approval_token_hash:
            raise StaleProposalError("approval token mismatch")
        return session.model_copy(
            update={
                "state": target,
                "approved_revision": approval_revision,
                "approved_at": current,
            }
        )

    if target == ImportSessionState.REJECTED:
        return session.model_copy(update={"state": target})

    if target == ImportSessionState.COMMITTED:
        if session.state != ImportSessionState.COMMITTING:
            raise SessionStateError("commit output state must follow COMMITTING")
    return session.model_copy(update={"state": target})


def mark_source_ref(*, sheet: str, row: int, column: str) -> SourceCellRef:
    return SourceCellRef(sheet=sheet, row=row, column=column)


# transition alias kept for explicit public mapping
TransitionGuard = (can_transition, apply_transition)
