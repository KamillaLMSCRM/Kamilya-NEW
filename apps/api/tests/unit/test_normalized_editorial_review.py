import copy

import pytest

from app.modules.ai.v3.normalized_editorial_review import (
    is_normalized_editorial_review_format,
    matches_normalized_editorial_review,
    normalized_editorial_review_format,
    normalized_review_format,
)
from app.modules.ai.v3.practical_editorial_contract import (
    _review_format,
    compile_editorial_review,
    editorial_review_format,
)
from tests.unit.test_v3_editorial_contract import review_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def test_full_course_format_changes_only_name_and_preserves_inputs(case):
    _, packet, course = case
    old = editorial_review_format(packet, course)
    old_snapshot, course_snapshot = copy.deepcopy(old), copy.deepcopy(course)
    fmt = normalized_editorial_review_format(packet, course)
    assert fmt['json_schema']['name'] == 'v3_practical_editorial_review_v2'
    renamed = copy.deepcopy(fmt)
    renamed['json_schema']['name'] = old['json_schema']['name']
    assert renamed == old_snapshot
    assert is_normalized_editorial_review_format(fmt)
    assert not is_normalized_editorial_review_format(old)
    fmt['json_schema']['schema']['properties']['summary']['type'] = 'number'
    assert old == old_snapshot and course == course_snapshot


def test_narrow_format_changes_only_name_and_copies_inputs():
    refs, lessons, questions = ['s1'], ['l1'], ['q1']
    old = _review_format(refs, lessons, questions, 'source', 'course')
    fmt = normalized_review_format(refs, lessons, questions, 'source', 'course')
    renamed = copy.deepcopy(fmt)
    renamed['json_schema']['name'] = old['json_schema']['name']
    assert renamed == old and is_normalized_editorial_review_format(fmt)
    old_snapshot = copy.deepcopy(old)
    refs.append('s2')
    lessons.append('l2')
    questions.append('q2')
    assert renamed == old_snapshot
    assert is_normalized_editorial_review_format(fmt)


@pytest.mark.parametrize('change', ['name', 'extra', 'schema_extra', 'schema_change'])
def test_fake_and_extra_format_properties_rejected(case, change):
    _, packet, course = case
    fmt = normalized_editorial_review_format(packet, course)
    if change == 'name':
        fmt['json_schema']['name'] = 'fake'
    elif change == 'extra':
        fmt['extra'] = True
    elif change == 'schema_extra':
        fmt['json_schema']['schema']['extra'] = True
    else:
        fmt['json_schema']['schema']['properties']['summary']['type'] = 'number'
    assert not is_normalized_editorial_review_format(fmt)
    assert not matches_normalized_editorial_review(review_value(packet, course), fmt)


def test_matching_retains_old_value_semantics(case):
    _, packet, course = case
    fmt = normalized_editorial_review_format(packet, course)
    value = review_value(packet, course)
    fmt_before, value_before = copy.deepcopy(fmt), copy.deepcopy(value)
    assert matches_normalized_editorial_review(value, fmt)
    assert compile_editorial_review(value, packet, course)
    assert fmt == fmt_before and value == value_before
    for key in ('summary', 'findings'):
        invalid = copy.deepcopy(value)
        invalid[key] = None
        assert not matches_normalized_editorial_review(invalid, fmt)
    invalid = copy.deepcopy(value)
    invalid['extra'] = 'unexpected'
    assert not matches_normalized_editorial_review(invalid, fmt)

