import copy
import json
from dataclasses import replace

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_editor import SimpleCourseResult
from app.modules.ai.v3.simple_editor_findings import compile_finding_dispositions
from app.modules.ai.v3.simple_finding_evidence import apply_evidence, evidence_request, validate_evidence
from tests.unit.test_simple_editor_findings import case as finding_fixture


@pytest.fixture
def example():
    packet, original, items, decision = finding_fixture.__wrapped__()
    packet.fingerprint = 'a' * 64
    for item in items:
        item['source_fingerprint'] = packet.fingerprint
    decision['source_quote'] = 'Stitched nonexistent source quote'
    rows = compile_finding_dispositions(items, [decision], packet, original, original)
    receipt = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
        'review_finding_dispositions': rows, 'unapplied_review_findings': [
            {**rows[0], 'id': 'simple-v9-unapplied-' + rows[0]['id']}],
        'unverified_source_questions': [{'id': 'genuine-source-hold'}]}
    base = SimpleCourseResult(original, copy.deepcopy(original), {}, [], [],
        {'revision_receipt': receipt}, [])
    messages, fmt, context = evidence_request(packet, base)
    proposal = {key: context[key] for key in ('source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')}
    proposal['bindings'] = {rows[0]['id']: 'SRC1'}
    return packet, base, messages, fmt, context, proposal


def test_metadata_repair_never_changes_course_or_approves_semantics(example):
    packet, base, _, _, context, proposal = example
    result = apply_evidence(packet, base, context, proposal)
    assert result.course == base.course and result.draft == base.draft
    receipt = result.review['revision_receipt']
    row = receipt['review_finding_dispositions'][0]
    assert row['model_resolved'] and row['source_quote_match'] == 'literal'
    assert row['status'] == 'UNVERIFIED' and not row['semantic_approval']
    assert receipt['unapplied_review_findings'] == []
    assert receipt['unverified_source_questions'] == [{'id': 'genuine-source-hold'}]
    assert result.review['source_evidence_repair']['original_revision_receipt'] == base.review['revision_receipt']
    validate_evidence(packet, result)


@pytest.mark.parametrize('fault', ['source', 'draft', 'result', 'inventory', 'foreign', 'missing', 'extra_content'])
def test_stale_foreign_or_content_edit_payload_rejected(example, fault):
    packet, base, _, _, context, proposal = example
    proposal = copy.deepcopy(proposal)
    if fault in ('source', 'draft', 'result', 'inventory'):
        proposal[fault + '_fingerprint'] = 'b' * 64
    elif fault == 'foreign':
        proposal['bindings'][next(iter(proposal['bindings']))] = 'OTHER'
    elif fault == 'missing':
        proposal['bindings'] = {}
    else:
        proposal['body_edits'] = []
    with pytest.raises(ValueError):
        apply_evidence(packet, base, context, proposal)


def test_unresolved_preserves_every_existing_issue(example):
    packet, base, _, _, context, proposal = example
    proposal['bindings'] = {key: 'UNRESOLVED' for key in proposal['bindings']}
    result = apply_evidence(packet, base, context, proposal)
    assert result.review['revision_receipt'] == base.review['revision_receipt']
    validate_evidence(packet, result)


def test_metadata_repair_cannot_close_missing_actual_final_evidence(example):
    packet, base, *_ = example
    bad = replace(base, course=copy.deepcopy(base.course))
    bad.course['lessons'][0]['content'] = 'Different text without claimed evidence'
    with pytest.raises(ValueError, match='simple_evidence_not_eligible'):
        evidence_request(packet, bad)


def test_forged_resolution_or_source_quote_fails_materialization_validation(example):
    packet, base, _, _, context, proposal = example
    result = apply_evidence(packet, base, context, proposal)
    result.review['revision_receipt']['review_finding_dispositions'][0]['decision']['final_quote'] = 'fabricated'
    with pytest.raises(ValueError, match='simple_evidence_receipt_stale'):
        validate_evidence(packet, result)


def test_owned_source_change_under_stale_fingerprint_fails(example):
    packet, base, _, _, context, proposal = example
    result = apply_evidence(packet, base, context, proposal)
    packet.blocks[0].text = 'Changed source with stale fingerprint'
    with pytest.raises(ValueError, match='simple_evidence_receipt_stale'):
        validate_evidence(packet, result)


def test_later_editor_removing_final_evidence_reopens_only_that_finding(example):
    from app.modules.ai.v3.simple_course_editor_v10 import _revalidated_parent
    packet, base, _, _, context, proposal = example
    repaired = apply_evidence(packet, base, context, proposal)
    course = copy.deepcopy(repaired.course)
    course['lessons'][0]['content'] = 'New text without the previous final evidence'
    review = _revalidated_parent(repaired, course, packet)
    review['postedit_card_review'] = {'before_lesson_bodies': {
        base.course['lessons'][0]['id']: base.course['lessons'][0]['content']}, 'before_questions': {}}
    changed = replace(repaired, course=course, review=review)
    row = changed.review['revision_receipt']['review_finding_dispositions'][0]
    assert not row['model_resolved']
    assert changed.review['revision_receipt']['unapplied_review_findings']
    validate_evidence(packet, changed)
    row['model_resolved'] = True
    with pytest.raises(ValueError, match='simple_evidence_receipt_stale'):
        validate_evidence(packet, changed)


def test_unrelated_pending_entry_is_not_removed(example):
    packet, base, *_ = example
    base.review['revision_receipt']['unapplied_review_findings'].append({'id': 'unrelated', 'finding': {'problem': 'Peer'}})
    _, _, context = evidence_request(packet, base)
    proposal = {key: context[key] for key in ('source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')}
    proposal['bindings'] = {key: 'SRC1' for key in context['bindings']}
    result = apply_evidence(packet, base, context, proposal)
    assert result.review['revision_receipt']['unapplied_review_findings'] == [{'id': 'unrelated', 'finding': {'problem': 'Peer'}}]
    validate_evidence(packet, result)


def test_multiple_evidence_bindings_survive_jsonb_custody_without_schema_change():
    from app.modules.ai.v3.practical_author_transport import (
        author_custody,
        normalize_practical_author,
        validate_author_custody,
    )
    from app.modules.ai.v3.simple_finding_evidence import evidence_format, is_evidence_format
    from tests.unit.qa_journal_test_support import jsonb_roundtrip
    fingerprints = {key: 'a' * 64 for key in (
        'source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')}
    fmt = evidence_format(fingerprints, {'finding-z': ['SRC2', 'SRC1'], 'finding-a': ['SRC1']})
    original = copy.deepcopy(fmt)
    value = {**fingerprints, 'bindings': {'finding-z': 'SRC2', 'finding-a': 'UNRESOLVED'}}
    artifact = normalize_practical_author(json.dumps(value), fmt)
    custody = author_custody(artifact, fmt)
    restored = jsonb_roundtrip(custody)
    assert list(restored['format']['json_schema']['schema']['properties']['bindings']['properties']) == ['finding-a', 'finding-z']
    assert is_evidence_format(restored['format'])
    assert validate_author_custody(restored, value, fmt)
    assert fmt == original


@pytest.mark.parametrize('required', [None, [], ['finding-z'], ['finding-z', 'finding-z'],
                                      ['finding-z', 'foreign'], 'finding-z'])
def test_binding_required_array_must_own_each_property_exactly_once(required):
    from app.modules.ai.v3.simple_finding_evidence import evidence_format, is_evidence_format
    fmt = evidence_format({key: 'a' * 64 for key in (
        'source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')},
        {'finding-z': ['SRC1'], 'finding-a': ['SRC2']})
    fmt['json_schema']['schema']['properties']['bindings']['required'] = required
    assert not is_evidence_format(fmt)


@pytest.mark.parametrize('value', [None, 'not allowed'])
def test_real_normalizer_retains_null_custody_and_rejects_unknown_nonnull(example, value):
    import json

    from app.modules.ai.v3.practical_author_transport import normalize_practical_author
    packet, _, _, fmt, _, proposal = example
    proposal['unexpected'] = value
    if value is None:
        artifact = normalize_practical_author(json.dumps(proposal), fmt)
        assert 'unexpected' not in artifact.normalized_value
        assert '/unexpected' in artifact.receipt.removed_paths
        assert artifact.normalized_value['source_fingerprint'] == packet.fingerprint
    else:
        with pytest.raises(ValueError):
            normalize_practical_author(json.dumps(proposal), fmt)
