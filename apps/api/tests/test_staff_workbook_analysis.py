from __future__ import annotations

from app.modules.staff_workbook_analysis import (
    LoadedStaffSheet,
    analyze_staff_workbook,
)


def test_analysis_reports_dimensions_merges_and_header_evidence_without_raw_rows() -> None:
    workbook = [
        LoadedStaffSheet(
            name="Штатная структура",
            rows=(
                ("Филиал Павлодар", None, None, None),
                ("Табельный номер", "ФИО сотрудника", "Должность", "Отдел"),
                ("001", "Анонимный сотрудник", "Кассир", "Касса"),
                (None, None, None, None),
            ),
            merged_ranges=("A1:D1",),
        )
    ]

    report = analyze_staff_workbook(workbook)
    inspection = report.sheets[0]

    assert inspection.row_count == 4
    assert inspection.column_count == 4
    assert inspection.merged_ranges == ("A1:D1",)
    assert inspection.header_candidates[0].row_number == 2
    assert inspection.header_candidates[0].raw_labels == (
        "Табельный номер",
        "ФИО сотрудника",
        "Должность",
        "Отдел",
    )
    assert inspection.header_candidates[0].confidence == "high"
    assert inspection.empty_or_decorative_rows == (1, 4)
    assert inspection.employee_sheet_evidence.confidence == "high"
    assert inspection.employee_sheet_evidence.score >= 0.8
    assert report.likely_employee_sheets == ("Штатная структура",)


def test_analysis_detects_repeated_headers_and_preserves_ru_kk_en_labels() -> None:
    sheet = LoadedStaffSheet(
        name="Қызметкерлер / Employees",
        rows=(
            ("№", "Аты-жөні", "Лауазымы", "E-mail"),
            ("1", "Аноним", "Маман", "a@example.test"),
            (None, None, None, None),
            ("№", "Аты-жөні", "Лауазымы", "E-mail"),
            ("2", "Аноним 2", "Маман", "b@example.test"),
        ),
    )

    inspection = analyze_staff_workbook([sheet]).sheets[0]

    assert inspection.header_candidates[0].raw_labels == ("№", "Аты-жөні", "Лауазымы", "E-mail")
    assert inspection.repeated_header_candidates[0].row_number == 4
    assert inspection.repeated_header_candidates[0].matches_row_number == 1
    assert inspection.repeated_header_candidates[0].confidence == "high"
    assert inspection.employee_sheet_evidence.matched_fields == (
        "employee_identity",
        "position",
    )
    assert inspection.empty_or_decorative_rows == (3,)


def test_non_employee_sheet_is_low_confidence_and_decorative_rows_are_deterministic() -> None:
    sheets = [
        LoadedStaffSheet(
            name="Положение",
            rows=(
                ("Положение об обучении", None, None),
                ("Версия", "1.0", None),
                (None, None, None),
                ("Примечание: только для внутреннего использования", None, None),
            ),
        ),
        LoadedStaffSheet(
            name="Empty",
            rows=(),
        ),
    ]

    report = analyze_staff_workbook(sheets)
    policy = report.sheets[0]

    assert policy.employee_sheet_evidence.confidence == "low"
    assert policy.employee_sheet_evidence.score < 0.5
    assert policy.empty_or_decorative_rows == (1, 2, 3, 4)
    assert report.sheets[1].row_count == 0
    assert report.sheets[1].column_count == 0
    assert report.likely_employee_sheets == ()


def test_header_candidates_are_sorted_by_score_then_row_and_analysis_is_deterministic() -> None:
    sheet = LoadedStaffSheet(
        name="Data",
        rows=(
            ("Описание", None, None),
            ("Сотрудник", "Отдел", "Должность"),
            ("001", "Касса", "Кассир"),
        ),
    )

    first = analyze_staff_workbook([sheet])
    second = analyze_staff_workbook([sheet])

    assert first == second
    assert [candidate.row_number for candidate in first.sheets[0].header_candidates] == [2]
