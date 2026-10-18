"""Closed catalog of printable completion fields; never arbitrary ORM attributes."""

from typing import Literal

CompletionFormField = Literal[
    "organization",
    "employee_name",
    "personnel_number",
    "department",
    "position",
    "course_title",
    "course_version",
    "assigned_at",
    "due_at",
    "test_results",
    "test_title",
    "test_score",
    "test_threshold",
    "test_completed_at",
    "test_duration",
    "generated_at",
    "employee_confirmation",
    "employee_signature",
    "representative_signature",
    "footer_note",
]

REQUIRED_FORM_FIELDS = frozenset({"employee_name", "course_title", "test_results"})
DEFAULT_FORM_FIELDS: list[CompletionFormField] = [
    "organization",
    "employee_name",
    "course_title",
    "course_version",
    "test_results",
    "test_title",
    "test_score",
    "test_threshold",
    "test_completed_at",
    "generated_at",
    "employee_confirmation",
    "employee_signature",
    "representative_signature",
    "footer_note",
]

# IDs are the wire contract; labels are presentation, not a data lookup path.
FORM_FIELD_CATALOG = [
    ("organization", "Организация", "Общие сведения"),
    ("employee_name", "ФИО сотрудника", "Сотрудник"),
    ("personnel_number", "Табельный номер", "Сотрудник"),
    ("department", "Подразделение", "Сотрудник"),
    ("position", "Должность", "Сотрудник"),
    ("course_title", "Название курса", "Курс и назначение"),
    ("course_version", "Версия публикации", "Курс и назначение"),
    ("assigned_at", "Дата назначения", "Курс и назначение"),
    ("due_at", "Срок прохождения", "Курс и назначение"),
    ("test_results", "Итог каждой попытки", "Тестирование"),
    ("test_title", "Название теста", "Тестирование"),
    ("test_score", "Результат в процентах", "Тестирование"),
    ("test_threshold", "Проходной порог", "Тестирование"),
    ("test_completed_at", "Дата сдачи теста", "Тестирование"),
    ("test_duration", "Время прохождения теста", "Тестирование"),
    ("generated_at", "Дата формирования документа", "Оформление"),
    ("employee_confirmation", "Текст подтверждения сотрудника", "Оформление"),
    ("employee_signature", "Подпись и дата сотрудника", "Оформление"),
    ("representative_signature", "Представитель организации, подпись и дата", "Оформление"),
    ("footer_note", "Примечание", "Оформление"),
]
