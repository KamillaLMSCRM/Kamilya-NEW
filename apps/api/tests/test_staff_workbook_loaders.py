import io

import openpyxl

from app.modules.staff_workbook_analysis import load_staff_workbook


def test_loader_reads_xlsx_metadata_without_mutation() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Штат"
    sheet.append(["ФИО", "Должность", "Филиал"])
    sheet.append(["Иванов Иван", "Кассир", "Павлодар"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    loaded = load_staff_workbook(buffer.getvalue(), "staff.xlsx")

    assert loaded[0].name == "Штат"
    assert loaded[0].rows[0] == ("ФИО", "Должность", "Филиал")


def test_loader_reads_cp1251_csv() -> None:
    content = "ФИО;Должность;Отдел\nИванов Иван;Кассир;Касса\n".encode("cp1251")
    loaded = load_staff_workbook(content, "staff.csv")
    assert loaded[0].rows[1][1] == "Кассир"
