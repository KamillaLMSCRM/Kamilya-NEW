import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_address_repair import (
    address_repair_format,
    apply_address_repair,
    is_address_repair_format,
    matches_address_repair_shape,
)
from app.modules.ai.v3.simple_course_block_editor import body_blocks
from tests.unit.test_simple_course_block_editor import setup_block


def sample():
    packet, original, proposal = setup_block()
    proposal['body_edits'] = [{'block_id': 'BODY1', 'after': 'First incompatible edit.'},
                              {'block_id': 'BODY1', 'after': 'Second incompatible edit.'}]
    ids = [packet.blocks[0].block_id]
    source, draft, fingerprint = packet.fingerprint, _digest(original), _digest(proposal)
    fmt = address_repair_format(source, draft, fingerprint, 2, [b['id'] for b in body_blocks(original)])
    value = {'source_fingerprint': source, 'draft_fingerprint': draft, 'proposal_fingerprint': fingerprint,
             'assignments': [{'edit_id': 'EDIT1', 'block_id': 'BODY1'},
                             {'edit_id': 'EDIT2', 'block_id': 'BODY2'}]}
    return original, proposal, ids, source, draft, fmt, value


def test_repair_only_changes_addresses_and_preserves_inputs():
    original, proposal, ids, source, draft, fmt, value = sample()
    before = copy.deepcopy((original, proposal, value, fmt))
    assert is_address_repair_format(fmt) and matches_address_repair_shape(value, fmt)
    repaired, receipt = apply_address_repair(value, proposal, original, ids, source, draft)
    expected = copy.deepcopy(proposal)
    expected['body_edits'][1]['block_id'] = 'BODY2'
    assert repaired == expected
    assert (original, proposal, value, fmt) == before
    assert receipt['semantic_text_preserved'] is True
    assert receipt['proposal_fingerprint'] == _digest(proposal) and receipt['repaired_fingerprint'] == _digest(repaired)
    assert receipt['assignments'][1] == {'edit_id': 'EDIT2', 'proposed_block_id': 'BODY1', 'resolved_block_id': 'BODY2'}


@pytest.mark.parametrize('fault,code', [('unresolved', 'unresolved'), ('missing', 'assignments_invalid'),
    ('duplicate_edit', 'assignments_invalid'), ('duplicate_target', 'duplicate_target'),
    ('foreign_edit', 'response_invalid'), ('foreign_block', 'response_invalid'),
    ('stale_source', 'response_invalid'), ('stale_draft', 'response_invalid'),
    ('stale_proposal', 'response_invalid'), ('extra', 'response_invalid'), ('null', 'response_invalid')])
def test_invalid_assignments_fail_closed(fault, code):
    original, proposal, ids, source, draft, fmt, value = sample()
    if fault == 'unresolved':
        value['assignments'][0]['block_id'] = 'UNRESOLVED'
    elif fault == 'missing':
        value['assignments'].pop()
    elif fault == 'duplicate_edit':
        value['assignments'][1]['edit_id'] = 'EDIT1'
    elif fault == 'duplicate_target':
        value['assignments'][1]['block_id'] = 'BODY1'
    elif fault == 'foreign_edit':
        value['assignments'][0]['edit_id'] = 'EDIT9'
    elif fault == 'foreign_block':
        value['assignments'][0]['block_id'] = 'BODY9'
    elif fault.startswith('stale_'):
        value[fault.replace('stale_', '') + '_fingerprint'] = '0' * 64
    elif fault == 'extra':
        value['assignments'][0]['after'] = 'injected'
    else:
        value['assignments'] = None
    if fault in ('missing', 'duplicate_edit', 'duplicate_target', 'unresolved'):
        assert matches_address_repair_shape(value, fmt)
    before = copy.deepcopy((original, proposal, value))
    with pytest.raises(ValueError, match='simple_address_repair_' + code):
        apply_address_repair(value, proposal, original, ids, source, draft)
    assert (original, proposal, value) == before


def test_stale_original_and_invalid_proposal_rejected():
    original, proposal, ids, source, draft, fmt, value = sample()
    changed = copy.deepcopy(original)
    changed['lessons'][0]['content'] += ' stale'
    with pytest.raises(ValueError, match='draft_stale'):
        apply_address_repair(value, proposal, changed, ids, source, draft)
    proposal['body_edits'][0]['after'] = None
    with pytest.raises(ValueError, match='proposal_invalid'):
        apply_address_repair(value, proposal, original, ids, source, draft)


def test_format_rejects_extra_and_altered_identity():
    *_, fmt, value = sample()
    for bad in (None, {}, {**fmt, 'extra': True}):
        assert not is_address_repair_format(bad)
        assert not matches_address_repair_shape(value, bad)
