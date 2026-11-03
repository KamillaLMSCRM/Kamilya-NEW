import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.service import _lesson_claim_table_parts, generate_v3_course_from_corpus
from tests.unit.test_v3_partitioned_extraction import Journal, corpus


def test_table_claim_parts_preserve_every_row_and_header_context():
    text = '## Таблица\n\n| Условие | Действие |\n|---|---|\n' + ''.join(
        f'| Условие {i} | Действие {i} |\n' for i in range(1, 9)) + '\nЗавершение.\n'
    parts = _lesson_claim_table_parts(text)
    assert ''.join(part for part, _ in parts) == text
    assert len(parts) == 3 and parts[0][1] == ''
    assert all('| Условие | Действие |' in context for _, context in parts[1:])
    for i in range(1, 9):
        assert sum(f'Условие {i}' in part for part, _ in parts) == 1


def test_table_like_fenced_code_is_not_split():
    text = '## Пример\n```text\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n| 7 | 8 |\n```\n'
    assert _lesson_claim_table_parts(text) == [(text, '')]


@pytest.mark.asyncio
async def test_failed_question_review_does_not_skip_lesson_claim_review():
    journal = Journal()
    seen = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': 'r1', 'section': 'Раздел', 'title': 'Правило',
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'NEEDS_REVISION', 'factual_score': 4, 'alignment_score': 4,
                    'didactic_score': 3, 'summary': 'Обнаружено замечание к кейсу.',
                    'defects': [{'scope': 'question', 'question_id': 'missing-case', 'issue': 'ошибка кейса'}]}
        if 'Фактические утверждения текста урока' in user:
            seen.append(user)
            return {'verdict': 'CONTRADICTED', 'claims': [{'claim': 'Факт', 'status': 'CONTRADICTED',
                    'reason': 'Противоречит источнику.'}], 'summary': 'Есть ошибка текста.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': 'Ошибочное утверждение',
                'cases': [{'case_id': 'c1', 'rule_id': 'r1', 'variants': [{'variant_id': 'v1',
                    'prompt': 'Вопрос', 'correct_option': {'text': 'верный 1'},
                    'source_quote': 'Правило первое.\n\nПравило второе.',
                    'distractor_pool': [{'text': 'ошибка 1'}, {'text': 'ошибка 2'}, {'text': 'ошибка 3'}]}]}]}

    result = await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
        extraction_journal=journal, route_fingerprint='a' * 64)
    assert seen, 'question failure must not hide independent prose defects'
    assert result.diagnostics['requires_source_review']
    assert any('проверка текста' in item for item in result.diagnostics['violations'])


@pytest.mark.asyncio
async def test_table_rows_are_checked_in_context_and_unknown_result_is_preserved():
    journal = Journal()
    seen = []
    table = '## Таблица\n| Условие | Действие |\n|---|---|\n' + ''.join(
        f'| Условие {i} | Действие {i} |\n' for i in range(1, 8))

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5,
                    'didactic_score': 5, 'summary': 'Проверка выполнена.', 'defects': []}
        if 'Фактические утверждения текста урока' in user:
            seen.append(user)
            if len(seen) > 1:
                assert '| Условие | Действие |' in user
            status = 'UNCERTAIN' if '| Условие 4 |' in user else 'SUPPORTED'
            return {'verdict': status, 'claims': [{'claim': 'Факт', 'status': status,
                    'reason': 'Проверено.'}], 'summary': 'Сверено с источником.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': table, 'cases': []}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint='a' * 64)
    result = await generate()
    assert len(seen) == 3 and any('UNCERTAIN' in item for item in result.diagnostics['violations'])
    assert any('строками таблицы' in warning for warning in result.content.source_warnings)
    await generate()
    assert len(seen) == 3

@pytest.mark.asyncio
async def test_table_second_part_timeout_preserves_first_and_is_not_retried():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    seen = []
    table = '## Таблица\n| Условие | Действие |\n|---|---|\n' + ''.join(
        f'| Условие {i} | Действие {i} |\n' for i in range(1, 8))

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5,
                    'didactic_score': 5, 'summary': 'Проверка выполнена.', 'defects': []}
        if 'Фактические утверждения текста урока' in user:
            seen.append(user)
            if '| Условие 4 |' in user:
                raise TimeoutError('unknown outcome')
            return {'verdict': 'SUPPORTED', 'claims': [{'claim': 'Факт', 'status': 'SUPPORTED',
                    'reason': 'Проверено.'}], 'summary': 'Сверено с источником.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': table, 'cases': []}

    async def generate(allow_unreviewed=False):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint='a' * 64, allow_unreviewed_on_unknown=allow_unreviewed)
    with pytest.raises(TimeoutError):
        await generate()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    partial = await generate(True)
    review = partial.diagnostics['validation_report']['semantic_reviews']['l1']
    assert review['verdict'] == 'ERROR' and len(review['lesson_claim_reviews']) == 1
    assert partial.diagnostics['requires_source_review'] and len(seen) == 2
