import copy
import hashlib
import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_curriculum import validate_curriculum
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_core import (
    compile_source_core,
    is_source_core_format,
    source_core_blueprint,
    source_core_format,
    source_core_messages,
)
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision
from tests.unit.test_v3_practical_curriculum import plan_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def author_value(packet, plan, **options):
    blueprint = source_core_blueprint(packet, plan, course_title='Source course', **options)
    fmt = source_core_format(packet, plan, course_title='Source course', **options)
    props = fmt['json_schema']['schema']['properties']
    rows = []
    for lesson in blueprint['lessons']:
        ref = lesson['source_refs'][0]
        def question(label, lesson_id=lesson['id'], source_ref=ref):
            return {'prompt': label + lesson_id, 'choices': ['Wrong', 'Correct', 'Other'],
                    'correct_index': 1, 'source_refs': [source_ref]}
        rows.append({'lesson_id': lesson['id'], 'practice': question('Practice '),
                     'assessment': [question(f'Exam {i} ') for i in range(3)]})
    return {'source_fingerprint': packet.fingerprint, 'blueprint_fingerprint': props['blueprint_fingerprint']['enum'][0],
            'curriculum_fingerprint': props['curriculum_fingerprint']['enum'][0], 'lessons': rows}


def test_source_custody_practice_and_assessment_are_distinct(case):
    corpus, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    value = author_value(packet, plan)
    fmt = source_core_format(packet, plan, course_title='Source course')
    view = PracticalModelView(packet)
    assert is_source_core_format(fmt) and response_contract(fmt) == 'practical_source_core'
    assert matches_response_contract(view.encode(value), view.schema(fmt))
    course, meta = compile_source_core(packet, plan, value, course_title='Source course')
    owned = [ref for lesson in meta['source_custody'] for ref in lesson['source_blocks']]
    assert owned == [block.block_id for block in packet.blocks]
    assert corpus.documents[0].source_text in course['lessons'][0]['content']
    assert value['lessons'][0]['practice']['prompt'] in course['lessons'][0]['content']
    assert all(q['prompt'] != value['lessons'][0]['practice']['prompt'] for q in course['lessons'][0]['questions'])
    assert all(q['choices'][q['correct_index']] == 'Correct' for q in course['lessons'][0]['questions'])
    assert not meta['automatic_approval'] and meta['source_readiness'] == 'UNVERIFIED'
    assert 'explanation' not in source_core_messages(packet, plan, course_title='Source course')[1]['content']


@pytest.mark.parametrize('mutation', ['stale', 'foreign_ref', 'missing_lesson', 'duplicate_lesson', 'invalid_key', 'practice_duplicate', 'extra_prose'])
def test_author_contract_fails_closed(case, mutation):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    value = author_value(packet, plan)
    if mutation == 'stale':
        value['source_fingerprint'] = '0' * 64
    elif mutation == 'foreign_ref':
        value['lessons'][0]['practice']['source_refs'] = ['foreign']
    elif mutation == 'missing_lesson':
        value['lessons'] = []
    elif mutation == 'duplicate_lesson':
        value['lessons'].append(copy.deepcopy(value['lessons'][0]))
    elif mutation == 'invalid_key':
        value['lessons'][0]['practice']['correct_index'] = 9
    elif mutation == 'practice_duplicate':
        value['lessons'][0]['assessment'][0] = copy.deepcopy(value['lessons'][0]['practice'])
    else:
        value['lessons'][0]['normative_prose'] = 'invented'
    with pytest.raises(ValueError):
        compile_source_core(packet, plan, value, course_title='Source course')


def test_duplicate_within_section_or_excluded_units_and_foreign_tenant_reject(case):
    _, packet, _ = case
    raw = plan_value(packet)
    raw['sections'][0]['source_units'].append(raw['sections'][0]['source_units'][0])
    with pytest.raises(ValueError):
        source_core_blueprint(packet, validate_curriculum(raw, packet), course_title='Source course')
    raw = plan_value(packet)
    raw['non_teaching_units'] = [raw['sections'][0]['source_units'][0]]
    with pytest.raises(ValueError):
        source_core_blueprint(packet, validate_curriculum(raw, packet), course_title='Source course')
    plan = validate_curriculum(plan_value(packet), packet)
    with pytest.raises(ValueError):
        source_core_blueprint(replace(packet, tenant_id='another-tenant'), plan, course_title='Source course')


def test_owner_clarification_requires_exact_typed_custody_and_scope(case):
    corpus, _, _ = case
    document = corpus.documents[0]
    text = document.source_text
    ref, target = 'ticket', 'records the approval'
    start, target_start = text.index(ref), text.index(target)
    decision = SourceReferenceDecision(corpus.tenant_id, document.doc_id, document.source_revision,
        hashlib.sha256(text.encode()).hexdigest(), start, start + len(ref), ref,
        target_start, target_start + len(target), target, 'owner_chat')
    packet = build_practical_source_packet(corpus, (decision,))
    plan = validate_curriculum(plan_value(packet), packet)
    with pytest.raises(ValueError, match='reference_custody_required'):
        source_core_blueprint(packet, plan, course_title='Source course')
    options = {'corpus': corpus, 'reference_decisions': (decision,)}
    value = author_value(packet, plan, **options)
    course, metadata = compile_source_core(packet, plan, value, course_title='Source course', **options)
    content = course['lessons'][0]['content']
    assert 'Подтверждённое уточнение для указанной ссылки' in content
    assert f'«{ref}» относится к фрагменту «{target}»' in content
    assert decision.document_id not in content and decision.source_revision not in content
    assert not metadata['automatic_approval']
    from app.modules.ai.v3.practical_source_core import prepare_source_core_request
    prepared = prepare_source_core_request(packet, plan, course_title='Source course', **options)
    prepared_course, prepared_metadata = prepared.compile_response(
        PracticalModelView(packet).encode(value), sent_request=prepared.request())
    assert f'«{ref}» относится к фрагменту «{target}»' in prepared_course['lessons'][0]['content']
    assert prepared_metadata['source_fingerprint'] == packet.fingerprint
    assert not prepared_metadata['automatic_approval']
    for bad in (replace(decision, tenant_id='other'), replace(decision, source_revision='stale'),
                replace(decision, reference_start=0), replace(decision, target_exact='invented')):
        with pytest.raises(ValueError):
            source_core_blueprint(packet, plan, course_title='Source course', corpus=corpus, reference_decisions=(bad,))


def test_source_holds_retained_without_approval(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    hold = {'note': 'Source requires human interpretation.', 'source_refs': [packet.blocks[0].block_id]}
    value = author_value(packet, plan, source_holds=(hold,))
    _, metadata = compile_source_core(packet, plan, value, course_title='Source course', source_holds=(hold,))
    assert metadata['source_holds'] == (hold,) and not metadata['automatic_approval']


def test_shipped_runner_accepts_format(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location('source_core_runner', root / 'infra/codex-reserve/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    fmt = PracticalModelView(packet).schema(source_core_format(packet, plan, course_title='Source course'))
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


def test_permuted_practice_answers_still_duplicate(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    value = author_value(packet, plan)
    item = copy.deepcopy(value['lessons'][0]['practice'])
    item['choices'] = list(reversed(item['choices']))
    value['lessons'][0]['assessment'][0] = item
    with pytest.raises(ValueError, match='practice_exam_duplicate'):
        compile_source_core(packet, plan, value, course_title='Source course')


def test_existing_projection_preserves_correct_text(case):
    from app.modules.ai.v3.practical_cycle import PracticalCycleResult
    from app.modules.ai.v3.practical_review import PracticalReviewDecision
    from app.modules.ai.v3.practical_service import practical_artifacts

    corpus, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    course, _ = compile_source_core(packet, plan, author_value(packet, plan), course_title='Source course')
    review = {'source_notes': [], 'narrative_sources': {'L1': [packet.blocks[0].block_id]}}
    decision = PracticalReviewDecision(False, False, (), (), False, ())
    result = PracticalCycleResult(course, review, decision, (), 'review_required')
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    for question in artifacts.assessment.assessments[0].mcq:
        assert [option.text for option in question.options if option.is_correct] == ['Correct']


def test_reference_note_is_scoped_to_owning_lesson_and_dependency_refs(case):
    from app.modules.ai.direct_source import DirectSourceCorpus
    from app.modules.ai.v3.practical_audit_units import audit_units

    base_corpus, _, _ = case
    doc1 = base_corpus.documents[0]
    text2 = 'A separate document requires a second distinct workflow.'
    doc2 = replace(doc1, doc_id='doc2', title='Other document', source_text=text2,
                   source_revision='document:' + hashlib.sha256(text2.encode()).hexdigest())
    corpus = DirectSourceCorpus(base_corpus.tenant_id, (doc1, doc2), len(doc1.source_text) + len(text2), 0)
    source = doc1.source_text
    ref, target = 'ticket', 'records the approval'
    start, target_start = source.index(ref), source.index(target)
    decision = SourceReferenceDecision(corpus.tenant_id, doc1.doc_id, doc1.source_revision,
        hashlib.sha256(source.encode()).hexdigest(), start, start + len(ref), ref,
        target_start, target_start + len(target), target, 'owner_chat')
    packet = build_practical_source_packet(corpus, (decision,))
    units = audit_units(packet).groups
    assert len(units) >= 2
    def goals(refs):
        return [{'id': 'model', 'decision': 'Decide the appropriate action',
                 'essential_case_conditions': [], 'source_refs': list(refs)}]
    raw = {'source_fingerprint': packet.fingerprint, 'non_teaching_units': [], 'source_uncertainties': [],
        'sections': [{'title': 'First', 'source_units': [unit[0] for unit in units[:-1]], 'depends_on_units': [], 'goals': goals(units[0][1])},
                     {'title': 'Second', 'source_units': [units[-1][0]], 'depends_on_units': [units[0][0]], 'goals': goals(units[-1][1])}]}
    plan = validate_curriculum(raw, packet)
    options = {'corpus': corpus, 'reference_decisions': (decision,)}
    value = author_value(packet, plan, **options)
    value['lessons'][1]['practice']['source_refs'].append(units[0][1][0])
    course, metadata = compile_source_core(packet, plan, value, course_title='Source course', **options)
    marker = 'Подтверждённое уточнение для указанной ссылки'
    assert marker in course['lessons'][0]['content'] and marker not in course['lessons'][1]['content']
    assert sum(len(row['source_blocks']) for row in metadata['source_custody']) == len(packet.blocks)
    assert 'First' in course['lessons'][1]['content']
    hold = {'note': 'Review second document.', 'source_refs': [units[-1][1][0]]}
    held_value = author_value(packet, plan, source_holds=(hold,), **options)
    held, held_metadata = compile_source_core(packet, plan, held_value, course_title='Source course',
                                               source_holds=(hold,), **options)
    assert hold['note'] not in held['lessons'][0]['content'] and hold['note'] in held['lessons'][1]['content']
    assert held_metadata['source_holds'] == (hold,) and held_metadata['source_readiness'] == 'UNVERIFIED'
    # L1 has no planned dependency on the second document; a referenced extra
    # source creates a proposed link, not new source ownership or authority.
    linked_value = author_value(packet, plan, source_holds=(hold,), **options)
    linked_value['lessons'][0]['practice']['source_refs'].append(units[-1][1][0])
    linked, linked_meta = compile_source_core(packet, plan, linked_value, course_title='Source course',
                                              source_holds=(hold,), **options)
    assert hold['note'] in linked['lessons'][0]['content']
    assert 'Дополнительные связи источника (требуют проверки): Second.' in linked['lessons'][0]['content']
    assert linked_meta['unverified_discovered_dependencies'] == [{'lesson_id': 'L1', 'case_kind': 'practice',
        'case_index': 0, 'source_refs': [units[-1][1][0]], 'owner_lesson_ids': ['L2'], 'status': 'UNVERIFIED'}]
    assert [ref for row in linked_meta['source_custody'] for ref in row['source_blocks']] == [b.block_id for b in packet.blocks]
    assert not linked_meta['automatic_approval']
    invalid = copy.deepcopy(value)
    invalid['lessons'][0]['practice']['source_refs'] = [units[-1][1][0]]
    with pytest.raises(ValueError, match='question_basis_invalid'):
        compile_source_core(packet, plan, invalid, course_title='Source course', **options)


def test_seven_lessons_preserve_every_source_block_and_all_21_exam_fields(case):
    from app.modules.ai.direct_source import DirectSourceCorpus
    from app.modules.ai.v3.practical_audit_units import audit_units

    base, _, _ = case
    documents = []
    for i in range(7):
        text = f'Workplace rule {i + 1}: perform the specified action.'
        documents.append(replace(base.documents[0], doc_id=f'doc-{i}', title=f'Document {i}', source_text=text,
                                 source_revision='document:' + hashlib.sha256(text.encode()).hexdigest()))
    corpus = DirectSourceCorpus(base.tenant_id, tuple(documents), sum(len(d.source_text) for d in documents), 0)
    packet = build_practical_source_packet(corpus)
    groups = audit_units(packet).groups
    assert len(groups) == 7
    sections = [{'title': f'Topic {i}', 'source_units': [unit], 'depends_on_units': [],
                 'goals': [{'id': 'ignored', 'decision': f'Decide {i}', 'essential_case_conditions': [],
                            'source_refs': list(refs)}]}
                for i, (unit, refs) in enumerate(groups, 1)]
    plan = validate_curriculum({'source_fingerprint': packet.fingerprint, 'sections': sections,
                                'non_teaching_units': [], 'source_uncertainties': []}, packet)
    author = author_value(packet, plan)
    course, meta = compile_source_core(packet, plan, author, course_title='Source course')
    assert len(course['lessons']) == 7 and sum(len(row['questions']) for row in course['lessons']) == 21
    assert [ref for row in meta['source_custody'] for ref in row['source_blocks']] == [b.block_id for b in packet.blocks]
    for lesson, response in zip(course['lessons'], author['lessons'], strict=True):
        for output, original in zip(lesson['questions'], response['assessment'], strict=True):
            assert all(output[field] == original[field] for field in ('prompt', 'choices', 'correct_index', 'source_refs'))
            assert output['explanation'] == next(b.text for b in packet.blocks if b.block_id == original['source_refs'][0])


def test_missing_source_unit_cannot_compile(case):
    _, packet, _ = case
    raw = plan_value(packet)
    raw['sections'][0]['source_units'].pop()
    with pytest.raises(ValueError):
        source_core_blueprint(packet, raw, course_title='Source course')


def test_title_bound_to_author_response_and_required(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    value = author_value(packet, plan)
    course, _ = compile_source_core(packet, plan, value, course_title='Source course')
    assert course['title'] == 'Source course'
    with pytest.raises(ValueError, match='source_core_author_response_invalid'):
        compile_source_core(packet, plan, value, course_title='Different source')
    with pytest.raises(ValueError, match='course_title_invalid'):
        source_core_format(packet, plan, course_title='  ')


def test_source_hold_visible_unverified_and_foreign_rejected(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    hold = {'note': 'Exception relationship needs owner review.', 'source_refs': [packet.blocks[0].block_id]}
    value = author_value(packet, plan, source_holds=(hold,))
    course, meta = compile_source_core(packet, plan, value, course_title='Source course', source_holds=(hold,))
    assert 'Непроверенное замечание к источнику — требуется проверка' in course['lessons'][0]['content']
    assert hold['note'] in course['lessons'][0]['content']
    assert meta['source_holds'] == (hold,) and not meta['automatic_approval']
    assert meta['source_readiness'] == 'UNVERIFIED'
    bad = {'note': 'bad', 'source_refs': ['foreign']}
    with pytest.raises(ValueError, match='source_core_hold_invalid'):
        compile_source_core(packet, plan, value, course_title='Source course', source_holds=(bad,))


def test_plan_uncertainty_is_unverified_metadata_not_confirmed_reference(case):
    _, packet, _ = case
    raw = plan_value(packet)
    raw['source_uncertainties'] = [{'note': 'Model proposes uncertainty.', 'source_refs': [packet.blocks[0].block_id]}]
    plan = validate_curriculum(raw, packet)
    course, meta = compile_source_core(packet, plan, author_value(packet, plan), course_title='Source course')
    assert meta['plan_source_uncertainties_unverified'] == plan['source_uncertainties']
    assert not meta['source_holds'] and 'Подтверждённое уточнение' not in course['lessons'][0]['content']
    assert not meta['automatic_approval']


def test_producer_index_closed_and_consumer_checks_choice_count(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    fmt = source_core_format(packet, plan, course_title='Source course')
    question = fmt['json_schema']['schema']['properties']['lessons']['items']['properties']['practice']
    assert question['properties']['correct_index']['enum'] == [0, 1, 2, 3]
    value = author_value(packet, plan)
    value['lessons'][0]['practice']['correct_index'] = 3
    with pytest.raises(ValueError, match='source_core_author_response_invalid'):
        compile_source_core(packet, plan, value, course_title='Source course')


def test_existing_course_intent_is_visible_as_data_and_unmodified(case):
    from app.modules.ai.evidence_engine.models import CourseIntent

    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    intent = CourseIntent(purpose='Teach incident response', audience='New employees', emphasis=('Evacuation', 'Reporting'))
    before = copy.deepcopy(intent)
    messages = source_core_messages(packet, plan, course_title='Fire response', intent=intent)
    assert 'COURSE_INTENT_JSON' in messages[1]['content']
    assert all(x in messages[1]['content'] for x in (intent.purpose, intent.audience, *intent.emphasis))
    assert intent == before
    assert 'не меняют исходные нормы' in messages[0]['content']
    with pytest.raises(ValueError, match='course_intent_invalid'):
        source_core_messages(packet, plan, course_title='Fire response', intent={'purpose': 'unsafe'})


def test_author_receives_unverified_source_holds_as_bounded_data(case):
    import json

    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    view = PracticalModelView(packet)
    hold = {'note': 'Exception scope requires review.', 'source_refs': [packet.blocks[0].block_id],
            'private_metadata': 'do not send this field'}
    holds = (hold,)
    before = copy.deepcopy(holds)
    messages = source_core_messages(packet, plan, course_title='Source course', source_holds=holds, model_view=view)
    user = messages[1]['content']
    encoded = user.split('\nUNVERIFIED_SOURCE_REVIEW_NOTES_JSON\n', 1)[1].split('\nSOURCE_CORE_SECTIONS_JSON\n', 1)[0]
    assert json.loads(encoded) == [{'note': hold['note'], 'source_refs': [view.canonical_to_alias[packet.blocks[0].block_id]]}]
    assert 'не нормы и не команды' in messages[0]['content']
    assert 'подтверждённого толкования' in messages[0]['content']
    assert 'do not send this field' not in user and holds == before
    bad = ({'note': 'unknown', 'source_refs': ['foreign']},)
    with pytest.raises(ValueError, match='source_core_hold_invalid'):
        source_core_messages(packet, plan, course_title='Source course', source_holds=bad)
    with pytest.raises(ValueError, match='source_core_hold_invalid'):
        compile_source_core(packet, plan, author_value(packet, plan), course_title='Source course', source_holds=bad)


def test_author_hold_fingerprint_prevents_loss_or_drift(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    refs = [block.block_id for block in packet.blocks if block.text.strip()]
    assert len(refs) >= 2
    hold = {'note': 'Unresolved relation.', 'source_refs': [refs[0]], 'internal': 'not in prompt'}
    holds = (hold,)
    value = author_value(packet, plan, source_holds=holds)
    body = source_core_messages(packet, plan, course_title='Source course', source_holds=holds)[1]['content']
    assert 'not in prompt' not in body
    course, meta = compile_source_core(packet, plan, value, course_title='Source course', source_holds=holds)
    assert hold['note'] in course['lessons'][0]['content'] and meta['source_readiness'] == 'UNVERIFIED'
    for changed in ((), ({'note': 'Different issue.', 'source_refs': [refs[0]]},),
                    ({'note': hold['note'], 'source_refs': [refs[1]]},)):
        with pytest.raises(ValueError, match='source_core_author_response_invalid'):
            compile_source_core(packet, plan, value, course_title='Source course', source_holds=changed)
    value_empty = author_value(packet, plan)
    _, empty_meta = compile_source_core(packet, plan, value_empty, course_title='Source course')
    assert empty_meta['source_holds'] == () and not empty_meta['automatic_approval']


def test_prepared_context_freezes_plan_and_holds_and_rejects_mixed_request(case):
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.practical_source_core import prepare_source_core_request

    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    hold = {'note': 'Original warning', 'source_refs': [packet.blocks[0].block_id]}
    holds = (hold,)
    intent = CourseIntent(purpose='Onboarding', audience='New staff', emphasis=('Safety',))
    author = author_value(packet, plan, source_holds=holds)
    prepared = prepare_source_core_request(packet, plan, course_title='Source course', intent=intent, source_holds=holds)
    sent_request = prepared.request()
    clean = prepare_source_core_request(packet, plan, course_title='Source course', intent=intent)
    mixed = prepared.request()
    mixed['response_format'] = clean.request()['response_format']
    with pytest.raises(ValueError, match='prepared_request_mismatch'):
        prepared.compile_response(PracticalModelView(packet).encode(author), sent_request=mixed)
    plan['sections'][0]['goals'][0]['decision'] = 'Mutated after dispatch'
    hold['note'] = 'Mutated after dispatch'
    hold['source_refs'].clear()
    assert prepared.request() == sent_request
    course, metadata = prepared.compile_response(PracticalModelView(packet).encode(author), sent_request=sent_request)
    assert 'Original warning' in course['lessons'][0]['content']
    assert 'Mutated after dispatch' not in course['lessons'][0]['content']
    assert metadata['source_holds'][0]['note'] == 'Original warning' and not metadata['automatic_approval']
    altered = prepared.request()
    altered['messages'][1]['content'] = 'tampered'
    with pytest.raises(ValueError, match='prepared_request_mismatch'):
        prepared.compile_response(PracticalModelView(packet).encode(author), sent_request=altered)


def test_prepared_context_rejects_mixed_wire_response(case):
    from app.modules.ai.v3.practical_source_core import prepare_source_core_request

    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    hold = {'note': 'Check source.', 'source_refs': [packet.blocks[0].block_id]}
    prepared = prepare_source_core_request(packet, plan, course_title='Source course', source_holds=(hold,))
    empty_hold_author = PracticalModelView(packet).encode(author_value(packet, plan))
    with pytest.raises(ValueError, match='prepared_response_invalid'):
        prepared.compile_response(empty_hold_author, sent_request=prepared.request())
