import pytest

from app.modules.ai.assessment import _header_answer_is_supported, _validate_question_evidence


@pytest.mark.parametrize("subject,expected", [("Орион", True), ("Вега", False)])
def test_answer_must_belong_to_the_named_column_subject(subject, expected):
    row = "| Материал ручек | Матовый металл. | Прочный пластик. |"
    source = "| Поле | Орион | Вега |\n| --- | --- | --- |\n" + row
    question = {
        "question": f"Какой материал ручек используется у коллекции {subject}?",
        "source_quote_id": "E01",
        "options": [
            {"text": "Прочный пластик", "is_correct": True},
            {"text": "Тёмное стекло", "is_correct": False},
            {"text": "Натуральная кожа", "is_correct": False},
            {"text": "Керамические вставки", "is_correct": False},
        ],
    }
    issues = _validate_question_evidence({"mcq": [question]}, {"E01": row}, source, "ru")
    assert any("different table subject" in issue for issue in issues) is expected


@pytest.mark.parametrize("answer,expected", [("Орион", True), ("Вега", False)])
def test_header_answer_requires_distinctive_context_in_its_own_cell(answer, expected):
    row = "| Стиль | Современный минимализм с нейтральной палитрой. | Классический стиль с резными фасадами. |"
    source = "| Поле | Орион | Вега |\n| --- | --- | --- |\n" + row
    assert _header_answer_is_supported("Какая коллекция имеет нейтральную палитру?", answer, row, source) is expected


def test_header_answer_does_not_resolve_an_ambiguous_shared_attribute():
    row = "| Стиль | Нейтральная палитра с гладкими фасадами. | Нейтральная палитра с резными фасадами. |"
    source = "| Поле | Орион | Вега |\n| --- | --- | --- |\n" + row
    assert not _header_answer_is_supported("Какая коллекция имеет нейтральную палитру?", "Орион", row, source)


def test_grounded_collection_choice_is_not_mistaken_for_unscoped_attribute():
    row = "| Стиль | Современный минимализм с нейтральной палитрой. | Классический стиль с резными фасадами. |"
    source = "| Поле | Орион | Вега |\n| --- | --- | --- |\n" + row
    data = {
        "mcq": [
            {
                "question": "Какую коллекцию выбрать для нейтральной палитры?",
                "source_quote_id": "E01",
                "options": [
                    {"text": "Орион", "is_correct": True},
                    {"text": "Вега", "is_correct": False},
                    {"text": "Классический стиль", "is_correct": False},
                    {"text": "Резные фасады", "is_correct": False},
                ],
            }
        ]
    }
    issues = _validate_question_evidence(data, {"E01": row}, source, "ru")
    assert not any("unscoped attribute" in issue or "omits its specific subject" in issue for issue in issues)
    assert not any("answer does not use its source" in issue for issue in issues)
