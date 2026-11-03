import json
from copy import deepcopy

import pytest

from app.modules.ai.v3.typed_review_buckets import (
    BUCKETS,
    build_typed_review_format,
    is_typed_review_format,
    is_typed_review_response,
    normalize_typed_reviews,
)
from tests.unit.test_v3_batch_review_response_schema import reviews


def sample():
    expected = {method: [f'{index:064x}'] for index, method in enumerate(BUCKETS, 1)}
    values = {bucket: [{'id': expected[method][0], 'review': reviews()[index]}]
              for index, (method, bucket) in enumerate(BUCKETS.items())}
    return expected, values


def test_all_negative_shapes_and_deterministic_format():
    expected, value = sample()
    fmt = build_typed_review_format(expected)
    assert is_typed_review_format(fmt) and is_typed_review_response(value, fmt)
    assert len(normalize_typed_reviews(value, fmt)['items']) == 5
    assert fmt == build_typed_review_format(dict(reversed(list(expected.items()))))
    empty = build_typed_review_format({method: [] for method in BUCKETS})
    assert is_typed_review_format(empty)
    assert is_typed_review_response({bucket: [] for bucket in BUCKETS.values()}, empty)


@pytest.mark.parametrize('fault', ['swap', 'foreign', 'duplicate', 'missing', 'extra', 'nonfinite', 'bool', 'tamper'])
def test_fail_closed(fault):
    expected, value = sample()
    fmt = build_typed_review_format(expected)
    if fault == 'swap':
        value['lesson_reviews'][0]['review'] = value['answer_reviews'][0]['review']
    elif fault == 'foreign':
        value['lesson_reviews'][0]['id'] = 'f' * 64
    elif fault == 'duplicate':
        value['lesson_reviews'].append(deepcopy(value['lesson_reviews'][0]))
    elif fault == 'missing':
        value['lesson_reviews'] = []
    elif fault == 'extra':
        value['extra'] = []
    elif fault == 'nonfinite':
        value['lesson_reviews'][0]['review']['factual_score'] = float('nan')
    elif fault == 'bool':
        value['lesson_reviews'][0]['review']['factual_score'] = True
    else:
        fmt['json_schema']['schema']['properties']['lesson_reviews']['maxItems'] = 999
        assert not is_typed_review_format(fmt)
    assert not is_typed_review_response(value, fmt)


def test_ids_unique_across_methods_and_bounded_typical_schema():
    expected, _ = sample()
    expected['review_answer'] = expected['review_lesson'][:]
    with pytest.raises(ValueError):
        build_typed_review_format(expected)
    expected = {method: [f'{index:064x}' for index in range(1 + position * 12, 13 + position * 12)]
                for position, method in enumerate(BUCKETS)}
    fmt = build_typed_review_format(expected)
    assert is_typed_review_format(fmt)
    assert len(json.dumps(fmt).encode()) < 65536
    def dimensions(node, depth=0):
        children = []
        if node.get('type') == 'object':
            children = list(node['properties'].values())
        elif node.get('type') == 'array':
            children = [node['items']]
        measures = [dimensions(child, depth + 1) for child in children]
        return 1 + sum(count for count, _ in measures), max([depth, *(level for _, level in measures)])
    count, depth = dimensions(fmt['json_schema']['schema'])
    assert count <= 512 and depth <= 12
