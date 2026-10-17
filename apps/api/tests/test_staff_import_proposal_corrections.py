from uuid import uuid4

from app.modules.staff_import_legacy_adapter import LEGACY_ROOT_EXTERNAL_KEY, LegacyStaffRow, adapt_legacy_rows
from app.modules.staff_import_sessions import ImportMode, MatchAction, ProposalConfidence
from app.modules.staff_import_sessions.corrections import apply_proposal_corrections
from app.modules.staff_import_sessions.schemas import (
    BranchProposal,
    CanonicalDepartmentProposal,
    CanonicalPositionProposal,
    CanonicalStaffProposal,
    ImportSessionConflict,
    ImportSessionProposal,
    ProposalCorrection,
    ProposalItemKind,
)


def _proposal() -> ImportSessionProposal:
    return ImportSessionProposal(
        mode=ImportMode.ADD_OR_UPDATE,
        source_file_name="staff.xlsx",
        source_file_sha256="a" * 64,
        branches=[BranchProposal(external_key="b1", branch_id="b1", branch_name="Филиал 1", action=MatchAction.CREATE)],
        departments=[
            CanonicalDepartmentProposal(
                external_key="d1",
                department_id="d1",
                department_name="Старое имя",
                branch_external_key="b1",
                action=MatchAction.CONFLICT,
                confidence=ProposalConfidence.LOW,
            )
        ],
        positions=[
            CanonicalPositionProposal(
                external_key="p1",
                position_id="p1",
                position_name="Кассир",
                branch_external_key="b1",
                department_external_key="d1",
                action=MatchAction.CREATE,
            )
        ],
        staff=[
            CanonicalStaffProposal(
                external_key="s1",
                personnel_number="1",
                first_name="А",
                last_name="Б",
                position_external_key="p1",
                branch_external_key="b1",
                department_external_key="d1",
                action=MatchAction.CREATE,
            )
        ],
        conflicts=[
            ImportSessionConflict(
                conflict_code="ambiguous",
                scope="department",
                message="Исправьте отдел",
                blocking=True,
                proposal_ids=["d1"],
            )
        ],
    )


def test_methodologist_correction_rebinds_hierarchy_and_clears_linked_conflict() -> None:
    corrected = apply_proposal_corrections(
        _proposal(),
        [ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key="d1", name="Отдел продаж")],
    )
    assert corrected.departments[0].department_name == "Отдел продаж"
    assert corrected.departments[0].action is MatchAction.CREATE
    assert corrected.departments[0].confidence is ProposalConfidence.HIGH
    assert corrected.conflicts == []
    assert corrected.revision is corrected.revision_hash is None


def test_methodologist_correction_rejects_unknown_parent() -> None:
    try:
        apply_proposal_corrections(
            _proposal(),
            [ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key="d1", branch_external_key="missing")],
        )
    except ValueError as exc:
        assert "unknown department branch" in str(exc)
    else:
        raise AssertionError("unknown parent must be rejected")


def test_legacy_correction_synchronizes_exact_generic_branch_and_department_mirrors() -> None:
    proposal = adapt_legacy_rows(
        tenant_id=uuid4(),
        source_file_name="legacy.xlsx",
        source_file_sha256="b" * 64,
        rows=[LegacyStaffRow(row_number=2, personnel_number="1", first_name="A", last_name="B", branch="North", department="Sales", position="Manager")],
    )
    branch = proposal.branches[0]
    department = proposal.departments[0]
    corrected = apply_proposal_corrections(
        proposal,
        [
            ProposalCorrection(kind=ProposalItemKind.BRANCH, external_key=branch.external_key, name="North corrected"),
            ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key=department.external_key, name="Sales corrected"),
        ],
    )

    corrected_branch = next(item for item in corrected.branches if item.external_key == branch.external_key)
    corrected_department = next(item for item in corrected.departments if item.external_key == department.external_key)
    generic_branch = next(item for item in corrected.organization_units if item.external_key == branch.external_key)
    generic_department = next(item for item in corrected.organization_units if item.external_key == department.external_key)
    assert generic_branch.name == corrected_branch.branch_name == "North corrected"
    assert generic_department.name == corrected_department.department_name == "Sales corrected"
    assert generic_branch.action is corrected_branch.action is MatchAction.CREATE
    assert generic_department.action is corrected_department.action is MatchAction.CREATE
    assert generic_branch.confidence is corrected_branch.confidence is ProposalConfidence.HIGH
    assert generic_department.confidence is corrected_department.confidence is ProposalConfidence.HIGH
    assert generic_branch.evidence[-1].evidence_code == generic_department.evidence[-1].evidence_code == "methodologist_correction"
    assert generic_department.parent_external_key == corrected_department.branch_external_key == branch.external_key
    assert [item.external_key for item in corrected.positions] == [item.external_key for item in proposal.positions]
    assert [item.external_key for item in corrected.staff] == [item.external_key for item in proposal.staff]


def test_legacy_root_department_mirror_uses_none_parent() -> None:
    proposal = adapt_legacy_rows(
        tenant_id=uuid4(),
        source_file_name="legacy.xlsx",
        source_file_sha256="c" * 64,
        rows=[LegacyStaffRow(row_number=2, personnel_number="1", first_name="A", last_name="B", branch="", department="Sales", position="Manager")],
    )
    corrected = apply_proposal_corrections(
        proposal,
        [ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key=proposal.departments[0].external_key, name="Sales corrected")],
    )
    generic_department = next(item for item in corrected.organization_units if item.external_key == proposal.departments[0].external_key)
    assert generic_department.name == "Sales corrected"
    assert generic_department.parent_external_key is None


def test_department_name_only_correction_preserves_existing_generic_parent() -> None:
    proposal = _dual_branch_proposal()
    department = proposal.departments[0]
    generic_department = next(item for item in proposal.organization_units if item.external_key == department.external_key)
    proposal = proposal.model_copy(
        update={
            "organization_units": [
                item.model_copy(update={"parent_external_key": None})
                if item.external_key == generic_department.external_key
                else item
                for item in proposal.organization_units
            ]
        }
    )
    corrected = apply_proposal_corrections(
        proposal,
        [ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key=department.external_key, name="Sales renamed")],
    )
    corrected_generic = next(item for item in corrected.organization_units if item.external_key == department.external_key)
    assert corrected_generic.name == "Sales renamed"
    assert corrected_generic.parent_external_key is None


def test_explicit_position_and_staff_department_corrections_sync_organization_unit_links() -> None:
    proposal = adapt_legacy_rows(
        tenant_id=uuid4(),
        source_file_name="legacy.xlsx",
        source_file_sha256="d" * 64,
        rows=[
            LegacyStaffRow(row_number=2, personnel_number="1", first_name="A", last_name="B", branch="North", department="Sales", position="Manager"),
            LegacyStaffRow(row_number=3, personnel_number="2", first_name="C", last_name="D", branch="North", department="Support", position="Manager"),
        ],
    )
    target_department = next(item for item in proposal.departments if item.department_name == "Support")
    corrected = apply_proposal_corrections(
        proposal,
        [
            ProposalCorrection(kind=ProposalItemKind.POSITION, external_key=proposal.positions[0].external_key, department_external_key=target_department.external_key),
            ProposalCorrection(kind=ProposalItemKind.STAFF, external_key=proposal.staff[0].external_key, department_external_key=target_department.external_key),
        ],
    )
    assert corrected.positions[0].department_external_key == target_department.external_key
    assert corrected.positions[0].organization_unit_external_key == target_department.external_key
    assert corrected.staff[0].department_external_key == target_department.external_key
    assert corrected.staff[0].organization_unit_external_key == target_department.external_key


def _dual_branch_proposal():
    return adapt_legacy_rows(
        tenant_id=uuid4(),
        source_file_name="legacy.xlsx",
        source_file_sha256="e" * 64,
        rows=[
            LegacyStaffRow(row_number=2, personnel_number="1", first_name="A", last_name="B", branch="North", department="Sales", position="Manager"),
            LegacyStaffRow(row_number=3, personnel_number="2", first_name="C", last_name="D", branch="South", department="Support", position="Manager"),
        ],
    )


def test_position_clear_to_legacy_root_keeps_existing_branch_as_effective_organization_unit() -> None:
    proposal = _dual_branch_proposal()
    corrected = apply_proposal_corrections(
        proposal,
        [ProposalCorrection(kind=ProposalItemKind.POSITION, external_key=proposal.positions[0].external_key, department_external_key=LEGACY_ROOT_EXTERNAL_KEY)],
    )
    assert corrected.positions[0].department_external_key is None
    assert corrected.positions[0].branch_external_key == proposal.branches[0].external_key
    assert corrected.positions[0].organization_unit_external_key == proposal.branches[0].external_key


def test_position_branch_only_correction_preserves_existing_department_organization_unit() -> None:
    proposal = _dual_branch_proposal()
    target_branch = next(item for item in proposal.branches if item.external_key == proposal.positions[0].branch_external_key)
    original_department = proposal.positions[0].department_external_key
    corrected = apply_proposal_corrections(
        proposal,
        [ProposalCorrection(kind=ProposalItemKind.POSITION, external_key=proposal.positions[0].external_key, branch_external_key=target_branch.external_key)],
    )
    assert corrected.positions[0].branch_external_key == target_branch.external_key
    assert corrected.positions[0].department_external_key == original_department
    assert corrected.positions[0].organization_unit_external_key == original_department


def test_position_name_only_correction_preserves_existing_organization_unit() -> None:
    proposal = _dual_branch_proposal()
    original_department = proposal.positions[0].organization_unit_external_key
    corrected = apply_proposal_corrections(
        proposal,
        [ProposalCorrection(kind=ProposalItemKind.POSITION, external_key=proposal.positions[0].external_key, name="Senior manager")],
    )
    assert corrected.positions[0].position_name == "Senior manager"
    assert corrected.positions[0].organization_unit_external_key == original_department


def test_editing_an_unchanged_proposal_marks_actual_change_as_update_not_unchanged() -> None:
    original = _proposal()
    proposal = original.model_copy(update={"departments": [original.departments[0].model_copy(update={"action": MatchAction.UNCHANGED})]})
    renamed = apply_proposal_corrections(proposal, [ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key="d1", name="New name")])
    assert renamed.departments[0].action is MatchAction.UPDATE
    same = apply_proposal_corrections(proposal, [ProposalCorrection(kind=ProposalItemKind.DEPARTMENT, external_key="d1", name="Старое имя")])
    assert same.departments[0].action is MatchAction.UNCHANGED
