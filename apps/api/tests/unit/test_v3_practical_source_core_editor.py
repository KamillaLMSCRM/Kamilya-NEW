import copy
import hashlib
import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_curriculum import validate_curriculum
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_core import prepare_source_core_request
from app.modules.ai.v3.practical_source_core_editor import (
    _contextual_evidence,
    _legacy_bundle,
    matches_source_core_editor,
    prepare_source_core_editor,
)
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from tests.unit.test_v3_practical_curriculum import plan_value
from tests.unit.test_v3_practical_source_core import author_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.parametrize('heading', ['Employees must:', 'Employees must not:'])
@pytest.mark.parametrize('selection', [['E3'], ['E1', 'E3']])
def test_list_evidence_retains_actor_and_polarity(heading, selection):
    lines = [heading + '\n', '- first action\n', '- second action\n']
    text = ''.join(lines)
    block = SimpleNamespace(block_id='owned', text=text)
    offsets = [0, len(lines[0]), len(lines[0]) + len(lines[1])]
    pieces = {f'E{i + 1}': {'source_ref': 'owned', 'text': line, 'start': offsets[i],
              'end': offsets[i] + len(line)} for i, line in enumerate(lines)}
    rendered, custody = _contextual_evidence(SimpleNamespace(blocks=[block]), pieces, selection)
    assert heading in rendered and 'second action' in rendered and 'first action' not in rendered
    assert custody[0]['automatically_added_context'] is ('E1' not in selection)
    assert custody[1]['automatically_added_context'] is False


def test_header_only_selection_uses_whole_block():
    text = 'Employees must not:\n- first action\n- second action\n'
    lines = text.splitlines(keepends=True)
    pieces = {}
    pos = 0
    for i, line in enumerate(lines, 1):
        pieces[f'E{i}'] = {'source_ref': 'owned', 'text': line, 'start': pos, 'end': pos + len(line)}
        pos += len(line)
    rendered, custody = _contextual_evidence(SimpleNamespace(blocks=[SimpleNamespace(block_id='owned', text=text)]), pieces, ['E1'])
    assert rendered == text and custody[0]['context_mode'] == 'whole_block'


def test_uncertain_structure_keeps_whole_block():
    text = 'Employees must not:\n- first action\nException applies:\n- second action\n'
    lines = text.splitlines(keepends=True)
    pos = 0
    pieces = {}
    for i, line in enumerate(lines, 1):
        pieces[f'E{i}'] = {'source_ref': 'owned', 'text': line, 'start': pos, 'end': pos + len(line)}
        pos += len(line)
    rendered, custody = _contextual_evidence(SimpleNamespace(blocks=[SimpleNamespace(block_id='owned', text=text)]), pieces, ['E4'])
    assert rendered == text
    assert custody[0]['context_mode'] == 'whole_block'
    assert custody[0]['automatically_added_context'] is True


def setup_editor(packet, plan, targets=('L1Q1',), holds=()):
    core = prepare_source_core_request(packet, plan, course_title='Source course', source_holds=holds)
    author = author_value(packet, plan, source_holds=holds)
    wire = PracticalModelView(packet).encode(author)
    return core, author, prepare_source_core_editor(core, wire, core.request(), target_ids=targets)


def editor_response(editor, packet):
    fmt = editor.request()['response_format']
    p = fmt['json_schema']['schema']['properties']
    replacements = []
    for target in editor._targets:
        q = copy.deepcopy(editor._cases[target])
        q['prompt'] += ' revised'
        replacements.append({'case_id': target, 'question': q})
    evidence = []
    for case_id, question in editor._cases.items():
        evidence.append({'case_id': case_id, 'piece_ids': [next(key for key, piece in editor._pieces.items()
            if piece['source_ref'] == ref) for ref in question['source_refs']]})
    value = {'source_fingerprint': p['source_fingerprint']['enum'][0], 'editor_fingerprint': p['editor_fingerprint']['enum'][0],
             'author_fingerprint': p['author_fingerprint']['enum'][0], 'replacements': replacements, 'evidence': evidence}
    return PracticalModelView(packet).encode(value)


def test_scoped_update_and_literal_evidence_preserve_peers(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    core, author, editor = setup_editor(packet, plan)
    wire = editor_response(editor, packet)
    fmt = editor.request()['response_format']
    assert response_contract(fmt) == 'practical_source_core_editor' and matches_response_contract(wire, fmt)
    original, _ = core.compile_response(PracticalModelView(packet).encode(author), sent_request=core.request())
    course, metadata = editor.compile_response(wire, sent_request=editor.request())
    assert course['lessons'][0]['questions'][0]['prompt'].endswith(' revised')
    assert course['lessons'][0]['questions'][1]['prompt'] == original['lessons'][0]['questions'][1]['prompt']
    for question in course['lessons'][0]['questions']:
        assert question['explanation'] in packet.blocks[0].text or any(question['explanation'] in b.text for b in packet.blocks)
    assert not metadata['semantic_entailment_verified'] and not metadata['automatic_approval']
    assert len(metadata['evidence_custody']) == 4


def test_unchanged_target_remains_unresolved_while_peer_edit_survives(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, _, editor = setup_editor(packet, plan, targets=('L1Q1', 'L1Q2'))
    view = PracticalModelView(packet)
    value = view.decode(editor_response(editor, packet))
    value['replacements'][0]['question'] = copy.deepcopy(editor._cases['L1Q1'])
    course, metadata = editor.compile_response(view.encode(value), sent_request=editor.request())
    questions = course['lessons'][0]['questions']
    assert questions[0]['prompt'] == editor._cases['L1Q1']['prompt']
    assert questions[1]['prompt'].endswith(' revised')
    assert metadata['unresolved_target_ids'] == ['L1Q1']
    assert metadata['automatic_approval'] is False


@pytest.mark.parametrize('kind', ['missing_case', 'duplicate_case', 'foreign_piece', 'foreign_case', 'wrong_fingerprint', 'duplicate_piece'])
def test_invalid_editor_envelopes_reject(case, kind):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, _, editor = setup_editor(packet, plan)
    value = editor_response(editor, packet)
    if kind == 'missing_case':
        value['evidence'].pop()
    elif kind == 'duplicate_case':
        value['evidence'][1]['case_id'] = value['evidence'][0]['case_id']
    elif kind == 'foreign_piece':
        value['evidence'][0]['piece_ids'] = ['E999999']
    elif kind == 'foreign_case':
        value['replacements'][0]['case_id'] = 'L999Q1'
    elif kind == 'wrong_fingerprint':
        value['editor_fingerprint'] = '0' * 64
    else:
        value['evidence'][0]['piece_ids'] *= 2
    with pytest.raises(ValueError):
        editor.compile_response(value, sent_request=editor.request())


def test_wrong_piece_ownership_and_request_swap_reject(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, _, editor = setup_editor(packet, plan)
    value = editor_response(editor, packet)
    first_ref = editor._cases['L1P1']['source_refs'][0]
    foreign = next((key for key, item in editor._pieces.items() if item['source_ref'] != first_ref), None)
    assert foreign is not None
    value['evidence'][0]['piece_ids'] = [foreign]
    with pytest.raises(ValueError, match='piece_ownership_invalid'):
        editor.compile_response(value, sent_request=editor.request())


def test_partial_owned_evidence_failure_retains_original_and_valid_peer(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, _, editor = setup_editor(packet, plan, targets=('L1Q1', 'L1Q2'))
    value = editor_response(editor, packet)
    first_ref = editor._cases['L1Q1']['source_refs'][0]
    foreign = next(key for key, item in editor._pieces.items() if item['source_ref'] != first_ref)
    next(row for row in value['evidence'] if row['case_id'] == 'L1Q1')['piece_ids'] = [foreign]
    with pytest.raises(ValueError, match='piece_ownership_invalid'):
        editor.compile_response(value, sent_request=editor.request())
    course, metadata = editor.compile_response(value, sent_request=editor.request(), allow_partial=True)
    questions = course['lessons'][0]['questions']
    assert questions[0]['prompt'] == editor._cases['L1Q1']['prompt']
    assert questions[1]['prompt'].endswith(' revised')
    assert metadata['unresolved_cases'] == {'L1Q1': 'evidence_ownership_unverified'}
    assert metadata['evidence_custody']['L1Q1'][0]['context_mode'] == 'unverified_full_block'
    assert not metadata['automatic_approval']
    value['evidence'][0]['piece_ids'] = ['E999999']
    with pytest.raises(ValueError, match='response_invalid'):
        editor.compile_response(value, sent_request=editor.request(), allow_partial=True)
    changed = editor.request()
    changed['messages'][1]['content'] += ' changed'
    with pytest.raises(ValueError, match='request_mismatch'):
        editor.compile_response(editor_response(editor, packet), sent_request=changed)


def test_legacy_author_bundle_is_exact_and_hold_binding_preserved(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    hold = {'note': 'An unresolved source issue.', 'source_refs': [packet.blocks[0].block_id]}
    core = prepare_source_core_request(packet, plan, course_title='Source course', source_holds=(hold,))
    author = PracticalModelView(packet).encode(author_value(packet, plan, source_holds=(hold,)))
    legacy = _legacy_bundle(core.request())
    editor = prepare_source_core_editor(core, author, legacy, target_ids=('L1Q1',))
    assert 'An unresolved source issue.' in editor.request()['messages'][1]['content']
    assert editor._custody['author_bundle_sha256'] != editor._custody['core_bundle_sha256']
    tampered = copy.deepcopy(legacy)
    tampered['messages'][1]['content'] = tampered['messages'][1]['content'].replace('An unresolved source issue.', 'changed')
    with pytest.raises(ValueError, match='author_request_mismatch'):
        prepare_source_core_editor(core, author, tampered, target_ids=('L1Q1',))
    other = copy.deepcopy(legacy)
    other['messages'][0]['content'] += ' arbitrary'
    with pytest.raises(ValueError, match='author_request_mismatch'):
        prepare_source_core_editor(core, author, other, target_ids=('L1Q1',))


def test_seven_lessons_require_exactly_28_evidence_rows_and_empty_targets(case):
    base, _, _ = case
    docs = []
    for i in range(7):
        text = f'Source rule {i + 1}: distinct required action.'
        docs.append(replace(base.documents[0], doc_id=f'doc-{i}', source_text=text,
                            source_revision='document:' + hashlib.sha256(text.encode()).hexdigest()))
    corpus = DirectSourceCorpus(base.tenant_id, tuple(docs), sum(len(x.source_text) for x in docs), 0)
    packet = build_practical_source_packet(corpus)
    groups = audit_units(packet).groups
    sections = [{'title': f'Topic {i}', 'source_units': [unit], 'depends_on_units': [],
        'goals': [{'id': 'model', 'decision': f'Decide {i}', 'essential_case_conditions': [], 'source_refs': list(refs)}]}
        for i, (unit, refs) in enumerate(groups, 1)]
    plan = validate_curriculum({'source_fingerprint': packet.fingerprint, 'sections': sections,
                                'non_teaching_units': [], 'source_uncertainties': []}, packet)
    _, _, editor = setup_editor(packet, plan, targets=())
    value = editor_response(editor, packet)
    assert len(value['evidence']) == 28 and value['replacements'] == []
    assert matches_source_core_editor(value, editor.request()['response_format'])
    course, metadata = editor.compile_response(value, sent_request=editor.request())
    assert sum(len(row['questions']) for row in course['lessons']) == 21
    assert len(metadata['evidence_custody']) == 28


def test_shipped_runner_accepts_editor_schema(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, _, editor = setup_editor(packet, plan)
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location('source_editor_runner', root / 'infra/codex-reserve/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(editor.request()['response_format'])


def test_editor_prompt_contains_source_once_and_only_owned_target_guidance(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    core = prepare_source_core_request(packet, plan, course_title='Source course')
    author = PracticalModelView(packet).encode(author_value(packet, plan))
    guidance = ({'case_id': 'L1Q1', 'note': 'Clarify the case premise.', 'origin': 'HUMAN_REFINEMENT'},)
    editor = prepare_source_core_editor(core, author, core.request(), target_ids=('L1Q1',), guidance=guidance)
    body = editor.request()['messages'][1]['content']
    assert body.count('The approver signs the ticket.') == 1
    assert 'TARGET_IDS_JSON' in body and 'HUMAN_REFINEMENT' in body
    assert all(piece['text'] in next(block.text for block in packet.blocks if block.block_id == piece['source_ref'])
               for piece in editor._pieces.values())
    with pytest.raises(ValueError, match='guidance_invalid'):
        prepare_source_core_editor(core, author, core.request(), target_ids=('L1Q1',),
            guidance=({'case_id': 'L1Q2', 'note': 'outside target', 'origin': 'HUMAN_REFINEMENT'},))


def test_practice_repair_keeps_immutable_source_and_other_questions(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, author, editor = setup_editor(packet, plan, targets=('L1P1',))
    value = editor_response(editor, packet)
    course, metadata = editor.compile_response(value, sent_request=editor.request())
    assert author['lessons'][0]['practice']['prompt'] + ' revised' in course['lessons'][0]['content']
    for block in packet.blocks:
        assert block.text in course['lessons'][0]['content']
    assert len(course['lessons'][0]['questions']) == len(author['lessons'][0]['assessment'])
    assert not metadata['automatic_approval']


def test_unmodified_target_is_not_reported_as_repaired(case):
    _, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    _, _, editor = setup_editor(packet, plan)
    value = editor_response(editor, packet)
    value['replacements'][0]['question'] = PracticalModelView(packet).encode(editor._cases['L1Q1'])
    _, metadata = editor.compile_response(value, sent_request=editor.request())
    assert metadata['unresolved_target_ids'] == ['L1Q1']
    assert metadata['automatic_approval'] is False
