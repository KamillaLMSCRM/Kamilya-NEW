from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.staff_workbook_analysis import (
    LoadedStaffSheet,
    analyze_staff_workbook,
    compute_workbook_signature,
)
from app.modules.users.staff_import_mapping_schemas import (
    StaffImportMappingCreate,
    StaffImportMappingUpdate,
)

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0115_staff_import_mapping_profiles.py"


def test_workbook_signature_ignores_employee_values() -> None:
    first = analyze_staff_workbook([LoadedStaffSheet(name="Штат", rows=(("ФИО", "Должность"), ("Иванов", "Кассир")))])
    second = analyze_staff_workbook(
        [LoadedStaffSheet(name="Штат", rows=(("ФИО", "Должность"), ("Петров", "Директор")))]
    )
    assert compute_workbook_signature(first) == compute_workbook_signature(second)


def test_workbook_signature_distinguishes_unknown_tenant_headers() -> None:
    analysis = analyze_staff_workbook([LoadedStaffSheet(name="Лист1", rows=(("Код", "Роль"), ("01", "Кассир")))])
    first = compute_workbook_signature(
        analysis,
        selected_sheet="Лист1",
        raw_columns=("Код", "Роль"),
    )
    second = compute_workbook_signature(
        analysis,
        selected_sheet="Лист1",
        raw_columns=("Табель", "Позиция"),
    )
    assert first != second


def test_0115_adds_tenant_scoped_versioned_profile() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0115"' in source
    assert 'down_revision = "0114"' in source
    assert "uq_staff_import_mappings_tenant_signature" in source
    assert "profile_json" in source
    assert "schema_version" in source
    assert "approved_by" in source
    assert "fk_staff_import_mappings_approved_by_users" in source
    assert "trg_validate_staff_import_mapping_profile_approval" in source
    assert "staff import mapping approver tenant mismatch" in source
    assert "0115 downgrade refused" in source


def test_public_mapping_crud_cannot_forge_approved_workbook_profile() -> None:
    with pytest.raises(ValidationError):
        StaffImportMappingCreate.model_validate(
            {
                "name": "unsafe",
                "mapping_json": {"full_name": "ФИО"},
                "workbook_signature": "a" * 64,
            }
        )
    with pytest.raises(ValidationError):
        StaffImportMappingUpdate.model_validate({"profile_json": {"selected_sheet": "Штат"}})
