"""Positive controls for false rejections found in the frozen pilot."""
import json

from app.modules.ai.evidence_engine.models import SourceFact
from scripts.dev.objective_alignment.engine import parse_plan, parse_quiz


def short_plan():
    return {"objectives": [{"id": "o1", "learner_action": "Различать материалы фасада коллекции",
                            "decision": "Определить материал фасада данной коллекции",
                            "conditions": "При сравнении продукции", "evidence": [{"fact_id": "f1", "quote": "МДФ"}]}],
            "omitted": []}


def test_short_exact_source_is_not_invalid_just_because_it_is_short():
    plan = parse_plan(json.dumps(short_plan()), {"f1": SourceFact("f1", "Север", "Материал", "МДФ", "s1")})
    assert plan.objectives[0].evidence[0].quote == "МДФ"


def test_distinct_wrong_values_can_share_a_general_error_category():
    plan = parse_plan(json.dumps(short_plan()), {"f1": SourceFact("f1", "Север", "Материал", "МДФ", "s1")})
    raw = {"items": [{"objective_id": "o1", "prompt": "Из какого материала выполнен фасад коллекции Север?",
                      "options": [
                          {"text": "МДФ", "correct": True, "action_or_property": "МДФ", "error_mechanism": ""},
                          {"text": "ЛДСП", "correct": False, "action_or_property": "ЛДСП", "error_mechanism": "Перепутан материал"},
                          {"text": "Массив", "correct": False, "action_or_property": "Массив", "error_mechanism": "Перепутан материал"}],
                      "taught_quote": "МДФ", "explanation": "Фасад коллекции Север выполнен из МДФ."}], "unassessable": []}
    assert len(parse_quiz(json.dumps(raw), plan, "Материал фасада: МДФ").items) == 1
