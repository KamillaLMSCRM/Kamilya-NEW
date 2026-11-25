import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.response_contracts import matches_transport_contract
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V12_POLICY
from app.modules.ai.v3.simple_course_block_editor import block_editor_format
from app.modules.ai.v3.simple_course_editor_v12 import apply_branch_edits
from app.modules.ai.v3.simple_course_service import simple_stage_allowed
from app.modules.ai.v3.simple_joint_related_source import companion_branch_targets, select_branch_targets
from app.modules.ai.v3.source_access_contract import access_format


def test_related_branch_is_compared_to_current_owned_paragraph():
    quote = ('Before accepting a regional equipment order, ask for a signed operations approval, '
             'or if the customer has no operations department, request the separate depot confirmation.')
    body = 'Before accepting a regional equipment order, ask for a signed operations approval.'
    payload = {
        'companion_source_refs': ['SRC3'],
        'source_blocks': [{'id': 'SRC3', 'segments': [{'text': quote}]}],
        'original_course': {'lessons': [{'id': 'lesson-owned', 'title': 'Order approval',
                                         'body_blocks': [{'id': 'BODY10', 'text': body}]}]},
    }
    rows = select_branch_targets(companion_branch_targets(payload, {'body_edits': []}))
    assert rows == [{
        'lesson_id': 'lesson-owned', 'lesson_title': 'Order approval', 'block_id': 'BODY10',
        'current_paragraph': body, 'companion_clauses': [{'source_ref': 'SRC3', 'quote': quote}],
    }]
    current = {'body_edits': [{'block_id': 'BODY10', 'after': quote}]}
    assert not companion_branch_targets(payload, current)


@pytest.mark.parametrize('foreign', [False, True])
def test_companion_review_applies_only_addressed_prose_and_adds_its_source(foreign):
    source = 'a' * 64
    draft = 'b' * 64
    scope = [{'block_id': 'BODY1', 'lesson_id': 'lesson-owned',
              'companion_clauses': [{'source_ref': 'SRC3', 'quote': 'An actual supported exception.'}]}]
    fmt = block_editor_format(['SRC3'], source, draft, ['BODY1'])
    original = {
        'body_edits': [{'block_id': 'BODY7', 'after': 'Unrelated and correct.'}],
        'lesson_sources': [{'lesson_id': 'lesson-owned', 'source_refs': ['SRC1']}],
        'source_questions': [], 'question_edits': [{'id': 'stable'}],
    }
    delta = {
        'source_fingerprint': source, 'draft_fingerprint': draft,
        'body_edits': [{'block_id': 'BODY1', 'after': 'Both options are included.'}],
        'title_edits': [], 'question_edits': [], 'added_lessons': [], 'source_questions': [],
        'lesson_sources': [{'lesson_id': 'lesson-peer' if foreign else 'lesson-owned', 'source_refs': ['SRC3']}],
    }
    assert matches_transport_contract(delta, fmt)
    if foreign:
        with pytest.raises(ValueError, match='simple_branch_review_scope_invalid'):
            apply_branch_edits(delta, fmt, scope, original, {'BODY1': 'BODY10'})
        return
    result = apply_branch_edits(delta, fmt, scope, original, {'BODY1': 'BODY10'})
    assert result['body_edits'] == original['body_edits'] + [{'block_id': 'BODY10', 'after': 'Both options are included.'}]
    assert result['lesson_sources'][0]['source_refs'] == ['SRC1', 'SRC3']
    assert result['question_edits'] == original['question_edits']
    assert len(original['body_edits']) == 1


def test_branch_review_is_admitted_by_owned_v12_transport_only_for_bound_scope():
    source, draft, context = 'a' * 64, 'b' * 64, 'c' * 64
    base = f'practical:simple:branch-review:v12:{source}:unit={draft}'
    inner = block_editor_format(['SRC3'], source, draft, ['BODY1'])
    outer = access_format(inner, source, context, base, [])
    group = f'practical:simple:lookup:v12:{source}:base={_digest(base)}:context={context}:round=0:output=32768'

    def allow(stage, scope, response_format):
        return simple_stage_allowed(
            stage, scope, response_format, policy=SIMPLE_COURSE_REVIEW_V12_POLICY, validator=lambda _: None,
        )

    assert allow('repair', group, outer)
    assert not allow('review', group, outer)
    assert not allow('repair', group.replace(context, 'd' * 64), outer)
    wrong_draft = copy.deepcopy(outer)
    wrong_draft['json_schema']['schema']['properties']['results']['items']['properties']['draft_fingerprint']['enum'] = ['e' * 64]
    assert not allow('repair', group, wrong_draft)
