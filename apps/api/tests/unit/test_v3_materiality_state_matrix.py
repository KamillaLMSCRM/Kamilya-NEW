"""Decision-table simulation of review states, verdicts and proof completeness.

The oracle defines authority and retention, not whether an LLM understood a rule.
No network, model, database or private course fixture is involved.
"""
import copy
from itertools import product

import pytest

from app.modules.ai.v3.practical_arbitration import evidence_inventory
from tests.unit.test_v3_practical_materiality import apply, issue, row, value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)

KINDS = ('source_coverage', 'lesson_coverage', 'assessment', 'comparison', 'answer', 'lesson', 'source')
STATES = ('raw', 'needs_review', 'source_ambiguity', 'nested_ambiguity', 'nested_needs_review')
VERDICTS = ('MATERIAL_ERROR', 'ALREADY_COVERED', 'STYLE_ONLY', 'NON_MATERIAL', 'SOURCE_AMBIGUITY', 'NEEDS_REVIEW')
PROOFS = ('none', 'prompt', 'prompt_and_choice', 'content')
SCENARIOS = tuple(product(KINDS, STATES, VERDICTS, PROOFS))


def wrap(item, reason, source):
    return {'issue_id':item['issue_id'], 'scope':'source', 'id':source,
            'evidence':{'problem':reason, 'source_refs':[source], 'original_finding':copy.deepcopy(item)}}


@pytest.mark.parametrize('scenario', SCENARIOS, ids=lambda x: '/'.join(x))
def test_review_authority_and_resolution_decision_table(case, scenario):
    _, packet, course = case
    kind, state, verdict, proof = scenario
    source = packet.blocks[0].block_id
    scope, target, purpose = {
        'source_coverage':('coverage',source,None), 'lesson_coverage':('coverage','l1',None),
        'assessment':('assessment','l1',None), 'comparison':('question','q1','COURSE_ASSESSMENT'),
        'answer':('question','q1','ANSWER_VALIDITY'), 'lesson':('lesson','l1',None),
        'source':('source',source,None),
    }[kind]
    original = issue(packet, 'stable-owned-issue', scope, target, purpose)
    held = original
    if state in {'needs_review','nested_needs_review'}:
        held = wrap(held, 'NEEDS_REVIEW', source)
        if state == 'nested_needs_review':
            held = wrap(held, 'NEEDS_REVIEW', source)
    elif state in {'source_ambiguity','nested_ambiguity'}:
        held = wrap(held, 'SOURCE_AMBIGUITY', source)
        if state == 'nested_ambiguity':
            held = wrap(held, 'NEEDS_REVIEW', source)
    inventory = evidence_inventory(course)[0]
    prompt = next(k for k,z in inventory.items() if z['question_id']=='q1' and z['field']=='prompt')
    choice = next(k for k,z in inventory.items() if z['question_id']=='q1' and z['field']=='choice')
    content = next(k for k,z in inventory.items() if z['lesson_id']=='l1' and z['field']=='content')
    evidence = {'none':[], 'prompt':[prompt], 'prompt_and_choice':[prompt,choice], 'content':[content]}[proof]
    answer = None
    if kind == 'answer' and verdict in {'ALREADY_COVERED','STYLE_ONLY'}:
        answer = {'status':'UNIQUE', 'question_id':'q1', 'possible_options':[0],
                  'source_refs':[source], 'reason':'Independent check of this owned question.'}
    response = value(packet, course, [row(held, verdict=verdict, evidence=evidence, answer=answer)])
    if kind == 'answer' and proof == 'content':
        # Blind answer review must reject lesson-prose evidence at the boundary.
        with pytest.raises(ValueError):
            apply(packet, course, [held], response, question_only=True)
        return
    result = apply(packet, course, [held], response, question_only=kind == 'answer')

    # Genuine source ambiguity remains independent of later course judgments.
    source_hold = kind == 'source' or state in {'source_ambiguity','nested_ambiguity'}
    if source_hold:
        assert result.source_uncertain and not result.accepted
        assert len(result.feedback)==1 and result.feedback[0]['issue_id']=='stable-owned-issue'
        assert not (result.lesson_ids or result.question_ids or result.assessment_lesson_ids or result.allow_new_lessons)
        return

    assessed = kind in {'assessment','comparison'}
    if verdict == 'NON_MATERIAL':
        eligible = kind == 'source_coverage' or assessed and proof == 'prompt_and_choice'
        assert result.accepted is eligible
        assert bool(result.feedback) is not eligible
        assert not (result.lesson_ids or result.question_ids or result.assessment_lesson_ids or result.allow_new_lessons)
        if not eligible:
            assert result.source_uncertain
    elif verdict in {'ALREADY_COVERED','STYLE_ONLY'}:
        sufficient = proof != 'none'
        if assessed:
            sufficient = proof == 'prompt_and_choice'
        elif kind == 'answer':
            sufficient = proof in {'prompt','prompt_and_choice'}
        assert result.accepted is sufficient
        assert bool(result.feedback) is not sufficient
        if not sufficient:
            assert result.source_uncertain
    elif verdict in {'SOURCE_AMBIGUITY','NEEDS_REVIEW'}:
        assert result.source_uncertain and not result.accepted
        assert not (result.lesson_ids or result.question_ids or result.assessment_lesson_ids or result.allow_new_lessons)
    else:
        assert verdict == 'MATERIAL_ERROR'
        assert not result.accepted and not result.source_uncertain
        assert result.lesson_ids or result.question_ids or result.assessment_lesson_ids or result.allow_new_lessons
    if result.feedback:
        assert len(result.feedback)==1 and result.feedback[0]['issue_id']=='stable-owned-issue'
