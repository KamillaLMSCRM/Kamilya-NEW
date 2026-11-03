"""Behavior of the ordinary entry point, scoped editing and crash recovery without a model."""

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.source_fidelity import ConversionFidelity
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_cycle import run_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_scope import scoped_course_view
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from app.modules.ai.v3.revision_policy import POLICY, PRACTICAL_REVIEW_POLICY, REVIEW_POLICY, stamp_policy
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_v3_partitioned_extraction import Journal


@pytest.fixture
def case():
    text = "The approver signs the ticket.\n\nThe approver also records the approval in the system."
    doc = DirectSourceDocument(
        "doc",
        "Title",
        "source.md",
        "general",
        "document:" + hashlib.sha256(text.encode()).hexdigest(),
        (),
        conversion_fidelity=ConversionFidelity.from_metadata({
            'engine': 'python-docx', 'fallback_used': False, 'warnings': []}),
        source_text=text,
    )
    corpus = DirectSourceCorpus("tenant-1", (doc,), len(text), 0)
    packet = build_practical_source_packet(corpus)
    refs = [b.block_id for b in packet.blocks]
    course = {
        "title": "Course",
        "lessons": [
            {
                "id": "l1",
                "title": "Approval",
                "content": text,
                "questions": [
                    {
                        "id": "q1",
                        "prompt": "What is the complete procedure?",
                        "choices": ["Sign and record", "Sign only", "Do neither"],
                        "correct_index": 0,
                        "explanation": "Both actions are required.",
                        "source_refs": refs,
                    },
                    {
                        "id": "q2",
                        "prompt": "Who records the approval?",
                        "choices": ["Approver", "Cashier", "Customer"],
                        "correct_index": 0,
                        "explanation": "The approver records it.",
                        "source_refs": [refs[-1]],
                    },
                ],
            }
        ],
    }
    return corpus, packet, course


def model_wire(packet, model, audit_calls=None):
    view = PracticalModelView(packet)
    async def invoke(*args):
        fmt = args[1] if len(args) == 2 else args[3]
        if response_contract(fmt) == 'practical_source_audit':
            if audit_calls is not None:
                audit_calls.append(args)
            lessons = fmt['json_schema']['schema']['properties']['narrative_sources']['properties']
            grouping = audit_units(packet)
            return view.encode({'source_fingerprint': packet.fingerprint, 'source_review': 'Sign and record.',
                'source_notes': [], 'findings': [],
                'source_units_fingerprint': grouping.fingerprint,
                'source_checks': [{'unit_id': key, 'source_refs': list(refs), 'status': 'TAUGHT',
                    'lesson_ids': list(lessons), 'reason': 'Both required actions taught.'}
                    for key, refs in grouping.groups],
                'narrative_sources': {lid: [b.block_id for b in packet.blocks] for lid in lessons}})
        value = await model(*args)
        if response_contract(fmt) == 'practical_patch':
            value = {**value, 'course_fingerprint': fmt['json_schema']['schema']['properties']['course_fingerprint']['enum'][0]}
        return view.encode(value)
    return invoke


def checked(packet, course, *, bad_question=False, previous=()):
    refs = [block.block_id for block in packet.blocks]
    result = {
        "source_fingerprint": packet.fingerprint,
        "source_review": "The approver must sign and record approval.",
        "source_notes": [],
        "question_rules": [{'question_id': q['id'], 'rules': [{'rule': 'Both applicable actions are required.',
             'source_refs': refs, 'supported_options': [q['correct_index']]}]}
             for lesson in course['lessons'] for q in lesson['questions']],
        "option_checks": [{'question_id': q['id'], 'options': [
            {'index': index, 'status': 'YES' if index == q['correct_index'] else 'NO',
             'possible_correct_case': {'exists': 'FOUND' if index == q['correct_index'] else 'NONE',
                 'explanation': 'The complete stated procedure.' if index == q['correct_index'] else 'Does not answer the question.',
                 'source_refs': refs if index == q['correct_index'] else []}}
            for index in range(len(q['choices']))]} for lesson in course['lessons'] for q in lesson['questions']],
        "answer_keys": {q["id"]: q["correct_index"] for lesson in course["lessons"] for q in lesson["questions"]},
        "narrative_sources": {lesson["id"]: refs for lesson in course["lessons"]},
        "findings": ([{"scope": "question", "target_id": "q1", "problem": "The question is ambiguous",
                      "source_refs": refs, "expected_rule": "Both steps required", "correction": "Ask for full procedure"}]
                     if bad_question else []),
    }
    if previous:
        result["issue_checks"] = {item["issue_id"]: {"status": "RESOLVED", "reason": "The checked issue was fixed"}
                                  for item in previous}
    return result


@pytest.mark.asyncio
async def test_coherent_course_and_source_audit_through_real_entry_adapter_and_replay(case):
    corpus, packet, course = case
    calls = []
    audit_calls = []

    async def model(messages, fmt):
        kind = response_contract(fmt)
        calls.append(kind)
        value = course if kind == "practical_course" else checked(packet, course)
        assert matches_response_contract(PracticalModelView(packet).encode(value), fmt)
        return copy.deepcopy(value)

    journal = Journal()
    args = dict(
        intent=CourseIntent(audience="Staff"),
        generation_client=model_wire(packet, model, audit_calls),
        revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY,
        extraction_journal=journal,
        route_fingerprint="b" * 64,
    )
    first = await generate_v3_course_from_corpus(corpus, **args)
    second = await generate_v3_course_from_corpus(corpus, **args)
    assert calls == ["practical_course", "practical_review"]
    assert len(audit_calls) == 1  # A distinct prose check, replayed without another provider request.
    assert first == second and first.diagnostics["automated_review_passed"] is True
    assert first.diagnostics["quality_verdict"] == "verified"
    assert first.diagnostics['requires_source_review'] is False
    content = first.content.modules[0].lessons[0]
    assert content.content == course["lessons"][0]["content"]
    source = corpus.documents[0].source_text
    for ref in content.source_references:
        assert ref["doc_id"] == "doc" and ref["source_revision"] == corpus.documents[0].source_revision
        assert ref["span_sha256"] == hashlib.sha256(source[ref["start"] : ref["end"]].encode()).hexdigest()
    questions = first.assessment.assessments[0].mcq
    assert len(questions[0].options) == 3
    assert questions[0].question == scoped_course_view(packet, course)['lessons'][0]['questions'][0]['prompt']
    assert questions[0].source_quote == source  # Contiguous span retains the intervening separator.
    assert sum(o.is_correct for o in questions[0].options) == 1
    assert next(o.text for o in questions[0].options if o.is_correct) == 'Sign and record'
    assert stamp_policy({})["v3_review_policy"] == REVIEW_POLICY  # Candidate does not alter fresh DEV admissions.


@pytest.mark.asyncio
async def test_accepted_content_preserves_context_only_source_hold(case):
    corpus, packet, course = case
    corpus = replace(corpus, documents=(replace(corpus.documents[0],
        review_only_source_context=({'note': 'A conversion candidate needs source confirmation.'},)),))

    async def model(messages, fmt):
        return copy.deepcopy(course if response_contract(fmt) == 'practical_course' else checked(packet, course))

    result = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(audience='Staff'),
        generation_client=model_wire(packet, model), revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY, route_fingerprint='b' * 64)
    assert result.diagnostics['automated_review_passed'] is True
    assert result.diagnostics['requires_source_review'] is True
    assert result.content.modules[0].lessons[0].source_validation_status == 'needs_review'


@pytest.mark.asyncio
@pytest.mark.parametrize('fidelity', [ConversionFidelity.unverified(), ConversionFidelity.from_metadata({
    'engine': 'python-docx', 'fallback_used': False, 'warnings': ['A table was not recovered.']})])
async def test_accepted_content_does_not_clear_unverified_or_degraded_conversion(case, fidelity):
    corpus, packet, course = case
    corpus = replace(corpus, documents=(replace(corpus.documents[0], conversion_fidelity=fidelity),))

    async def model(messages, fmt):
        return copy.deepcopy(course if response_contract(fmt) == 'practical_course' else checked(packet, course))

    result = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(audience='Staff'),
        generation_client=model_wire(packet, model), revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY, route_fingerprint='b' * 64)
    assert result.diagnostics['automated_review_passed'] is True
    assert result.diagnostics['requires_source_review'] is True
    assert result.content.modules[0].lessons[0].source_validation_status == 'needs_review'


@pytest.mark.asyncio
async def test_scoped_repair_rechecked_and_siblings_unchanged(case):
    _, packet, course = case
    calls = []
    revised = copy.deepcopy(course)
    revised["lessons"][0]["questions"][0]["prompt"] = "Which two actions together are required?"

    async def invoke(stage, group, messages, fmt, validate):
        calls.append(stage)
        if stage == "lesson":
            return copy.deepcopy(course)
        if stage == "repair":
            assert json.loads(messages[1]["content"].split('CHECKED_FINDINGS_JSON\n')[1])[0]['id'] == 'q1'
            return {
                "new_lessons": [],
                "new_questions": [],
                "question_updates": {"q1": copy.deepcopy(revised["lessons"][0]["questions"][0])},
            }
        return checked(packet, course if calls.count("review") == 1 else revised, bad_question=calls.count("review") == 1,
                       previous=json.loads(messages[1]['content'].split('PREVIOUS_FINDINGS_JSON\n')[1]))

    result = await run_practical_cycle(packet, {}, model_wire(packet, invoke))
    assert calls == ["lesson", "review", "repair", "review"]
    assert result.decision.accepted and len(result.history) == 2
    assert result.course == revised and course["lessons"][0]["questions"][1] == revised["lessons"][0]["questions"][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("source_uncertain", [True, False])
async def test_source_uncertainty_and_unchanged_repair_are_explicit_holds(case, source_uncertain):
    _, packet, course = case
    calls = []

    async def invoke(stage, group, messages, fmt, validate):
        calls.append(stage)
        if stage == "lesson":
            return copy.deepcopy(course)
        if stage == "repair":
            return {
                "new_lessons": [],
                "new_questions": [],
                "question_updates": {"q1": copy.deepcopy(course["lessons"][0]["questions"][0])},
            }
        review = checked(packet, course, bad_question=not source_uncertain)
        if source_uncertain:
            review['findings'] = [{'scope':'source', 'target_id':packet.blocks[0].block_id,
                                  'problem':'Conflicting duties', 'source_refs':[packet.blocks[0].block_id],
                                  'expected_rule':'Clear duty', 'correction':'Ask the source author'}]
        return review

    result = await run_practical_cycle(packet, {}, model_wire(packet, invoke))
    assert result.stop_reason == ("source_uncertain" if source_uncertain else "no_progress")
    assert not result.decision.accepted and result.course == course
    assert calls == (["lesson", "review"] if source_uncertain else ["lesson", "review", "repair"])


@pytest.mark.asyncio
async def test_unknown_review_is_not_reissued_on_service_resume(case):
    corpus, packet, course = case
    calls = []

    async def model(messages, fmt):
        kind = response_contract(fmt)
        calls.append(kind)
        if kind == 'practical_course':
            return copy.deepcopy(course)
        raise TimeoutError("unknown provider outcome")

    args = dict(
        intent=CourseIntent(),
        generation_client=model_wire(packet, model),
        revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY,
        extraction_journal=Journal(),
        route_fingerprint="b" * 64,
    )
    with pytest.raises(TimeoutError):
        await generate_v3_course_from_corpus(corpus, **args)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate_v3_course_from_corpus(corpus, **args)
    assert calls == ["practical_course", "practical_review"]


@pytest.mark.asyncio
async def test_changed_source_cannot_reuse_previous_author_or_review(case):
    corpus, packet, course = case
    calls = []

    async def model(messages, fmt):
        calls.append(response_contract(fmt))
        return copy.deepcopy(course) if calls[-1] == "practical_course" else checked(packet, course)

    args = dict(
        intent=CourseIntent(),
        generation_client=model_wire(packet, model),
        revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY,
        extraction_journal=Journal(),
        route_fingerprint="b" * 64,
    )
    await generate_v3_course_from_corpus(corpus, **args)
    old = corpus.documents[0]
    changed = DirectSourceDocument(
        old.doc_id,
        old.title,
        old.filename,
        old.category,
        "document:" + "c" * 64,
        (),
        source_text=old.source_text + "\nChanged obligation.",
    )
    with pytest.raises(ValueError, match="v3_stage_response_shape_invalid"):
        await generate_v3_course_from_corpus(
            DirectSourceCorpus("tenant-1", (changed,), len(changed.source_text), 0), **args
        )
    assert calls == ["practical_course", "practical_review", "practical_course", "practical_review"]


@pytest.mark.asyncio
async def test_wrong_journal_owner_is_rejected_before_model(case):
    corpus, _, _ = case
    calls = []

    async def model(messages, fmt):
        calls.append(1)

    journal = Journal()
    journal.tenant_id = "other-tenant"
    with pytest.raises(ValueError, match="practical_journal_owner_mismatch"):
        await generate_v3_course_from_corpus(
            corpus,
            intent=CourseIntent(),
            generation_client=model,
            revision_policy=POLICY,
            review_policy=PRACTICAL_REVIEW_POLICY,
            extraction_journal=journal,
            route_fingerprint="b" * 64,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_cross_document_quotes_remain_explicit_hold(case):
    corpus, _, original = case
    second = DirectSourceDocument(
        "doc2", "Other", "other.md", "general", "document:" + "d" * 64, (), source_text="The system is electronic."
    )
    corpus = DirectSourceCorpus(corpus.tenant_id, (*corpus.documents, second), corpus.total_chars + 25, 0)
    packet = build_practical_source_packet(corpus)
    course = copy.deepcopy(original)
    course['lessons'][0]['content'] += '\n' + second.source_text
    course["lessons"][0]["questions"][0]["source_refs"] = [b.block_id for b in packet.blocks]
    course["lessons"][0]["questions"][1]["source_refs"] = [packet.blocks[0].block_id]

    async def model(messages, fmt):
        return copy.deepcopy(course) if response_contract(fmt) == "practical_course" else checked(packet, course)

    result = await generate_v3_course_from_corpus(
        corpus,
        intent=CourseIntent(),
        generation_client=model_wire(packet, model),
        revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY,
    )
    assert not result.diagnostics["automated_review_passed"]
    assert not result.diagnostics["validation_report"]["automated_review_passed"]
    assert result.diagnostics["practical_cross_document_question_ids"] == ["q1"]
    assert result.assessment.assessments[0].mcq[0].source_quote == ""
    assert {ref["doc_id"] for ref in result.content.modules[0].lessons[0].source_references} == {"doc", "doc2"}


@pytest.mark.asyncio
async def test_failed_second_repair_keeps_latest_reviewed_course_not_initial(case):
    _, packet, original = case
    latest = copy.deepcopy(original)
    latest["lessons"][0]["questions"][0]["prompt"] = "A first improvement"
    repairs = 0

    async def invoke(stage, group, messages, fmt, validate):
        nonlocal repairs
        if stage == "lesson":
            return copy.deepcopy(original)
        if stage == "review":
            return checked(packet, original if not repairs else latest, bad_question=True,
                           previous=json.loads(messages[1]['content'].split('PREVIOUS_FINDINGS_JSON\n')[1]))
        repairs += 1
        q = (latest if repairs == 1 else original)["lessons"][0]["questions"][0]
        return {"new_lessons": [], "new_questions": [], "question_updates": {"q1": copy.deepcopy(q)}}

    result = await run_practical_cycle(packet, {}, model_wire(packet, invoke))
    assert result.stop_reason == "no_progress" and result.course == latest
    assert len(result.history) == 2 and not result.decision.accepted


@pytest.mark.asyncio
@pytest.mark.parametrize('claim_removed', [True, False])
async def test_source_uncertainty_allows_only_explicit_course_remediation_then_rechecks(case, claim_removed):
    _, packet, original = case
    original_source = packet.to_payload()
    course = copy.deepcopy(original)
    course['lessons'][0]['content'] += '\nAn unproved permission.'
    calls = []
    repaired = copy.deepcopy(course)
    repaired['lessons'][0]['content'] = original['lessons'][0]['content'] + '\nThe source leaves the other case unresolved.'

    async def invoke(stage, group, messages, fmt, validate):
        calls.append(stage)
        if stage == 'lesson':
            return copy.deepcopy(course)
        if stage == 'repair':
            return {'new_lessons': [], 'new_questions': [],
                'lesson_updates': {'l1': {'title': course['lessons'][0]['title'],
                    'replacements': [{'fragment_id': 'F2',
                    'new_text': original['lessons'][0]['content'].split('\n\n')[1]
                        + '\nThe source leaves the other case unresolved.'}]}}}
        previous = json.loads(messages[1]['content'].split('PREVIOUS_FINDINGS_JSON\n')[1])
        review = checked(packet, course if calls.count('review') == 1 else repaired, previous=previous)
        source_finding = {'scope': 'source', 'target_id': packet.blocks[0].block_id,
            'problem': 'The source does not establish the added permission',
            'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'No invented permission',
            'correction': 'Keep the original source unchanged'}
        if calls.count('review') == 1:
            review['findings'] = [source_finding, {**source_finding, 'scope': 'lesson', 'target_id': 'l1',
                                                  'correction': 'Remove only the unproved permission'}]
        else:
            review['source_notes'] = [{'note': 'Original source uncertainty remains visible',
                                       'source_refs': [packet.blocks[0].block_id]}]
            if not claim_removed:
                for item in previous:
                    if item['scope'] == 'source':
                        review['issue_checks'][item['issue_id']] = {'status': 'OPEN', 'reason': 'Still affects the claim'}
        return review

    result = await run_practical_cycle(packet, {}, model_wire(packet, invoke), max_revisions=1)
    assert calls == ['lesson', 'review', 'repair', 'review']
    assert packet.to_payload() == original_source
    assert result.course == repaired
    assert result.decision.accepted is claim_removed
    assert result.stop_reason == ('accepted' if claim_removed else 'source_uncertain')
    assert result.review['source_notes'] and len(result.history) == 2


@pytest.mark.asyncio
async def test_course_remediation_does_not_bypass_persisted_source_preflight_hold(case):
    corpus, _, _ = case
    held = replace(corpus.documents[0], review_only_source_unresolved=True)
    calls = []
    async def model(*args):
        calls.append(args)
        raise AssertionError('Held source cannot dispatch a model')
    with pytest.raises(ValueError, match='practical_source_review_required'):
        await generate_v3_course_from_corpus(replace(corpus, documents=(held,)), intent=CourseIntent(),
            generation_client=model, revision_policy=POLICY, review_policy=PRACTICAL_REVIEW_POLICY)
    assert not calls


@pytest.mark.asyncio
async def test_source_audit_can_block_a_combined_editor_false_pass_without_changing_keys(case):
    _, packet, original = case
    bad = copy.deepcopy(original)
    bad['lessons'][0]['content'] = 'The approver signs the ticket.'
    view = PracticalModelView(packet)
    repairs = 0
    events = []
    source_before = packet.to_payload()
    async def invoke(stage, group, messages, fmt, validate):
        nonlocal repairs
        kind = response_contract(fmt)
        events.append(kind)
        current = bad if not repairs else original
        if kind == 'practical_course':
            value = bad
        elif kind == 'practical_review':
            previous = json.loads(messages[1]['content'].split('PREVIOUS_FINDINGS_JSON\n')[1])
            value = checked(packet, current, previous=previous)  # Deliberately misses the prose omission.
        elif kind == 'practical_source_audit':
            value = {key: copy.deepcopy(checked(packet, current)[key]) for key in (
                'source_fingerprint', 'source_review', 'source_notes', 'findings', 'narrative_sources')}
            grouping = audit_units(packet)
            value['source_units_fingerprint'] = grouping.fingerprint
            value['source_checks'] = [{'unit_id': key, 'source_refs': list(refs), 'status': 'TAUGHT',
                'lesson_ids': [current['lessons'][0]['id']], 'reason': 'Checked against current lesson.'}
                for key, refs in grouping.groups]
            if not repairs:
                value['findings'] = [{'scope': 'lesson', 'target_id': 'l1', 'problem': 'Recording duty omitted',
                    'source_refs': [packet.blocks[-1].block_id], 'expected_rule': 'Sign and record',
                    'correction': 'Restore the recording duty'}]
        else:
            repairs += 1
            value = {'new_lessons': [], 'new_questions': [], 'lesson_updates': {'l1': {
                'title': original['lessons'][0]['title'], 'replacements': [{
                    'fragment_id': 'F1', 'new_text': original['lessons'][0]['content']}]}}}
            value['course_fingerprint'] = fmt['json_schema']['schema']['properties']['course_fingerprint']['enum'][0]
        wire = view.encode(value)
        validate(wire)
        return wire
    result = await run_practical_cycle(packet, {}, invoke)
    assert events == ['practical_course', 'practical_review', 'practical_source_audit', 'practical_patch',
                      'practical_review', 'practical_source_audit']
    assert result.decision.accepted and result.course == original and repairs == 1
    assert result.history[0]['review']['findings'] == []
    assert result.history[0]['source_audit']['findings'] and not result.history[0]['accepted']
    assert result.review['answer_keys'] == checked(packet, original)['answer_keys']
    assert packet.to_payload() == source_before


@pytest.mark.asyncio
async def test_unknown_source_audit_is_held_on_service_resume(case):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []
    async def model(messages, fmt):
        kind = response_contract(fmt)
        calls.append(kind)
        if kind == 'practical_source_audit':
            raise TimeoutError('Unknown source audit outcome')
        return view.encode(course if kind == 'practical_course' else checked(packet, course))
    args = dict(intent=CourseIntent(), generation_client=model, revision_policy=POLICY,
        review_policy=PRACTICAL_REVIEW_POLICY, extraction_journal=Journal(), route_fingerprint='b' * 64)
    with pytest.raises(TimeoutError):
        await generate_v3_course_from_corpus(corpus, **args)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate_v3_course_from_corpus(corpus, **args)
    assert calls == ['practical_course', 'practical_review', 'practical_source_audit']
