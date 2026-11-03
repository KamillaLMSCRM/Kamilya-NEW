from copy import deepcopy

import pytest

from app.modules.ai.v3.batch_review_response_schema import (
    batch_review_response_format,
    batch_review_schema_hash,
    is_batch_review_response,
    is_batch_review_response_format,
)


def reviews():
    claim = {'claim': 'a', 'status': 'CONTRADICTED', 'reason': 'source'}
    entailment = {'verdict': 'CONTRADICTED', 'claims': [claim], 'summary': 'disagrees'}
    option = {'index': 0, 'verdict': 'CONTRADICTED', 'omitted_required_elements': [],
              'claims': [claim], 'summary': 'disagrees'}
    lesson = {'verdict': 'NEEDS_REVISION', 'factual_score': 2, 'alignment_score': 3.5, 'didactic_score': 4,
              'summary': 'needs revision', 'defects': [{'scope': 'lesson', 'question_id': '',
                                                        'issue': 'issue', 'recommendation': 'fix'}]}
    return [lesson, entailment, {'options': [option]}, {'options': [option]},
            {'answers': [{'index': 0, 'omissions': ['missing']}], 'explanation_review': entailment}]


def test_five_existing_review_shapes_and_unfavorable_verdicts():
    payload = {'items': [{'id': str(i) * 64, 'review': review} for i, review in enumerate(reviews())]}
    assert is_batch_review_response(payload)
    fmt = batch_review_response_format()
    assert is_batch_review_response_format(fmt)
    assert len(batch_review_schema_hash()) == 64
    fmt['json_schema']['strict'] = False
    assert not is_batch_review_response_format(fmt)
    assert is_batch_review_response_format(batch_review_response_format())


@pytest.mark.parametrize('change', ['missing', 'extra', 'bool', 'nonfinite', 'badindex', 'wrongroot'])
def test_shape_rejects_malformed_values(change):
    value = {'items': [{'id': 'a' * 64, 'review': deepcopy(reviews()[0])},
                       {'id': 'b' * 64, 'review': deepcopy(reviews()[2])}]}
    if change == 'missing':
        del value['items'][0]['review']['summary']
    elif change == 'extra':
        value['items'][0]['review']['extra'] = 'x'
    elif change == 'bool':
        value['items'][0]['review']['factual_score'] = True
    elif change == 'nonfinite':
        value['items'][0]['review']['factual_score'] = float('nan')
    elif change == 'badindex':
        value['items'][1]['review']['options'][0]['index'] = 0.5
    else:
        value['extra'] = True
    assert not is_batch_review_response(value)
