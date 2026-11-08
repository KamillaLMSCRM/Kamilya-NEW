"""One owner decision must retain every underlying model observation."""
import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_autonomous_editorial_cycle import (
    _owner_source_questions,
    run_autonomous_editorial_cycle,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value, rule_wire, source_wire
from tests.unit.test_v3_editorial_contract import review_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def test_different_source_choices_or_owned_ref_sets_remain_distinct():
    first = {'issue_id': 'a', 'source_question': 'Which value?', 'source_refs': ['s1', 's2']}
    same = {**first, 'issue_id': 'b', 'source_refs': ['s2', 's1']}
    other_text = {**first, 'issue_id': 'c', 'source_question': 'Which actor?'}
    other_refs = {**first, 'issue_id': 'd', 'source_refs': ['s3']}
    questions = _owner_source_questions({x['issue_id']: x for x in (first, same, other_text, other_refs)}, 'current-source')
    assert len(questions) == 3
    assert questions[0]['issue_ids'] == ['a', 'b']
    assert questions[1]['issue_ids'] == ['c'] and questions[2]['issue_ids'] == ['d']
    assert questions[0]['evidence_decisions'] == [first, same]


@pytest.mark.asyncio
async def test_same_confirmed_source_question_is_one_owner_request_with_all_decisions(case):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        calls.append(group)
        if name == 'lesson':
            value = course
        elif 'option-predicates' in group:
            value = predicate_value(packet, course, fmt=fmt)
        elif ':verify:' in group:
            prior = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            value = review_value(packet, course)
            value['findings'] = []
            value['resolutions'] = [{
                'issue_id': row['issue_id'], 'disposition': 'SOURCE_AMBIGUITY',
                'reason': 'Two source readings require different work decisions.',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                'course_quote': '', 'source_question': 'Which source condition applies?',
            } for row in prior]
        else:
            value = review_value(packet, course, domain='source')
            duplicate = copy.deepcopy(value['findings'][0])
            duplicate['problem'] = 'Another observation of the same source ambiguity.'
            value['findings'].append(duplicate)
        wire = view.encode(rule_wire(value, fmt, course))
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    history = result.history[0]
    assert result.decision.source_uncertain and not result.decision.accepted
    assert len(result.decision.feedback) == 1
    assert len(history['confirmed_source_questions']) == 1
    owner_question = history['confirmed_source_questions'][0]
    assert len(owner_question['issue_ids']) == 2
    assert set(owner_question['issue_ids']) == {row['issue_id'] for row in history['verified_resolutions']}
    assert len(owner_question['evidence_decisions']) == 2
    assert result.decision.feedback[0]['evidence']['source_issue_ids'] == owner_question['issue_ids']
    assert not any(':revision:' in group for group in calls)
