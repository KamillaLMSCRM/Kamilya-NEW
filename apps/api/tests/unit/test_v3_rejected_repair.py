import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_v3_partitioned_extraction import Journal, corpus


@pytest.mark.asyncio
async def test_unsafe_correct_answer_change_is_held_without_losing_original_or_review():
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'Исправь только варианты' in system:
            calls.append('repair')
            return {'repairs': [{'variant_id': 'v1', 'correct': 'newer', 'explanation': 'объяснение',
                    'distractors': [{'text': value, 'category': 'procedural_confusion'}
                                    for value in ('wrong', 'false', 'other')]}]}
        if 'независимый контролер' in system:
            return {'verdict': 'NEEDS_REVISION', 'factual_score': 4, 'alignment_score': 4,
                    'didactic_score': 3, 'summary': 'Обнаружена неоднозначность.',
                    'defects': [{'scope': 'question', 'question_id': 'case-a', 'issue': 'неоднозначный вариант'}]}
        if 'ВАРИАНТЫ:\n' in user:
            options = json.loads(user.split('ВАРИАНТЫ:\n', 1)[1])
            return {'options': [{'index': item['index'], 'verdict': (status := 'SUPPORTED' if item['text'] == 'right' else 'CONTRADICTED'),
                                 'claims': [{'claim': 'x', 'status': status, 'reason': 'source'}],
                                 'summary': 'Проверено по источнику.'} for item in options]}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': 'Текст',
                'cases': [{'case_id': 'case-a', 'rule_id': 'Правило первое.', 'variants': [
                    {'variant_id': 'v1', 'prompt': 'question', 'correct_option': {'text': 'right'},
                     'source_quote': 'Правило первое.',
                     'distractor_pool': [{'text': 'wrong'}, {'text': 'false'}, {'text': 'other'}]}]}]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint='a' * 64)

    result = await generate()
    report = result.diagnostics['validation_report']
    assert result.diagnostics['requires_source_review']
    assert any('неоднозначный вариант' in item for item in result.diagnostics['violations'])
    assert report['semantic_repairs'][0]['rejected'] == 'v3_semantic_repair_changed_correct_answer'
    assert report['semantic_repairs'][0]['original_review']['defects']
    answers = result.assessment.assessments[0].mcq[0].options
    assert [item.text for item in answers if item.is_correct] == ['right']
    assert calls == ['repair']
    await generate()
    assert calls == ['repair']

@pytest.mark.asyncio
async def test_unknown_repair_provider_error_is_not_mistaken_for_local_rejection():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]['content']
        if 'Карту регламента' in system:
            target = messages[1]['content'].split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'Исправь только варианты' in system:
            calls.append('repair')
            raise ValueError('v3_semantic_repair_changed_correct_answer')
        if 'независимый контролер' in system:
            return {'verdict': 'NEEDS_REVISION', 'factual_score': 4, 'alignment_score': 4,
                    'didactic_score': 3, 'summary': 'Обнаружена неоднозначность.',
                    'defects': [{'scope': 'question', 'question_id': 'case-a', 'issue': 'неоднозначный вариант'}]}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': 'Текст',
                'cases': [{'case_id': 'case-a', 'rule_id': 'Правило первое.', 'variants': [
                    {'variant_id': 'v1', 'prompt': 'question', 'correct_option': {'text': 'right'},
                     'source_quote': 'Правило первое.',
                     'distractor_pool': [{'text': 'wrong'}, {'text': 'false'}, {'text': 'other'}]}]}]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint='a' * 64)

    with pytest.raises(ValueError, match='v3_semantic_repair_changed_correct_answer'):
        await generate()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    assert calls == ['repair']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_stage', ['critic', 'option', 'compatibility', 'completeness', 'success', 'timeout'])
async def test_failed_recheck_keeps_original_question_and_both_reviews(failure_stage):
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    source = 'Правило первое.'
    chunk = DirectSourceChunk(chunk_id='c', doc_id='d', doc_name='d', title='d', headings=(), text=source,
                              source_revision='rev', chunk_index=0)
    doc = DirectSourceDocument(doc_id='d', title='d', filename='d', category='general', source_revision='rev',
                               chunks=(chunk,), source_text=source)
    owned = DirectSourceCorpus(tenant_id='tenant-1', documents=(doc,), total_chars=len(source), total_chunks=1)
    critic_calls = []
    answer_calls = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            return {'rules': [{'rule_id': 'r1', 'section': 'Раздел', 'title': 'Правило',
                               'statement': source, 'source_quote': source}]}
        if 'Исправь только варианты' in system:
            return {'repairs': [{'variant_id': 'v1', 'correct': 'верный 1', 'explanation': 'Проверено по правилу.',
                'distractors': [{'text': value, 'category': 'procedural_confusion'}
                                for value in ('ложный 1', 'ложный 2', 'ложный 3')]}]}
        if 'независимый контролер' in system:
            critic_calls.append(1)
            if len(critic_calls) > 1 and failure_stage != 'critic':
                return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5, 'didactic_score': 5,
                        'summary': 'Кейс проверен.', 'defects': []}
            issue = 'первая ошибка' if len(critic_calls) == 1 else 'ошибка после правки'
            return {'verdict': 'NEEDS_REVISION', 'factual_score': 4, 'alignment_score': 4, 'didactic_score': 3,
                    'summary': 'Замечание к вопросу.',
                    'defects': [{'scope': 'question', 'question_id': 'c1', 'issue': issue}]}
        if 'Фактические утверждения текста урока' in user:
            return {'verdict': 'SUPPORTED', 'claims': [{'claim': 'Факт', 'status': 'SUPPORTED',
                    'reason': 'Источник'}], 'summary': 'Проверено.'}
        if 'ВАРИАНТЫ:\n' in user:
            entries = json.loads(user.split('ВАРИАНТЫ:\n', 1)[1])
            stage = 'compatibility' if 'Проверь совместимость' in system else 'option'
            candidate = any(item['text'].startswith('ложный') for item in entries)
            answer_calls.append((stage, candidate))
            if failure_stage == 'timeout' and candidate and stage == 'compatibility':
                raise TimeoutError('unknown candidate review')
            return {'options': [{'index': item['index'], 'verdict': status,
                'claims': [{'claim': 'Факт', 'status': status, 'reason': 'Источник'}],
                'summary': 'Проверено.', 'omitted_required_elements': []}
                for item in entries
                for status in [('UNCERTAIN' if candidate and stage == failure_stage and item['text'] == 'верный 1'
                                else 'SUPPORTED' if item['text'] == 'верный 1' else 'CONTRADICTED')]]}
        if 'Сравни каждый ответ с источником' in system:
            answer_calls.append(('completeness', True))
            return {'answers': [{'index': 0, 'omissions': ['условие'] if failure_stage == 'completeness' else []}], 'explanation_review': {"verdict": "SUPPORTED", "claims": [{"claim": "Fact", "status": "SUPPORTED", "reason": "Source"}], "summary": "Checked"}}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль', 'content': 'Правило',
                'cases': [{'case_id': 'c1', 'rule_id': 'r1', 'variants': [{'variant_id': 'v1',
                    'scenario_premise': 'Ситуация', 'prompt': 'Вопрос', 'correct_option': {'text': 'верный 1'},
                    'source_quote': source, 'explanation': 'Проверено по правилу.',
                    'distractor_pool': [{'text': 'ошибка 1'}, {'text': 'ошибка 2'}, {'text': 'ошибка 3'}]}]}]}

    journal = Journal()
    async def generate(allow_unreviewed=False):
        return await generate_v3_course_from_corpus(owned, intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint='a' * 64, allow_unreviewed_on_unknown=allow_unreviewed)

    if failure_stage == 'timeout':
        with pytest.raises(TimeoutError):
            await generate()
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate()
        result = await generate(True)
        options = {option.text for option in result.assessment.assessments[0].mcq[0].options}
        assert {'ошибка 1', 'ошибка 2', 'ошибка 3'} <= options
        repairs = result.diagnostics['validation_report']['semantic_repairs']
        assert repairs[0]['original_review']['defects'] and repairs[0]['recheck']
        assert repairs[0]['answer_rechecks'][0]['review'] and len(answer_calls) == 2
        assert result.diagnostics['requires_source_review']
        return
    result = await generate()
    options = {option.text for option in result.assessment.assessments[0].mcq[0].options}
    repairs = result.diagnostics['validation_report']['semantic_repairs']
    if failure_stage == 'success':
        assert {'ложный 1', 'ложный 2', 'ложный 3'} <= options
        assert repairs[0]['accepted'] and repairs[0]['original_review']['defects']
        assert answer_calls == [('option', True), ('compatibility', True), ('completeness', True)]
        return
    assert {'ошибка 1', 'ошибка 2', 'ошибка 3'} <= options
    assert not any(text.startswith('ложный') for text in options)
    assert repairs[0]['original_review']['defects'] and repairs[0]['recheck']
    assert repairs[0]['rejected'].startswith('candidate_')
    assert result.diagnostics['requires_source_review']
