from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from app.modules.users.staff_import_service import parse_upload


def _xlsx_with_branch_column(*, merged: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Сотрудники"
    sheet.append(["Табельный номер", "ФИО", "Должность", "Филиал"])
    sheet.append(["001", "Иванов Иван", "Кассир", "Павлодар"])
    sheet.append(["002", "Петров Пётр", "Менеджер", None])
    if merged:
        sheet.merge_cells("D2:D3")
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_branch_alias_and_forward_fill_are_preserved_in_parsed_rows():
    parsed = parse_upload("staff.xlsx", _xlsx_with_branch_column())

    assert parsed.missing_required_columns == []
    assert parsed.detected_columns["Филиал"] == "branch"
    assert [row.branch for row in parsed.rows] == ["Павлодар", "Павлодар"]
    assert [row.department for row in parsed.rows] == ["", ""]
    assert parsed.invalid_rows == []


def test_merged_branch_cells_are_expanded_before_parsing():
    parsed = parse_upload("staff.xlsx", _xlsx_with_branch_column(merged=True))

    assert parsed.invalid_rows == []
    assert [row.branch for row in parsed.rows] == ["Павлодар", "Павлодар"]
