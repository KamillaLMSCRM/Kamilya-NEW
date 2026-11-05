import copy
import json
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_curriculum import validate_curriculum
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.practical_source_core import compile_source_core
from app.modules.ai.v3.practical_source_core_cycle import (
    _finding_targets,
    _retain_unverified,
    _review_bank,
    _review_projection,
    run_source_core_cycle,
)
from app.modules.ai.v3.practical_source_core_editor import _case_inventory, _pieces
from app.modules.ai.v3.response_contracts import response_contract
from app.modules.ai.v3.revision_policy import (
    SOURCE_CORE_PRACTICAL_REVIEW_POLICY,
    is_practical_policy,
    read_review_policy,
)
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_counterexamples import counterexample
from tests.unit.test_v3_practical_curriculum import bank_response, plan_value
from tests.unit.test_v3_practical_source_core import author_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
async def test_owned_coverage_gap_reaches_final_review_without_answer_scope_failure(case):
    corpus, packet, _ = case
    view = PracticalModelView(packet)
    plan = validate_curriculum(plan_value(packet), packet)
    author = author_value(packet, plan)
    course, _ = compile_source_core(packet, plan, author, course_title='Source course')
    cases = _case_inventory(author)
    bank_count = 0
    calls = []

    async def stage(name, group, messages, fmt, validate):
        nonlocal bank_count
        calls.append(group)
        props = fmt['json_schema']['schema']['properties']
        if 'source-curriculum' in group:
            value = view.encode(plan)
        elif 'source-core:author' in group:
            value = view.encode(copy.deepcopy(author))
            value['blueprint_fingerprint'] = props['blueprint_fingerprint']['enum'][0]
        elif 'source-core:editor' in group:
            piece = props['evidence']['items']['properties']['piece_ids']['items']['enum'][0]
            targets = props['replacements']['items']['properties']['case_id']['enum']
            value = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                'editor_fingerprint': props['editor_fingerprint']['enum'][0],
                'author_fingerprint': props['author_fingerprint']['enum'][0],
                'replacements': [{'case_id': key, 'question': view.encode(cases[key])} for key in targets],
                'evidence': [{'case_id': key, 'piece_ids': [piece]} for key in cases]}
        else:
            bank_count += 1
            value = bank_response(packet, _review_projection(course, cases), plan)
            for row in value['goal_checks']:
                row['question_ids'] = ['L1Q1']
            if bank_count == 1:
                value['goal_checks'][0].update(status='MISSING', assessment_lesson_id='L1')
            else:
                assert 'issue_checks' not in props  # Coverage has its own goal checks.
            value = view.encode(value)
        validate(value)
        return value

    result = await run_source_core_cycle(packet, corpus, CourseIntent(purpose='Practice', audience='Workers'), (), stage)
    assert bank_count == 2 and len(calls) == 5
    assert len(result.course['lessons'][0]['questions']) == 3
    assert any(row['scope'] == 'assessment' for row in result.decision.feedback)
    assert not result.decision.accepted  # No-op editing cannot erase the original gap.
    assert any(row['evidence'].get('goal_id') == 'G1' for row in result.decision.feedback)


@pytest.mark.parametrize('status,witnesses,changed,cleared', [
    ('NOT_REQUIRED', ['L1Q1'], {'L1Q2'}, False),
    ('INVALID_GOAL', [], {'L1Q2'}, False),
    ('MISSING', ['L1Q2'], {'L1Q2'}, False),
    ('COVERED', ['L1Q1'], {'L1Q2'}, False),
    ('COVERED', ['L1P1'], {'L1P1'}, False),
    ('COVERED', ['L1Q2'], {'L1Q2'}, True),
])
def test_original_goal_needs_its_own_changed_reviewed_witness(status, witnesses, changed, cleared):
    finding = {'scope': 'assessment', 'id': 'L1', 'issue_id': 'gap1', 'evidence': {'goal_id': 'G1'}}
    owners = {'L1Q1': 'L1', 'L1Q2': 'L1', 'L1P1': 'L1'}
    goals = {'G1': {'status': status, 'question_ids': witnesses}}
    result = _retain_unverified((finding,), (), changed, owners, goals)
    assert (result == []) is cleared
    if cleared:
        conflict = {'scope': 'question', 'id': 'L1Q2', 'issue_id': 'answer1', 'evidence': {}}
        assert finding in _retain_unverified((finding,), (conflict,), changed, owners, goals)


def test_assessment_scope_does_not_require_edits_and_source_holds_never_clear():
    cases = {'L1P1': {}, 'L1Q1': {}, 'L1Q2': {}, 'L2Q1': {}}
    owners = {key: key[:2] for key in cases}
    assessment = {'scope': 'assessment', 'id': 'L1', 'issue_id': 'i1', 'evidence': {'problem': 'gap'}}
    source = {'scope': 'source', 'id': 's1', 'issue_id': 'i2', 'evidence': {'problem': 'uncertain'}}
    findings = (assessment, source)
    assert set(_finding_targets(findings, cases, owners)) == {'L1Q1', 'L1Q2'}
    assert _retain_unverified(findings, (), set(), owners) == [assessment, source]
    assert _retain_unverified(findings, (), {'L1P1'}, owners) == [assessment, source]
    assert _retain_unverified(findings, (), {'L1Q1'}, owners) == [source]
    conflicting = {'scope': 'question', 'id': 'L1Q1', 'issue_id': 'i3', 'evidence': {}}
    assert _retain_unverified(findings, (conflicting,), {'L1Q1'}, owners) == [conflicting, assessment, source]


def test_counterexample_evidence_is_forwarded_with_owned_aliases(case):
    _, packet, _ = case
    view = PracticalModelView(packet)
    ref = packet.blocks[0].block_id
    finding = {'scope': 'question', 'id': 'L1Q1', 'issue_id': 'issue',
        'evidence': {'problem': 'option_answerability_unresolved', 'counterexample':
                     {'case_description': 'A source-compatible competing case', 'source_refs': [ref]}}}
    guidance = _finding_targets((finding,), {'L1Q1': {}}, {'L1Q1': 'L1'}, view)['L1Q1'][0]
    assert 'source-compatible competing case' in guidance
    assert view.canonical_to_alias[ref] in guidance and ref not in guidance


def test_practice_is_reviewed_but_cannot_witness_assessment_coverage(case):
    corpus, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    author = author_value(packet, plan)
    course, _ = compile_source_core(packet, plan, author, course_title='Source course')
    projected = _review_projection(course, _case_inventory(author))
    assert projected['lessons'][0]['questions'][-1]['id'] == 'L1P1'
    assert len(course['lessons'][0]['questions']) == 3
    response = bank_response(packet, projected, plan)
    for row in response['goal_checks']:
        row['question_ids'] = ['L1P1']
    decision, unresolved = _review_bank(response, packet, projected, plan, ())
    assert not decision.accepted and set(unresolved) == {'G1', 'G2'}


@pytest.mark.asyncio
async def test_five_stages_zero_target_and_final_blind_review(case):
    corpus, packet, _ = case
    intent = CourseIntent(purpose='Practice', audience='Workers')
    view = PracticalModelView(packet)
    plan_raw = plan_value(packet)
    plan = validate_curriculum(plan_raw, packet)
    author = author_value(packet, plan)
    calls = []
    course = None
    cases = _case_inventory(author)
    use_bad_evidence = False
    refs_only_mode = False
    bank_round = 0
    active_corpus = corpus

    async def stage(name, group, messages, fmt, validate):
        nonlocal course, bank_round
        calls.append((name, group))
        props = fmt['json_schema']['schema']['properties']
        if 'source-curriculum' in group:
            value = view.encode(plan_raw)
        elif 'source-core:author' in group:
            if active_corpus.documents[0].review_only_source_context:
                assert 'Unverified candidate' in messages[1]['content']
            if plan['source_uncertainties']:
                assert 'Uncertain source clause' in messages[1]['content']
            value = view.encode(copy.deepcopy(author))
            value['blueprint_fingerprint'] = props['blueprint_fingerprint']['enum'][0]
            decoded = view.decode(value)
            course, _ = compile_source_core(packet, plan, decoded, course_title=active_corpus.documents[0].title,
                                             corpus=active_corpus)
        elif 'source-core:editor' in group:
            case_ids = props['evidence']['items']['properties']['case_id']['enum']
            piece = props['evidence']['items']['properties']['piece_ids']['items']['enum'][0]
            value = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                'editor_fingerprint': props['editor_fingerprint']['enum'][0],
                'author_fingerprint': props['author_fingerprint']['enum'][0], 'replacements': [],
                'evidence': [{'case_id': case_id, 'piece_ids': [piece]} for case_id in case_ids]}
            if refs_only_mode:
                assert props['replacements']['maxItems'] == 1
                assert 'Signature without a record leaves the procedure incomplete.' in messages[1]['content']
                assert view.canonical_to_alias[packet.blocks[0].block_id] in messages[1]['content']
                changed_question = copy.deepcopy(cases['L1Q1'])
                foreign_ref = next(block.block_id for block in packet.blocks
                                   if block.block_id not in changed_question['source_refs'])
                changed_question['source_refs'].append(foreign_ref)
                value['replacements'] = [{'case_id': 'L1Q1', 'question': view.encode(changed_question)}]
                inventory, _ = _pieces(packet)
                foreign = next(key for key, item in inventory.items() if item['source_ref'] == foreign_ref)
                next(row for row in value['evidence'] if row['case_id'] == 'L1Q1')['piece_ids'].append(foreign)
            else:
                assert props['replacements']['maxItems'] == 0
            if use_bad_evidence:
                inventory, _ = _pieces(packet)
                foreign = next(key for key, item in inventory.items() if item['source_ref'] != cases['L1Q1']['source_refs'][0])
                next(row for row in value['evidence'] if row['case_id'] == 'L1Q1')['piece_ids'] = [foreign]
        else:
            bank_round += 1
            projected = _review_projection(course, cases)
            raw = bank_response(packet, projected, plan)
            for row in raw['goal_checks']:
                row['question_ids'] = ['L1Q1']
            if refs_only_mode and bank_round == 1:
                first = next(row for row in raw['answerability'] if row['question_id'] == 'L1Q1')
                first['counterexample'] = counterexample('FOUND', [packet.blocks[0].block_id])
                raw['goal_checks'][0]['status'] = 'MISSING'
                raw['goal_checks'][0]['question_ids'] = []
            if 'issue_checks' in props:
                raw['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Reviewed.'}
                                       for key in props['issue_checks']['properties']}
            value = view.encode(raw)
            body = messages[1]['content']
            assert 'PRACTICE_CASE_IDS_JSON' in body and 'L1P1' in body
            bank = json.loads(body.split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0])
            assert all('correct_index' not in row and 'explanation' not in row for row in bank)
        validate(value)
        return value

    result = await run_source_core_cycle(packet, corpus, intent, (), stage)
    assert [name for name, _ in calls] == ['review', 'lesson', 'review', 'review', 'review']
    assert result.source_core and result.decision.accepted
    assert len(result.course['lessons'][0]['questions']) == 3
    assert result.history[0]['editor_custody']['unresolved_target_ids'] == []
    assert is_practical_policy(SOURCE_CORE_PRACTICAL_REVIEW_POLICY)
    assert read_review_policy({'v3_review_policy': SOURCE_CORE_PRACTICAL_REVIEW_POLICY}) == SOURCE_CORE_PRACTICAL_REVIEW_POLICY

    async def invoke(messages, fmt):
        kind = response_contract(fmt)
        name, group = {
            'practical_curriculum': ('review', 'practical:source-curriculum:v30'),
            'practical_source_core': ('lesson', 'practical:source-core:author:v30'),
            'practical_curriculum_bank': ('review', 'practical:review:bank:v30'),
            'practical_source_core_editor': ('review', 'practical:source-core:editor:v30'),
        }[kind]
        return await stage(name, group, messages, fmt, lambda value: None)

    journal = Journal()
    progress = []
    async def report(*args):
        progress.append(args)
    async def generate(client):
        return await generate_practical_course(corpus, intent=intent, invoke=client,
            source_sha256='a' * 64, journal=journal, route_fingerprint='b' * 64,
            review_policy=SOURCE_CORE_PRACTICAL_REVIEW_POLICY, progress_callback=report)
    artifacts = await generate(invoke)
    assert artifacts.diagnostics['v3_review_policy'] == SOURCE_CORE_PRACTICAL_REVIEW_POLICY
    assert len(artifacts.assessment.assessments[0].mcq) == 3
    assert len(progress) == 5 and progress[-1][1:3] == (5, 5)
    prior_calls = len(calls)
    replay = await generate(invoke)
    assert len(calls) == prior_calls
    assert replay.diagnostics['practical_course'] == artifacts.diagnostics['practical_course']
    proposal = {'text': 'Unverified candidate', 'source_sha256': 'c' * 64, 'composite_sha256': 'd' * 64}
    held_doc = replace(corpus.documents[0], review_only_source_context=(proposal,))
    held_corpus = replace(corpus, documents=(held_doc,))
    active_corpus = held_corpus
    held = await generate_practical_course(held_corpus, intent=intent, invoke=invoke,
        source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
        review_policy=SOURCE_CORE_PRACTICAL_REVIEW_POLICY)
    assert held.diagnostics['practical_unverified_source_proposals'][0]['proposals'] == [proposal]
    assert held.diagnostics['requires_source_review'] is True
    assert 'Unverified candidate' in held.diagnostics['practical_course']['lessons'][0]['content']
    active_corpus = corpus
    use_bad_evidence = True
    bad_journal = Journal()
    async def generate_bad():
        return await generate_practical_course(corpus, intent=intent, invoke=invoke,
            source_sha256='a' * 64, journal=bad_journal, route_fingerprint='b' * 64,
            review_policy=SOURCE_CORE_PRACTICAL_REVIEW_POLICY)
    partial = await generate_bad()
    assert partial.diagnostics['practical_source_core_unresolved_cases'] == ['L1Q1']
    assert partial.diagnostics['automated_review_passed'] is False
    partial_calls = len(calls)
    partial_replay = await generate_bad()
    assert len(calls) == partial_calls
    assert partial_replay.diagnostics['practical_course'] == partial.diagnostics['practical_course']
    assert partial_replay.diagnostics['practical_source_core_unresolved_cases'] == ['L1Q1']
    use_bad_evidence = False
    plan_raw['source_uncertainties'] = [{'note': 'Uncertain source clause', 'source_refs': [packet.blocks[0].block_id]}]
    plan = validate_curriculum(plan_raw, packet)
    author = author_value(packet, plan)
    cases = _case_inventory(author)
    uncertain = await generate_practical_course(corpus, intent=intent, invoke=invoke,
        source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
        review_policy=SOURCE_CORE_PRACTICAL_REVIEW_POLICY)
    assert uncertain.diagnostics['practical_source_core_source_review_pending'] is True
    assert uncertain.diagnostics['requires_source_review'] is True
    assert 'Uncertain source clause' in uncertain.diagnostics['practical_course']['lessons'][0]['content']
    plan_raw['source_uncertainties'] = []
    plan = validate_curriculum(plan_raw, packet)
    author = author_value(packet, plan)
    cases = _case_inventory(author)
    refs_only_mode = True
    bank_round = 0
    refs_only = await generate_practical_course(corpus, intent=intent, invoke=invoke,
        source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
        review_policy=SOURCE_CORE_PRACTICAL_REVIEW_POLICY)
    assert refs_only.diagnostics['automated_review_passed'] is False
    assert any('question:L1Q1' == item for item in refs_only.diagnostics['validation_report']['violations'])
    assert 'G1' in refs_only.diagnostics['practical_unresolved_curriculum_goals']


@pytest.mark.asyncio
async def test_unknown_owned_call_is_not_reissued(case):
    corpus, _, _ = case
    journal = Journal()
    calls = 0
    async def invoke(messages, fmt):
        nonlocal calls
        calls += 1
        raise TimeoutError('unknown outcome')
    async def generate():
        return await generate_practical_course(corpus, intent=CourseIntent(), invoke=invoke,
            source_sha256='a' * 64, journal=journal, route_fingerprint='b' * 64,
            review_policy=SOURCE_CORE_PRACTICAL_REVIEW_POLICY)
    with pytest.raises(TimeoutError):
        await generate()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    assert calls == 1
