import pytest

from app.modules.ai.evidence_engine.adapters import _narrative_attribute as adapter_attribute
from app.modules.ai.evidence_engine.application import _narrative_attribute as application_attribute


@pytest.mark.parametrize("classify", [adapter_attribute, application_attribute])
@pytest.mark.parametrize("claim", [
    "При частичной приемке нельзя отмечать всю накладную как принятую.",
    "Сотрудник должен записать деньги в журнал.",
    "Сотрудник должен заполнить дневник приемки.",
])
def test_similar_words_are_not_temporal_source_attributes(classify, claim):
    assert classify(claim) != "срок"


@pytest.mark.parametrize("classify", [adapter_attribute, application_attribute])
@pytest.mark.parametrize("claim", [
    "Сообщить в течение 30 минут.", "Сообщить в течение одного часа.",
    "Завершить за три дня.", "Ответить в течение двух месяцев.",
])
def test_real_inflected_units_remain_temporal_source_attributes(classify, claim):
    assert classify(claim) == "срок"
