"""Replay a real model correction without making another provider request."""
import copy
import json
from pathlib import Path

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_source_semantics import (
    compile_source_completeness,
    compile_source_semantics,
    compile_source_semantics_verification,
    source_semantics_context,
    source_semantics_final_rules,
)


def test_model_grammar_revision_changes_binding_without_rewriting_source_or_original_reading():
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/v3/source-qualifier-model-revision.json').read_text(encoding='utf-8'))
    text = fixture['reading']['source_quote']
    doc = DirectSourceDocument('doc', 'Instruction', 'source', 'general', 'immutable', (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    source_ref = packet.blocks[0].block_id
    original = copy.deepcopy(fixture['reading'])
    original['source_refs'] = [source_ref]
    raw = {'source_fingerprint': packet.fingerprint, 'sections': [{'section': 'Assessment', 'rules': [original]}], 'uncertainties': []}
    reading = compile_source_semantics(raw, packet)
    before = copy.deepcopy(reading)
    check = copy.deepcopy(fixture['verification'])
    check['rule_id'] = 'R1'
    check['replacement'][0]['source_refs'] = [source_ref]
    verified = compile_source_semantics_verification({'source_fingerprint': packet.fingerprint,
        'reading_fingerprint': reading['reading_fingerprint'], 'rule_checks': [check], 'additional_rules': []}, packet, reading)
    corrected = verified['interpretations'][0]
    assert corrected['status'] == 'REVISE' and corrected['custody_valid']
    assert corrected['source_question'] == ''
    assert corrected['rule']['conditions'][1]['applies_to'] == 'микрокредит'
    assert original['conditions'][1]['applies_to'] != 'микрокредит'
    assert reading == before and packet.blocks[0].text == text
    context = json.loads(source_semantics_context(verified).split('\nINDEPENDENT_PRE_COURSE_READING_JSON\n')[1].split('\nIndependent pre-course interpretation')[0])
    condition = context['interpretations'][0]['rule']['conditions'][1]
    assert condition['condition_id'] == 'R1.C2' and condition['applies_to'] == 'микрокредит'
    assert verified['original_reading']['original']['sections'][0]['rules'][0] == original
    completed = compile_source_completeness({'source_fingerprint': packet.fingerprint,
        'verified_reading_fingerprint': verified['verified_reading_fingerprint'], 'additional_rules': []}, packet, verified)
    assert source_semantics_final_rules(packet, completed)[0] == corrected
    assert completed['completeness_lineage']['previous'] == verified
