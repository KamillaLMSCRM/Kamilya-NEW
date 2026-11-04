import copy
import hashlib
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.source_fidelity import ConversionFidelity
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_service import practical_artifacts

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def build_result(course, packet, scopes=('assessment',), *, v26=True, source_uncertain=False,
                 narrative=None, unresolved=()):
    feedback = tuple({'scope': scope, 'id': 'l1', 'evidence': {}} for scope in scopes)
    decision = PracticalReviewDecision(not feedback, source_uncertain, (), (), False, feedback)
    return PracticalCycleResult(course, {'narrative_sources': narrative or {'l1': [b.block_id for b in packet.blocks]},
        'source_notes': []}, decision, (), 'complete', standalone_review=True, claim_evidence=v26,
        materiality_review=True, unresolved_question_context=unresolved)


def lesson_status(artifacts):
    return artifacts.content.modules[0].lessons[0].source_validation_status


def test_assessment_only_keeps_quiz_review_and_separates_source(case):
    corpus, packet, course = case
    result = build_result(course, packet)
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['quality_verdict'] == 'needs_review'
    assert artifacts.diagnostics['automated_review_passed'] is False
    assert artifacts.diagnostics['requires_source_review'] is False
    assert artifacts.diagnostics['requires_assessment_review'] is True
    assert 'assessment:l1' in artifacts.diagnostics['violations']
    assert lesson_status(artifacts) == 'verified'
    assert artifacts.assessment.assessments[0].mcq


@pytest.mark.parametrize('other', ['source', 'lesson', 'question', 'coverage'])
def test_mixed_findings_remain_source_held(case, other):
    corpus, packet, course = case
    artifacts = practical_artifacts(build_result(course, packet, ('assessment', other)), corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['requires_source_review'] is True
    assert lesson_status(artifacts) == 'needs_review'
    assert not artifacts.diagnostics.get('requires_assessment_review', False)


def test_accepted_and_legacy_assessment_behavior(case):
    corpus, packet, course = case
    accepted = practical_artifacts(build_result(course, packet, ()), corpus, packet, 'a' * 64)
    assert accepted.diagnostics['quality_verdict'] == 'verified'
    assert not accepted.diagnostics['requires_source_review']
    legacy = practical_artifacts(build_result(course, packet, v26=False), corpus, packet, 'a' * 64)
    assert legacy.diagnostics['requires_source_review'] and lesson_status(legacy) == 'needs_review'
    assert 'requires_assessment_review' not in legacy.diagnostics


def test_wrapped_or_inconsistent_findings_cannot_be_approved(case):
    corpus, packet, course = case
    result = build_result(course, packet)
    result.decision.feedback[0]['evidence']['original_finding'] = {'scope': 'source'}
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['requires_source_review']
    clean = build_result(course, packet)
    inconsistent = replace(clean, decision=replace(clean.decision, accepted=True))
    artifacts = practical_artifacts(inconsistent, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['quality_verdict'] == 'needs_review'
    assert artifacts.diagnostics['automated_review_passed'] is False


@pytest.mark.parametrize('kind', ['conversion', 'uncertain', 'context', 'missing_prose', 'unresolved_reference'])
def test_independent_source_holds_are_never_cleared(case, kind):
    corpus, packet, course = case
    kwargs = {}
    if kind == 'conversion':
        corpus = replace(corpus, documents=(replace(corpus.documents[0], conversion_fidelity=ConversionFidelity.unverified()),))
    elif kind == 'uncertain':
        kwargs['source_uncertain'] = True
    elif kind == 'context':
        kwargs['unresolved'] = ('q1',)
    elif kind == 'missing_prose':
        kwargs['narrative'] = {'l1': []}
    else:
        kwargs['narrative'] = {'l1': ['not-a-valid-rule']}
    artifacts = practical_artifacts(build_result(course, packet, **kwargs), corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['requires_source_review']
    assert lesson_status(artifacts) == 'needs_review'


def test_cross_document_question_stays_source_held(case):
    corpus, _, course = case
    text = 'Another source.'
    doc = DirectSourceDocument('doc2', 'Other', 'other.txt', 'general',
        'document:' + hashlib.sha256(text.encode()).hexdigest(), (),
        conversion_fidelity=corpus.documents[0].conversion_fidelity, source_text=text)
    corpus = DirectSourceCorpus(corpus.tenant_id, (*corpus.documents, doc), corpus.total_chars + len(text), 0)
    packet = build_practical_source_packet(corpus)
    course = copy.deepcopy(course)
    course['lessons'][0]['questions'][0]['source_refs'].append(packet.blocks[-1].block_id)
    result = build_result(course, packet, narrative={'l1': [packet.blocks[0].block_id]})
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['requires_source_review']
    assert artifacts.diagnostics['practical_cross_document_question_ids'] == ['q1']


def test_fresh_domain_question_hold_keeps_assessment_review_without_false_source_hold(case):
    from app.modules.ai.v3.practical_review import REVIEW_HOLD_KEY
    from app.modules.ai.v3.revision_policy import DOMAIN_PRACTICAL_REVIEW_POLICY

    corpus, packet, course = case
    result = replace(build_result(course, packet, ('question',)), review_domains=True)
    result.decision.feedback[0][REVIEW_HOLD_KEY] = True
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['v3_review_policy'] == DOMAIN_PRACTICAL_REVIEW_POLICY
    assert artifacts.diagnostics['automated_review_passed'] is False
    assert artifacts.diagnostics['quality_verdict'] == 'needs_review'
    assert artifacts.diagnostics['requires_source_review'] is False
    assert artifacts.diagnostics['requires_assessment_review'] is True
    assert lesson_status(artifacts) == 'verified'
    assert artifacts.diagnostics['practical_course'] == course


def test_fresh_question_domain_does_not_clear_real_source_uncertainty(case):
    corpus, packet, course = case
    result = replace(build_result(course, packet, ('question',), source_uncertain=True), review_domains=True)
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['requires_source_review'] is True
    assert lesson_status(artifacts) == 'needs_review'
