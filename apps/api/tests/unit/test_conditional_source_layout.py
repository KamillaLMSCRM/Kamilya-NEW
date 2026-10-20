"""Display whitespace must not detach a condition from its required action."""
from __future__ import annotations

import re

import pytest

from app.modules.ai.evidence_engine.provider_engine import _readable_source_text


@pytest.mark.parametrize("marker", ["- ", "1) ", "2. ", "- 2) ", "- 2. ", "2. - "])
def test_conditional_branch_keeps_inline_action_dash(marker: str) -> None:
    value = (
        f"{marker}при нахождении пункта в городе - проверка проводится в день выдачи.\n"
        "- при нахождении пункта за городом - проверка проводится при выездной проверке."
    )
    rendered = _readable_source_text(value)
    assert "в городе - проверка" in rendered
    assert "за городом - проверка" in rendered
    assert "\n- при нахождении пункта за городом" in rendered
    assert re.sub(r"\s+", "", rendered) == re.sub(r"\s+", "", value)


def test_ordinary_inline_list_still_splits_and_negative_amount_does_not() -> None:
    value = "Проверить: - описание, - вес, - пробу. Остаток - 10 тенге."
    rendered = _readable_source_text(value)
    assert ":\n- описание,\n- вес,\n- пробу." in rendered
    assert "Остаток - 10 тенге." in rendered


def test_next_conditional_branch_is_not_joined_to_previous_one() -> None:
    value = "- при первом условии - действие первое; - при втором условии - действие второе."
    rendered = _readable_source_text(value)
    assert "- при первом условии - действие первое;\n- при втором условии - действие второе." == rendered


def test_next_numbered_conditional_branch_remains_separate() -> None:
    value = "- 1) при первом условии - действие первое; - 2) при втором условии - действие второе."
    assert _readable_source_text(value) == (
        "- 1) при первом условии - действие первое;\n- 2) при втором условии - действие второе."
    )
