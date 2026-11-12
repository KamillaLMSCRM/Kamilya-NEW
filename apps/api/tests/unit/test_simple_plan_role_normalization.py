"""Redundant owned support is metadata, never a source or teaching decision."""
import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_plan_formatting import canonicalize_plan_support
from app.modules.ai.v3.simple_semantic_source_plan import (
    compile_semantic_plan,
    matches_semantic_plan,
    matches_semantic_plan_structure,
    semantic_plan_format,
)
from tests.unit.test_simple_plan_accounting import fixture


def overlapping_plan():
    corpus, packet, value, ids = fixture()
    value['units'][0]['primary_slices'] = ids
    value['units'][0]['supporting_slices'] = ids[:1]
    return corpus, packet, value, ids


def test_primary_dominates_only_redundant_support_with_immutable_raw_receipt():
    corpus, packet, value, ids = overlapping_plan()
    original = copy.deepcopy(value)
    fmt = semantic_plan_format(packet, corpus)
    assert matches_semantic_plan_structure(value, fmt)
    assert not matches_semantic_plan(value, fmt)
    with pytest.raises(ValueError):
        compile_semantic_plan(value, packet, corpus)
    canonical, receipt = canonicalize_plan_support(value, packet, corpus)
    assert value == original
    assert canonical['units'][0]['primary_slices'] == ids
    assert canonical['units'][0]['supporting_slices'] == []
    assert compile_semantic_plan(canonical, packet, corpus) == canonical
    assert receipt['original_plan'] == original
    assert receipt['model_plan_fingerprint'] == _digest(original)
    assert receipt['normalized_plan_fingerprint'] == _digest(canonical)
    assert receipt['semantic_approval'] is False
    assert canonicalize_plan_support(canonical, packet, corpus) == (canonical, None)


@pytest.mark.parametrize('fault', [
    'source', 'catalog', 'foreign', 'primary_duplicate', 'support_duplicate',
    'unit_duplicate', 'excluded_primary',
])
def test_role_normalization_cannot_hide_owned_plan_faults(fault):
    corpus, packet, value, ids = overlapping_plan()
    if fault == 'source':
        value['source_fingerprint'] = '0' * 64
    elif fault == 'catalog':
        value['slices_fingerprint'] = '0' * 64
    elif fault == 'foreign':
        value['units'][0]['supporting_slices'].append('S999999')
    elif fault == 'primary_duplicate':
        value['units'][0]['primary_slices'].append(ids[0])
    elif fault == 'support_duplicate':
        value['units'][0]['supporting_slices'].append(ids[0])
    elif fault == 'unit_duplicate':
        value['units'].append(copy.deepcopy(value['units'][0]))
    else:
        value['non_teaching'] = [{'slice_ids': ids[:1], 'reason': 'Conflicting exclusion.'}]
    with pytest.raises(ValueError):
        canonicalize_plan_support(value, packet, corpus)


def test_missing_meaningful_slice_still_requires_accounting_after_role_normalization():
    corpus, packet, value, ids = overlapping_plan()
    value['units'][0]['primary_slices'] = ids[:-1]
    canonical, receipt = canonicalize_plan_support(value, packet, corpus)
    assert receipt is not None and ids[-1] not in canonical['units'][0]['primary_slices']
    assert matches_semantic_plan_structure(canonical, semantic_plan_format(packet, corpus))
    with pytest.raises(ValueError):
        compile_semantic_plan(canonical, packet, corpus)
