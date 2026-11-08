import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_option_predicates import _inventory
from tests.unit.test_v3_editorial_contract import review_value, revision_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def predicate_value(packet, course, *, fmt, wrong_question=None):
    expected = fmt['json_schema']['schema']['properties']['bank_fingerprint']['enum'][0]
    units = [course, *[{**course, 'lessons': [lesson]} for lesson in course['lessons']]]
    matching = [unit for unit in units if _inventory(packet, unit)[0] == expected]
    if not matching:
        raise ValueError('predicate_fixture_unit_not_found')
    bank, items, owners = _inventory(packet, matching[0])
    questions = {q['id']: q for lesson in course['lessons'] for q in lesson['questions']}
    judgments = []
    for item in items:
        qid, index = owners[item['item_id']]
        key = questions[qid]['correct_index']
        if qid == wrong_question:
            key = (key + 1) % len(questions[qid]['choices'])
        supported = index == key
        judgments.append({'item_id': item['item_id'], 'status': 'SUPPORTED' if supported else 'NOT_SUPPORTED',
            'reason': 'Compared this choice with the source.', 'source_refs': [packet.blocks[0].block_id],
            'compatible_case': 'Source-backed case.' if supported else ''})
    return {'source_fingerprint': packet.fingerprint, 'bank_fingerprint': bank, 'judgments': judgments}


def source_wire(packet, view, fmt, messages, validate=None):
    """Source-only fixture; editor tests do not simulate a language model's skill."""
    name = fmt['json_schema']['name']
    if name == 'v3_practical_source_semantics_v1':
        value = {'source_fingerprint': packet.fingerprint, 'uncertainties': [],
            'sections': [{'section': 'Approval', 'rules': [
                {'source_refs': [b.block_id], 'source_quote': b.text,
                 'actor': 'Approver', 'action': 'Perform the stated action', 'object': 'Approval',
                 'conditions': [], 'modality': 'must', 'alternatives': [], 'limits': []}
                for b in packet.blocks if b.text.strip()]}]}
    elif name == 'v3_practical_source_semantics_verify_v3':
        reading = json.loads(messages[1]['content'].split('\nINDEPENDENT_SOURCE_READING_JSON\n')[1])
        value = {'source_fingerprint': packet.fingerprint, 'reading_fingerprint': reading['reading_fingerprint'],
            'additional_rules': [], 'rule_checks': [{'rule_id': r['rule_id'], 'status': 'SUPPORTED', 'reason': 'Source action confirmed.',
                'replacement': [], 'source_question': ''} for s in reading['sections'] for r in s['rules']]}
    elif name == 'v3_practical_source_completeness_v1':
        value = {'source_fingerprint': packet.fingerprint,
            'verified_reading_fingerprint': fmt['json_schema']['schema']['properties']['verified_reading_fingerprint']['enum'][0],
            'additional_rules': []}
    else:
        return None
    wire = view.encode(value)
    if validate:
        validate(wire)
    return wire


def rule_wire(value, fmt, course):
    if fmt['json_schema']['name'] in ('v3_practical_compact_editorial_review_v2', 'v3_practical_compact_editorial_verification_v2'):
        props = fmt['json_schema']['schema']['properties']
        value = copy.deepcopy(value)
        value['reading_fingerprint'] = props['reading_fingerprint']['enum'][0]
        value['source_rule_checks'] = [{'rule_id': rule_id, 'status': 'SUPPORTED',
            'lesson_ids': [course['lessons'][0]['id']],
            'lesson_quotes': [{'lesson_id': course['lessons'][0]['id'], 'quote': course['lessons'][0]['content']}],
            'reason': 'Source action taught.',
            'correction': '', 'severity': 'material'}
            for rule_id in props['source_rule_checks']['items']['properties']['rule_id']['enum']]
        return value
    if fmt['json_schema']['name'] not in ('v3_practical_rule_editorial_review_v3', 'v3_practical_rule_editorial_verification_v3'):
        return value
    props = fmt['json_schema']['schema']['properties']
    value = copy.deepcopy(value)
    value['reading_fingerprint'] = props['reading_fingerprint']['enum'][0]
    value['source_rule_checks'] = [{'rule_id': rule_id, 'status': 'SUPPORTED',
        'lesson_quotes': [{'lesson_id': course['lessons'][0]['id'], 'quote': course['lessons'][0]['content']}],
        'condition_checks': [], 'reason': 'Source action taught.', 'correction': '', 'severity': 'material'}
        for rule_id in props['source_rule_checks']['items']['properties']['rule_id']['enum']]
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', ['keyed', 'blind'])
async def test_model_repair_is_verified_and_blind_defect_reaches_editor(case, origin):
    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

    corpus, packet, original = case
    view = PracticalModelView(packet)
    candidate = copy.deepcopy(original)
    calls = []
    finding = None

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        nonlocal candidate, finding
        calls.append(group)
        if name == 'lesson':
            value = original
        elif ':revision:' in group:
            assert 'EDITORIAL_FINDINGS_UNVERIFIED_JSON' in messages[1]['content']
            if origin == 'blind':
                assert any(':verify:' in item for item in calls[:-1])
            candidate['lessons'][0]['questions'][0]['prompt'] = 'Which two actions complete approval?'
            value = revision_value(packet, original, candidate)
        elif ':verify:' in group:
            import json
            pending = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            value = review_value(packet, candidate)
            value['findings'] = []
            value['resolutions'] = [{'issue_id': row['issue_id'],
                'disposition': 'NEEDS_REVISION' if origin == 'blind' and candidate == original else 'FIXED',
                'reason': 'The question needs revision or the revised question asks for both actions.',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                'course_quote': candidate['lessons'][0]['questions'][0]['prompt'], 'source_question': ''}
                for row in pending]
        elif ':review:' in group and 'option-predicates' not in group:
            value = review_value(packet, original)
            if origin == 'blind':
                value['findings'] = []
            finding = compile_editorial_review(value, packet, original)
        else:
            assert 'correct_index' not in messages[1]['content']
            assert original['lessons'][0]['content'] not in messages[1]['content']
            value = predicate_value(packet, candidate, fmt=fmt, wrong_question=(
                'q1' if origin == 'blind' and ':revision:' not in '|'.join(calls) else None))
        wire = view.encode(rule_wire(value, fmt, candidate))
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus,
        CourseIntent(purpose='Training', audience='Staff'), (), stage, max_revisions=3)
    assert result.decision.accepted and not result.decision.feedback
    assert result.course == candidate and _digest(candidate) != _digest(original)
    assert result.course['lessons'][0]['questions'][1] == original['lessons'][0]['questions'][1]
    assert result.history[0]['unverified_revised_prose'] == []
    assert result.history[0]['initial_blind_review'] and result.history[0]['initial_editorial_review_raw']
    assert any(':verify:' in call for call in calls)
    assert calls[-1].startswith('practical:review:option-predicates:v33:')


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['source', 'new_question', 'no_progress', 'unknown'])
async def test_source_question_new_findings_no_progress_and_unknown_outcome(case, mode):
    import json

    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

    corpus, packet, original = case
    view = PracticalModelView(packet)
    candidate = copy.deepcopy(original)
    calls = []

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        calls.append(group)
        if name == 'lesson':
            value = original
        elif ':revision:' in group:
            if mode != 'no_progress':
                candidate['lessons'][0]['questions'][0]['prompt'] = 'Which two actions complete approval?'
            value = revision_value(packet, original, candidate)
        elif ':verify:' in group:
            if mode == 'unknown':
                raise ExtractionOutcomeUnknownError('test_unknown')
            pending = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            value = review_value(packet, candidate)
            value['findings'] = []
            value['resolutions'] = []
            for row in pending:
                source = row['domain'] == 'source'
                disposition = ('SOURCE_AMBIGUITY' if mode == 'source' else
                    'NOT_MATERIAL' if source else 'UNRESOLVED' if mode == 'no_progress' else 'FIXED')
                value['resolutions'].append({'issue_id': row['issue_id'], 'disposition': disposition,
                    'reason': 'Independent source-bound check.', 'source_refs': [packet.blocks[0].block_id],
                    'source_quote': packet.blocks[0].text,
                    'course_quote': '' if source else candidate['lessons'][0]['questions'][0]['prompt'],
                    'source_question': 'Which contradictory source condition applies?' if mode == 'source' else ''})
            first_assessment_verification = ':assessment:' in group and len(
                [c for c in calls if ':verify:' in c and ':assessment:' in c]) == 1
            if mode == 'new_question' and first_assessment_verification:
                value['findings'] = review_value(packet, candidate)['findings']
        elif 'option-predicates' in group:
            value = predicate_value(packet, candidate, fmt=fmt)
        else:
            value = review_value(packet, candidate, domain='assessment' if mode == 'no_progress' else 'source')
        wire = view.encode(rule_wire(value, fmt, candidate))
        validate(wire)
        return wire

    run = run_autonomous_editorial_cycle(packet, corpus,
        CourseIntent(purpose='Training', audience='Staff'), (), stage, max_revisions=3)
    if mode == 'unknown':
        with pytest.raises(ExtractionOutcomeUnknownError):
            await run
        assert len([c for c in calls if ':verify:' in c]) == 1
        assert not any(':revision:' in c for c in calls)
        return
    result = await run
    if mode == 'new_question':
        assert result.decision.accepted and any(':revision:' in c for c in calls)
        assert result.history[0]['revisions_used'] == 1
    elif mode == 'source':
        assert not result.decision.accepted and result.decision.source_uncertain
        assert result.history[0]['confirmed_source_questions'][0]['source_question']
        assert not any(':revision:' in c for c in calls)
    else:
        assert not result.decision.accepted and not result.decision.source_uncertain
        assert result.stop_reason == 'autonomous_edit_no_progress'
        assert result.history[0]['revisions_used'] == 1


@pytest.mark.asyncio
async def test_ordinary_service_autonomous_artifact_does_not_invent_human_defect(case):
    from app.modules.admin.runtime_configuration.catalog import default_snapshot
    from app.modules.admin.runtime_configuration.runtime import runtime_settings_scope
    from app.modules.ai.v3.practical_service import generate_practical_course
    from app.modules.ai.v3.revision_policy import AUTONOMOUS_EDITORIAL_REVIEW_POLICY
    from app.modules.courses.draft_review import read_draft_review

    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        source = source_wire(packet, view, fmt, messages)
        if source is not None:
            return source
        if name == 'practical_course':
            value = course
        elif name in ('v3_practical_rule_editorial_review_v3', 'v3_practical_compact_editorial_review_v2',
                      'v3_practical_editorial_review_v1'):
            value = review_value(packet, course)
            value['findings'] = []
        else:
            value = predicate_value(packet, course, fmt=fmt)
        return view.encode(rule_wire(value, fmt, course))

    with runtime_settings_scope(default_snapshot()):
        artifacts = await generate_practical_course(corpus, intent=CourseIntent(), invoke=invoke,
            source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
            review_policy=AUTONOMOUS_EDITORIAL_REVIEW_POLICY)
    assert len(calls) == 7
    diagnostics = artifacts.diagnostics
    assert diagnostics['automated_review_passed'] is True
    assert diagnostics['draft_review']['content_review_required'] is False
    assert diagnostics['draft_review']['human_review_required'] is True  # Ordinary publication consent.
    assert diagnostics['draft_review']['issues'] == []
    assert read_draft_review({'evidence_v3': diagnostics})['self_review_status'] == 'passed'
    forged = copy.deepcopy(diagnostics)
    forged['v3_review_policy'] = 'v3-practical-source-review-v32'
    with pytest.raises(ValueError, match='draft_review_manifest_invalid'):
        read_draft_review({'evidence_v3': forged})


@pytest.mark.asyncio
async def test_prose_only_edit_reuses_exact_blind_input_and_reinterprets_current_key(case):
    import json

    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

    corpus, packet, original = case
    view = PracticalModelView(packet)
    candidate = copy.deepcopy(original)
    blind_requests = []

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = original
        elif ':revision:' in group:
            candidate['lessons'][0]['content'] += '\nThe approver signs and records the approval.'
            value = revision_value(packet, original, candidate)
        elif ':verify:' in group:
            pending = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            value = review_value(packet, candidate)
            value['findings'] = []
            value['resolutions'] = [{'issue_id': row['issue_id'], 'disposition': 'FIXED',
                'reason': 'Teaching now explicitly states both actions.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text,
                'course_quote': candidate['lessons'][0]['content'], 'source_question': ''} for row in pending]
        elif 'option-predicates' in group:
            blind_requests.append((messages, fmt))
            value = predicate_value(packet, candidate, fmt=fmt)
        else:
            value = review_value(packet, candidate, kind='lesson', target='l1', domain='content')
            if ':assessment:' in group:
                value['findings'] = []
        wire = view.encode(rule_wire(value, fmt, candidate))
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert result.decision.accepted
    assert len(blind_requests) == 1, 'Identical blind model input must not be sent twice after a prose-only edit.'


@pytest.mark.asyncio
async def test_changed_author_key_reinterprets_cached_independent_answer(case):
    import json

    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

    corpus, packet, correct = case
    original = copy.deepcopy(correct)
    original['lessons'][0]['questions'][0]['correct_index'] = 1
    candidate = copy.deepcopy(original)
    view = PracticalModelView(packet)
    blind_calls = 0

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        nonlocal blind_calls
        if name == 'lesson':
            value = original
        elif ':revision:' in group:
            candidate['lessons'][0]['questions'][0]['correct_index'] = 0
            value = revision_value(packet, original, candidate)
        elif ':verify:' in group:
            pending = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            value = review_value(packet, candidate)
            value['findings'] = []
            value['resolutions'] = [{'issue_id': row['issue_id'], 'disposition': ('NEEDS_REVISION' if candidate['lessons'][0]['questions'][0]['correct_index'] != 0 else 'FIXED'),
                'reason': 'The independent answer identifies the current key status.',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                'course_quote': candidate['lessons'][0]['questions'][0]['prompt'], 'source_question': ''}
                for row in pending]
        elif 'option-predicates' in group:
            blind_calls += 1
            value = predicate_value(packet, correct, fmt=fmt)
        else:
            value = review_value(packet, original)
            value['findings'] = []
        wire = view.encode(rule_wire(value, fmt, candidate))
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert result.decision.accepted and result.course == correct
    assert result.history[0]['revisions_used'] == 1 and blind_calls == 1


@pytest.mark.asyncio
async def test_prose_repair_cannot_hide_new_wrong_key_behind_cached_pass(case):
    import json

    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

    corpus, packet, original = case
    candidate = copy.deepcopy(original)
    view = PracticalModelView(packet)
    repairs = 0
    blind_calls = 0

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        nonlocal repairs, blind_calls
        if name == 'lesson':
            value = original
        elif ':revision:' in group:
            before = copy.deepcopy(candidate)
            repairs += 1
            if repairs == 1:
                candidate['lessons'][0]['content'] += '\nBoth required steps must be completed.'
                candidate['lessons'][0]['questions'][0]['correct_index'] = 1
            else:
                candidate['lessons'][0]['questions'][0]['correct_index'] = 0
            value = revision_value(packet, before, candidate)
        elif ':verify:' in group:
            pending = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            value = review_value(packet, candidate)
            value['findings'] = []
            value['resolutions'] = [{'issue_id': row['issue_id'], 'disposition': ('NEEDS_REVISION' if row['target']['kind'] == 'question' and
                    candidate['lessons'][0]['questions'][0]['correct_index'] != 0 else 'FIXED'),
                'reason': 'Current target checked.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'source_question': '',
                'course_quote': candidate['lessons'][0]['content'] if row['target']['kind'] == 'lesson'
                    else candidate['lessons'][0]['questions'][0]['prompt']} for row in pending]
        elif 'option-predicates' in group:
            blind_calls += 1
            value = predicate_value(packet, original, fmt=fmt)
        else:
            value = review_value(packet, candidate, kind='lesson', target='l1', domain='content')
        wire = view.encode(rule_wire(value, fmt, candidate))
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert result.decision.accepted and repairs == 2 and blind_calls == 1
    assert result.course['lessons'][0]['questions'][0]['correct_index'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('origin,disposition', [('map', 'SOURCE_AMBIGUITY'), ('rule', 'SOURCE_AMBIGUITY'),
    ('invalid_quote', 'SOURCE_AMBIGUITY'), ('map', 'NOT_MATERIAL')])
async def test_source_only_proposals_cannot_disappear_or_automatically_become_owner_questions(case, origin, disposition):
    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle
    corpus, packet, course = case
    view = PracticalModelView(packet)
    edits = []

    async def stage(name, group, messages, fmt, validate):
        wire = source_wire(packet, view, fmt, messages)
        if wire is not None:
            value = view.decode(wire)
            if ':source-semantics:read:' in group and origin != 'rule':
                value['uncertainties'] = [{'source_refs': [packet.blocks[0].block_id],
                    'source_quote': 'not present' if origin == 'invalid_quote' else packet.blocks[0].text,
                    'question': 'Which contradictory instruction applies?'}]
            if ':source-semantics:verify:' in group and origin == 'rule':
                value['rule_checks'][0].update(status='SOURCE_AMBIGUITY', source_question='Which contradictory instruction applies?')
        elif name == 'lesson':
            value = course
        elif ':revision:' in group:
            edits.append(group)
            raise AssertionError('Source or evidence uncertainty must not trigger a lesson rewrite')
        elif 'option-predicates' in group:
            value = predicate_value(packet, course, fmt=fmt)
        else:
            value = review_value(packet, course)
            value['findings'] = []
            if ':verify:' in group:
                pending = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1].split('\n', 1)[0])
                value['resolutions'] = [{'issue_id': row['issue_id'], 'disposition': disposition,
                    'reason': 'The course needs an owner choice.' if disposition == 'SOURCE_AMBIGUITY' else 'The known steps can be taught without deciding this detail.',
                    'source_refs': [packet.blocks[0].block_id],
                    'source_quote': 'not present' if origin == 'invalid_quote' else packet.blocks[0].text,
                    'course_quote': '', 'source_question': 'Which contradictory instruction applies?' if disposition == 'SOURCE_AMBIGUITY' else ''}
                    for row in pending]
            value = rule_wire(value, fmt, course)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert not edits
    if disposition == 'NOT_MATERIAL':
        assert result.decision.accepted and not result.decision.source_uncertain
    else:
        assert not result.decision.accepted
        assert result.decision.source_uncertain is (origin != 'invalid_quote')
        assert bool(result.history[0]['confirmed_source_questions']) is (origin != 'invalid_quote')
