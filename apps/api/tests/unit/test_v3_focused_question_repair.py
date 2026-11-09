import copy
import json

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3 import practical_focused_cycle as cycle
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['repair', 'no_progress', 'two_unresolved', 'outside_scope'])
async def test_question_repair_scoped_rechecks_only_changed_units(mode):
    text = 'Не касаться поверхности.'
    doc = DirectSourceDocument('doc', 'Source', 'file', 'other', 'r', (), source_text=text)
    corpus = DirectSourceCorpus('tenant', (doc,), len(text), 0)
    packet = build_practical_source_packet(corpus)
    view = PracticalModelView(packet)
    def question(qid, prompt):
        return {'id': qid, 'prompt': prompt, 'choices': ['a', 'b', 'c'], 'correct_index': 0,
                'explanation': 'Reason', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [
        {'id': 'l1', 'title': 'One', 'content': text, 'questions': [question('q1', 'First?')]},
        {'id': 'l2', 'title': 'Two', 'content': text, 'questions': [question('q2', 'Second?')]}]}
    groups = []
    async def stage(name, group, messages, fmt, validator):
        groups.append(group)
        if ':author:' in group:
            value = view.encode(copy.deepcopy(course))
        elif ':graph:' in group:
            data = json.loads(messages[1]['content'])
            value = {'role': data['role'], 'input_fingerprint': data['input_fingerprint'], 'decisions': [
                {'token_id': row['token_id'], 'classification': 'UNKNOWN', 'object_kind': 'UNKNOWN',
                 'object_quote': '', 'negation_quote': '', 'note': ''} for row in data['candidate_tokens']]}
        elif ':questions:' in group or ':question-repair:' in group:
            data = json.loads(messages[1]['content'].split('\nQUESTION_EDITOR_JSON\n', 1)[1].split(
                '\nUNVERIFIED_CURRENT_QUESTION_FINDINGS_JSON\n', 1)[0])
            checks = [{'question_id': qid, 'status': 'VALID', 'reason': 'reviewed'} for qid in ('q1', 'q2')]
            updates = []
            if ':question-repair:' in group and mode not in ('no_progress', 'two_unresolved'):
                index = 1 if mode == 'outside_scope' else 0
                q = copy.deepcopy(data['questions'][index]['questions'][0])
                q['prompt'] = 'Changed?'
                checks[index]['status'] = 'REPAIRED'
                updates = [{'lesson_id': data['questions'][index]['lesson_id'], 'question': q}]
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': data['course_fingerprint'],
                     'checks': checks, 'updates': updates}
        elif ':blind:' in group:
            assert 'correct_index' not in messages[1]['content']
            props = fmt['json_schema']['schema']['properties']
            ids = props['judgments']['items']['properties']['item_id']['enum']
            uncertain = 'First?' in messages[1]['content'] or (mode == 'two_unresolved' and 'Second?' in messages[1]['content'])
            value = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                'bank_fingerprint': props['bank_fingerprint']['enum'][0], 'judgments': [
                    {'item_id': item, 'status': ('UNDECIDABLE' if uncertain else
                        'SUPPORTED' if index == 0 else 'NOT_SUPPORTED'), 'reason': 'read',
                     'source_refs': ['SRC1'] if not uncertain and index == 0 else [],
                     'compatible_case': 'grounded' if not uncertain and index == 0 else ''}
                    for index, item in enumerate(ids)]}
        else:
            raise AssertionError(group)
        validator(copy.deepcopy(value))
        return value
    if mode == 'outside_scope':
        with pytest.raises(ValueError, match='outside_scope'):
            await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=1024, max_revisions=2)
        return
    result = await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=1024, max_revisions=2)
    assert not result.decision.accepted and not result.decision.source_uncertain
    assert result.course['lessons'][1] == course['lessons'][1]
    assert sum(':question-repair:' in group for group in groups) == 1
    if mode == 'repair':
        assert result.course['lessons'][0]['questions'][0]['prompt'] == 'Changed?'
        assert sum(':blind:' in group for group in groups) == 3
    else:
        assert result.course == course and sum(':blind:' in group for group in groups) == 2
        assert result.decision.feedback[0]['evidence']['status'] == 'AUTOMATIC_REVIEW_UNRESOLVED'
        assert result.decision.feedback[0]['evidence']['unverified_observation']
        if mode == 'two_unresolved':
            assert {row['id'] for row in result.decision.feedback} == {'q1', 'q2'}
