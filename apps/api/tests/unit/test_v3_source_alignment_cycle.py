"""Model source-reading corrections reach writing before semantic acceptance."""

import copy

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3 import practical_autonomous_editorial_cycle as cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_semantics import compile_source_semantics, compile_source_semantics_verification
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value, rule_wire
from tests.unit.test_v3_editorial_contract import review_value, revision_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [True, False])
async def test_source_model_correction_is_alignment_intent_not_a_fabricated_course_defect(case, monkeypatch, changed):
    corpus, packet, original = case
    view = PracticalModelView(packet)
    rule = {'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
        'actor': 'Auditor', 'action': 'Approve', 'object': 'Ticket', 'modality': 'must',
        'conditions': [], 'alternatives': [], 'limits': []}
    reading = compile_source_semantics({'source_fingerprint': packet.fingerprint,
        'sections': [{'section': 'Approval', 'rules': [rule]}], 'uncertainties': []}, packet)
    replacement = {**rule, 'actor': 'Approver'}
    checked = compile_source_semantics_verification({'source_fingerprint': packet.fingerprint,
        'reading_fingerprint': reading['reading_fingerprint'], 'additional_rules': [],
        'rule_checks': [{'rule_id': 'R1', 'status': 'REVISE', 'reason': 'The source names the approver, not auditor.',
            'replacement': [replacement], 'source_question': ''}]}, packet, reading)

    async def source(*args):
        return checked

    monkeypatch.setattr(cycle, 'prepare_source_semantics', source)
    candidate = copy.deepcopy(original)
    if changed:
        candidate['lessons'][0]['content'] = 'The approver performs both required actions.'
    calls = []

    async def stage(name, group, messages, fmt, validate):
        calls.append(group)
        if name == 'lesson':
            value = original
        elif ':source-alignment:' in group:
            assert 'MODEL_SOURCE_READING_CORRECTIONS_JSON' in messages[1]['content']
            assert 'EDITORIAL_FINDINGS_UNVERIFIED_JSON' not in messages[1]['content']
            assert checked['interpretations'][0]['reason'] in messages[1]['content']
            value = revision_value(packet, original, candidate)
        elif 'option-predicates' in group:
            value = predicate_value(packet, candidate, fmt=fmt)
        else:
            value = review_value(packet, candidate)
            value['findings'] = []
            value = rule_wire(value, fmt, candidate)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    alignment = result.history[0]['source_interpretation_alignment']
    assert alignment['revision']['course_error_asserted'] is False
    assert alignment['revision']['revision_applied'] is changed
    assert result.course == candidate and result.decision.accepted
    assert result.history[0]['initial_editorial_review']['findings'] == []
    assert result.history[0]['revisions_used'] == 0
    assert len([group for group in calls if ':source-alignment:' in group]) == 1
    assert not result.history[0]['confirmed_source_questions']
