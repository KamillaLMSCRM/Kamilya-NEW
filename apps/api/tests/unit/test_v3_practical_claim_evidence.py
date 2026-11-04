import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_arbitration import evidence_inventory
from app.modules.ai.v3.practical_atomic_audit import (
    _source_with_child_markers,
    atomic_audit_format,
    atomic_audit_messages,
    compiled_atomic_audit_findings,
    is_atomic_audit_format,
    matches_atomic_audit,
    validate_atomic_audit,
)
from app.modules.ai.v3.practical_audit_spans import audit_spans
from app.modules.ai.v3.practical_contract import PracticalSourceBlock, PracticalSourcePacket
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_scope import scoped_course_view
from app.modules.ai.v3.response_contracts import response_contract
from tests.unit.test_v3_practical_atomic_audit import audit_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
OPTIONS = {'typed_findings': True, 'strict_owners': True, 'claim_evidence': True}


def response(packet, course):
    lesson = course['lessons'][0]
    inventory = evidence_inventory(scoped_course_view(packet, course))[0]
    evidence = next(key for key, item in inventory.items() if item['field'] == 'content'
                    and item['lesson_id'] == lesson['id'] and item['text'].strip())
    from app.modules.ai.v3.practical_contract import _digest
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
            'source_review': 'Reviewed.', 'source_notes': [], 'findings': [],
            'source_checks': [{'span_id': span.span_id, 'status': 'TAUGHT', 'reason': '', 'evidence': [evidence]}
                for span in audit_spans(packet)]}


def test_child_inventory_and_literal_ownership(case):
    _, packet, course = case
    value = response(packet, course)
    fmt = atomic_audit_format(packet, course, **OPTIONS)
    assert is_atomic_audit_format(fmt) and matches_atomic_audit(value, fmt)
    assert validate_atomic_audit(value, packet, course, **OPTIONS) == value
    wire = PracticalModelView(packet)
    assert is_atomic_audit_format(wire.schema(fmt))
    assert matches_atomic_audit(wire.encode(value), wire.schema(fmt))
    assert wire.decode(wire.encode(value)) == value
    missing = copy.deepcopy(value)
    missing['source_checks'].pop()
    assert not matches_atomic_audit(missing, fmt)
    duplicate = copy.deepcopy(value)
    duplicate['source_checks'][1]['span_id'] = duplicate['source_checks'][0]['span_id']
    assert not matches_atomic_audit(duplicate, fmt)
    wrong = copy.deepcopy(value)
    wrong['source_checks'][0]['span_id'] = 'SPAN999999'
    assert not matches_atomic_audit(wrong, fmt)


@pytest.mark.parametrize('evidence', [[], ['foreign'], ['E999999'], ['  ']])
def test_unproven_taught_is_held(case, evidence):
    _, packet, course = case
    value = response(packet, course)
    value['source_checks'][0]['evidence'] = evidence
    checked = validate_atomic_audit(value, packet, course, **OPTIONS)
    assert checked['source_checks'][0]['status'] == 'UNCONFIRMED'
    assert validate_atomic_audit(checked, packet, course, **OPTIONS) == checked
    assert compiled_atomic_audit_findings(value, packet, course, **OPTIONS)[0]['scope'] == 'coverage'
    assert value['source_checks'][0]['status'] == 'TAUGHT'


def test_lesson_owners_derive_from_content_evidence(case):
    _, packet, course = case
    second = copy.deepcopy(course['lessons'][0])
    second['id'] = 'l2'
    second['content'] = 'Unique other lesson text.'
    for index, question in enumerate(second['questions']):
        question['id'] = f'other{index}'
    course['lessons'].append(second)
    value = response(packet, course)
    inventory = evidence_inventory(scoped_course_view(packet, course))[0]
    other = next(key for key, item in inventory.items() if item['lesson_id'] == 'l2' and item['field'] == 'content')
    explanation = next(key for key, item in inventory.items() if item['field'] == 'explanation')
    value['source_checks'][0]['evidence'].extend([other, explanation])
    assert validate_atomic_audit(value, packet, course, **OPTIONS)['source_checks'][0]['status'] == 'UNCONFIRMED'
    value['source_checks'][0].update(status='MISSING', reason='Missing.', evidence=[other])
    assert compiled_atomic_audit_findings(value, packet, course, **OPTIONS)[0]['target_id'] == 'l2'
    value['source_checks'][0].update(status='CONTRADICTED', evidence=[])
    assert validate_atomic_audit(value, packet, course, **OPTIONS)['source_checks'][0]['status'] == 'UNCONFIRMED'
    assert compiled_atomic_audit_findings(value, packet, course, **OPTIONS)[0]['scope'] == 'coverage'


def test_portable_list_parent_context_and_single_source_render():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    text = '4.5. When energized AND the guard is open:\n- isolate the UNIQUE-LONG-POWER-UNIT before work;\n- keep the guard closed.\n'
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
                               'document:' + hashlib.sha256(text.encode()).hexdigest(), (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    spans = audit_spans(packet)
    assert len(spans) == 2 and ''.join(span.text for span in spans) == text
    assert 'AND the guard' in spans[0].text
    rendered = _source_with_child_markers(packet, None)
    block_body = rendered.split('SOURCE_BLOCK ' + packet.blocks[0].block_id, 1)[1].split(
        '\n\nПОДТВЕРЖДЁННЫЕ УТОЧНЕНИЯ', 1)[0]
    assert re.sub(r'\n\[CHILD SPAN\d+\]\n', '', block_body) == text
    question = {'id': 'q', 'prompt': 'What?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
                'explanation': 'A.', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'l', 'title': 'Lesson', 'content': 'Isolate first.',
                                              'questions': [question]}]}
    body = atomic_audit_messages(packet, course, **OPTIONS)[1]['content']
    assert body.count('UNIQUE-LONG-POWER-UNIT') == 1


def test_legacy_bytes_and_stale_fingerprint(case):
    _, packet, course = case
    assert atomic_audit_format(packet, course, typed_findings=True, strict_owners=True) == atomic_audit_format(
        packet, course, typed_findings=True, strict_owners=True, claim_evidence=False)
    assert atomic_audit_messages(packet, course, typed_findings=True, strict_owners=True) == atomic_audit_messages(
        packet, course, typed_findings=True, strict_owners=True, claim_evidence=False)
    assert matches_atomic_audit(audit_value(packet, course), atomic_audit_format(packet, course))
    value = response(packet, course)
    value['source_fingerprint'] = '0' * 64
    assert not matches_atomic_audit(value, atomic_audit_format(packet, course, **OPTIONS))


def test_saved_fire_compound_block_and_parent_context():
    path = Path(__file__).resolve().parents[4] / '.release-evidence/v3-production/p14-private-readback-536cd5a074b64acfa6c4d59cc689685d/packet.json'
    if not path.exists():
        pytest.skip('private saved packet unavailable')
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    packet = PracticalSourcePacket(raw['tenant_id'], tuple(PracticalSourceBlock(**b) for b in raw['blocks']),
        tuple(raw['reference_context']), raw['fingerprint'],
        tuple((d['doc_id'], d['source_revision'], d['text_sha256']) for d in raw['source_documents']))
    block = next(b for b in packet.blocks if '4.5.' in b.text)
    spans = [s for s in audit_spans(packet) if s.source_ref == block.block_id]
    assert len(spans) == 7
    assert block.text == ''.join(s.text for s in spans)
    assert spans[0].text.startswith(block.text.splitlines()[0])
    course = json.loads(path.with_name('course.json').read_text(encoding='utf-8-sig'))
    value = response(packet, course)
    row = next(row for row in value['source_checks'] if row['span_id'] == spans[1].span_id)
    row.update(status='MISSING', reason='A child provision is absent.', evidence=[])
    findings = compiled_atomic_audit_findings(value, packet, course, **OPTIONS)
    assert any(spans[1].span_id in finding['problem'] and finding['scope'] == 'coverage' for finding in findings)


def test_shipped_runner_accepts_large_aliased_contract():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    text = ''.join(f'Rule {i}.\n\n' for i in range(1000))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
                               'document:' + hashlib.sha256(text.encode()).hexdigest(), (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    question = {'id': 'q1', 'prompt': 'What?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
                'explanation': 'A.', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Rule.',
                                              'questions': [question]}]}
    fmt = PracticalModelView(packet).schema(atomic_audit_format(packet, course, **OPTIONS))
    spec = importlib.util.spec_from_file_location('claim_evidence_runner',
        Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert response_contract(fmt) == 'practical_source_audit'
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


def test_unconfirmed_child_reaches_arbiter_with_exact_source_text_not_just_parent(case):
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_arbitration import arbitration_messages
    from app.modules.ai.v3.practical_contract import build_practical_source_packet
    from app.modules.ai.v3.practical_review import PracticalReviewDecision, _issue

    text = '4.5. When delivery is approved:\n- sign the receipt;\n- record the approval in the system.\n'
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
                               'document:' + hashlib.sha256(text.encode()).hexdigest(), (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    course = copy.deepcopy(case[2])
    course['lessons'][0]['content'] = 'Sign the receipt.'
    for q in course['lessons'][0]['questions']:
        q['source_refs'] = [packet.blocks[0].block_id]
    value = response(packet, course)
    children = audit_spans(packet)
    assert len(children) == 2 and children[0].source_ref == children[1].source_ref
    target = children[-1]
    row = next(r for r in value['source_checks'] if r['span_id'] == target.span_id)
    row['evidence'] = []
    finding = compiled_atomic_audit_findings(value, packet, course, **OPTIONS)[0]
    assert target.text in finding['expected_rule']
    assert target.span_id in finding['expected_rule']
    issue = _issue(finding['scope'], finding['target_id'], finding)
    decision = PracticalReviewDecision(False, False, (), (), True, (issue,))
    messages = arbitration_messages(packet, course, decision, selectors=True,
                                     typed_findings=True, materiality_review=True)
    payload = json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1])
    assert target.text in payload['critic_findings'][0]['evidence']['expected_rule']


def test_literal_missing_lesson_target_stays_owned_without_becoming_taught_proof(case):
    _corpus, packet, course = case
    value = response(packet, course)
    row = value['source_checks'][0]
    row.update(status='MISSING', reason='An independent action is absent.', evidence=['l1'])
    finding = compiled_atomic_audit_findings(value, packet, course, **OPTIONS)[0]
    assert finding['scope'] == 'coverage' and finding['target_id'] == 'l1'
    system = atomic_audit_messages(packet, course, **OPTIONS)[0]['content']
    assert 'E-ID связанного фрагмента content, а не ID урока' in system
    row.update(status='TAUGHT', reason='')
    assert validate_atomic_audit(value, packet, course, **OPTIONS)['source_checks'][0]['status'] == 'UNCONFIRMED'
