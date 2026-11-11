import copy
import hashlib
import json
from dataclasses import replace

import pytest

from app.modules.ai.assessment_schema import mcq_options_for_persistence
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.source_fidelity import ConversionFidelity
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_contract import PracticalSourceBlock, build_practical_source_packet
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from app.modules.ai.v3.simple_course_editor import SimpleCourseResult, _review_format
from app.modules.ai.v3.simple_course_service import _question_quote, simple_course_artifacts, simple_stage_allowed
from app.modules.ai.v3.stage_checkpoint import stage_once
from app.modules.courses.draft_review import read_draft_review
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from tests.unit.test_pending_stage_journal import journal
from tests.unit.test_v3_simple_course_editor import course, fixture


def corpus_fixture():
    corpus, _ = fixture()
    doc = corpus.documents[0]
    revision = 'document:' + 'c' * 64
    approved = replace(doc.editorial_document, source_revision=revision)
    fidelity = ConversionFidelity.from_metadata({'engine': 'python-docx', 'fallback_used': False, 'warnings': []})
    return replace(corpus, documents=(replace(doc, source_revision=revision, editorial_document=approved,
        conversion_fidelity=fidelity),))


def test_long_lesson_provenance_is_not_limited_by_a_separate_correction_tool():
    corpus = corpus_fixture()
    doc = corpus.documents[0]
    text = 'Instruction ' * 3000
    working, spans = render_text(text, [])
    approved = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approved-long', text, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approved),))
    packet = build_practical_source_packet(corpus)
    refs = [b.block_id for b in packet.blocks]
    raw = course(ref=refs[0])
    result = SimpleCourseResult(copy.deepcopy(raw), raw, {}, [], [], {'proposals': []},
        [{'lesson_id': 'lesson', 'source_refs': refs}])
    artifacts = simple_course_artifacts(result, corpus, packet, 'd' * 64)
    pinned = artifacts.content.modules[0].lessons[0].source_references
    assert sum(p['end'] - p['start'] for p in pinned) > 24_000
    assert all(p['span_sha256'] == hashlib.sha256(text[p['start']:p['end']].encode()).hexdigest() for p in pinned)


def test_sparse_question_references_do_not_invent_one_continuous_quote():
    corpus = corpus_fixture()
    doc = corpus.documents[0]
    text = 'First selected. Unselected rule. Last selected.'
    corpus = replace(corpus, documents=(replace(doc, source_text=text),))

    def block(start, end):
        quote = text[start:end]
        return PracticalSourceBlock(str(start), doc.doc_id, doc.source_revision, start, end, quote,
            hashlib.sha256(quote.encode()).hexdigest())

    first, last = block(0, 15), block(32, len(text))
    assert _question_quote([first, last], corpus) == ''
    assert _question_quote([first], corpus) == text[:15]


def test_unverified_reviewer_question_reaches_draft_without_becoming_source_ambiguity():
    from app.modules.ai.v3.simple_course_editor import _digest

    corpus = corpus_fixture()
    packet = build_practical_source_packet(corpus)
    ref = packet.blocks[0].block_id
    raw = course(ref=ref)
    receipt = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(raw),
               'unverified_source_questions': [{'id': 'reviewer-question', 'question': 'Unresolved observation',
                                                'source_refs': [ref], 'status': 'UNVERIFIED'}]}
    result = SimpleCourseResult(copy.deepcopy(raw), raw, {}, [], [],
        {'proposals': [], 'revision_receipt': receipt}, [{'lesson_id': 'lesson', 'source_refs': [ref]}])
    artifacts = simple_course_artifacts(result, corpus, packet, 'd' * 64)
    review = read_draft_review({'generation_engine': 'evidence_v3', 'evidence_v3': artifacts.diagnostics})
    assert review['source_clarification_required'] is False
    assert artifacts.diagnostics['requires_source_review'] is False
    issue = next(row for row in review['issues'] if row['id'] == 'reviewer-question')
    assert issue['message'] == 'Unresolved observation' and issue['blocking'] is True
    result.review['revision_receipt']['draft_fingerprint'] = 'e' * 64
    with pytest.raises(ValueError, match='simple_revision_receipt_stale'):
        simple_course_artifacts(result, corpus, packet, 'd' * 64)


@pytest.mark.parametrize('fault', [None, 'source', 'draft', 'question', 'ref'])
def test_independent_uncertainty_survives_editor_change_and_rejects_stale_or_foreign_evidence(fault):
    from app.modules.ai.v3.simple_course_editor import _digest

    corpus = corpus_fixture()
    packet = build_practical_source_packet(corpus)
    ref = packet.blocks[0].block_id
    draft = course(ref=ref)
    edited = copy.deepcopy(draft)
    edited['lessons'][0]['questions'][0]['prompt'] = 'Edited question does not resolve an unverified observation.'
    independent = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(draft),
        'unverified_observations': [{'question_id': 'question', 'status': 'UNVERIFIED',
            'problem': 'Independent review could not resolve the question.', 'source_refs': [ref]}]}
    if fault in {'source', 'draft'}:
        independent[fault + '_fingerprint'] = 'e' * 64
    elif fault == 'question':
        independent['unverified_observations'][0]['question_id'] = 'foreign-question'
    elif fault == 'ref':
        independent['unverified_observations'][0]['source_refs'] = ['foreign-ref']
    result = SimpleCourseResult(draft, edited, {}, [], [],
        {'proposals': [], 'independent_option_review': independent}, [{'lesson_id': 'lesson', 'source_refs': [ref]}])
    if fault:
        with pytest.raises(ValueError, match='simple_independent_'):
            simple_course_artifacts(result, corpus, packet, 'd' * 64)
        return
    artifacts = simple_course_artifacts(result, corpus, packet, 'd' * 64)
    review = read_draft_review({'generation_engine': 'evidence_v3', 'evidence_v3': artifacts.diagnostics})
    issue = next(row for row in review['issues'] if row['id'].startswith('simple-independent-'))
    assert issue['target_id'] == 'question' and issue['blocking'] is True
    assert review['source_clarification_required'] is False
    assert issue['evidence']['reviewed_draft_fingerprint'] == _digest(draft)
    assert issue['evidence']['current_question_fingerprint'] == _digest(edited['lessons'][0]['questions'][0])


def test_unapplied_course_finding_reaches_ordinary_draft_review():
    from app.modules.ai.v3.simple_course_editor import _digest

    corpus = corpus_fixture()
    packet = build_practical_source_packet(corpus)
    ref = packet.blocks[0].block_id
    raw = course(ref=ref)
    finding = {'domain': 'content', 'severity': 'material', 'target': {'kind': 'course', 'id': 'course'},
               'problem': 'Missing procedure', 'basis': 'Unverified comparison', 'correction': 'Locate the gap',
               'source_refs': [ref]}
    receipt = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(raw),
               'unapplied_review_findings': [{'id': 'unapplied', 'source_fingerprint': packet.fingerprint,
                   'draft_fingerprint': _digest(raw), 'status': 'UNVERIFIED', 'finding': finding}]}
    result = SimpleCourseResult(copy.deepcopy(raw), raw, {}, [], [],
        {'proposals': [], 'revision_receipt': receipt}, [{'lesson_id': 'lesson', 'source_refs': [ref]}])
    artifacts = simple_course_artifacts(result, corpus, packet, 'd' * 64)
    review = read_draft_review({'generation_engine': 'evidence_v3', 'evidence_v3': artifacts.diagnostics})
    issue = next(row for row in review['issues'] if row['id'] == 'unapplied')
    assert issue['message'] == 'Missing procedure\nLocate the gap' and issue['blocking'] is True
    assert not artifacts.diagnostics['requires_source_review']
    assert result.course == raw


def responses():
    calls = []

    async def invoke(messages, fmt):
        kind = fmt['json_schema']['name']
        calls.append(kind)
        payload = json.loads(messages[1]['content'])
        value = {'source_fingerprint': payload['source_fingerprint']}
        if kind == 'practical_course':
            return course()
        elif kind == 'simple_course_review_v1':
            value.update(draft_fingerprint=payload['draft_fingerprint'], proposals=[], source_questions=[])
        else:
            assert kind == 'simple_course_editor_v1'
            value.update(draft_fingerprint=payload['draft_fingerprint'], course=course(), source_questions=[],
                lesson_sources=[{'lesson_id': 'lesson', 'source_refs': ['SRC1']}])
            # The ordinary string-producing provider shares the strict null-only transport.
            value['extra'] = None
            return json.dumps(value)
        return value
    return calls, invoke


@pytest.mark.asyncio
async def test_normal_service_dispatch_preserves_course_keys_and_source_revision():
    corpus = corpus_fixture()
    calls, invoke = responses()
    artifacts = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=invoke,
        revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_POLICY)
    assert calls == ['practical_course', 'simple_course_review_v1', 'simple_course_editor_v1']
    lesson = artifacts.content.modules[0].lessons[0]
    assert lesson.source_references[0]['source_revision'] == corpus.documents[0].source_revision
    assert lesson.source_references[0]['source_text_sha256'] == corpus.documents[0].editorial_document.working_sha256
    assert artifacts.diagnostics['requires_source_review'] is False
    assert artifacts.diagnostics['requires_editorial_review'] is True
    assert artifacts.diagnostics['automated_review_passed'] is False
    analysis = {'generation_engine': 'evidence_v3', 'evidence_v3': artifacts.diagnostics}
    assert read_draft_review(analysis)['human_review_required'] is True
    question = artifacts.assessment.assessments[0].mcq[0]
    assert [o.is_correct for o in mcq_options_for_persistence(question, 2, analysis)] == [True, False, False]
    assert question.source_quote in corpus.documents[0].source_text


@pytest.mark.parametrize('fault', ['old_policy', 'wrong_stage', 'wrong_format', 'wrong_source', 'missing_validator'])
def test_stage_guard_refuses_cross_policy_and_forged_scope(fault):
    fmt = _review_format(['SRC1'], ['lesson'], 'a' * 64, 'b' * 64)
    options = dict(stage='review', group='practical:simple:review:v1:' + 'a' * 64 + ':output=32768',
        fmt=fmt, policy=SIMPLE_COURSE_REVIEW_POLICY, validator=lambda value: value)
    assert simple_stage_allowed(**options)
    if fault == 'old_policy':
        options['policy'] = 'v3-practical-source-review-v36'
    elif fault == 'wrong_stage':
        options['stage'] = 'lesson'
    elif fault == 'wrong_format':
        options['fmt'] = {'type': 'json_object'}
    elif fault == 'wrong_source':
        options['group'] = options['group'].replace('a' * 64, 'b' * 64)
    else:
        options['validator'] = None
    assert not simple_stage_allowed(**options)


@pytest.mark.asyncio
async def test_pending_completed_stage_replays_but_unknown_never_calls_twice():
    active, fake = journal()
    active.review_policy_bound = True
    active.expected_review_policy = SIMPLE_COURSE_REVIEW_POLICY
    verified = []

    async def verify(*_args):
        verified.append(1)
        return True

    active.verify_source = verify
    fmt = _review_format(['SRC1'], ['lesson'], 'a' * 64, 'b' * 64)
    value = {'source_fingerprint': 'a' * 64, 'draft_fingerprint': 'b' * 64, 'proposals': [], 'source_questions': []}
    calls = []

    async def invoke():
        calls.append(1)
        return copy.deepcopy(value)

    args = dict(journal=active, stage='review', group_id='practical:simple:review:v1:' + 'a' * 64 + ':output=32768',
        source_sha256='a' * 64, route_fingerprint='b' * 64, response_format=fmt,
        messages=[{'role': 'user', 'content': 'source'}], invoke=invoke, response_validator=lambda raw: raw)
    assert await stage_once(**args) == value
    assert await stage_once(**args) == value
    assert len(calls) == 1 and verified
    args['messages'] = [{'role': 'user', 'content': 'changed owned input'}]

    async def timeout():
        calls.append(1)
        raise TimeoutError()

    args['invoke'] = timeout
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    assert len(calls) == 2
