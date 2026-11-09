"""Native coherent semantics stay model-owned; custody and all-row coverage are strict."""
import copy
import json
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_coherent_editorial_cycle import blind_review_units, run_coherent_editorial_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value
from tests.unit.test_v3_editorial_contract import review_value, revision_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
async def test_native_service_replays_completed_author_after_preclaim_interruption(case):
    from app.modules.admin.runtime_configuration.catalog import default_snapshot
    from app.modules.admin.runtime_configuration.runtime import runtime_settings_scope
    from app.modules.ai.v3.practical_service import generate_practical_course
    from app.modules.ai.v3.revision_policy import COHERENT_EDITORIAL_REVIEW_POLICY
    from app.modules.courses.draft_review import read_draft_review
    from tests.unit.test_v3_partitioned_extraction import Journal

    corpus, packet, course = case
    view = PracticalModelView(packet)
    journal = Journal()
    calls = []

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        if name == 'practical_course':
            value = course
        elif name == 'v3_practical_editorial_review_v1':
            value = review_value(packet, course)
            value['findings'] = []
        else:
            value = predicate_value(packet, course, fmt=fmt)
        return view.encode(value)

    class PreclaimInterruptedError(Exception):
        pass

    checks = 0

    async def interrupt_before_review():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise PreclaimInterruptedError

    kwargs = dict(intent=CourseIntent(), invoke=invoke, source_sha256='a' * 64,
        journal=journal, route_fingerprint='b' * 64,
        review_policy=COHERENT_EDITORIAL_REVIEW_POLICY, direct_max_output_tokens=32768)
    with runtime_settings_scope(default_snapshot()):
        with pytest.raises(PreclaimInterruptedError):
            await generate_practical_course(corpus, **kwargs, cancellation_callback=interrupt_before_review)
        assert calls == ['practical_course']
        artifacts = await generate_practical_course(corpus, **kwargs)
        assert len(calls) == 3  # The acknowledged author was not dispatched twice.
        replay = await generate_practical_course(corpus, **kwargs)
        assert len(calls) == 3
    assert replay.diagnostics == artifacts.diagnostics
    assert artifacts.diagnostics['v3_review_policy'] == COHERENT_EDITORIAL_REVIEW_POLICY
    assert artifacts.diagnostics['automated_review_passed'] is True
    assert artifacts.diagnostics['assessment_option_order_policy'] == 'preserve-reviewed-options-v1'
    manifest = read_draft_review({'evidence_v3': artifacts.diagnostics})
    assert manifest['self_review_status'] == 'passed'
    assert manifest['human_review_required'] is True  # Ordinary publication consent.
    assert manifest['content_review_required'] is False
    assert all(':output=32768' in plan['group_id'] for plan in journal.plans.values())


@pytest.mark.asyncio
async def test_coherent_unknown_model_outcome_is_never_retried_or_saved(case):
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    corpus, packet, _ = case
    stage = AsyncMock(side_effect=ExtractionOutcomeUnknownError('unknown_transport'))
    with pytest.raises(ExtractionOutcomeUnknownError, match='unknown_transport'):
        await run_coherent_editorial_cycle(packet, corpus, CourseIntent(), (), stage,
            max_revisions=3, max_output_tokens=32768)
    stage.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['clean', 'keyed', 'blind', 'owner', 'unverified', 'no_progress', 'new_finding'])
async def test_coherent_native_model_flow_retains_issues_and_owned_fixes(case, mode):
    corpus, packet, original = case
    view = PracticalModelView(packet)
    candidate = copy.deepcopy(original)
    calls = []
    writes = 0

    async def stage(name, group, messages, fmt, validate):
        nonlocal candidate, writes
        calls.append(group)
        assert 'INDEPENDENT_SOURCE_READING_JSON' not in messages[1]['content']
        if name == 'lesson':
            value = original
        elif 'option-predicates' in group:
            assert 'correct_index' not in messages[1]['content']
            value = predicate_value(packet, candidate, fmt=fmt,
                wrong_question='q1' if mode == 'blind' and writes == 0 else None)
        elif ':revision:' in group:
            authority = json.loads(messages[1]['content'].split('\nEDIT_AUTHORITY_JSON\n')[1]
                                   .split('\nEDITORIAL_FINDINGS_UNVERIFIED_JSON\n')[0])
            assert authority['lessons'][0]['content_editable'] is False
            assert 'RELATED_SOURCE_INTERPRETATIONS_JSON\n[]' in messages[1]['content']
            before = copy.deepcopy(candidate)
            if mode != 'no_progress':
                index = 1 if mode == 'new_finding' and writes else 0
                candidate['lessons'][0]['questions'][index]['prompt'] += ' Corrected current question.'
            writes += 1
            value = revision_value(packet, before, candidate)
        elif ':verify:' in group:
            value = review_value(packet, candidate)
            value['findings'] = []
            ids = fmt['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum']
            claims = json.loads(messages[1]['content'].split('\nUNRESOLVED_ALLEGATIONS_JSON\n')[1]
                                .split('\nCURRENT_PROSE_CHECKS_UNVERIFIED_JSON\n')[0])
            target_ids = {r['issue_id']: r['target']['id'] for r in claims}
            question_texts = {q['id']: q['prompt'] for lesson in candidate['lessons'] for q in lesson['questions']}
            disposition = ('SOURCE_AMBIGUITY' if mode == 'owner' else 'UNRESOLVED' if mode == 'unverified'
                           else 'NEEDS_REVISION' if writes == 0 or mode == 'no_progress' else 'FIXED')
            value['resolutions'] = [{'issue_id': key, 'disposition': disposition,
                'reason': 'Compared exact current owned source and question.',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                'course_quote': '' if mode == 'owner' else question_texts[target_ids[key]],
                'source_question': 'Which of the two source alternatives applies?' if mode == 'owner' else ''}
                for key in ids]
            if mode == 'new_finding' and writes == 1:
                value['findings'] = review_value(packet, candidate, target='q2')['findings']
        else:
            value = review_value(packet, candidate, kind='source', target=packet.blocks[0].block_id) if mode == 'owner' else review_value(packet, candidate)
            if mode in {'clean', 'blind'}:
                value['findings'] = []
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_coherent_editorial_cycle(packet, corpus, CourseIntent(), (), stage,
                                               max_revisions=3, max_output_tokens=32768)
    assert not any('source-semantics' in group for group in calls)
    if mode == 'clean':
        assert len(calls) == 3 and writes == 0 and result.decision.accepted
    elif mode in {'keyed', 'blind', 'new_finding'}:
        assert result.decision.accepted and not result.decision.feedback
        assert writes == (2 if mode == 'new_finding' else 1)
        assert result.course['lessons'][0]['content'] == original['lessons'][0]['content']
        if mode != 'new_finding':
            assert result.course['lessons'][0]['questions'][1] == original['lessons'][0]['questions'][1]
        assert result.history[0]['all_material_findings']
        assert result.history[0]['verified_resolutions']
    elif mode == 'owner':
        assert not result.decision.accepted and result.decision.source_uncertain and writes == 0
        assert result.decision.feedback[0]['evidence']['status'] == 'SOURCE_UNRESOLVED'
    elif mode == 'unverified':
        assert not result.decision.accepted and not result.decision.source_uncertain and writes == 0
        assert result.decision.feedback[0]['evidence']['status'] == 'AUTOMATIC_REVIEW_UNRESOLVED'
    else:
        assert not result.decision.accepted and writes == 1
        assert result.stop_reason == 'autonomous_edit_no_progress'


@pytest.mark.parametrize('tokens', [1024, 8192, 16384, 32768, 65536])
def test_long_course_packing_preserves_every_question_and_complete_choices(case, tokens):
    _, _, base = case
    course = {'title': base['title'], 'lessons': []}
    for index in range(100):
        lesson = copy.deepcopy(base['lessons'][0])
        lesson['id'] = 'lesson-' + str(index)
        for q in lesson['questions']:
            q['id'] += '-' + str(index)
        course['lessons'].append(lesson)
    before = copy.deepcopy(course)
    units = blind_review_units(course, tokens)
    expected = [q for lesson in course['lessons'] for q in lesson['questions']]
    actual = [q for unit in units for lesson in unit['lessons'] for q in lesson['questions']]
    assert actual == expected and course == before
    assert len({q['id'] for q in actual}) == len(expected)
    assert all(sum(len(q['choices']) for lesson in unit['lessons'] for q in lesson['questions']) <= tokens // 256 for unit in units)
    assert all(len(q['choices']) == len(expected[0]['choices']) for q in actual)


@pytest.mark.asyncio
@pytest.mark.parametrize('revisions,tokens', [(0, 32768), (True, 32768), (6, 32768), (3, False), (3, 10)])
async def test_invalid_budgets_fail_before_any_provider_call(revisions, tokens):
    async def forbidden(*_args):
        raise AssertionError('must not dispatch')
    with pytest.raises(ValueError):
        await run_coherent_editorial_cycle(None, None, None, (), forbidden,
                                           max_revisions=revisions, max_output_tokens=tokens)
