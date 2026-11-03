"""Source partitioning must preserve original bytes and table interpretation."""

from app.modules.ai.v3.source_units import (
    coalesce_leading_context,
    coalesce_structural_prose,
    coalesce_table_headers,
    find_rendered_quote_spans,
    plan_source_units,
    source_section_label,
)


def test_leading_context_joins_first_section_without_losing_source():
    source = "УТВЕРЖДАЮ\r\nПодпись\r\n\r\n1. Общие правила\r\nНорма.\r\n\r\n2. Далее\r\nДругая норма."
    units = coalesce_leading_context(plan_source_units(source), source)
    assert len(units) == 2
    assert units[0].text.startswith("УТВЕРЖДАЮ")
    assert "1. Общие правила" in units[0].text
    assert "".join(unit.text for unit in units) == source


def test_section_and_two_layer_table_heading_stay_with_first_data_row():
    source = (
        "2. Порядок согласования\n\n"
        "|  |  |\n| --- | --- |\n| **Категория** | **Условия** |\n"
        "| I | Проверить документы |\n| II | Согласовать выдачу |\n"
    )
    units = coalesce_leading_context(coalesce_table_headers(plan_source_units(source), source), source)
    assert "".join(unit.text for unit in units) == source
    assert len(units) == 2
    assert "Порядок согласования" in units[0].text
    assert "**Категория**" in units[0].text
    assert "Проверить документы" in units[0].text
    assert "Согласовать выдачу" in units[1].text


def test_source_section_uses_source_heading_not_generated_labels():
    source = "Утверждаю\n\n1. Общие правила\nПервое.\n\n**2. Порядок работы**\nВторое.\n"
    units = coalesce_leading_context(plan_source_units(source), source)
    assert [source_section_label(source, unit) for unit in units] == ["Раздел 1", "Раздел 2"]


def test_source_without_heading_does_not_invent_one():
    source = "Текст без заголовка.\n\nСледующий абзац."
    assert all(not source_section_label(source, unit) for unit in plan_source_units(source))


def test_markdown_sections_group_toc_parents_and_nested_numbered_lists_without_loss():
    source = (
        "# Заголовок\n\n## Содержание:\n\n1. Определения\n\n2. Процедура\n\n"
        "## 1. ОПРЕДЕЛЕНИЯ\n\n1. Общая норма.\n\n2. Термины:\n\n1) Первый термин;\n\n"
        "2) Второй термин.\n\n3. Дополнительная норма.\n\n"
        "## 2. ПРОЦЕДУРА\n\n1. Выполнить проверку.\n\n2. Сообщить результат.\n"
    )
    units = coalesce_structural_prose(coalesce_table_headers(plan_source_units(source), source), source)
    assert "".join(unit.text for unit in units) == source
    assert len(units) < len(plan_source_units(source))
    nested = next(unit for unit in units if "Первый термин" in unit.text)
    assert "Термины:" in nested.text and "Второй термин" in nested.text
    assert source_section_label(source, nested) == "Раздел 1"
    procedure = next(unit for unit in units if "Выполнить проверку" in unit.text)
    assert "Сообщить результат" in procedure.text
    assert source_section_label(source, procedure) == "Раздел 2"


def test_frontmatter_table_does_not_disable_later_section_grouping():
    source = ("| Документ | Значение |\n| --- | --- |\n| Версия | 1 |\n\n"
              "## 1. Раздел\n\n1. Пункт:\n\n1) Первое;\n\n2) Второе.\n\n"
              "## 2. Другой раздел\n\n1. Норма.\n")
    units = coalesce_structural_prose(coalesce_table_headers(plan_source_units(source), source), source)
    assert "".join(unit.text for unit in units) == source
    assert any("Пункт:" in unit.text and "Первое;" in unit.text and "Второе." in unit.text for unit in units)


def test_planner_retains_repetitions_and_complete_table_rows():
    source = (
        "# Условия\n\nДо таблицы. Повтор. Повтор.\n\n"
        "| Категория | Условие |\n| --- | --- |\n"
        "| I | Вначале звонок.<br>Затем проверка. |\n"
        "| II | Только при условии; иначе отказ. |\n\n"
        "После таблицы.\n"
    )
    units = plan_source_units(source)
    assert "".join(unit.text for unit in units) == source
    rows = [unit for unit in units if unit.kind == "table_row"]
    assert len(rows) == 2
    assert "Вначале звонок.<br>Затем проверка." in rows[0].text
    assert all("Категория" in unit.context for unit in rows)
    assert [unit.start for unit in units] == [0, *[unit.end for unit in units[:-1]]]
    assert units[-1].end == len(source)


def test_planner_never_splits_large_single_table_cell_or_discards_blank_text():
    cell = "Очень длинное условие. " * 600
    source = "\n\n| Поле | Значение |\n| --- | --- |\n| X | " + cell + " |\n\n"
    units = plan_source_units(source)
    assert "".join(unit.text for unit in units) == source
    rows = [unit for unit in units if unit.kind == "table_row"]
    assert len(rows) == 1
    assert cell in rows[0].text


def test_planner_keeps_ordinary_pipe_text_and_blank_documents():
    for source in ("", "\n\n", "Правило A | правило B\n\nИсключение."):
        assert "".join(unit.text for unit in plan_source_units(source)) == source


def test_empty_formal_header_keeps_bold_first_row_as_context():
    source = "|  |  |\n| --- | --- |\n| **Категория** | **Правило** |\n| I | Условие. |\n"
    units = plan_source_units(source)
    assert "".join(unit.text for unit in units) == source
    data_row = next(unit for unit in units if "| I |" in unit.text)
    assert "**Категория**" in data_row.context
    assert "**Правило**" in data_row.context


def test_crlf_and_missing_final_newline_keep_exact_offsets():
    source = "Ввод\r\n\r\n| Имя | Правило |\r\n| --- | --- |\r\n| X | Проверка |"
    units = plan_source_units(source)
    assert "".join(unit.text for unit in units) == source
    assert all(source[unit.start:unit.end] == unit.text for unit in units)


def test_rendered_quote_candidates_preserve_source_offsets_and_polarity():
    source = "Условие:<br>проверить **вес** и пробу; не выдавать."
    spans = find_rendered_quote_spans(source, "проверить вес и пробу; не выдавать.")
    assert len(spans) == 1
    assert source[spans[0][0]:spans[0][1]] == "проверить **вес** и пробу; не выдавать."
    assert not find_rendered_quote_spans(source, "проверить вес и пробу; выдавать.")


def test_rendered_quote_candidates_report_each_occurrence():
    source = "**Осторожно**<br>Осторожно"
    spans = find_rendered_quote_spans(source, "Осторожно")
    assert len(spans) == 2
    assert all(source[start:end] == "Осторожно" for start, end in spans)


def test_rows_remain_addressably_linked_to_only_their_own_table():
    source = (
        "| Раздел | Правило |\n| --- | --- |\n| I | Первое. |\n| II | Как в I. |\n\n"
        "| Параметр | Значение |\n| --- | --- |\n| X | Второе. |\n"
    )
    rows = [unit for unit in plan_source_units(source) if unit.kind == "table_row"]
    assert len(rows) == 3
    assert rows[0].container_id
    assert rows[0].container_id == rows[1].container_id
    assert rows[2].container_id != rows[0].container_id


def test_long_unstructured_document_keeps_paragraph_boundaries_without_truncation():
    source = "Первое правило.\n\n" + "Второе правило. " * 500 + "\n\nТретье правило."
    units = plan_source_units(source)
    assert "".join(unit.text for unit in units) == source
    assert len(units) == 3
    assert "Второе правило. " * 500 in units[1].text


def test_numbered_sections_keep_their_paragraphs_together():
    source = "Утверждаю.\n\n1. Общие правила.\n\nУсловие первое.\n\nИсключение.\n\n2. Другой раздел.\n\nДействие."
    units = plan_source_units(source)
    assert "".join(unit.text for unit in units) == source
    assert len(units) == 3
    assert "Условие первое." in units[1].text and "Исключение." in units[1].text


def test_table_header_and_first_row_share_one_lossless_target():
    source = "| Название | Действие |\n| --- | --- |\n| A | Проверить. |\n| B | Сообщить. |\n"
    units = coalesce_table_headers(plan_source_units(source), source)
    assert "".join(unit.text for unit in units) == source
    assert len(units) == 2
    assert "Название" in units[0].text and "Проверить" in units[0].text
    assert "Название" in units[1].context
