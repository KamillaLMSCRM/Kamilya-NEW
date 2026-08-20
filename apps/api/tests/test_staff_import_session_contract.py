"""Behavior-focused tests for staff import session contract and state machine."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.staff_import_sessions import (
    BranchProposal,
    CanonicalDepartmentProposal,
    CanonicalPositionProposal,
    CanonicalStaffProposal,
    EvidenceItem,
    ImportMode,
    ImportSession,
    ImportSessionConflict,
    ImportSessionProposal,
    ImportSessionState,
    MatchAction,
    ProposalConfidence,
    SourceCellRef,
)
from app.modules.staff_import_sessions.state_machine import (
    ApprovalBlockedError,
    StaleProposalError,
    apply_transition,
    bind_proposal_revision,
    can_approve_session,
    compute_proposal_hash,
    compute_proposal_revision,
    next_states,
)


def _base_session() -> ImportSession:
    return ImportSession(
        session_id="sess-001",
        tenant_id=uuid4(),
        actor_id=uuid4(),
        actor_role="methodologist",
        approval_token_hash="tok-abc",
    )


def _empty_proposal(mode: ImportMode = ImportMode.ADD_OR_UPDATE) -> ImportSessionProposal:
    return ImportSessionProposal(
        mode=mode,
        source_file_name="staff.xlsx",
        source_file_sha256="0" * 64,
        branches=[],
        departments=[],
        positions=[],
        staff=[],
        conflicts=[],
        evidence=[],
    )


def _proposal_with_overrides(**overrides: object) -> ImportSessionProposal:
    return _empty_proposal().model_copy(update=overrides)


def _blocking_conflict(blocking: bool) -> ImportSessionConflict:
    return ImportSessionConflict(
        conflict_code="name_collision",
        scope="staff",
        message="same personnel number maps to multiple rows",
        blocking=blocking,
        source_refs=[SourceCellRef(sheet="Сотрудники", row=2, column="B")],
    )


def test_next_state_map_has_add_or_update_default():
    session = _base_session()
    assert session.mode == ImportMode.ADD_OR_UPDATE


def test_default_transition_map_from_uploaded_state():
    states = next_states(ImportSessionState.UPLOADED)
    assert set(states) == {
        ImportSessionState.INSPECTING,
        ImportSessionState.FAILED,
        ImportSessionState.EXPIRED,
    }


def test_committing_and_rejected_states_do_not_reopen_review():
    assert ImportSessionState.REJECTED not in next_states(ImportSessionState.COMMITTING)
    assert next_states(ImportSessionState.REJECTED) == []


def test_deterministic_proposal_hash_and_revision_for_identical_payload():
    proposal = _empty_proposal()
    assert compute_proposal_hash(proposal) == compute_proposal_hash(proposal.model_copy())
    assert compute_proposal_revision(proposal) == compute_proposal_revision(proposal.model_copy())


def test_binding_revision_is_immutable_and_reproducible():
    session = _base_session()
    proposal = _empty_proposal()
    revised = bind_proposal_revision(session, proposal)

    assert revised.proposal is not None
    assert revised.proposal.revision is not None
    assert revised.reviewed_revision == revised.proposal.revision
    assert revised.proposal.revision_hash == compute_proposal_hash(proposal)


def test_blocking_conflict_blocks_approval():
    session = _base_session()
    proposal = _empty_proposal().model_copy(update={"conflicts": [_blocking_conflict(True)]})
    prepared = bind_proposal_revision(session, proposal).model_copy(
        update={"state": ImportSessionState.READY_FOR_APPROVAL}
    )

    assert not can_approve_session(prepared, revision=prepared.proposal.revision)
    with pytest.raises(ApprovalBlockedError):
        apply_transition(
            prepared,
            ImportSessionState.APPROVED,
            approval_revision=prepared.proposal.revision,
            approval_token_hash="tok-abc",
        )


def test_non_blocking_conflict_allows_approval_when_ready():
    session = _base_session().model_copy(update={"state": ImportSessionState.READY_FOR_APPROVAL})
    proposal = _empty_proposal().model_copy(update={"conflicts": [_blocking_conflict(False)]})
    prepared = bind_proposal_revision(session, proposal)

    assert can_approve_session(prepared, revision=prepared.proposal.revision)
    approved = apply_transition(
        prepared,
        ImportSessionState.APPROVED,
        approval_revision=prepared.proposal.revision,
        approval_token_hash="tok-abc",
    )
    assert approved.state == ImportSessionState.APPROVED
    assert approved.approved_revision == prepared.proposal.revision


def test_full_reconciliation_mode_requires_confirmation_flag():
    session = _base_session().model_copy(
        update={
            "mode": ImportMode.FULL_RECONCILIATION,
            "state": ImportSessionState.READY_FOR_APPROVAL,
        }
    )
    proposal = _empty_proposal(mode=ImportMode.FULL_RECONCILIATION)
    prepared = bind_proposal_revision(session, proposal)

    assert not can_approve_session(prepared, revision=prepared.proposal.revision)

    confirmed = prepared.model_copy(update={"full_reconciliation_confirmation": True})
    assert can_approve_session(confirmed, revision=confirmed.proposal.revision)


def test_expired_session_is_not_approvable():
    proposal = _empty_proposal()
    expired = _base_session().model_copy(
        update={
            "state": ImportSessionState.READY_FOR_APPROVAL,
            "expires_at": datetime(2000, 1, 1, tzinfo=UTC),
        }
    )
    prepared = bind_proposal_revision(expired, proposal)

    assert not can_approve_session(prepared, revision=prepared.proposal.revision, now=datetime(2030, 1, 1, tzinfo=UTC))


def test_stale_revision_rejected():
    proposal = _empty_proposal()
    prepared = bind_proposal_revision(
        _base_session().model_copy(update={"state": ImportSessionState.READY_FOR_APPROVAL}), proposal
    )

    with pytest.raises(ApprovalBlockedError):
        apply_transition(
            prepared,
            ImportSessionState.APPROVED,
            approval_revision="rev-stale-000",
            approval_token_hash="tok-abc",
        )


def test_tampered_proposal_with_old_revision_is_not_approvable():
    proposal = _empty_proposal()
    prepared = bind_proposal_revision(
        _base_session().model_copy(update={"state": ImportSessionState.READY_FOR_APPROVAL}),
        proposal,
    )
    tampered = prepared.model_copy(
        update={
            "proposal": prepared.proposal.model_copy(
                update={
                    "branches": [
                        BranchProposal(
                            branch_id="unexpected",
                            branch_name="Неутверждённый филиал",
                            external_key="branch:unexpected",
                            action=MatchAction.CREATE,
                            confidence=ProposalConfidence.HIGH,
                        )
                    ]
                }
            )
        }
    )

    assert not can_approve_session(
        tampered,
        revision=tampered.proposal.revision,
    )


def test_low_confidence_unresolved_item_blocks_approval():
    proposal = _proposal_with_overrides(
        branches=[
            BranchProposal(
                branch_id="ambiguous",
                branch_name="Подразделение 1",
                external_key="branch:ambiguous",
                action=MatchAction.CREATE,
                confidence=ProposalConfidence.LOW,
            )
        ]
    )
    prepared = bind_proposal_revision(
        _base_session().model_copy(update={"state": ImportSessionState.READY_FOR_APPROVAL}),
        proposal,
    )

    assert not can_approve_session(
        prepared,
        revision=prepared.proposal.revision,
    )


def test_approval_token_mismatch_raises_stale_error():
    proposal = _empty_proposal()
    prepared = bind_proposal_revision(
        _base_session().model_copy(update={"state": ImportSessionState.READY_FOR_APPROVAL}), proposal
    )

    with pytest.raises(StaleProposalError):
        apply_transition(
            prepared,
            ImportSessionState.APPROVED,
            approval_revision=prepared.proposal.revision,
            approval_token_hash="wrong",
        )


def test_can_approve_without_proposal_is_false():
    session = _base_session().model_copy(update={"state": ImportSessionState.READY_FOR_APPROVAL})
    assert not can_approve_session(session, revision="anything")


def test_canonical_dto_fields_are_preserved():
    proposal = _proposal_with_overrides(
        branches=[
            BranchProposal(
                branch_id="b1",
                branch_name="Петропавловск",
                external_key="ext-b1",
                action=MatchAction.CREATE,
                confidence=ProposalConfidence.HIGH,
                source_refs=[SourceCellRef(sheet="Сотрудники", row=3, column="A")],
            )
        ],
        departments=[
            CanonicalDepartmentProposal(
                department_id="d1",
                department_name="HR",
                branch_external_key="ext-b1",
                external_key="dep-hr",
                action=MatchAction.CREATE,
                confidence=ProposalConfidence.MEDIUM,
            )
        ],
        positions=[
            CanonicalPositionProposal(
                position_id="p1",
                position_name="Менеджер",
                department_external_key="dep-hr",
                branch_external_key="ext-b1",
                external_key="pos-mgr",
                action=MatchAction.CREATE,
                confidence=ProposalConfidence.LOW,
            )
        ],
        evidence=[
            EvidenceItem(
                evidence_code="header_detected",
                claim="found header on row 3",
                confidence=ProposalConfidence.HIGH,
            )
        ],
    )

    staff = CanonicalStaffProposal(
        personnel_number="PN-001",
        first_name="Айбек",
        last_name="Ахметов",
        position_external_key="pos-mgr",
        department_external_key="dep-hr",
        branch_external_key="ext-b1",
        external_key="stf-AK-1",
        action=MatchAction.CREATE,
        confidence=ProposalConfidence.HIGH,
    )
    proposal = proposal.model_copy(update={"staff": [staff]})

    stored = bind_proposal_revision(_base_session(), proposal)
    assert stored.proposal is not None
    assert stored.proposal.branches[0].branch_name == "Петропавловск"
    assert stored.proposal.staff[0].personnel_number == "PN-001"
    assert stored.proposal.evidence[0].claim == "found header on row 3"


def test_position_and_staff_can_belong_directly_to_branch():
    position = CanonicalPositionProposal(
        position_id="p-direct",
        position_name="Управляющий филиалом",
        branch_external_key="branch:pavlodar",
        department_external_key=None,
        external_key="position:pavlodar:manager",
        action=MatchAction.CREATE,
        confidence=ProposalConfidence.HIGH,
    )
    staff = CanonicalStaffProposal(
        personnel_number="PN-DIRECT",
        first_name="Тест",
        last_name="Сотрудник",
        position_external_key=position.external_key,
        branch_external_key="branch:pavlodar",
        department_external_key=None,
        external_key="staff:pn-direct",
        action=MatchAction.CREATE,
        confidence=ProposalConfidence.HIGH,
    )

    assert position.department_external_key is None
    assert staff.department_external_key is None
