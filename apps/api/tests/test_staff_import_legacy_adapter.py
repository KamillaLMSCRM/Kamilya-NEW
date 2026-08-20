from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.staff_import_legacy_adapter import (
    LEGACY_ROOT_EXTERNAL_KEY,
    LegacyStaffRow,
    adapt_legacy_rows,
)
from app.modules.staff_import_sessions import ImportMode, MatchAction, ProposalConfidence

TENANT_ID = uuid4()
SOURCE_SHA = "a" * 64


def _row(
    row_number: int,
    *,
    department: str,
    position: str,
    personnel_number: str = "001",
    full_name: str = "Иванов Иван",
    email: str | None = None,
) -> LegacyStaffRow:
    first_name, last_name = full_name.split(" ", 1)
    return LegacyStaffRow(
        row_number=row_number,
        personnel_number=personnel_number,
        first_name=first_name,
        last_name=last_name,
        department=department,
        position=position,
        email=email,
    )


def test_flat_legacy_branch_labels_become_branches_with_direct_positions():
    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="staff.xls",
        source_file_sha256=SOURCE_SHA,
        rows=[
            _row(3, department="Филиал Павлодар", position="Кассир", personnel_number="001", email="a@example.test"),
            _row(
                4,
                department="Филиал Павлодар",
                position="Кассир",
                personnel_number="002",
                full_name="Петров Пётр",
                email="b@example.test",
            ),
        ],
        generated_at=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert proposal.mode is ImportMode.ADD_OR_UPDATE
    assert len(proposal.branches) == 1
    assert proposal.departments == []
    assert len(proposal.positions) == 1
    assert len(proposal.staff) == 2
    assert proposal.positions[0].department_external_key is None
    assert proposal.positions[0].branch_external_key == proposal.branches[0].external_key
    assert proposal.branches[0].action is MatchAction.CREATE
    assert proposal.branches[0].source_refs[0].row == 3
    assert proposal.positions[0].source_refs[0].column == "C"
    assert proposal.staff[0].source_refs[0].row == 3
    assert all(
        set(ref.model_dump()) == {"sheet", "row", "column"}
        for item in (*proposal.branches, *proposal.departments, *proposal.positions, *proposal.staff)
        for ref in item.source_refs
    )
    assert any(item.evidence_code == "legacy_branch_label" for item in proposal.branches[0].evidence)


def test_missing_branch_uses_explicit_legacy_root_department_compatibility():
    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="flat-departments.xlsx",
        source_file_sha256=SOURCE_SHA,
        rows=[
            _row(2, department="Продажи", position="Менеджер", personnel_number="100"),
            _row(3, department="Продажи", position="Менеджер", personnel_number="101", full_name="Петров Пётр"),
        ],
    )

    assert proposal.branches == []
    assert len(proposal.departments) == 1
    department = proposal.departments[0]
    assert department.branch_external_key == LEGACY_ROOT_EXTERNAL_KEY
    assert department.department_name == "Продажи"
    assert proposal.positions[0].branch_external_key == LEGACY_ROOT_EXTERNAL_KEY
    assert proposal.positions[0].department_external_key == department.external_key
    assert any(item.evidence_code == "legacy_root_department" for item in department.evidence)
    assert all(item.confidence is ProposalConfidence.MEDIUM for item in department.evidence)


def test_repeated_import_has_stable_external_keys_and_add_update_mode():
    rows = [
        _row(2, department="Филиал Астана", position="Кассир", personnel_number="A-1"),
        _row(3, department="Филиал Восток", position="Кассир", personnel_number="A-2", full_name="Петров Пётр"),
    ]
    first = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="partial.xls",
        source_file_sha256=SOURCE_SHA,
        rows=rows,
    )
    second = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="partial.xls",
        source_file_sha256=SOURCE_SHA,
        rows=rows,
    )

    assert first.mode is second.mode is ImportMode.ADD_OR_UPDATE
    assert [item.external_key for item in first.branches] == [item.external_key for item in second.branches]
    assert [item.external_key for item in first.positions] == [item.external_key for item in second.positions]
    assert [item.external_key for item in first.staff] == [item.external_key for item in second.staff]
    assert first.model_copy(update={"generated_at": second.generated_at}).model_dump(
        exclude={"generated_at"}
    ) == second.model_dump(exclude={"generated_at"})


def test_row_order_does_not_change_canonical_entity_order_or_keys():
    rows = [
        _row(2, department="Филиал Восток", position="Кассир", personnel_number="A-2"),
        _row(3, department="Филиал Астана", position="Кассир", personnel_number="A-1", full_name="Петров Пётр"),
    ]
    first = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="reordered.xls",
        source_file_sha256=SOURCE_SHA,
        rows=rows,
    )
    second = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="reordered.xls",
        source_file_sha256=SOURCE_SHA,
        rows=list(reversed(rows)),
    )

    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})


def test_duplicate_personnel_rows_are_blocked_and_not_silently_duplicated():
    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="duplicate.xls",
        source_file_sha256=SOURCE_SHA,
        rows=[
            _row(2, department="Филиал Астана", position="Кассир", personnel_number="001"),
            _row(3, department="Филиал Астана", position="Кассир", personnel_number="001", full_name="Петров Пётр"),
        ],
    )

    assert len(proposal.staff) == 1
    assert any(conflict.conflict_code == "duplicate_personnel_number" for conflict in proposal.conflicts)
    assert any(conflict.blocking for conflict in proposal.conflicts)


def test_missing_required_legacy_value_is_a_blocking_conflict_without_partial_staff():
    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="invalid.xls",
        source_file_sha256=SOURCE_SHA,
        rows=[
            _row(2, department="Филиал Астана", position="", personnel_number="001"),
        ],
    )

    assert proposal.positions == []
    assert proposal.staff == []
    assert any(conflict.conflict_code == "missing_position" for conflict in proposal.conflicts)


def test_explicit_branch_column_nests_departments_and_uses_branch_cell_reference():
    row = LegacyStaffRow(
        row_number=7,
        personnel_number="B-7",
        first_name="Иван",
        last_name="Иванов",
        department="Продажи",
        position="Менеджер",
        branch="Павлодар",
    )

    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="new-layout.xlsx",
        source_file_sha256=SOURCE_SHA,
        rows=[row],
    )

    assert len(proposal.branches) == 1
    assert len(proposal.departments) == 1
    branch = proposal.branches[0]
    department = proposal.departments[0]
    assert department.branch_external_key == branch.external_key
    assert proposal.positions[0].department_external_key == department.external_key
    assert branch.source_refs[0].column == "G"
    assert department.source_refs[0].column == "D"
    assert any(item.evidence_code == "explicit_branch_column" for item in branch.evidence)


def test_requested_reconciliation_mode_is_preserved():
    proposal = adapt_legacy_rows(
        tenant_id=TENANT_ID,
        source_file_name="full.xlsx",
        source_file_sha256=SOURCE_SHA,
        rows=[_row(2, department="Продажи", position="Менеджер")],
        mode=ImportMode.FULL_RECONCILIATION,
    )

    assert proposal.mode is ImportMode.FULL_RECONCILIATION
