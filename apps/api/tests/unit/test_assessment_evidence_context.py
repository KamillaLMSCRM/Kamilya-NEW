from __future__ import annotations

import pytest

from app.modules.ai.assessment import _build_evidence_bank


@pytest.mark.parametrize(
    "source",
    [
        (
            "Если при осмотре обнаружено повреждение упаковки, продавец:\n\n"
            "- **прекращает выдачу**;\n"
            "- **сообщает руководителю смены**."
        ),
        (
            "В журнал проверки вносятся:\n\n"
            "- **номер заказа**;\n"
            "- **дата проверки**."
        ),
    ],
)
def test_evidence_bank_retains_list_introducer_with_its_items(source: str) -> None:
    bank = _build_evidence_bank(source)

    assert bank == {"E01": source}


def test_evidence_bank_retains_numbered_multiline_list_context() -> None:
    source = (
        "Если при осмотре обнаружено повреждение упаковки, продавец:\n\n"
        "1. **прекращает выдачу** повреждённого товара;\n"
        "   товар остаётся в зоне проверки;\n"
        "2. **сообщает руководителю смены** о повреждении."
    )

    assert _build_evidence_bank(source) == {"E01": source}


def test_long_numbered_list_uses_exact_bounded_contextual_spans() -> None:
    source = (
        "В журнал проверки вносятся:\n\n"
        "1. **номер заказа** и идентификатор операции для последующей сверки;\n"
        "2. **дата проверки** и время выполнения контрольного действия;\n"
        "3. **результат осмотра** с кратким описанием обнаруженного состояния;\n"
        "4. **решение продавца** о продолжении или остановке выдачи товара;\n"
        "5. **уведомление руководителя** с отметкой о времени передачи сведений."
    )

    bank = _build_evidence_bank(source)

    assert len(source) > 280
    assert all(quote in source and len(quote) <= 280 for quote in bank.values())
    assert any(
        "В журнал проверки вносятся:" in quote
        and "номер заказа" in quote
        and "дата проверки" in quote
        for quote in bank.values()
    )
    assert all(
        quote.count("\n") >= 1
        for quote in bank.values()
        if quote.lstrip().startswith(("2.", "3.", "4.", "5."))
    )
