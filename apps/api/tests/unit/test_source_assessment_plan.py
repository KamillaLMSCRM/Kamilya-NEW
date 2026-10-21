import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.source_assessment_plan import SourcePlanError, build_source_assessment_plan


class Model:
    def __init__(self, *values):
        self.values = iter(values)
        self.requests = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        self.requests.append(json.loads(messages[1]["content"]))
        return SimpleNamespace(value=parser(json.dumps(next(self.values))), attempt_count=1)


SOURCE = "При пожаре немедленно сообщите адрес и свою фамилию."
FACT = SourceFact("f1", "Пожар", "Действия", SOURCE, "doc_id=d1;part=1")
LESSON = LessonDraft("l1", "m", "Пожар", "Действия", SOURCE, ("f1",), (), 1)


def plan():
    return {"targets": [{"id": "call", "description": "Сообщить о пожаре полностью",
        "source_refs": ["F1"], "context": [], "question_format": "",
        "answer_components": [{"ref": "F1", "terms": [term]}
                              for term in ("немедленно", "адрес", "фамили")]}],
        "dispositions": [{"ref": "F1", "target_ids": ["call"], "excluded": ""}]}


def audit():
    return {"admit": True, "target_ids": ["call"], "source_refs": ["F1"],
            "omissions": [], "errors": []}


@pytest.mark.asyncio
async def test_extracts_required_parts_from_source_without_manual_targets():
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(plan(), audit()))
    assert result.targets[0].answer_requirements == (("немедленно",), ("адрес",), ("фамили",))
    assert result.source_target_ids == {"f1": ("call",)}
    assert result.model_calls == 2


@pytest.mark.asyncio
async def test_unproved_context_is_never_used_even_if_model_repeats_it():
    bad = plan()
    bad["targets"][0]["context"] = [{"ref": "F1", "text": "В первую очередь"}]
    with pytest.raises(SourcePlanError):
        await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(bad, bad))


@pytest.mark.asyncio
async def test_incomplete_plan_repaired_before_questions_can_be_authored():
    rejected = audit() | {"admit": False, "omissions": ["Срочность вызова"]}
    model = Model(plan(), rejected, plan(), audit())
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)
    assert result.model_calls == 4
    assert "Срочность вызова" in json.dumps(model.requests[2], ensure_ascii=False)
    assert model.requests[2]["previous_plan"] == plan()


@pytest.mark.asyncio
async def test_cannot_silently_drop_a_source_unit():
    missing = SourceFact("f2", "Пожар", "Эвакуация", "Выведите посетителей.", "doc_id=d1;part=2")
    with pytest.raises(SourcePlanError):
        await build_source_assessment_plan(LESSON, [FACT, missing], [FACT, missing], client=Model(plan(), plan()))


@pytest.mark.asyncio
async def test_full_audit_inventory_required_not_just_admit_true():
    invalid = audit() | {"source_refs": []}
    with pytest.raises(SourcePlanError):
        await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(plan(), invalid, plan(), invalid))


@pytest.mark.asyncio
async def test_source_coverage_is_derived_from_target_refs_not_redundant_model_claims():
    claimed = plan()
    claimed["dispositions"][0]["target_ids"].append("not-a-target")
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(claimed, audit()))
    assert result.source_target_ids == {"f1": ("call",)}
    assert result.evidence["plan"]["dispositions"][0]["target_ids"] == ["call"]
