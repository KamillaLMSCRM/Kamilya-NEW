import pytest

from app.modules.ai.evidence_engine.application import _narrative_attribute
from app.modules.ai.evidence_engine.assessment_axes import _claim_attribute


@pytest.mark.parametrize("classify", [_narrative_attribute, _claim_attribute])
@pytest.mark.parametrize("claim", [
    "Участник набрал не менее 70 процентов по каждой проверочной работе.",
    "Допускается влажность не более 70 процентов.",
])
def test_percentage_alone_is_not_a_financial_condition(classify, claim):
    assert classify(claim) != "финансовое условие"


@pytest.mark.parametrize("classify", [_narrative_attribute, _claim_attribute])
def test_explicit_financial_context_remains_financial(classify):
    assert classify("Ставка вознаграждения составляет 20 процентов.") == "финансовое условие"
