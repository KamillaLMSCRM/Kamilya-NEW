import copy

import pytest

from app.modules.ai.v3.practical_source_comparisons import build_source_comparison_groups
from tests.unit.test_v3_source_comparisons import comparison_case


@pytest.mark.parametrize('budget', [1, 2, 3, 6, 128])
def test_batching_preserves_every_rule_scope_and_dependency_without_rewriting_goals(budget):
    packet, reading, course = comparison_case()
    before = copy.deepcopy((reading, course))
    separate = build_source_comparison_groups(packet, reading, course, max_rules=budget)
    together = build_source_comparison_groups(packet, reading, course, max_rules=budget, coalesce=True)
    assert [goal for group in together for goal in group['goals']] == [
        goal for group in separate for goal in group['goals']]
    assert [key for group in together for key in group['rule_ids']] == [
        key for group in separate for key in group['rule_ids']]
    assert [row for group in together for row in group['logical_groups']] == [
        {key: group[key] for key in ('rule_ids', 'lesson_ids', 'scope', 'source_section')}
        for group in separate]
    assert all(0 < len(group['rule_ids']) <= budget for group in together)
    assert all(group['lesson_ids'] == list(dict.fromkeys(
        key for row in group['logical_groups'] for key in row['lesson_ids'])) for group in together)
    assert len(together) <= len(separate)
    if budget >= 6:
        assert len(separate) == 6 and len(together) == 1
    assert (reading, course) == before
    disputed = next(goal for group in together for goal in group['goals'] if goal['rule_id'] == 'R5')
    assert disputed['status'] == 'SOURCE_AMBIGUITY' and disputed['comparison_status'] == 'UNVERIFIED'


def test_default_comparison_contract_is_unchanged_and_results_are_independent_copies():
    packet, reading, course = comparison_case()
    default = build_source_comparison_groups(packet, reading, course, max_rules=128)
    assert default == build_source_comparison_groups(packet, reading, course, max_rules=128, coalesce=False)
    batched = build_source_comparison_groups(packet, reading, course, max_rules=128, coalesce=True)
    batched[0]['logical_groups'][0]['lesson_ids'].append('foreign')
    batched[0]['goals'][0]['rule']['action'] = 'changed copy'
    assert default == build_source_comparison_groups(packet, reading, course, max_rules=128)


@pytest.mark.parametrize('value', [1, None, 'true'])
def test_batch_policy_is_explicit_boolean(value):
    packet, reading, course = comparison_case()
    with pytest.raises(ValueError, match='source_comparison_coalescing_invalid'):
        build_source_comparison_groups(packet, reading, course, max_rules=128, coalesce=value)
