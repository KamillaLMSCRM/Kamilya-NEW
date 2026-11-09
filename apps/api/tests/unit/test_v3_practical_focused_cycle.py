import copy
import json

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3 import practical_focused_cycle as cycle
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView


@pytest.fixture
def example():
    text = 'Не касаться поверхности.'
    doc = DirectSourceDocument('doc', 'Source', 'file', 'other', 'r', (), source_text=text)
    corpus = DirectSourceCorpus('tenant', (doc,), len(text), 0)
    packet = build_practical_source_packet(corpus)
    question = {'id': 'q', 'prompt': 'Question?', 'choices': ['a', 'b', 'c'], 'correct_index': 0,
                'explanation': 'Reason', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'lesson', 'title': 'Title',
              'content': 'Не касаться поверхности.', 'questions': [question]}]}
    return corpus, packet, course


@pytest.mark.asyncio
async def test_no_finding_is_not_acceptance_and_blind_question_runs(example):
    corpus, packet, course = example
    view = PracticalModelView(packet)
    groups = []
    async def stage(name, group, messages, fmt, validator):
        groups.append(group)
        if ':author:' in group:
            result = view.encode(copy.deepcopy(course))
        elif ':graph:' in group:
            payload = json.loads(messages[1]['content'])
            result = {'role': payload['role'], 'input_fingerprint': payload['input_fingerprint'],
                'decisions': [{'token_id': row['token_id'], 'classification': 'UNKNOWN', 'object_kind': 'UNKNOWN',
                               'object_quote': '', 'negation_quote': '', 'note': ''}
                              for row in payload['candidate_tokens']]}
        elif ':questions:' in group:
            payload = json.loads(messages[1]['content'].split('\nQUESTION_EDITOR_JSON\n', 1)[1])
            result = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': payload['course_fingerprint'],
                      'checks': [{'question_id': 'q', 'status': 'UNVERIFIED', 'reason': 'Insufficient'}], 'updates': []}
            assert 'Не касаться поверхности.' not in json.dumps(payload['questions'], ensure_ascii=False)
        elif ':question-repair:' in group:
            payload = json.loads(messages[1]['content'].split('\nQUESTION_EDITOR_JSON\n', 1)[1].split(
                '\nUNVERIFIED_CURRENT_QUESTION_FINDINGS_JSON\n', 1)[0])
            result = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': payload['course_fingerprint'],
                      'checks': [{'question_id': 'q', 'status': 'UNVERIFIED', 'reason': 'Insufficient'}], 'updates': []}
        elif ':blind:' in group:
            props = fmt['json_schema']['schema']['properties']
            ids = props['judgments']['items']['properties']['item_id']['enum']
            result = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                'bank_fingerprint': props['bank_fingerprint']['enum'][0],
                'judgments': [{'item_id': item, 'status': 'UNDECIDABLE', 'reason': 'Unknown',
                               'source_refs': [], 'compatible_case': ''} for item in ids]}
        else:
            raise AssertionError(group)
        validator(copy.deepcopy(result))
        return result
    result = await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=8192, max_revisions=2)
    assert result.course == course and result.decision.accepted is False and not result.decision.source_uncertain
    assert result.stop_reason == 'focused_review_pending' and result.review['narrative_sources'] == {'lesson': []}
    assert result.history[0]['question_receipt']['unverified_question_ids'] == ['q']
    assert sum(':graph:' in x for x in groups) == 2 and any(':blind:' in x for x in groups)
    assert not any(':attachment:' in x or ':action:' in x or ':noun:' in x for x in groups)


def test_editor_uncertainty_merges_grounds_and_rejects_stale_revision(example):
    _, packet, course = example
    receipt = {'source_fingerprint': packet.fingerprint, 'after_course_fingerprint': _digest(course),
        'checks': [{'question_id': 'q', 'status': 'UNVERIFIED', 'reason': 'EDITOR_REASON'}]}
    blind = [{'issue_id': 'blind', 'scope': 'question', 'id': 'q', 'evidence': {'problem': 'BLIND_REASON'}}]
    combined = cycle._with_question_uncertainty(packet, course, receipt, blind)
    assert len(combined) == 1
    assert 'BLIND_REASON' in combined[0]['evidence']['problem'] and 'EDITOR_REASON' in combined[0]['evidence']['problem']
    assert combined[0]['evidence']['question_editor_unverified']['reviewed_course_fingerprint'] == _digest(course)
    assert blind[0]['evidence'] == {'problem': 'BLIND_REASON'}
    edited = copy.deepcopy(course)
    edited['lessons'][0]['questions'][0]['explanation'] = 'Changed current explanation.'
    with pytest.raises(ValueError, match='receipt_stale'):
        cycle._with_question_uncertainty(packet, edited, receipt, blind)


@pytest.mark.asyncio
async def test_unknown_graph_stage_propagates_without_retry(example):
    corpus, packet, course = example
    view = PracticalModelView(packet)
    groups = []
    async def stage(name, group, messages, fmt, validator):
        groups.append(group)
        if ':author:' in group:
            value = view.encode(copy.deepcopy(course))
            validator(value)
            return value
        raise TimeoutError('unknown transport outcome')
    with pytest.raises(TimeoutError):
        await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=8192, max_revisions=2)
    assert len(groups) == 2 and ':graph:source:' in groups[-1]


def test_prose_protection_fails_closed_for_media_and_questions(example):
    _, _, course = example
    course['lessons'][0]['content'] += '\n\n![photo](image.png)'
    changed = copy.deepcopy(course)
    changed['lessons'][0]['content'] = 'Revised body.'
    with pytest.raises(ValueError, match='media'):
        cycle._protect_prose(course, changed)
    changed = copy.deepcopy(course)
    changed['lessons'][0]['questions'][0]['prompt'] = 'Different question?'
    with pytest.raises(ValueError, match='structure'):
        cycle._protect_prose(course, changed)


@pytest.mark.asyncio
@pytest.mark.parametrize('later_status', ['UNVERIFIED', 'VALID', 'REPAIRED'])
async def test_question_editor_uncertainty_is_addressed_and_remains_current(example, later_status):
    from app.modules.ai.v3.practical_draft_review import editorial_manifest
    from app.modules.ai.v3.revision_policy import FOCUSED_EDITORIAL_REVIEW_POLICY

    corpus, packet, course = example
    view = PracticalModelView(packet)
    groups = []
    async def stage(name, group, messages, fmt, validator):
        groups.append(group)
        if ':author:' in group:
            value = view.encode(copy.deepcopy(course))
        elif ':graph:' in group:
            payload = json.loads(messages[1]['content'])
            value = {'role': payload['role'], 'input_fingerprint': payload['input_fingerprint'], 'decisions': [
                {'token_id': row['token_id'], 'classification': 'UNKNOWN', 'object_kind': 'UNKNOWN',
                 'object_quote': '', 'negation_quote': '', 'note': ''} for row in payload['candidate_tokens']]}
        elif ':questions:' in group or ':question-repair:' in group:
            payload = json.loads(messages[1]['content'].split('\nQUESTION_EDITOR_JSON\n', 1)[1].split(
                '\nUNVERIFIED_CURRENT_QUESTION_FINDINGS_JSON\n', 1)[0])
            status = later_status if ':question-repair:' in group else 'UNVERIFIED'
            updates = []
            if status == 'REPAIRED':
                question = copy.deepcopy(payload['questions'][0]['questions'][0])
                question['explanation'] = 'Revised current explanation.'
                updates = [{'lesson_id': 'lesson', 'question': question}]
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': payload['course_fingerprint'],
                'checks': [{'question_id': 'q', 'status': status, 'reason': 'EDITOR_CURRENT_REASON'}],
                'updates': updates}
        elif ':blind:' in group:
            props = fmt['json_schema']['schema']['properties']
            ids = props['judgments']['items']['properties']['item_id']['enum']
            value = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                'bank_fingerprint': props['bank_fingerprint']['enum'][0], 'judgments': [
                    {'item_id': item, 'status': 'SUPPORTED' if index == 0 else 'NOT_SUPPORTED',
                     'reason': 'Grounded options', 'source_refs': ['SRC1'] if index == 0 else [],
                     'compatible_case': 'Grounded current case' if index == 0 else ''}
                    for index, item in enumerate(ids)]}
        else:
            raise AssertionError(group)
        validator(copy.deepcopy(value))
        return value

    result = await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage,
                                           max_output_tokens=8192, max_revisions=2)
    assert sum(':question-repair:' in group for group in groups) == 1
    assert not result.decision.accepted and not result.decision.source_uncertain
    manifest = editorial_manifest(result, packet, [], review_policy=FOCUSED_EDITORIAL_REVIEW_POLICY)
    assert manifest['source_clarification_required'] is False
    if later_status == 'UNVERIFIED':
        assert {row['id'] for row in result.decision.feedback} == {'q'}
        assert any(row['target_id'] == 'q' and 'EDITOR_CURRENT_REASON' in str(row) for row in manifest['issues'])
    else:
        assert not result.decision.feedback
        assert not any(row['target_id'] == 'q' for row in manifest['issues'])
    assert result.history[0]['question_receipt']['unverified_question_ids'] == ['q']
