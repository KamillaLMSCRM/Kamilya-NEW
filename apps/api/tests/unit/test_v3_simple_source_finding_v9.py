"""Unverified diagnostic source observations survive ordinary draft materialization."""
import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V8_POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.simple_course_editor import SimpleCourseResult
from app.modules.ai.v3.simple_course_service import simple_course_artifacts
from tests.unit.test_v3_simple_owned_transport_v3 import unit_course
from tests.unit.test_v3_simple_service import corpus_fixture


@pytest.mark.parametrize('pending', [False, True])
def test_v9_materialization_keeps_unverified_source_issue_and_hold(pending):
    corpus = corpus_fixture()
    packet = build_practical_source_packet(corpus)
    ref = next(block.block_id for block in packet.blocks if block.text.strip())
    course = unit_course(ref, 'Practical lesson body.')
    assert not any(doc.conversion_fidelity.needs_review or doc.review_only_source_unresolved
                   or doc.review_only_source_context for doc in corpus.documents)
    row = {'id': 'simple-v9-source-test', 'status': 'UNVERIFIED', 'question': 'Unresolved source observation',
           'problem': 'Unresolved source observation', 'basis': 'Original source passage', 'source_refs': [ref],
           'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(course)}
    receipt = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(course),
               'unverified_source_questions': [row] if pending else []}
    result = SimpleCourseResult(course, copy.deepcopy(course), {}, [], [],
        {'proposals': [], 'revision_receipt': receipt}, [{'lesson_id': 'lesson', 'source_refs': [ref]}])
    artifact = simple_course_artifacts(result, corpus, packet, 'a' * 64, review_policy=SIMPLE_COURSE_REVIEW_V9_POLICY)
    review = artifact.diagnostics['draft_review']
    assert artifact.diagnostics['requires_source_review'] is pending
    assert review['source_clarification_required'] is pending
    matching = [issue for issue in review['issues'] if issue['id'] == row['id']]
    assert len(matching) == int(pending)
    if pending:
        assert matching[0]['kind'] == 'editorial_review' and matching[0]['blocking'] is True
        assert matching[0]['message'] == row['question']
        assert matching[0]['evidence'] == {'unverified': True, 'source_fingerprint': packet.fingerprint,
                                          'reviewed_draft_fingerprint': _digest(course)}
        assert all(lesson.source_validation_status == 'needs_review' for module in artifact.content.modules
                   for lesson in module.lessons)
    # Existing policy meaning is unchanged; the new diagnostic hold belongs to V9.
    old = simple_course_artifacts(result, corpus, packet, 'a' * 64, review_policy=SIMPLE_COURSE_REVIEW_V8_POLICY)
    assert old.diagnostics['requires_source_review'] is False
    receipt['draft_fingerprint'] = '0' * 64
    with pytest.raises(ValueError, match='receipt_stale'):
        simple_course_artifacts(result, corpus, packet, 'a' * 64, review_policy=SIMPLE_COURSE_REVIEW_V9_POLICY)


@pytest.mark.parametrize('resolved', [False, True])
def test_v9_editor_dispositions_remain_visible_and_bound_to_final_course(resolved):
    from app.modules.ai.v3.simple_editor_findings import compile_finding_dispositions, inventory

    corpus = corpus_fixture()
    packet = build_practical_source_packet(corpus)
    block = next(block for block in packet.blocks if block.text.strip())
    original = unit_course(block.block_id, 'Original teaching.')
    final = copy.deepcopy(original)
    final['lessons'][0]['content'] = 'Updated teaching.'
    finding = {'domain': 'content', 'severity': 'material', 'target': {'kind': 'lesson', 'id': 'lesson'},
               'problem': 'Missing operative rule', 'basis': 'Source comparison', 'correction': 'Explain the rule',
               'source_refs': [block.block_id]}
    items = inventory(packet.fingerprint, _digest(original), [('global', {'findings': [finding]})])
    decisions = [{'finding_id': items[0]['id'], 'status': 'CORRECTED', 'reason': 'The rule is now explained.',
                  'source_refs': [block.block_id], 'source_quote': block.text,
                  'target': {'kind': 'lesson_content', 'id': 'lesson', 'choice_index': 0},
                  'final_quote': 'Updated teaching.'}] if resolved else []
    rows = compile_finding_dispositions(items, decisions, packet, original, final)
    receipt = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
               'review_finding_dispositions': rows, 'unapplied_review_findings': [] if resolved else rows}
    result = SimpleCourseResult(original, final, {}, [], [], {'proposals': [], 'revision_receipt': receipt},
                                [{'lesson_id': 'lesson', 'source_refs': [block.block_id]}])
    artifact = simple_course_artifacts(result, corpus, packet, 'a' * 64, review_policy=SIMPLE_COURSE_REVIEW_V9_POLICY)
    issue = next(row for row in artifact.diagnostics['draft_review']['observations' if resolved else 'issues']
                 if row['message'].startswith(finding['problem']))
    assert issue['blocking'] is not resolved and issue['evidence']['unverified'] is True
    if resolved:
        assert issue['evidence']['semantic_approval'] is False
        assert issue['evidence']['model_disposition'] == 'CORRECTED'
    # Neither a later course edit nor replay under a changed final snapshot can borrow this resolution.
    receipt['review_finding_dispositions'][0]['result_fingerprint'] = '0' * 64
    with pytest.raises(ValueError, match='finding_disposition_stale'):
        simple_course_artifacts(result, corpus, packet, 'a' * 64, review_policy=SIMPLE_COURSE_REVIEW_V9_POLICY)
