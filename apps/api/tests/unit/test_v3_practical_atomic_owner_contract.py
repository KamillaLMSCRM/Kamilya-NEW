"""A new audit schema expresses the existing owned-lesson invariant."""
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_atomic_audit import (
    STRICT_OWNER_NAME,
    atomic_audit_format,
    atomic_audit_messages,
    atomic_audit_narrative_sources,
    compiled_atomic_audit_findings,
    is_atomic_audit_format,
    matches_atomic_audit,
    validate_atomic_audit,
)
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from tests.unit.test_v3_practical_atomic_audit import audit_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.parametrize('status', ['TAUGHT', 'CONTRADICTED'])
def test_old_schema_permits_held_shape_but_new_schema_requires_owner(case, status):
    _, packet, course = case
    value = audit_value(packet, course)
    value['source_checks'][0].update(status=status, lesson_ids=[], reason='Reason')
    old = atomic_audit_format(packet, course, typed_findings=True)
    new = atomic_audit_format(packet, course, typed_findings=True, strict_owners=True)
    assert _matches(value, old['json_schema']['schema'])
    assert not matches_atomic_audit(value, old)
    assert not _matches(value, new['json_schema']['schema'])
    assert not matches_response_contract(value, new)
    value['source_checks'][0]['lesson_ids'] = ['l1']
    assert _matches(value, new['json_schema']['schema'])
    assert matches_atomic_audit(value, new) and matches_response_contract(value, new)
    assert validate_atomic_audit(value, packet, course, typed_findings=True, strict_owners=True) == value
    assert atomic_audit_narrative_sources(value, packet, course, typed_findings=True, strict_owners=True)['l1']
    assert isinstance(compiled_atomic_audit_findings(value, packet, course, typed_findings=True, strict_owners=True), list)


def test_other_statuses_can_have_empty_owners_and_versions_are_closed(case):
    _, packet, course = case
    value = audit_value(packet, course)
    new = atomic_audit_format(packet, course, typed_findings=True, strict_owners=True)
    assert new['json_schema']['name'] == STRICT_OWNER_NAME and is_atomic_audit_format(new)
    for status in ['MISSING', 'UNCERTAIN', 'NON_TEACHING']:
        value['source_checks'][0].update(status=status, lesson_ids=[], reason='Reason')
        assert matches_atomic_audit(value, new)
    tampered = copy.deepcopy(new)
    tampered['json_schema']['schema']['properties']['source_checks']['items']['anyOf'][1]['properties']['status']['enum'].append('TAUGHT')
    assert not is_atomic_audit_format(tampered)
    old = atomic_audit_format(packet, course, typed_findings=True)
    assert old == atomic_audit_format(packet, course, typed_findings=True, strict_owners=False)
    assert atomic_audit_messages(packet, course, typed_findings=True) == atomic_audit_messages(
        packet, course, typed_findings=True, strict_owners=False)
    with pytest.raises(ValueError):
        atomic_audit_format(packet, course, strict_owners=True)


def test_new_aliased_schema_fits_shipped_runner_with_1000_sources():
    text = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(1000))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(text.encode()).hexdigest(), (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    question = {'id': 'q1', 'prompt': 'Question?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
                'explanation': 'Explanation.', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text.', 'questions': [question]}]}
    fmt = PracticalModelView(packet).schema(atomic_audit_format(packet, course, typed_findings=True, strict_owners=True))
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('atomic_owner_shipped_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert response_contract(fmt) == 'practical_source_audit'
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
