from app.modules.ai.assessment import _validate_question_evidence


def _question(*, incorrect_option: str) -> dict:
    return {
        "mcq": [
            {
                "question": "Какие направляющие указаны для Феникс-2?",
                "source_quote_id": "E01",
                "options": [
                    {"text": "Шариковые направляющие", "is_correct": True},
                    {"text": incorrect_option, "is_correct": False},
                    {"text": "Роликовые направляющие", "is_correct": False},
                    {"text": "Скрытые направляющие", "is_correct": False},
                ],
                "explanation": "Шариковые направляющие",
            }
        ],
        "true_false": [],
        "matching": [],
    }


def test_rejects_incorrect_option_supported_by_unique_original_parent_cell() -> None:
    bounded_source = """| Коллекция | Направляющие |
| --- | --- |
| Феникс-2 | Шариковые направляющие; Телескопические направляющие |
"""

    issues = _validate_question_evidence(
        _question(incorrect_option="Телескопические направляющие"),
        {"E01": "Шариковые направляющие"},
        bounded_source,
        "ru",
    )

    assert "MCQ #1: incorrect option is also supported by the unique containing original source cell" in issues


def test_does_not_use_a_different_original_cell_to_reject_an_option() -> None:
    bounded_source = """| Коллекция | Направляющие |
| --- | --- |
| Феникс-2 | Шариковые направляющие |
| Феникс-3 | Телескопические направляющие |
"""

    issues = _validate_question_evidence(
        _question(incorrect_option="Телескопические направляющие"),
        {"E01": "Шариковые направляющие"},
        bounded_source,
        "ru",
    )

    assert "MCQ #1: incorrect option is also supported by the unique containing original source cell" not in issues
