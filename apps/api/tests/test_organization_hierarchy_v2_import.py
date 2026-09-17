from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.staff_import_session import StaffImportSession
from app.modules.organization_units.domain import OrganizationUnitType
from app.modules.staff_import_legacy_adapter import LegacyStaffRow, adapt_legacy_rows
from app.modules.staff_import_matching import (
    ImportDiffAction,
    ImportHierarchyConflictError,
    IncomingOrganizationUnit,
    IncomingPosition,
    build_import_diff,
    topologically_order_organization_units,
)
from app.modules.staff_import_sessions import (
    CanonicalPositionProposal,
    CanonicalStaffProposal,
    ImportSession,
    ImportSessionProposal,
    ImportSessionState,
    MatchAction,
    OrganizationUnitProposal,
    bind_proposal_revision,
)
from app.modules.staff_import_sessions.commit_service import (
    ImportCommitConflictError,
    build_generic_unit_commit_plan,
    commit_approved_import_session,
)
from app.modules.staff_import_sessions.corrections import apply_proposal_corrections
from app.modules.staff_import_sessions.schemas import ProposalCorrection

TENANT_ID = uuid4()
SOURCE_SHA = "b" * 64


def test_generic_proposal_defaults_head_office_and_allows_optional_unit_links() -> None:
    proposal = ImportSessionProposal(
        source_file_name="generic.xlsx",
        source_file_sha256=SOURCE_SHA,
        organization_units=[
            OrganizationUnitProposal(
                external_key="unit-1",
                parent_external_key=None,
                unit_type=OrganizationUnitType.MANAGEMENT,
                name="Management",
                action=MatchAction.CREATE,
            )
        ],
        positions=[
            CanonicalPositionProposal(
                position_id="pos-1",
                position_name="Accountant",
                external_key="pos-1",
                action=MatchAction.CREATE,
                organization_unit_external_key="unit-1",
            ),
            CanonicalPositionProposal(
                position_id="pos-2",
                position_name="Floating specialist",
                external_key="pos-2",
                action=MatchAction.CREATE,
            ),
        ],
        staff=[
            CanonicalStaffProposal(
                personnel_number="001",
                first_name="A",
                last_name="User",
                position_external_key="pos-1",
                external_key="staff-1",
                action=MatchAction.CREATE,
                organization_unit_external_key="unit-1",
            ),
            CanonicalStaffProposal(
                personnel_number="002",
                first_name="B",
                last_name="User",
                position_external_key="pos-2",
                external_key="staff-2",
                action=MatchAction.CREATE,
            ),
        ],
    )

    assert proposal.organization_units[0].is_head_office is False
    assert proposal.positions[0].organization_unit_external_key == "unit-1"
    assert proposal.positions[1].organization_unit_external_key is None
    assert proposal.staff[0].organization_unit_external_key == "unit-1"
    assert proposal.staff[1].organization_unit_external_key is None


def test_legacy_adapter_keeps_legacy_projection_and_emits_equivalent_generic_units() -> None:
    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="legacy.xlsx",
        source_file_sha256=SOURCE_SHA,
        rows=[
            LegacyStaffRow(
                row_number=2,
                personnel_number="001",
                first_name="A",
                last_name="User",
                branch="North",
                department="Operations",
                position="Manager",
            )
        ],
    )

    assert len(proposal.branches) == 1
    assert len(proposal.departments) == 1
    assert [(unit.external_key, unit.parent_external_key, unit.unit_type, unit.name) for unit in proposal.organization_units] == [
        (proposal.branches[0].external_key, None, OrganizationUnitType.BRANCH, "North"),
        (
            proposal.departments[0].external_key,
            proposal.branches[0].external_key,
            OrganizationUnitType.DEPARTMENT,
            "Operations",
        ),
    ]
    assert all(unit.is_head_office is False for unit in proposal.organization_units)
    assert proposal.positions[0].organization_unit_external_key == proposal.departments[0].external_key
    assert proposal.staff[0].organization_unit_external_key == proposal.departments[0].external_key


def _unit(key: str, parent: str | None, name: str) -> OrganizationUnitProposal:
    return OrganizationUnitProposal(
        external_key=key,
        parent_external_key=parent,
        unit_type=OrganizationUnitType.OTHER,
        name=name,
        action=MatchAction.CREATE,
    )


def test_generic_units_are_committed_in_topological_order_at_any_supported_depth() -> None:
    units = [
        _unit("u4", "u3", "Team"),
        _unit("u2", "u1", "Division"),
        _unit("u1", None, "Organization"),
        _unit("u3", "u2", "Department"),
    ]

    assert [unit.external_key for unit in topologically_order_organization_units(units)] == [
        "u1",
        "u2",
        "u3",
        "u4",
    ]


def test_generic_units_reject_depth_nine_before_commit() -> None:
    units = [
        _unit(f"u{depth}", f"u{depth - 1}" if depth else None, f"Level {depth}")
        for depth in range(10)
    ]

    with pytest.raises(ImportHierarchyConflictError, match="maximum depth"):
        topologically_order_organization_units(units)


def test_generic_units_require_one_explicit_root_head_office() -> None:
    two_heads = [
        _unit("head-1", None, "Central A").model_copy(update={"is_head_office": True}),
        _unit("head-2", None, "Central B").model_copy(update={"is_head_office": True}),
    ]
    nested_head = _unit("head", "parent", "Central").model_copy(
        update={"is_head_office": True}
    )

    with pytest.raises(ImportHierarchyConflictError, match="more than one head office"):
        topologically_order_organization_units(two_heads)
    with pytest.raises(ImportHierarchyConflictError, match="root organization unit"):
        topologically_order_organization_units(
            [_unit("parent", None, "Parent"), nested_head]
        )

def test_generic_unit_parent_validation_rejects_missing_ambiguous_and_cyclic_graphs() -> None:
    with pytest.raises(ImportHierarchyConflictError, match="missing parent"):
        topologically_order_organization_units([_unit("child", "missing", "Child")])

    with pytest.raises(ImportHierarchyConflictError, match="ambiguous parent"):
        topologically_order_organization_units([_unit("parent", None, "Parent"), _unit("parent", None, "Other")])

    with pytest.raises(ImportHierarchyConflictError, match="cycle"):
        topologically_order_organization_units([_unit("a", "b", "A"), _unit("b", "a", "B")])


def test_same_generic_unit_name_is_valid_when_parents_differ() -> None:
    result = build_import_diff(
        tenant_id=TENANT_ID,
        incoming_units=[
            IncomingOrganizationUnit(
                tenant_id=TENANT_ID,
                external_key="u-a-child",
                parent_external_key="u-a",
                name="Operations",
                unit_type=OrganizationUnitType.DEPARTMENT,
            ),
            IncomingOrganizationUnit(
                tenant_id=TENANT_ID,
                external_key="u-b-child",
                parent_external_key="u-b",
                name="Operations",
                unit_type=OrganizationUnitType.DEPARTMENT,
            ),
        ],
    )

    assert [entry.action for entry in result.entries] == [ImportDiffAction.CREATE, ImportDiffAction.CREATE]
    assert not result.has_blocking_conflicts


def test_generic_commit_plan_preserves_matched_ids_and_orders_four_levels() -> None:
    root_id = uuid4()
    existing_root = SimpleNamespace(
        id=root_id,
        external_key="u1",
        parent_id=None,
        normalized_name="organization",
        name="Old organization",
        unit_type="other",
    )
    plan = build_generic_unit_commit_plan(
        [
            _unit("u4", "u3", "Team"),
            _unit("u2", "u1", "Division"),
            _unit("u1", None, "Organization"),
            _unit("u3", "u2", "Department"),
        ],
        existing_units=[existing_root],
    )

    assert [item.proposal.external_key for item in plan] == ["u1", "u2", "u3", "u4"]
    assert plan[0].existing is existing_root
    assert plan[0].existing.id == root_id


def test_matching_allows_a_position_without_an_organization_unit() -> None:
    result = build_import_diff(
        tenant_id=TENANT_ID,
        incoming_positions=[
            IncomingPosition(
                tenant_id=TENANT_ID,
                external_key="pos-unassigned",
                name="Floating specialist",
                org_unit_external_key=None,
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.CREATE
    assert not result.has_blocking_conflicts


def test_repeated_generic_commit_planning_is_idempotent_and_reuses_every_id() -> None:
    ids = {key: uuid4() for key in ("u1", "u2", "u3", "u4")}
    existing = [
        SimpleNamespace(
            id=ids[key],
            external_key=key,
            parent_id=ids[parent] if parent else None,
            normalized_name=name.casefold(),
            name=name,
            unit_type="other",
        )
        for key, parent, name in (
            ("u1", None, "Organization"),
            ("u2", "u1", "Division"),
            ("u3", "u2", "Department"),
            ("u4", "u3", "Team"),
        )
    ]
    proposals = [_unit("u4", "u3", "Team"), _unit("u1", None, "Organization"), _unit("u3", "u2", "Department"), _unit("u2", "u1", "Division")]

    first = build_generic_unit_commit_plan(proposals, existing_units=existing)
    second = build_generic_unit_commit_plan(proposals, existing_units=existing)

    assert [item.existing.id for item in first] == [ids[key] for key in ("u1", "u2", "u3", "u4")]
    assert [item.existing.id for item in second] == [item.existing.id for item in first]


def test_generic_commit_plan_rejects_child_below_existing_depth_eight() -> None:
    ids = [uuid4() for _ in range(9)]
    existing = [
        SimpleNamespace(
            id=ids[depth],
            external_key=f"existing-{depth}",
            parent_id=ids[depth - 1] if depth else None,
            normalized_name=f"level {depth}",
            name=f"Level {depth}",
            unit_type="other",
            is_active=True,
            is_head_office=False,
        )
        for depth in range(9)
    ]

    with pytest.raises(ImportCommitConflictError, match="maximum depth"):
        build_generic_unit_commit_plan(
            [_unit("incoming-child", "existing-8", "Too deep")],
            existing_units=existing,
        )


def test_generic_commit_plan_rejects_move_below_existing_descendant() -> None:
    root_id, child_id = uuid4(), uuid4()
    existing = [
        SimpleNamespace(
            id=root_id,
            external_key="root",
            parent_id=None,
            normalized_name="root",
            name="Root",
            unit_type="other",
            is_active=True,
            is_head_office=False,
        ),
        SimpleNamespace(
            id=child_id,
            external_key="child",
            parent_id=root_id,
            normalized_name="child",
            name="Child",
            unit_type="other",
            is_active=True,
            is_head_office=False,
        ),
    ]

    with pytest.raises(ImportCommitConflictError, match="cycle"):
        build_generic_unit_commit_plan(
            [_unit("root", "child", "Root")],
            existing_units=existing,
        )


def test_generic_unit_name_never_requests_head_office_without_explicit_flag() -> None:
    proposal = _unit("central", None, "Head Office")

    assert proposal.is_head_office is False


class _EmptyScalarResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _ReadOnlyCommitSession:
    def __init__(self) -> None:
        self.added = []
        self.flushes = 0

    async def execute(self, _statement):
        return _EmptyScalarResult()

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1


def test_invalid_generic_parent_is_rejected_before_commit_state_or_writes(monkeypatch) -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    session_id = uuid4()
    proposal = ImportSessionProposal(
        source_file_name="invalid.xlsx",
        source_file_sha256=SOURCE_SHA,
        organization_units=[_unit("child", "missing", "Child")],
    )
    domain = bind_proposal_revision(
        ImportSession(
            session_id=str(session_id),
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role="methodologist",
            state=ImportSessionState.APPROVED,
        ),
        proposal,
    )
    record = StaffImportSession(
        id=session_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role="methodologist",
        state=ImportSessionState.APPROVED.value,
        mode=domain.mode.value,
        idempotency_key="invalid-generic",
        source_file_name=proposal.source_file_name,
        source_file_sha256=proposal.source_file_sha256,
        source_format="xlsx",
        source_size_bytes=1,
        parser_version="test",
        proposal_json=domain.proposal.model_dump(mode="json"),
        proposal_revision=domain.proposal.revision,
        proposal_hash=domain.proposal.revision_hash,
        reviewed_revision=domain.proposal.revision,
        approved_revision=domain.proposal.revision,
        full_reconciliation_confirmation=False,
    )
    db = _ReadOnlyCommitSession()
    monkeypatch.setattr(
        "app.modules.staff_import_sessions.commit_service.get_import_session",
        lambda *args, **kwargs: _return_async(record),
    )

    with pytest.raises(ImportCommitConflictError, match="missing parent"):
        import asyncio

        asyncio.run(
            commit_approved_import_session(
                db,
                tenant_id=tenant_id,
                session_id=session_id,
                actor_id=actor_id,
                revision=domain.proposal.revision,
            )
        )

    assert record.state == ImportSessionState.APPROVED.value
    assert db.added == []


async def _return_async(value):
    return value


def test_generic_parent_correction_clears_revision_for_reapproval() -> None:
    proposal = ImportSessionProposal(
        source_file_name="corrected.xlsx",
        source_file_sha256=SOURCE_SHA,
        organization_units=[_unit("root", None, "Root"), _unit("child", "wrong", "Child")],
    )

    corrected = apply_proposal_corrections(
        proposal,
        [
            ProposalCorrection(
                kind="organization_unit",
                external_key="child",
                parent_external_key="root",
            )
        ],
    )

    assert corrected.organization_units[1].parent_external_key == "root"
    assert corrected.revision is None
    assert corrected.revision_hash is None
