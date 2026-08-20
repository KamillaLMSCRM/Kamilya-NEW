from __future__ import annotations

from uuid import uuid4

from app.modules.organization_units.domain import OrganizationUnitType
from app.modules.staff_import_matching import (
    ExistingOrganizationUnit,
    ExistingPosition,
    ExistingStaff,
    ImportDiffAction,
    IncomingOrganizationUnit,
    IncomingPosition,
    IncomingStaff,
    build_import_diff,
)


def _org(
    name: str,
    *,
    unit_type: OrganizationUnitType = OrganizationUnitType.BRANCH,
    external_key: str | None = None,
    parent_external_key: str | None = None,
    parent_name: str | None = None,
) -> IncomingOrganizationUnit:
    return IncomingOrganizationUnit(
        tenant_id=TENANT_ID,
        external_key=external_key,
        name=name,
        unit_type=unit_type,
        parent_external_key=parent_external_key,
        parent_name=parent_name,
    )


TENANT_ID = uuid4()


def test_units_match_by_external_key_before_normalized_identity_and_report_rename_and_move():
    branch = ExistingOrganizationUnit(
        tenant_id=TENANT_ID,
        record_id="branch-1",
        external_key="BR-1",
        name="Павлодар",
        unit_type=OrganizationUnitType.BRANCH,
    )
    department = ExistingOrganizationUnit(
        tenant_id=TENANT_ID,
        record_id="dep-1",
        external_key="DEP-1",
        name="Продажи",
        unit_type=OrganizationUnitType.DEPARTMENT,
        parent_external_key="BR-1",
        parent_name="Павлодар",
    )

    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_units=[branch, department],
        incoming_units=[
            _org("Павлодар Север", external_key="BR-1"),
            _org(
                "Продажи",
                unit_type=OrganizationUnitType.DEPARTMENT,
                external_key="DEP-1",
                parent_external_key="BR-2",
                parent_name="Астана",
            ),
        ],
    )

    assert [entry.action for entry in result.entries] == [
        ImportDiffAction.RENAME,
        ImportDiffAction.MOVE,
    ]
    assert result.entries[0].existing_id == "branch-1"
    assert "name" in result.entries[0].changed_fields
    assert "parent" in result.entries[1].changed_fields


def test_units_fallback_to_normalized_parent_type_name_and_never_duplicate():
    existing = ExistingOrganizationUnit(
        tenant_id=TENANT_ID,
        record_id="dep-1",
        external_key="old-dep-key",
        name="  Кредитование ",
        unit_type=OrganizationUnitType.DEPARTMENT,
        parent_external_key="old-branch-key",
        parent_name="Петропавловск",
    )

    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_units=[existing],
        incoming_units=[
            _org(
                "кредитование",
                unit_type=OrganizationUnitType.DEPARTMENT,
                external_key="new-dep-key",
                parent_external_key="new-branch-key",
                parent_name=" петропавловск ",
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.UPDATE
    assert result.entries[0].existing_id == "dep-1"
    assert "normalized_identity" in {item.evidence_code for item in result.entries[0].evidence}


def test_ambiguous_unit_match_is_blocking_conflict():
    existing = [
        ExistingOrganizationUnit(
            tenant_id=TENANT_ID,
            record_id="dep-1",
            external_key=None,
            name="Касса",
            unit_type=OrganizationUnitType.DEPARTMENT,
            parent_name="Павлодар",
        ),
        ExistingOrganizationUnit(
            tenant_id=TENANT_ID,
            record_id="dep-2",
            external_key=None,
            name="Касса",
            unit_type=OrganizationUnitType.DEPARTMENT,
            parent_name="Павлодар",
        ),
    ]
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_units=existing,
        incoming_units=[
            _org(
                "Касса",
                unit_type=OrganizationUnitType.DEPARTMENT,
                parent_name="Павлодар",
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.CONFLICT
    assert result.entries[0].blocking
    assert result.entries[0].conflict_code == "ambiguous_normalized_match"


def test_position_identity_is_org_unit_plus_normalized_name_and_direct_branch_is_supported():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_positions=[
            ExistingPosition(
                tenant_id=TENANT_ID,
                record_id="pos-1",
                org_unit_external_key="BR-1",
                name="Кассир",
            )
        ],
        incoming_positions=[
            IncomingPosition(
                tenant_id=TENANT_ID,
                external_key="position:branch:cashier",
                org_unit_external_key="BR-1",
                name=" кассир ",
            ),
            IncomingPosition(
                tenant_id=TENANT_ID,
                external_key="position:branch:manager",
                org_unit_external_key="BR-1",
                name="Управляющий",
            ),
        ],
    )

    assert [entry.action for entry in result.entries] == [
        ImportDiffAction.UNCHANGED,
        ImportDiffAction.CREATE,
    ]


def test_position_external_key_survives_rename_and_move():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_positions=[
            ExistingPosition(
                tenant_id=TENANT_ID,
                record_id="pos-1",
                external_key="POS-001",
                org_unit_external_key="BR-1",
                name="Кассир",
            )
        ],
        incoming_positions=[
            IncomingPosition(
                tenant_id=TENANT_ID,
                external_key="POS-001",
                org_unit_external_key="DEP-2",
                name="Старший кассир",
            )
        ],
    )

    assert result.entries[0].existing_id == "pos-1"
    assert result.entries[0].action is ImportDiffAction.MOVE
    assert set(result.entries[0].changed_fields) == {"name", "org_unit"}


def test_staff_matches_by_personnel_then_unique_email_not_name():
    existing = [
        ExistingStaff(
            tenant_id=TENANT_ID,
            record_id="staff-1",
            personnel_number="001",
            email="old@example.test",
            first_name="Анна",
            last_name="Иванова",
            position_external_key="pos-1",
        ),
        ExistingStaff(
            tenant_id=TENANT_ID,
            record_id="staff-2",
            personnel_number=None,
            email="unique@example.test",
            first_name="Борис",
            last_name="Петров",
            position_external_key="pos-2",
        ),
    ]
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_staff=existing,
        incoming_staff=[
            IncomingStaff(
                tenant_id=TENANT_ID,
                external_key="staff:001",
                personnel_number=" 001 ",
                email="changed@example.test",
                first_name="Анна",
                last_name="Иванова",
                position_external_key="pos-1",
            ),
            IncomingStaff(
                tenant_id=TENANT_ID,
                external_key="staff:boris",
                personnel_number=None,
                email="UNIQUE@example.test",
                first_name="Борис",
                last_name="Петров",
                position_external_key="pos-2",
            ),
        ],
    )

    assert [entry.action for entry in result.entries] == [
        ImportDiffAction.UPDATE,
        ImportDiffAction.UNCHANGED,
    ]
    assert [entry.existing_id for entry in result.entries] == ["staff-1", "staff-2"]


def test_blank_optional_staff_fields_do_not_clear_existing_values():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_staff=[
            ExistingStaff(
                tenant_id=TENANT_ID,
                record_id="staff-1",
                personnel_number="001",
                email="kept@example.test",
                phone="+77000000000",
                first_name="Анна",
                last_name="Иванова",
                position_external_key="pos-1",
                org_unit_external_key="branch-1",
            )
        ],
        incoming_staff=[
            IncomingStaff(
                tenant_id=TENANT_ID,
                personnel_number="001",
                email=None,
                phone=None,
                first_name="Анна",
                last_name="Иванова",
                position_external_key="pos-1",
                org_unit_external_key="branch-1",
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.UNCHANGED
    assert result.entries[0].changed_fields == ()


def test_new_personnel_number_cannot_silently_take_existing_email_identity():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_staff=[
            ExistingStaff(
                tenant_id=TENANT_ID,
                record_id="staff-1",
                personnel_number="001",
                email="same@example.test",
                first_name="Анна",
                last_name="Иванова",
            )
        ],
        incoming_staff=[
            IncomingStaff(
                tenant_id=TENANT_ID,
                personnel_number="999",
                email="same@example.test",
                first_name="Другой",
                last_name="Сотрудник",
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.CONFLICT
    assert result.entries[0].conflict_code == "personnel_number_email_conflict"


def test_staff_name_alone_never_matches_and_missing_identity_blocks():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_staff=[
            ExistingStaff(
                tenant_id=TENANT_ID,
                record_id="staff-1",
                personnel_number="001",
                email="a@example.test",
                first_name="Анна",
                last_name="Иванова",
            )
        ],
        incoming_staff=[
            IncomingStaff(
                tenant_id=TENANT_ID,
                external_key="staff:unknown",
                personnel_number=None,
                email=None,
                first_name="Анна",
                last_name="Иванова",
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.CONFLICT
    assert result.entries[0].conflict_code == "missing_staff_identity"


def test_ambiguous_email_and_cross_tenant_records_are_blocked():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        existing_staff=[
            ExistingStaff(
                tenant_id=TENANT_ID,
                record_id="staff-1",
                personnel_number=None,
                email="same@example.test",
                first_name="А",
                last_name="А",
            ),
            ExistingStaff(
                tenant_id=TENANT_ID,
                record_id="staff-2",
                personnel_number=None,
                email="same@example.test",
                first_name="Б",
                last_name="Б",
            ),
        ],
        incoming_staff=[
            IncomingStaff(
                tenant_id=TENANT_ID,
                external_key="staff:email",
                email="same@example.test",
                first_name="Новый",
                last_name="Сотрудник",
            )
        ],
    )

    assert result.entries[0].action is ImportDiffAction.CONFLICT
    assert result.entries[0].conflict_code == "ambiguous_email"


def test_duplicate_incoming_identity_blocks_every_duplicate_row():
    incoming = [
        IncomingStaff(
            tenant_id=TENANT_ID,
            external_key="staff:1",
            personnel_number="001",
            first_name="А",
            last_name="А",
        ),
        IncomingStaff(
            tenant_id=TENANT_ID,
            external_key="staff:2",
            personnel_number=" 001 ",
            first_name="Б",
            last_name="Б",
        ),
    ]

    result = build_import_diff(tenant_id=TENANT_ID, incoming_staff=incoming)

    assert [entry.action for entry in result.entries] == [
        ImportDiffAction.CONFLICT,
        ImportDiffAction.CONFLICT,
    ]
    assert all(entry.conflict_code == "duplicate_source_identity" for entry in result.entries)


def test_distinct_personnel_numbers_with_same_email_are_also_blocked():
    result = build_import_diff(
        tenant_id=TENANT_ID,
        incoming_staff=[
            IncomingStaff(
                tenant_id=TENANT_ID,
                external_key="staff:1",
                personnel_number="001",
                email="same@example.test",
                first_name="А",
                last_name="А",
            ),
            IncomingStaff(
                tenant_id=TENANT_ID,
                external_key="staff:2",
                personnel_number="002",
                email="SAME@example.test",
                first_name="Б",
                last_name="Б",
            ),
        ],
    )

    assert all(entry.action is ImportDiffAction.CONFLICT for entry in result.entries)
