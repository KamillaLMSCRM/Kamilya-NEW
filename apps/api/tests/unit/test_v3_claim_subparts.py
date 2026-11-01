import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.service import _lesson_claim_subparts, generate_v3_course_from_corpus
from tests.unit.test_v3_partitioned_extraction import Journal, corpus


def test_nested_subparts_keep_every_example_and_parent_context():
    text = '## Примеры\nВведение.\n' + ''.join(f'### Пример {i}\nДействие {i}.\n' for i in range(1, 6))
    parts = _lesson_claim_subparts(text)
    assert len(parts) == 2 and ''.join(part for part, _ in parts) == text
    assert parts[0][1] == '' and parts[1][1] == '## Примеры'
    for i in range(1, 6):
        assert sum(f'### Пример {i}' in part for part, _ in parts) == 1


def test_nested_subparts_keep_short_or_fenced_sections_intact():
    short = '## Тема\n### A\n1\n### B\n2\n### C\n3\n'
    fenced = '## Тема\n```text\n### A\n### B\n### C\n### D\n```\n'
    assert _lesson_claim_subparts(short) == [(short, '')]
    assert _lesson_claim_subparts(fenced) == [(fenced, '')]


@pytest.mark.asyncio
async def test_example_groups_are_reviewed_once_and_uncertain_later_group_holds():
    journal = Journal()
    seen = []
    text = '## Примеры\n' + ''.join(f'### Пример {i}\nДействие {i}.\n' for i in range(1, 6))

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
            if len(seen) == 2:
                assert 'родительский заголовок урока' in user and '## Примеры' in user
            status = 'UNCERTAIN' if '### Пример 4' in user else 'SUPPORTED'
            return {'verdict': status, 'claims': [{'claim': 'Факт', 'status': status,
                    'reason': 'Проверено.'}], 'summary': 'Сверено с источником.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': text, 'cases': []}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint='a' * 64)
    result = await generate()
    assert len(seen) == 2 and any('UNCERTAIN' in item for item in result.diagnostics['violations'])
    assert any('подразделами' in warning for warning in result.content.source_warnings)
    await generate()
    assert len(seen) == 2

@pytest.mark.asyncio
async def test_example_group_timeout_keeps_first_group_and_never_reissues_unknown():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    seen = []
    text = '## Примеры\n' + ''.join(f'### Пример {i}\nДействие {i}.\n' for i in range(1, 6))

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
            if '### Пример 4' in user:
                raise TimeoutError('unknown outcome')
            return {'verdict': 'SUPPORTED', 'claims': [{'claim': 'Факт', 'status': 'SUPPORTED',
                    'reason': 'Проверено.'}], 'summary': 'Сверено с источником.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': text, 'cases': []}

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
