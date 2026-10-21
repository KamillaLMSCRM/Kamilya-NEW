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
    assert model.requests[2]["previous_plan"] == plan() | {"excluded_units": []}


@pytest.mark.asyncio
async def test_cannot_silently_drop_a_source_unit():
    missing = SourceFact("f2", "Пожар", "Эвакуация", "Выведите посетителей.", "doc_id=d1;part=2")
    with pytest.raises(SourcePlanError):
        await build_source_assessment_plan(LESSON, [FACT, missing], [FACT, missing],
                                           client=Model(plan(), audit(), plan(), audit()))


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


@pytest.mark.asyncio
async def test_context_inventory_does_not_become_primary_coverage_or_break_valid_plan():
    context = SourceFact("f2", "II категория", "Область", "Речь о согласовании.", "doc_id=d1;part=2")
    value = plan()
    value["targets"][0]["context"] = [{"ref": "F2", "text": "II категория"}]
    value["dispositions"].append({"ref": "F2", "target_ids": ["call"], "excluded": ""})
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT, context], client=Model(value, audit()))
    assert result.targets[0].context == "II категория"
    assert result.source_target_ids == {"f1": ("call",)}


@pytest.mark.asyncio
async def test_positive_target_survives_another_targets_veto_without_claiming_complete_plan():
    from dataclasses import replace

    second = SourceFact("f2", "Пожар", "Питание", "При необходимости отключите электроэнергию.", "doc_id=d1;part=2")
    lesson = replace(LESSON, content=SOURCE + "\n" + second.value, fact_ids=("f1", "f2"))
    value = plan()
    value["targets"].append({"id": "power", "description": "Условие отключения питания", "source_refs": ["F2"],
                              "context": [], "answer_components": []})
    verdict = {"source_refs": ["F1", "F2"], "source_gaps": [], "target_verdicts": [
        {"target_id": "call", "admit": True, "errors": []},
        {"target_id": "power", "admit": False, "errors": ["Утрачено условие необходимости"]}]}
    result = await build_source_assessment_plan(lesson, [FACT, second], [FACT, second],
                                                client=Model(value, verdict, value, verdict))
    assert result.admitted_target_ids == ("call",)
    assert result.requires_review is True
    assert {target.target_id for target in result.targets} == {"call", "power"}


@pytest.mark.asyncio
async def test_source_gap_keeps_positive_plan_incomplete_and_checkpoint_revalidates_it():
    verdict = {"source_refs": ["F1"], "source_gaps": [{"ref": "F1", "reason": "Упущен отдельный адресат"}],
               "target_verdicts": [{"target_id": "call", "admit": True, "errors": []}]}
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(plan(), verdict, plan(), verdict))
    assert result.admitted_target_ids == ("call",) and result.requires_review
    restored = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(), saved_evidence=result.evidence)
    assert restored.requires_review and restored.unresolved_source_refs == ("F1",) and restored.model_calls == 0


@pytest.mark.asyncio
async def test_silence_is_not_positive_target_admission():
    bad = {"source_refs": ["F1"], "source_gaps": [], "target_verdicts": []}
    with pytest.raises(SourcePlanError):
        await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(plan(), bad, plan(), bad))


@pytest.mark.asyncio
async def test_invalid_repair_cannot_discard_prior_verified_target_or_hide_a_gap():
    verdict = {"source_refs": ["F1"], "source_gaps": [{"ref": "F1", "reason": "Не хватает отдельной цели"}],
               "target_verdicts": [{"target_id": "call", "admit": True, "errors": []}]}
    dropped = plan()
    dropped["targets"][0]["id"] = "unrelated"
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=Model(plan(), verdict, dropped))
    assert result.admitted_target_ids == ("call",) and result.requires_review and result.model_calls == 3


@pytest.mark.asyncio
async def test_all_component_bound_failures_are_returned_in_one_repair_prompt():
    bad = plan()
    bad["targets"][0]["answer_components"] = [{"ref": "F1", "terms": ["x" * 81]},
                                                {"ref": "F1", "terms": ["y" * 85]}]
    model = Model(bad, plan(), audit())
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)
    feedback = model.requests[1]["feedback"]["error"]
    assert "term_length=81" in feedback and "term_length=85" in feedback
    assert result.model_calls == 3


@pytest.mark.asyncio
async def test_server_detects_unmapped_source_even_when_reviewer_forgets_gap():
    missing = SourceFact("f2", "Пожар", "Эвакуация", "Выведите посетителей.", "doc_id=d1;part=2")
    verdict = {"source_refs": ["F1", "F2"], "source_gaps": [],
               "target_verdicts": [{"target_id": "call", "admit": True, "errors": []}]}
    result = await build_source_assessment_plan(LESSON, [FACT, missing], [FACT, missing],
                                               client=Model(plan(), verdict, plan(), verdict))
    assert result.admitted_target_ids == ("call",)
    assert result.source_target_ids["f2"] == ()
    assert result.unresolved_source_refs == ("F2",) and result.requires_review
