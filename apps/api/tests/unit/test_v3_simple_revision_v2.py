import copy

import pytest

from app.modules.ai.v3.simple_course_editor import _digest
from app.modules.ai.v3.simple_course_revision_v2 import (
    compile_simple_revision_v2,
    editor_format,
    is_simple_revision_v2_format,
    matches_simple_revision_v2,
    source_question_inventory,
)
from tests.unit.test_v3_simple_course_editor import course, fixture


def setup_revision():
    corpus, packet = fixture()
    ref = packet.blocks[0].block_id
    original = course(ref=ref, content='Body ![diagram](source-asset:asset-123)')
    second = copy.deepcopy(original['lessons'][0]['questions'][0])
    second['id'] = 'peer'
    original['lessons'][0]['questions'].append(second)
    fingerprint = _digest(original)
    def finding(domain, kind, target):
        return {'domain': domain, 'severity': 'material', 'target': {'kind': kind, 'id': target},
            'problem': 'Check ambiguity', 'basis': 'Source basis', 'correction': 'Clarify', 'source_refs': [ref]}
    content = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': fingerprint, 'summary': 'review',
               'findings': [finding('content', 'lesson', 'lesson'), finding('source', 'source', ref)],
               'source_notes': [], 'narrative_sources': {'lesson': [ref]}}
    assessment = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
                  'proposals': [{'target_id': 'question', 'correction': 'Fix question', 'source_refs': [ref]}],
                  'source_questions': [{'question': 'Another source uncertainty?', 'source_refs': [ref]}]}
    inventory = source_question_inventory(packet, original, content, assessment)
    value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint, 'course': copy.deepcopy(original),
             'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': [ref]}], 'source_questions': [],
             'source_question_decisions': []}
    return corpus, packet, original, content, assessment, inventory, value


def compile_value(parts, value):
    corpus, packet, original, content, assessment, inventory, _ = parts
    return compile_simple_revision_v2(value, packet=packet, corpus=corpus, original=original,
        content_review=content, assessment_review=assessment, source_questions=inventory)


def test_quiet_and_partial_editor_retains_unverified_without_source_hold():
    parts = setup_revision()
    corpus, packet, original, _, _, inventory, value = parts
    fmt = editor_format([packet.blocks[0].block_id], packet.fingerprint, _digest(original), [q['id'] for q in inventory])
    assert is_simple_revision_v2_format(fmt) and matches_simple_revision_v2(value, fmt)
    quiet = compile_value(parts, value)
    assert quiet.course == original and quiet.source_questions == []
    assert len(quiet.receipt['unverified_source_questions']) == 2
    value['source_question_decisions'] = [{'question_id': inventory[0]['id'], 'status': 'RESOLVED_FROM_SOURCE',
        'reason': 'Source resolves it', 'source_refs': [packet.blocks[0].block_id], 'source_quote': 'If approved'}]
    result = compile_value(parts, value)
    assert [d['status'] for d in result.receipt['source_question_decisions']] == ['RESOLVED_FROM_SOURCE', 'UNVERIFIED']
    assert result.receipt['unverified_source_questions'][0]['id'] == inventory[1]['id']
    assert not any(row['finding']['domain'] == 'source' for row in result.receipt['unapplied_review_findings'])
    assert not result.receipt['semantic_approval']


def test_domain_scopes_restore_peer_title_and_media():
    parts = setup_revision()
    original, value = parts[2], parts[-1]
    value['course']['title'] = 'unrequested title'
    lesson = value['course']['lessons'][0]
    lesson['title'] = 'unrequested lesson title'
    lesson['content'] = 'Changed without protected image'
    lesson['questions'][0]['prompt'] = 'Target change'
    lesson['questions'][1]['prompt'] = 'Peer change'
    result = compile_value(parts, value)
    assert result.course['title'] == original['title']
    assert result.course['lessons'][0]['title'] == original['lessons'][0]['title']
    assert result.course['lessons'][0]['content'] == original['lessons'][0]['content']
    assert result.course['lessons'][0]['questions'][0]['prompt'] == 'Target change'
    assert result.course['lessons'][0]['questions'][1] == original['lessons'][0]['questions'][1]
    assert 'lesson_content:lesson' in result.receipt['ignored_unrequested_changes']


def test_question_finding_alone_cannot_edit_lesson_body():
    parts = setup_revision()
    content, original, value = parts[3], parts[2], parts[-1]
    content['findings'] = [row for row in content['findings'] if row['domain'] != 'content']
    parts[5][:] = source_question_inventory(parts[1], original, content, parts[4])
    value['course']['lessons'][0]['content'] = 'Unauthorized body ![diagram](source-asset:asset-123)'
    value['course']['lessons'][0]['questions'][0]['prompt'] = 'Allowed question'
    result = compile_value(parts, value)
    assert result.course['lessons'][0]['content'] == original['lessons'][0]['content']
    assert result.course['lessons'][0]['questions'][0]['prompt'] == 'Allowed question'


def test_content_finding_alone_cannot_edit_question():
    parts = setup_revision()
    original, value = parts[2], parts[-1]
    parts[4]['proposals'] = []
    value['course']['lessons'][0]['content'] = 'Allowed body ![diagram](source-asset:asset-123)'
    value['course']['lessons'][0]['questions'][0]['prompt'] = 'Unauthorized question'
    result = compile_value(parts, value)
    assert result.course['lessons'][0]['content'].startswith('Allowed body')
    assert result.course['lessons'][0]['questions'][0] == original['lessons'][0]['questions'][0]


@pytest.mark.parametrize(('kind', 'target_id'), [('course', 'course'), ('question', 'question')])
def test_material_unapplied_content_finding_remains_actionable(kind, target_id):
    parts = setup_revision()
    packet, original, content, value = parts[1], parts[2], parts[3], parts[-1]
    content['findings'][0]['target'] = {'kind': kind, 'id': target_id}
    value['course']['lessons'][0]['content'] = 'Unrequested edit ![diagram](source-asset:asset-123)'
    value['course']['lessons'][0]['questions'][0]['prompt'] = 'Unrequested question'
    parts[4]['proposals'] = []
    result = compile_value(parts, value)
    assert result.course == original
    pending = result.receipt['unapplied_review_findings']
    row = next(row for row in pending if row['finding'] == content['findings'][0])
    assert row['status'] == 'UNVERIFIED'
    assert row['id'] == 'simple-unapplied-' + _digest([packet.fingerprint, _digest(original), content['findings'][0]])[:24]
    assert row['source_fingerprint'] == packet.fingerprint and row['draft_fingerprint'] == _digest(original)
    assert not any(row['finding']['domain'] == 'source' for row in pending)


@pytest.mark.parametrize('fault', ['duplicate', 'foreign_id', 'foreign_ref', 'stale', 'inventory'])
def test_foreign_duplicate_and_stale_integrity_rejected(fault):
    parts = setup_revision()
    packet, inventory, value = parts[1], parts[5], parts[-1]
    decision = {'question_id': inventory[0]['id'], 'status': 'RESOLVED_FROM_SOURCE', 'reason': 'Reason',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': 'If approved'}
    value['source_question_decisions'] = [decision]
    if fault == 'duplicate':
        value['source_question_decisions'].append(copy.deepcopy(decision))
    elif fault == 'foreign_id':
        decision['question_id'] = 'foreign'
    elif fault == 'foreign_ref':
        decision['source_refs'] = ['foreign']
    elif fault == 'stale':
        value['draft_fingerprint'] = '0' * 64
    else:
        parts[5].append({'id': 'forged', 'question': 'x', 'source_refs': [packet.blocks[0].block_id]})
    with pytest.raises(ValueError):
        compile_value(parts, value)


def test_bad_quote_or_reason_remains_unverified_and_genuine_ambiguity_is_separate():
    parts = setup_revision()
    packet, inventory, value = parts[1], parts[5], parts[-1]
    value['source_question_decisions'] = [
        {'question_id': inventory[0]['id'], 'status': 'SOURCE_AMBIGUITY', 'reason': 'Reason',
         'source_refs': [packet.blocks[0].block_id], 'source_quote': 'not in source'},
        {'question_id': inventory[1]['id'], 'status': 'SOURCE_AMBIGUITY', 'reason': 'Reason',
         'source_refs': [packet.blocks[0].block_id], 'source_quote': 'If approved'},
    ]
    result = compile_value(parts, value)
    assert len(result.source_questions) == 1 and result.source_questions[0]['question'] == inventory[1]['question']
    assert result.receipt['unverified_source_questions'][0]['id'] == inventory[0]['id']
