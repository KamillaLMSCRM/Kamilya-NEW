import pytest

from app.modules.ai.lesson_quality import (
    evaluate_lesson_quality,
    remove_unsupported_relationship_fragments,
)


def _evaluate(*, content: str, source: str):
    return evaluate_lesson_quality(
        title="Условия договора",
        content=content,
        source_chunks=[source],
    )


def test_rejects_percentage_introduced_into_a_blank_source_field() -> None:
    result = _evaluate(
        source="Процентная ставка: ____% годовых. Срок договора указан отдельно.",
        content="Процентная ставка составляет 7% годовых. Срок договора указан отдельно.",
    )

    assert result.accepted is False
    assert "unsupported_numeric_fact" in result.reason_codes


def test_numeric_cleanup_deletes_only_the_unsupported_sentence() -> None:
    content = (
        "Процентная ставка составляет 7% годовых. "
        "Срок договора указан отдельно."
    )

    filtered = remove_unsupported_relationship_fragments(
        content=content,
        source_chunks=["Процентная ставка: ____% годовых. Срок договора указан отдельно."],
    )

    assert filtered == "Срок договора указан отдельно."


@pytest.mark.parametrize(
    "content",
    [
        "Процентная ставка составляет 7% годовых. Срок договора указан отдельно.",
        "Процентная ставка составляет 7,0 % годовых. Срок договора указан отдельно.",
        "Процентная ставка составляет 7.00% годовых. Срок договора указан отдельно.",
    ],
)
def test_accepts_source_backed_equivalent_percentage_notation(content: str) -> None:
    result = _evaluate(
        source="Процентная ставка составляет 7 % годовых. Срок договора указан отдельно.",
        content=content,
    )

    assert "unsupported_numeric_fact" not in result.reason_codes


def test_rejects_percentage_attached_to_a_different_subject() -> None:
    result = _evaluate(
        source=(
            "Продукт Альфа: ставка 7% годовых. "
            "Продукт Бета: ставка 9% годовых. Условия указаны в договоре."
        ),
        content="Продукт Бета: ставка 7% годовых. Условия указаны в договоре.",
    )

    assert result.accepted is False
    assert "unsupported_numeric_fact" in result.reason_codes


def test_accepts_merged_source_facts_from_adjacent_sentences() -> None:
    result = _evaluate(
        source="Ставка 5% годовых. Срок договора 30 дней.",
        content="Ставка 5% годовых, срок договора 30 дней.",
    )

    assert "unsupported_numeric_fact" not in result.reason_codes


def test_accepts_grouped_thousands_equivalent_to_unspaced_number() -> None:
    result = _evaluate(
        source="Сумма договора составляет 1 000 тенге. Срок указан отдельно.",
        content="Сумма договора составляет 1000 тенге. Срок указан отдельно.",
    )

    assert "unsupported_numeric_fact" not in result.reason_codes


def test_rejects_numeric_sign_change() -> None:
    result = _evaluate(
        source="Температура составляет -5 градусов. Условие зафиксировано.",
        content="Температура составляет 5 градусов. Условие зафиксировано.",
    )

    assert result.accepted is False
    assert "unsupported_numeric_fact" in result.reason_codes


def test_rejects_different_unit_bearing_number() -> None:
    result = _evaluate(
        source="Срок составляет 5days. Условие зафиксировано.",
        content="Срок составляет 5percent. Условие зафиксировано.",
    )

    assert result.accepted is False
    assert "unsupported_numeric_fact" in result.reason_codes


def test_source_backed_date_and_numbered_list_markers_do_not_false_reject() -> None:
    result = _evaluate(
        source=(
            "Договор подписан 14.09.2026. "
            "Первый этап: проверка. Второй этап: подтверждение."
        ),
        content=(
            "1. Договор подписан 2026-09-14.\n"
            "2. Первый этап — проверка.\n"
            "3. Второй этап — подтверждение."
        ),
    )

    assert "unsupported_numeric_fact" not in result.reason_codes


def test_numeric_cleanup_preserves_markdown_list_structure_and_valid_decimal() -> None:
    content = "- **Ставка:** 7,0 % годовых.\n- **Срок:** 30 дней."

    filtered = remove_unsupported_relationship_fragments(
        content=content,
        source_chunks=["- **Ставка:** 7% годовых.\n- **Срок:** 30 дней."],
    )

    assert filtered == content


def test_numeric_cleanup_removes_only_unsupported_markdown_list_item() -> None:
    content = "1. **Ставка:** 7% годовых.\n2. **Срок:** 30 дней."

    filtered = remove_unsupported_relationship_fragments(
        content=content,
        source_chunks=["1. **Ставка:** ____% годовых.\n2. **Срок:** 30 дней."],
    )

    assert filtered == "2. **Срок:** 30 дней."


def test_rejects_formula_introducer_without_formula_before_variable_list() -> None:
    result = _evaluate(
        source="Расчёт описывает сумму, ставку и срок договора.",
        content=(
            "Расчёт выполняется по следующей формуле, где:\n"
            "- S — сумма;\n"
            "- r — ставка;\n"
            "- n — срок."
        ),
    )

    assert result.accepted is False
    assert "incomplete_formula_presentation" in result.reason_codes


@pytest.mark.parametrize(
    "formula",
    [
        "S = P × r × n",
        "**S = P × r × n**",
        r"\\(S = P \\times r \\times n\\)",
    ],
)
def test_formula_introducer_accepts_inline_markdown_and_latex_formulae(formula: str) -> None:
    result = _evaluate(
        source="Расчёт описывает сумму, ставку и срок договора.",
        content=(
            f"Расчёт выполняется по следующей формуле: {formula}, где:\n"
            "- S — сумма;\n"
            "- r — ставка;\n"
            "- n — срок."
        ),
    )

    assert "incomplete_formula_presentation" not in result.reason_codes
