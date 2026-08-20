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
