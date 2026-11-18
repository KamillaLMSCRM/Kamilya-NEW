"""Source-review table navigation is opt-in; existing generation units stay stable."""
import pytest

from app.modules.ai.v3.source_units import plan_source_units
from app.modules.source_editorial_review.question_context import contexts


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_spaced_table_navigation_does_not_change_generation_default(newline):
    source = newline.join(['# Catalogue', '', '| Item | Value |', '', '| --- | --- |', '',
        '| A | Two. Two. |', '', '| B | Three. |', '', 'After.'])
    default = plan_source_units(source)
    assert all(unit.kind == 'prose' for unit in default)
    assert ''.join(unit.text for unit in default) == source
    review = plan_source_units(source, allow_spaced_tables=True)
    assert ''.join(unit.text for unit in review) == source
    assert sum(unit.kind == 'table_row' for unit in review) == 2
    context, = contexts(source, [(0, source)])
    assert context is not None
    assert [u.text.strip() for u in context.references.values() if u.kind == 'table_row'] == [
        '| A | Two. Two. |', '| B | Three. |']


def test_compact_table_default_and_review_have_identical_units():
    source = '| Item | Value |\n| --- | --- |\n| A | Two. |\n| B | Three. |\n'
    assert plan_source_units(source) == plan_source_units(source, allow_spaced_tables=True)
