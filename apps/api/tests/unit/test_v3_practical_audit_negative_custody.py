"""Negative audit rows remain actionable even without duplicate findings."""
import copy

import pytest

from app.modules.ai.v3.practical_review import interpret_practical_review
from app.modules.ai.v3.practical_source_audit import compiled_source_audit_findings, validate_source_audit
from tests.unit.test_v3_practical_review import example, finding
from tests.unit.test_v3_practical_source_audit import audit


@pytest.mark.parametrize(('status', 'scope'), [('MISSING', 'coverage'), ('UNCERTAIN', 'source')])
def test_negative_row_without_duplicate_finding_reaches_decision(status, scope):
    packet, course, value, ref = audit.__wrapped__()
    _, _, review, _ = example.__wrapped__()
    row = value['source_checks'][0]
    row.update(status=status, lesson_ids=['lesson'], reason='Specific source concern')
    value['findings'] = []
    original = copy.deepcopy(value)
    assert validate_source_audit(value, packet, course) == original
    generated = compiled_source_audit_findings(value, packet, course)
    assert generated == [{'scope': scope, 'target_id': 'lesson' if status == 'MISSING' else ref, 'source_refs': [ref],
                          'problem': row['reason'], 'expected_rule': row['reason'], 'correction': row['reason']}]
    assert value == original
    review['findings'] = generated
    decision = interpret_practical_review(review, packet, course)
    assert not decision.accepted
    if status == 'MISSING':
        assert decision.lesson_ids == ('lesson',) and not decision.source_uncertain
    else:
        assert decision.source_uncertain and not decision.lesson_ids


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['MISSING', 'UNCERTAIN'])
async def test_actual_cycle_never_accepts_unmirrored_negative_audit(status):
    from app.modules.ai.v3.practical_audit_units import audit_units
    from app.modules.ai.v3.practical_cycle import run_practical_cycle
    from app.modules.ai.v3.practical_model_view import PracticalModelView
    from tests.unit.test_v3_practical_cycle import case, checked

    _, packet, course = case.__wrapped__()
    view = PracticalModelView(packet)
    refs = [block.block_id for block in packet.blocks]

    async def invoke(stage, group, messages, fmt, validator):
        if group.startswith('practical:author:'):
            value = course
        elif group.startswith('practical:review:'):
            value = checked(packet, course)
        else:
            assert group.startswith('practical:source-audit:')
            grouping = audit_units(packet)
            value = {'source_fingerprint': packet.fingerprint,
                'source_units_fingerprint': grouping.fingerprint, 'source_review': 'Reviewed.',
                'source_notes': [], 'findings': [], 'narrative_sources': {'l1': refs},
                'source_checks': [{'unit_id': key, 'source_refs': list(blocks), 'status': status,
                    'lesson_ids': ['l1'], 'reason': 'Specific unresolved source concern.'}
                    for key, blocks in grouping.groups]}
        wire = view.encode(value)
        validator(wire)
        return wire

    result = await run_practical_cycle(packet, {}, invoke, max_revisions=0)
    assert not result.decision.accepted
    assert result.decision.source_uncertain is (status == 'UNCERTAIN')
    assert result.history[0]['source_audit']['findings'] == []
    assert result.history[0]['consolidated_review']['findings']
    assert result.decision.feedback


@pytest.mark.parametrize('target', ['source', 'lesson'])
def test_explicit_coverage_does_not_erase_distinct_negative_reason(target):
    packet, course, value, ref = audit.__wrapped__()
    value['source_checks'][0].update(status='MISSING', lesson_ids=['lesson'], reason='Specific issue')
    explicit = finding('coverage', ref if target == 'source' else 'lesson', ref)
    value['findings'] = [explicit]
    result = compiled_source_audit_findings(value, packet, course)
    assert result[0] == explicit and len(result) == 2
    assert result[1]['target_id'] == 'lesson' and result[1]['problem'] == 'Specific issue'


def test_only_exact_duplicate_generated_finding_is_deduplicated():
    packet, course, value, ref = audit.__wrapped__()
    value['source_checks'][0].update(status='MISSING', lesson_ids=['lesson'], reason='Specific issue')
    explicit = {'scope': 'coverage', 'target_id': 'lesson', 'source_refs': [ref],
                'problem': 'Specific issue', 'expected_rule': 'Specific issue', 'correction': 'Specific issue'}
    value['findings'] = [explicit]
    assert compiled_source_audit_findings(value, packet, course) == [explicit]


def test_partial_missing_routes_named_lesson_even_if_narrative_has_other_source():
    from app.modules.ai.v3.practical_audit_units import audit_units
    from app.modules.ai.v3.practical_patch import practical_patch_format
    from tests.unit.test_v3_practical_cycle import case, checked

    _, packet, course = case.__wrapped__()
    groups = audit_units(packet).groups
    assert len(groups) >= 2
    target_ref = groups[0][1][0]
    other_ref = groups[1][1][0]
    value = {'source_fingerprint': packet.fingerprint, 'source_units_fingerprint': audit_units(packet).fingerprint,
             'source_review': 'Reviewed.', 'source_notes': [], 'findings': [],
             'narrative_sources': {'l1': [other_ref]},
             'source_checks': [{'unit_id': key, 'source_refs': list(refs),
                'status': 'MISSING' if i == 0 else 'TAUGHT', 'lesson_ids': ['l1'],
                'reason': 'Omitted action' if i == 0 else 'Taught'}
                for i, (key, refs) in enumerate(groups)]}
    findings = compiled_source_audit_findings(value, packet, course)
    assert findings[0]['target_id'] == 'l1' and target_ref in findings[0]['source_refs']
    review = checked(packet, course)
    review['narrative_sources'] = value['narrative_sources']
    review['findings'] = findings
    decision = interpret_practical_review(review, packet, course)
    assert decision.lesson_ids == ('l1',) and not decision.allow_new_lessons
    props = practical_patch_format(packet, course, decision)['json_schema']['schema']['properties']
    assert set(props['lesson_updates']['properties']) == {'l1'}
    assert props['new_questions']['maxItems'] == props['new_lessons']['maxItems'] == 0


def test_missing_row_routes_each_named_lesson():
    packet, course, value, ref = audit.__wrapped__()
    sibling = copy.deepcopy(course['lessons'][0])
    sibling['id'] = 'lesson-2'
    sibling['questions'][0]['id'] = 'question-2'
    course['lessons'].append(sibling)
    value['narrative_sources']['lesson-2'] = [ref]
    value['source_checks'][0].update(status='MISSING', lesson_ids=['lesson', 'lesson-2'], reason='Gap')
    value['findings'] = []
    findings = compiled_source_audit_findings(value, packet, course)
    assert [row['target_id'] for row in findings] == ['lesson', 'lesson-2']
    assert all(row['problem'] == 'Gap' for row in findings)


def test_unrelated_question_finding_cannot_erase_negative_row():
    packet, course, value, ref = audit.__wrapped__()
    value['source_checks'][0].update(status='MISSING', lesson_ids=[], reason='Specific issue')
    explicit = finding('question', 'question', ref)
    value['findings'] = [explicit]
    findings = compiled_source_audit_findings(value, packet, course)
    assert findings[0] == explicit and len(findings) == 2
    assert findings[1]['target_id'] == ref and findings[1]['problem'] == 'Specific issue'


def test_taught_rows_produce_no_invented_findings():
    packet, course, value, _ = audit.__wrapped__()
    value['findings'] = []
    assert compiled_source_audit_findings(value, packet, course) == []


@pytest.mark.parametrize('defect', ['foreign_target', 'foreign_ref', 'bad_fingerprint', 'blank_reason'])
def test_compilation_fails_closed_on_invalid_audit(defect):
    packet, course, value, _ = audit.__wrapped__()
    value['source_checks'][0]['status'] = 'MISSING'
    if defect == 'foreign_target':
        value['findings'][0]['target_id'] = 'foreign'
    elif defect == 'foreign_ref':
        value['source_checks'][0]['source_refs'] = ['foreign']
    elif defect == 'bad_fingerprint':
        value['source_units_fingerprint'] = '0' * 64
    else:
        value['source_checks'][0]['reason'] = ' '
    with pytest.raises(ValueError, match='practical_source_audit_response_invalid'):
        compiled_source_audit_findings(value, packet, course)
