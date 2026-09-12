import pytest

from app.modules.ai.assessment import (
    _is_extractive_answer,
    _validate_generated_question_set,
    _validate_question_evidence,
)


def test_rejects_unsupported_predicate_despite_shared_topic_words():
    source = 'Платформа Орион представляет модульное мебельное решение.'
    data = {'mcq': [{
        'question': 'Что представляет платформа Орион?',
        'source_quote_id': 'E01',
        'options': [
            {'text': 'Платформа Орион представляет цифровое решение', 'is_correct': True},
            {'text': 'Платформа Орион представляет бумажное решение', 'is_correct': False},
            {'text': 'Платформа Орион представляет временное решение', 'is_correct': False},
            {'text': 'Платформа Орион представляет устаревшее решение', 'is_correct': False},
        ],
        'explanation': 'Платформа Орион представляет цифровое решение.',
    }]}
    issues = _validate_question_evidence(data, {'E01': source}, source, 'ru')
    assert any('answer' in issue and 'source evidence' in issue for issue in issues)


@pytest.mark.parametrize(('answer', 'source', 'accepted'), [
    ('товар переносят вдвоём', 'Хрупкий **товар переносят вдвоём**.', True),
    ('Loan payment occurs after signing', 'Loan payment occurs after signing.', True),
    ('тауарды екі адам тасымалдайды', 'Нұсқаулық: тауарды екі адам тасымалдайды.', True),
    ('Высота составляет 2055 миллиметров', 'Высота составляет 2505 миллиметров.', False),
    ('скидка составляет 10', 'Скидка составляет 10.5 процентов.', False),
    ('изменение составляет 10%', 'Изменение составляет -10%.', False),
    ('Товар выдается покупателю', 'Товар не выдается покупателю.', False),
    ('проверка товара', 'Перепроверка товара обязательна.', False),
    ('A B', 'A/B', False),
    ('pre approval', 'pre-approval', False),
    ('разрешено запрещено', 'Разрешено; запрещено.', False),
])
def test_exact_answer_span_preserves_facts(answer, source, accepted):
    assert _is_extractive_answer(answer, source) is accepted


def test_explanation_uses_server_evidence_not_model_invention():
    source = 'Платформа Орион представляет модульное мебельное решение.'
    data = {'mcq': [{
        'question': 'Какое решение представляет платформа Орион?',
        'source_quote_id': 'E01',
        'options': [
            {'text': 'Модульное мебельное решение', 'is_correct': True},
            {'text': 'Модульное цифровое решение', 'is_correct': False},
            {'text': 'Модульное бумажное решение', 'is_correct': False},
            {'text': 'Модульное временное решение', 'is_correct': False},
        ],
        'explanation': 'Орион гарантирует скидку каждому покупателю.',
    }]}
    assert _validate_question_evidence(data, {'E01': source}, source, 'ru') == []
    assert data['mcq'][0]['explanation'] == f'В исходном материале указано: «{source}»'


def test_extractive_answer_starting_quote_does_not_trigger_explanation_leak():
    source = 'Loan approval occurs after application review.'
    data = {'mcq': [{
        'question': 'When does loan approval occur?', 'source_quote_id': 'E01',
        'options': [
            {'text': 'after application review', 'is_correct': True},
            {'text': 'before application review', 'is_correct': False},
            {'text': 'during application intake', 'is_correct': False},
            {'text': 'without manager approval', 'is_correct': False},
        ],
        'explanation': source,
    }]}
    assert _validate_question_evidence(data, {'E01': source}, source, 'en') == []
    assert _validate_generated_question_set(data, 'en') == []


def test_rejects_overlong_exact_answer_even_when_all_options_are_balanced():
    source = 'Сотрудник должен проверить полный комплект документов перед началом обработки каждой новой заявки клиента.'
    data = {'mcq': [{
        'question': 'Что должен проверить сотрудник?', 'source_quote_id': 'E01',
        'options': [{'text': source.replace('документов', noun), 'is_correct': noun == 'документов'}
                    for noun in ('документов', 'инструментов', 'каталогов', 'образцов')],
        'explanation': source,
    }]}
    assert len(source.split()) == 13
    assert any('exceeds 12 words' in issue for issue in
               _validate_question_evidence(data, {'E01': source}, source, 'ru'))


def test_rejects_changed_numeric_fact_despite_identical_word_stems():
    source = 'Высота шкафа Орион составляет 2055 миллиметров.'
    data = {'mcq': [{
        'question': 'Какова высота шкафа Орион?',
        'source_quote_id': 'E01',
        'options': [
            {'text': 'Высота составляет 2505 миллиметров', 'is_correct': True},
            {'text': 'Высота составляет 2100 миллиметров', 'is_correct': False},
            {'text': 'Высота составляет 1950 миллиметров', 'is_correct': False},
            {'text': 'Высота составляет 1800 миллиметров', 'is_correct': False},
        ],
        'explanation': 'Высота шкафа Орион составляет 2505 миллиметров.',
    }]}
    issues = _validate_question_evidence(data, {'E01': source}, source, 'ru')
    assert any('answer' in issue and 'source evidence' in issue for issue in issues)
