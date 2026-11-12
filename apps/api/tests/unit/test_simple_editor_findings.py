import copy
from types import SimpleNamespace

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_editor_findings import (
    compile_finding_dispositions,
    finding_disposition_schema,
    inventory,
)


@pytest.fixture
def case():
    packet = SimpleNamespace(fingerprint='source-fp', blocks=[SimpleNamespace(block_id='SRC1', text='Original source rule')])
    original = {'lessons': [{'id': 'L1', 'title': 'Title', 'content': 'Existing lesson body',
                            'questions': [{'id': 'Q1', 'prompt': 'Prompt', 'explanation': 'Explanation',
                                           'choices': ['First choice', 'Second choice']}]}]}
    finding = {'domain': 'content', 'severity': 'material', 'target': {'kind': 'lesson', 'id': 'L1'},
               'problem': 'A problem', 'basis': 'A basis', 'correction': 'A correction', 'source_refs': ['SRC1']}
    rows = inventory(packet.fingerprint, _digest(original), [('global', {'findings': [finding]}),
        ('unit', {'findings': [copy.deepcopy(finding)]})])
    decision = {'finding_id': rows[0]['id'], 'status': 'ALREADY_SATISFIED', 'reason': 'Already taught',
                'source_refs': ['SRC1'], 'source_quote': 'source rule', 'target': {
                    'kind': 'lesson_content', 'id': 'L1', 'choice_index': 0}, 'final_quote': 'lesson body'}
    return packet, original, rows, decision


def compile_case(case, decisions, final=None):
    packet, original, rows, _ = case
    return compile_finding_dispositions(rows, decisions, packet, original, final or original)[0]


def test_inventory_deduplicates_and_excludes_source_and_advisory(case):
    packet, original, rows, _ = case
    assert len(rows) == 1 and rows[0]['origins'] == ['global', 'unit']
    other = copy.deepcopy(rows[0]['finding'])
    other['domain'] = 'source'
    advisory = {**other, 'domain': 'content', 'severity': 'advisory'}
    assert inventory(packet.fingerprint, _digest(original), [('x', {'findings': [other, advisory]})]) == []
    assert 'enum' not in finding_disposition_schema([], [])['items']['properties']['finding_id']


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'unknown', 'stale_source', 'wrong_ref', 'empty_reason'])
def test_missing_duplicate_and_bad_evidence_stay_unverified(case, mode):
    decision = copy.deepcopy(case[3])
    decisions = [decision]
    if mode == 'missing':
        decisions = []
    elif mode == 'duplicate':
        decisions.append(copy.deepcopy(decision))
    elif mode == 'unknown':
        decision['finding_id'] = 'unknown'
    elif mode == 'stale_source':
        decision['source_quote'] = 'Absent source'
    elif mode == 'wrong_ref':
        decision['source_refs'] = ['SRC2']
    else:
        decision['reason'] = ' '
    row = compile_case(case, decisions)
    assert not row['model_resolved'] and row['status'] == 'UNVERIFIED' and not row['semantic_approval']


def test_correction_requires_change_to_owned_field(case):
    decision = copy.deepcopy(case[3])
    decision['status'] = 'CORRECTED'
    final = copy.deepcopy(case[1])
    final['lessons'][0]['questions'][0]['prompt'] = 'Unrelated change'
    assert not compile_case(case, [decision], final)['model_resolved']
    final['lessons'][0]['content'] = 'Corrected lesson body'
    decision['final_quote'] = 'Corrected lesson body'
    assert compile_case(case, [decision], final)['model_resolved']
    final['lessons'][0]['content'] = 'Text without quoted evidence'
    assert not compile_case(case, [decision], final)['evidence_valid']


@pytest.mark.parametrize('kind,identity,quote', [('lesson_title', 'L1', 'Title'),
                                                  ('question_prompt', 'Q1', 'Prompt')])
def test_lesson_finding_cannot_be_resolved_by_title_or_question(case, kind, identity, quote):
    decision = copy.deepcopy(case[3])
    decision['target'].update(kind=kind, id=identity)
    decision['final_quote'] = quote
    assert not compile_case(case, [decision])['model_resolved']


@pytest.mark.parametrize('status', ['ALREADY_SATISFIED', 'NOT_MATERIAL'])
def test_supported_model_claim_keeps_original_and_semantic_review(case, status):
    decision = copy.deepcopy(case[3])
    decision['status'] = status
    row = compile_case(case, [decision])
    assert row['evidence_valid'] and row['model_resolved'] and row['status'] == 'UNVERIFIED'
    assert not row['semantic_approval'] and row['result_fingerprint'] == _digest(case[1])


@pytest.mark.parametrize('after,quote,expected', [
    ('Corrected lesson body', 'Corrected lesson body.', True),
    ('Corrected lesson body.', 'CORRECTED   LESSON BODY', True),
    ('Corrected lesson body', 'Different lesson body.', False),
    ('Limit 1000', 'Limit 10000.', False),
    ('Pay, then record', 'Pay then record.', False),
    ('New prefix Existing lesson body', 'Existing lesson body.', False),
    ('Existing lesson body', 'Existing lesson body.', False),
])
def test_owned_final_field_typography_preserves_full_text_and_change_proof(case, after, quote, expected):
    packet, original, rows, decision = copy.deepcopy(case)
    final = copy.deepcopy(original)
    final['lessons'][0]['content'] = after
    decision.update(status='CORRECTED', final_quote=quote)
    row = compile_finding_dispositions(rows, [decision], packet, original, final,
        allow_final_field_typography=True)[0]
    assert row['model_resolved'] == expected
    assert row['decision']['final_quote'] == quote
    assert row['status'] == 'UNVERIFIED' and not row['semantic_approval']
    if expected:
        assert row['final_quote_match'] == 'owned_field_typography'
    legacy = compile_finding_dispositions(rows, [decision], packet, original, final)[0]
    assert not legacy['model_resolved']


def test_already_satisfied_quote_must_exist_in_original(case):
    final = copy.deepcopy(case[1])
    final['lessons'][0]['content'] = 'Fresh new body'
    decision = copy.deepcopy(case[3])
    decision['final_quote'] = 'Fresh new body'
    assert not compile_case(case, [decision], final)['model_resolved']


def test_course_finding_can_point_to_new_lesson_but_not_new_question(case):
    packet, original, rows, decision = copy.deepcopy(case)
    rows[0]['finding']['target'] = {'kind': 'course', 'id': 'course'}
    final = copy.deepcopy(original)
    final['lessons'].append({'id': 'L2', 'title': 'New', 'content': 'New lesson body',
                             'questions': [{'id': 'Q2', 'prompt': 'New question', 'explanation': 'Why',
                                            'choices': ['Yes', 'No']}]})
    decision.update(status='CORRECTED', final_quote='New lesson body')
    decision['target'].update(kind='lesson_content', id='L2')
    assert compile_finding_dispositions(rows, [decision], packet, original, final)[0]['model_resolved']
    decision['target'].update(kind='question_prompt', id='Q2')
    decision['final_quote'] = 'New question'
    assert not compile_finding_dispositions(rows, [decision], packet, original, final)[0]['model_resolved']


def test_content_finding_can_be_corrected_in_another_owned_lesson(case):
    packet, original, _, _ = copy.deepcopy(case)
    original['lessons'].append({'id': 'L2', 'title': 'Other', 'content': 'Other original body', 'questions': []})
    finding = copy.deepcopy(case[2][0]['finding'])
    rows = inventory(packet.fingerprint, _digest(original), [('global', {'findings': [finding]})])
    decision = copy.deepcopy(case[3])
    decision.update(finding_id=rows[0]['id'], status='CORRECTED', final_quote='Added teaching')
    decision['target'].update(kind='lesson_content', id='L2')
    final = copy.deepcopy(original)
    final['lessons'][1]['content'] = 'Other original body. Added teaching.'
    result = compile_finding_dispositions(rows, [decision], packet, original, final)[0]
    assert result['evidence_valid'] and result['model_resolved']
    assert result['finding']['target'] == {'kind': 'lesson', 'id': 'L1'}
    assert result['decision']['target']['id'] == 'L2'
    assert result['status'] == 'UNVERIFIED' and result['semantic_approval'] is False
    unchanged = copy.deepcopy(original)
    decision['final_quote'] = 'Other original body'
    assert not compile_finding_dispositions(rows, [decision], packet, original, unchanged)[0]['model_resolved']
    decision['target']['id'] = 'foreign'
    assert not compile_finding_dispositions(rows, [decision], packet, original, final)[0]['model_resolved']
    assert not compile_finding_dispositions(rows, [], packet, original, final)[0]['model_resolved']


def test_corrected_quote_must_be_new_in_changed_field(case):
    packet, original, _, _ = copy.deepcopy(case)
    original['lessons'][0]['content'] = 'A. B.'
    finding = copy.deepcopy(case[2][0]['finding'])
    rows = inventory(packet.fingerprint, _digest(original), [('global', {'findings': [finding]})])
    final = copy.deepcopy(original)
    final['lessons'][0]['content'] = 'A. C.'
    decision = copy.deepcopy(case[3])
    decision.update(finding_id=rows[0]['id'], status='CORRECTED', final_quote='A.')
    unchanged_quote = compile_finding_dispositions(rows, [decision], packet, original, final)[0]
    assert unchanged_quote['evidence_valid'] and not unchanged_quote['model_resolved']
    decision['final_quote'] = 'C.'
    changed_quote = compile_finding_dispositions(rows, [decision], packet, original, final)[0]
    assert changed_quote['model_resolved'] and changed_quote['status'] == 'UNVERIFIED'
    assert changed_quote['semantic_approval'] is False


@pytest.mark.parametrize(('quote', 'match'), [
    ('Limit 1\u00a0000 | Active', 'literal'),
    ('limit 1 000 | active', 'normalized_typography'),
    ('LIMIT 1\t000  |\nACTIVE', 'normalized_typography'),
    ('Limit 1 001 | Active', 'none'),
    ('Limit 1 000 | Inactive', 'none'),
    ('Limit 1 000 Active', 'none'),
    ('Limit 1 000 / Active', 'none'),
])
def test_source_quote_typography_preserves_content_and_table_delimiters(case, quote, match):
    packet, original, rows, decision = copy.deepcopy(case)
    packet.blocks[0].text = 'Table: Limit 1\u00a0000 | Active.'
    decision['source_quote'] = quote
    result = compile_finding_dispositions(rows, [decision], packet, original, original)[0]
    assert result['source_quote_match'] == match
    assert result['evidence_valid'] == (match != 'none')
    assert result['model_resolved'] == (match != 'none')
    assert result['decision']['source_quote'] == quote
    assert result['status'] == 'UNVERIFIED' and result['semantic_approval'] is False
