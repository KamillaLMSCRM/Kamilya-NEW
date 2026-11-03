import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.worker_lesson_cycle import WorkerLessonAssessor, create_dev_lesson_assessor
from tests.source_plan_audit_fixture import parse_canned_source_plan_response
from tests.unit.component_contract_fixture import complete_mock_component_fulfillments

RULE = "Обращение рассматривается не более 15 рабочих дней."
FACT = SourceFact("f1", "Обращение", "Срок", RULE, "doc_id=d1;part=1")
LESSON = LessonDraft("l1", "m", "Обращения", "Выбрать срок", RULE, ("f1",), (), 1)


class Journal:
    def __init__(self):
        self.rows = {}
        self.inputs = {}

    async def prepare(self, key, payload):
        assert self.inputs.setdefault(key, payload) == payload
        return deepcopy(self.rows.get(key))

    async def save_value(self, key, value):
        assert key in self.inputs
        self.rows[key] = json.loads(json.dumps(value))

    def _owned_key(self, key):
        return key

    async def inventory_versions(self, base_key):
        from app.modules.ai.worker_lesson_cycle import PLAN_POLICY, POLICY_VERSION
        return [dict(generation_key=key, plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                     plan_payload=deepcopy(plan), module_key="cycle", lesson_key="lesson",
                     assessment_status="completed" if key in self.rows else "pending",
                     assessment_payload=deepcopy(self.rows.get(key)))
                for key, plan in self.inputs.items() if plan.get("inventory_base_key") == base_key]

    async def append_inventory_version(self, key, plan, value):
        existing = await self.prepare(key, plan)
        assert existing is None or existing == value
        await self.save_value(key, value)


class Model:
    def __init__(self, values, *, auto_language=False, canonical=None):
        self.values = iter(values)
        self.calls = 0
        self.requests = []
        self.system_prompts = []
        self.auto_language = auto_language
        self.canonical = canonical

    async def ainvoke_validated(self, messages, parser, **kwargs):
        self.calls += 1
        self.system_prompts.append(messages[0]["content"])
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        if self.auto_language and request.get("task") == "learner_language_review":
            rows = [row | {"acceptable": True, "grammatical": True, "idiomatic": True,
                "cue_free": True, "comparable": True, "reason": "Test transport receipt, not a semantic oracle."}
                for row in request["questions"]]
            rows = [{key: value for key, value in row.items() if key not in {"text", "options"}} for row in rows]
            serialized = json.dumps({"language_reviews": rows})
            return SimpleNamespace(
                value=parse_canned_source_plan_response(parser, serialized, messages),
                attempt_count=1,
            )
        value = deepcopy(next(self.values))
        if self.auto_language and request.get("task") in {"lesson_assessment_review", "lesson_assessment_counterexample"}:
            # The scripted critic must address the actual native candidate, not
            # the old AUTHOR label. No other verdict or source field changes.
            assert len(request["questions"]) == 1
            for row in value["reviews" if request["task"] == "lesson_assessment_review" else "audits"]:
                row["question_id"] = request["questions"][0]["question_id"]
                if self.canonical is not None:
                    row["options"] = [{"index": i, "relation": "supported" if option == self.canonical else "contradicted",
                                       "source_ref": "S1P1"}
                                      for i, option in enumerate(request["questions"][0]["options"])]
        value = complete_mock_component_fulfillments(request, value)
        return SimpleNamespace(
            value=parse_canned_source_plan_response(
                parser, json.dumps(value), messages
            ),
            attempt_count=1,
        )


def responses():
    return [
        {"targets": [{"id": "term", "description": "Предельный срок", "source_refs": ["F1"],
                      "context": [], "question_format": "", "answer_components": []}],
         "dispositions": [{"ref": "F1", "target_ids": ["term"], "excluded": ""}]},
        {"admit": True, "target_ids": ["term"], "source_refs": ["F1"], "errors": [], "omissions": []},
        {"questions": [{"id": "q1", "target_ids": ["term"], "text": "Какой предельный срок рассмотрения обращения?",
                        "options": ["15 рабочих дней", "30 рабочих дней", "45 рабочих дней"]}]},
        {"reviews": [{"question_id": "q1", "educational": True, "lesson_answerable": True,
                      "educational_reason": "Проверяет предельный срок рассмотрения обращения.",
                      "unambiguous": True, "explanation_supported": True, "target_ids": ["term"],
                      "explanation": "Предельный срок — 15 рабочих дней.", "lesson_ref": "L1",
                      "options": [{"index": i, "relation": "supported" if i == 0 else "contradicted",
                                   "source_ref": "S1P1"} for i in range(3)],
                      "option_language": [{"index": i, "grammatical": True,
                                           "reason": "Вариант грамматически согласован с вопросом."}
                                          for i in range(3)]}]},
        {"audits": [{"question_id": "q1", "admit": True, "reason": "Maximum is explicit.",
                     "options": [{"index": i, "relation": "supported" if i == 0 else "contradicted",
                                  "source_ref": "S1P1"} for i in range(3)],
                     "option_language": [{"index": i, "grammatical": True,
                                          "reason": "Вариант грамматически согласован с вопросом."}
                                         for i in range(3)],
                     "target_proofs": [{"target_id": "term", "question_part": "answer", "source_ref": "S1P1"}]}]},
    ]


async def checkpoint():
    pass


@pytest.mark.asyncio
async def test_natural_scenario_worker_preserves_both_scope_receipts_and_zero_call_restore(monkeypatch):
    """Scripted transport proof; not an independent semantic quality oracle."""
    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.evidence_engine.quality import (
        _verified_question_source_rule_identity,
        question_duplicate_key,
        question_has_ambiguous_options,
    )
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan
    from tests.unit.test_natural_scenario import COMPONENT, _packet, _row, _wire_receipts

    packet = _packet()
    source = packet.sources[0].original_text
    fact = SourceFact("source", "Ответственность", "Последствия", source, "doc_id=qa;part=1")
    lesson = LessonDraft("natural-worker", "module", "Ответственность", "Последствие", source, ("source",), (), 1)

    async def planned(*args, **kwargs):
        return SourceAssessmentPlan(packet.targets, {"source": ("liability",)}, {}, 0, 0,
                                    admitted_target_ids=("liability",))

    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    maps = [{"target_id": "liability", "component_id": "liability:C1", "source_ref": "S1P1",
             "realizations": [{"part": "answer", "role": "discriminating_answer", "whole_part": True}]}]
    vector = [{"index": i, "relation": "supported" if i == 0 else "contradicted", "source_ref": "S1P1"}
              for i in range(2)]
    common = {"question_id": "q1", "options": vector, "component_realizations": maps,
              "qualification_realizations": _wire_receipts(packet)}
    values = [
        {"questions": [_row()]},
        {"reviews": [{**common, "educational": True, "educational_reason": "Проверяет последствие ошибки оценки.",
                       "lesson_answerable": True, "unambiguous": True, "explanation_supported": True,
                       "target_ids": ["liability"], "explanation": source, "lesson_ref": "L1"}]},
        {"audits": [{**common, "admit": True, "reason": "Полное условие и единственное последствие.",
                      "target_proofs": [{"target_id": "liability", "question_part": "answer", "source_ref": "S1P1"}]}]},
    ]
    journal, model = Journal(), Model(values, auto_language=True)
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal,
        checkpoint=checkpoint, learner_language_gate=True)(lesson, {"source": fact})
    assert len(result.questions) == 1 and model.calls == 4
    exported = result.questions[0]
    assert exported.correct_answer == COMPONENT
    assert exported.options == (COMPONENT, "не " + COMPONENT)
    assert exported.prompt.startswith("Ситуация: ")
    assert question_duplicate_key(exported) == exported.assessment_inventory_identity
    assert exported.assessment_inventory_identity
    assert exported.source_rule_identity == exported.source_rule_focus == ""
    assert _verified_question_source_rule_identity(exported) is None
    assert not question_has_ambiguous_options(exported)
    from dataclasses import replace

    tampered = replace(exported, prompt=exported.prompt + " Другие условия.")
    assert question_duplicate_key(tampered) != exported.assessment_inventory_identity
    cycle_key = next(key for key in journal.rows if key.startswith("lesson-cycle:"))
    stored = journal.rows[cycle_key]["questions"][0]
    assert stored["learner_premise"] and len(stored["qualification_realizations"]) == 3
    assert len(stored["semantic_audit"]["qualification_realizations"]) == 3
    restored_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=restored_model, journal=journal,
        checkpoint=checkpoint, learner_language_gate=True)(lesson, {"source": fact})
    assert restored.questions == result.questions and restored_model.calls == 0
    for field, replacement in (("learner_premise", "Другие условия."), ("qualification_realizations", [])):
        original = stored[field]
        stored[field] = replacement
        with pytest.raises(ValueError, match="checkpoint_invalid"):
            await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=journal,
                checkpoint=checkpoint, learner_language_gate=True)(lesson, {"source": fact})
        stored[field] = original


@pytest.mark.asyncio
@pytest.mark.parametrize("language_gate", [False, True])
async def test_source_proposition_worker_exports_bound_dedup_not_source_rule_exemption(monkeypatch, language_gate):
    """Mock only planning; run actual author/two critics/checkpoint/export seams."""
    from dataclasses import replace

    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.evidence_engine.quality import _verified_question_source_rule_identity, question_duplicate_key
    from app.modules.ai.lesson_cycle import LearningTarget
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan

    # This export contract belongs to the authored compound path. A genuinely
    # atomic rule now intentionally bypasses AUTHOR in language-gated mode.
    actor, condition, base = ("Оценщикам", "при отсутствии согласования",
                              "категорически запрещается продлевать договор и скрывать отсутствие согласования")
    source = f"{actor} {condition} {base}."
    fact = SourceFact("f1", "Продление", "Правило", source, "doc_id=qa;part=1")
    lesson = LessonDraft("l1", "m", "Продление", "Правило", source, ("f1",), (), 1)
    bindings = tuple({"facet_id": role, "source_id": "f1", "quote": quote, "role": role,
                      "branch_effect": "none" if role == "actor" else "scopes_action",
                      "quote_start": source.index(quote), "quote_end": source.index(quote) + len(quote)}
                     for role, quote in (("actor", actor), ("condition", condition)))
    target = LearningTarget("term", "Продление", answer_requirements=((base,),),
                            component_source_ids=(("f1",),), qualification_bindings=bindings)

    async def planned(*args, **kwargs):
        return SourceAssessmentPlan((target,), {"f1": ("term",)}, {}, 0, 0, admitted_target_ids=("term",))

    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    options = [base.capitalize(), "разрешается продлевать договор и скрывать отсутствие согласования",
               "обязательно продлевать договор и скрывать отсутствие согласования"]
    values = responses()[2:]
    values[0]["questions"] = [{"id": "q1", "target_ids": ["term"], "intent": "source_proposition", "options": options}]
    if language_gate:
        values[0]["questions"][0].pop("options")
        values[0]["questions"][0]["alternatives"] = options[1:]
    maps = [{"target_id": "term", "component_id": "term:C1", "source_ref": "S1P1",
             "realizations": [{"part": "answer", "role": "discriminating_answer", "whole_part": True}]}]
    values[1]["reviews"][0].update(explanation=source, component_realizations=maps)
    values[2]["audits"][0].update(component_realizations=maps)
    if language_gate:
        values[1]["reviews"][0].pop("option_language")
        values[2]["audits"][0].pop("option_language")
    journal, model = Journal(), Model(values, auto_language=language_gate, canonical=base if language_gate else None)
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal,
        checkpoint=checkpoint, learner_language_gate=language_gate)(lesson, {"f1": fact})
    assert len(result.questions) == 1 and model.calls == (4 if language_gate else 3)
    exported = result.questions[0]
    assert "complete relative to these shared premises" in model.system_prompts[0]
    assert "including opposite modality" in model.system_prompts[0]
    assert "do not invent a permission or contrary duty" not in model.system_prompts[0]
    if language_gate:
        reviewed = next(row for row in model.requests if row.get("task") == "lesson_assessment_review")["questions"][0]
        assert exported.options == tuple(reviewed["options"])  # No post-review shuffle.
        assert exported.correct_answer == base and base in exported.source_quote
    else:
        assert exported.correct_answer == options[0] and exported.correct_answer not in exported.source_quote
    assert exported.assessment_inventory_identity.startswith("source-proposition:")
    assert question_duplicate_key(exported) == exported.assessment_inventory_identity
    assert exported.source_rule_identity == "" and _verified_question_source_rule_identity(exported) is None
    changed = replace(exported, prompt=exported.prompt + " Другой вопрос?")
    assert question_duplicate_key(changed) == " ".join(changed.prompt.casefold().replace("ё", "е").split())
    restored_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=restored_model, journal=journal,
        checkpoint=checkpoint, learner_language_gate=language_gate)(lesson, {"f1": fact})
    assert restored.questions == result.questions and restored_model.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["несут солидарную ответственность", "предусмотрена дисциплинарная ответственность"])
async def test_ordinary_binary_identity_survives_real_cycle_worker_export_and_zero_call_restore(base):
    from app.modules.ai.evidence_engine.quality import question_has_ambiguous_options

    source = "При нарушении стандарта " + base + "."
    fact = SourceFact("f1", "Последствия", "Мера", source, "doc_id=d1;part=1")
    lesson = LessonDraft("l1", "m", "Последствия", "Мера", source, ("f1",), (), 1)
    values = responses()
    values[0]["targets"][0].update(description="Последствие", answer_components=[{"ref": "F1", "terms": [base]}])
    values[2]["questions"][0].update(text="Какое последствие предусмотрено при нарушении стандарта?",
                                    options=[base, "не " + base])
    maps = [{"target_id": "term", "component_id": "term:C1", "source_ref": "S1P1",
             "realizations": [{"part": "answer", "role": "discriminating_answer", "whole_part": True}]}]
    vector = [{"index": i, "relation": "supported" if i == 0 else "contradicted", "source_ref": "S1P1"}
              for i in range(2)]
    language = [{"index": i, "grammatical": True, "reason": "Самостоятельное грамматически корректное утверждение"}
                for i in range(2)]
    values[3]["reviews"][0].update(options=vector, explanation=source, option_language=language, component_realizations=maps)
    values[4]["audits"][0].update(options=vector, option_language=language, component_realizations=maps)
    journal, model = Journal(), Model(values)
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)(lesson, {"f1": fact})
    assert len(result.questions) == 1 and model.calls == 5
    exported = result.questions[0]
    assert exported.correct_answer == base and exported.source_rule_identity.startswith("source-rule:")
    assert exported.source_rule_focus == base.split()[0]
    assert not question_has_ambiguous_options(exported)
    no_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=no_model, journal=journal, checkpoint=checkpoint)(lesson, {"f1": fact})
    assert restored.questions == result.questions and no_model.calls == 0


@pytest.mark.asyncio
async def test_reviewed_ordinary_competency_exports_exact_bound_dedup_identity(monkeypatch):
    from dataclasses import replace

    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.evidence_engine.quality import question_duplicate_key, question_has_ambiguous_options
    from app.modules.ai.lesson_cycle import LearningTarget, LessonCycleResult, ReviewedQuestion
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan

    component = "пользоваться электронагревательными приборами"
    source = "Сотрудникам запрещается " + component + "."
    fact = SourceFact("f1", "Пожарная безопасность", "Запрет", source, "doc_id=qa;part=1")
    lesson = LessonDraft("fire", "module", "Пожарная безопасность", "Запреты", source, ("f1",), (), 1)
    target = LearningTarget("author-row-7", "Запрет приборов", answer_requirements=((component,),),
                            source_ids=("f1",), component_source_ids=(("f1",),))

    async def planned(*args, **kwargs):
        return SourceAssessmentPlan((target,), {"f1": ("author-row-7",)}, {}, 0, 0,
                                    admitted_target_ids=("author-row-7",))

    async def reviewed(packets, **kwargs):
        packet = packets[0]
        owner = packet.targets[0].component_source_ids[0][0]
        question = ReviewedQuestion(
            "native", ("author-row-7",),
            "Что запрещается сотрудникам ломбарда в помещениях организации?",
            (component, component + " по инструкции"), 0,
            "Источник устанавливает конкретный запрет.", source,
            ({"index": 0, "relation": "supported", "source_id": owner, "quote": source},
             {"index": 1, "relation": "contradicted", "source_id": owner, "quote": source}),
            semantic_audit={"target_proofs": [
                {"target_id": "author-row-7", "source_id": owner, "quote": source}
            ]},
        )
        return [LessonCycleResult(packet.tenant_id, packet.identity(), packet.lesson_id,
                                  "ready_for_methodologist", (question,), (), 4, 0.0, ())]

    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    monkeypatch.setattr(worker, "run_lesson_cycles", reviewed)
    result = await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=Journal(),
        checkpoint=checkpoint, learner_language_gate=True)(lesson, {"f1": fact})

    exported = result.questions[0]
    assert exported.assessment_inventory_identity.startswith("ordinary-competency:")
    assert question_duplicate_key(exported) == exported.assessment_inventory_identity
    assert exported.source_rule_identity == ""
    assert question_has_ambiguous_options(exported)
    for changed in (
        replace(exported, prompt=exported.prompt + " Иное условие."),
        replace(exported, options=tuple(reversed(exported.options))),
        replace(exported, correct_answer=exported.options[1]),
        replace(exported, source_quote="Другой источник"),
        replace(exported, evidence_fact_ids=("foreign",)),
        replace(exported, semantic_reviewed=False),
    ):
        assert question_duplicate_key(changed) != exported.assessment_inventory_identity


@pytest.mark.asyncio
@pytest.mark.parametrize("component_count", [2, 3])
async def test_native_worker_selects_component_constructor_before_packet_journal_and_cycle(monkeypatch, component_count):
    """Exercise native planner/ownership selection, not fake semantic acceptance."""
    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.lesson_cycle import LessonCycleResult

    clauses = ["проверить журнал", "закрыть шкаф", "выключить свет"][:component_count]
    source = "; ".join(clauses)
    fact = SourceFact("f1", "Завершение работы", "Действие", source, "doc_id=d1;part=1")
    lesson = LessonDraft("l1", "m1", "Завершение работы", "Действие", source, ("f1",), (), 1)
    values = [
        {"targets": [{"id": "action", "description": "Закрытие шкафа", "source_refs": ["F1"],
                      "context": [], "answer_components": [
                          {"ref": "F1", "terms": [clause]} for clause in clauses]}]},
        {"source_refs": ["F1"], "source_gaps": [], "target_verdicts": [
            {"target_id": "action", "admit": True, "errors": []}]},
    ]
    journal, model, packets = Journal(), Model(values), []

    async def inspect_native_packet(packets_arg, **kwargs):
        p = packets_arg[0]
        packets.append(p)
        assert len(p.targets) == 1 and len(p.targets[0].answer_requirements) == component_count
        assert p.targets[0].component_construction is (component_count == 2)
        assert p.targets[0].component_source_ids == ((worker._digest(worker.asdict(fact)),),) * component_count
        assert journal.inputs["lesson-cycle:" + p.identity()]["packet"]["targets"][0]["component_construction"] is (component_count == 2)
        return [LessonCycleResult(p.tenant_id, p.identity(), p.lesson_id, "review_required", (),
                                  ("action",), 0, 0.0, ())]

    monkeypatch.setattr(worker, "run_lesson_cycles", inspect_native_packet)
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal,
                                       checkpoint=checkpoint)(lesson, {"f1": fact})
    assert len(packets) == 1 and model.calls == 2
    assert not result.questions and result.audit["coverage"]["missing_target_ids"] == ["action"]


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_context,primary_context", [(False, False), (True, True), (True, False)])
async def test_partition_ownership_survives_planner_packet_and_question_export(
    monkeypatch, shared_context, primary_context,
):
    """Isolate ownership export, not semantic admission, at the cycle boundary."""
    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.lesson_cycle import LessonCycleResult, ReviewedQuestion

    clauses = [
        "отключить от электросети все электроприборы за исключением разрешенных приборов круглосуточного действия, а также дежурного и аварийного освещения",
        "визуально убедиться в исправности систем пожаротушения (если таковые имеются) и пожарной сигнализации",
    ]
    facts = {
        f"f{i}": SourceFact(f"f{i}", "Закрытие", "Действие", clause, f"doc_id=qa;part={i}")
        for i, clause in enumerate(clauses, 1)
    }
    context = []
    if shared_context:
        facts["f3"] = SourceFact("f3", "Закрытие", "Условие", "После окончания работы.", "doc_id=qa;part=3")
        context = [{"ref": "F3", "text": facts["f3"].value}]
    value = {"targets": [{"id": "parent", "description": "Действия при закрытии",
        "source_refs": ["F1", "F2", *(["F3"] if primary_context else [])], "context": context,
        "answer_components": [{"ref": f"F{i}", "terms": [clause]} for i, clause in enumerate(clauses, 1)]}]}

    class Planner(Model):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            self.requests.append(request)
            if "plan" in request:
                rows = request["plan"]["targets"]
                assert len(rows) == 2
                assert [row["source_refs"] for row in rows] == [
                    [f"F{i}", *(["F3"] if primary_context else [])] for i in (1, 2)]
                response = {"source_refs": value["targets"][0]["source_refs"], "source_gaps": [],
                    "target_verdicts": [{"target_id": row["id"], "admit": True, "errors": []} for row in rows]}
            else:
                response = value
            return SimpleNamespace(
                value=parse_canned_source_plan_response(
                    parser, json.dumps(response), messages
                ),
                attempt_count=1,
            )

    packets = []

    async def ownership_cycle(packets_arg, **kwargs):
        p = packets_arg[0]
        packets.append(p)
        questions = []
        for index, target in enumerate(p.targets, 1):
            expected = tuple(worker._digest(worker.asdict(facts[fid])) for fid in
                             [f"f{index}", *(["f3"] if primary_context else [])])
            assert target.source_ids == expected
            assert target.component_source_ids == ((expected[0],),)
            assert target.context == (facts["f3"].value if shared_context else "")
            if shared_context:
                assert any(source.source_id == worker._digest(worker.asdict(facts["f3"])) for source in p.sources)
            questions.append(ReviewedQuestion(
                f"q{index}", (target.target_id,), f"Действие {index}?", (clauses[index - 1], "Иное действие"),
                0, "Проверка только экспорта принадлежности источнику.", clauses[index - 1],
                ({"index": 0, "source_id": expected[0], "quote": clauses[index - 1]},)))
        return [LessonCycleResult(p.tenant_id, p.identity(), p.lesson_id, "ready_for_methodologist",
                                  tuple(questions), (), 0, 0.0, ())]

    monkeypatch.setattr(worker, "run_lesson_cycles", ownership_cycle)
    lesson = LessonDraft("l1", "m1", "Закрытие", "Действия", "\n".join(f.value for f in facts.values()),
                         ("f1", "f2", *(("f3",) if primary_context else ())), (), 1)
    result = await WorkerLessonAssessor(tenant_id="qa", client=Planner([]), journal=Journal(),
                                       checkpoint=checkpoint)(lesson, facts)
    assert len(packets) == 1 and len(result.questions) == 2
    assert [q.evidence_fact_ids for q in result.questions] == [
        (f"f{i}", *(["f3"] if primary_context else [])) for i in (1, 2)]
    assert result.audit["source_plan"]["plan"]["dispositions"] == [
        {"ref": f"F{i}", "target_ids": [packets[0].targets[i - 1].target_id], "excluded": ""}
        for i in (1, 2)
    ] + ([{"ref": "F3", "target_ids": [t.target_id for t in packets[0].targets], "excluded": ""}]
         if primary_context else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle_rejects", [False, True])
async def test_quote_worker_reconciles_actual_questions_not_only_planned_targets_and_restores(cycle_rejects):
    source = "Сотрудник должен проверить мусор (при проведении ремонтных работ)."
    focus = "при проведении ремонтных работ"
    fact = SourceFact("f1", "Проверка", "Условие", source, "doc_id=d1;part=1")
    lesson = LessonDraft("l1", "m", "Проверка", "Условие", source, ("f1",), (), 1)

    class QuoteModel(Model):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            self.calls += 1
            self.requests.append(request)
            task = request.get("task")
            if task in {"lesson_assessment_author", "lesson_assessment_repair"}:
                value = {"questions": [{"id": "q1", "target_ids": ["condition"], "intent": "source_quote_slot",
                    "alternatives": ["перед началом рабочей смены", "после замены оборудования"]}]}
            elif task is not None:
                q = request["questions"][0]
                key = q["options"].index(focus)
                row = {"question_id": q["question_id"],
                    "options": [{"index": i, "relation": "supported" if i == key else "contradicted",
                                 "source_ref": "S1P1"} for i in range(len(q["options"]))],
                    "option_language": [{"index": i, "grammatical": not cycle_rejects, "reason": "Проверена грамматика"}
                                        for i in range(len(q["options"]))],
                    "option_recall": [{"index": i, "slot_faithful": i == key, "material_difference": i != key,
                                       "reason": "Проверено исходное условие"} for i in range(len(q["options"]))],
                    "component_realizations": [{"target_id": "condition", "component_id": "condition:C1",
                        "source_ref": "S1P1", "realizations": [
                            {"part": "answer", "role": "discriminating_answer", "whole_part": True}]}]}
                if task == "lesson_assessment_review":
                    row.update(educational=True, lesson_answerable=True, unambiguous=True, explanation_supported=True,
                               educational_reason="Проверяет условие выполнения действия из исходного правила.",
                               target_ids=["condition"], explanation=source, lesson_ref="L1")
                    value = {"reviews": [row]}
                else:
                    row.update(admit=True, reason="Проверено положение документа", target_proofs=[
                        {"target_id": "condition", "question_part": "answer", "source_ref": "S1P1"}])
                    value = {"audits": [row]}
            elif "plan" in request:
                value = {"source_refs": ["F1"], "source_gaps": [], "target_verdicts": [
                    {"target_id": "condition", "admit": True, "errors": []}]}
            else:
                value = {"targets": [{"id": "condition", "description": "Условие из формулировки документа",
                    "source_refs": ["F1"], "context": [], "construction_mode": "source_quote_slot",
                    "assessed_focus": focus, "answer_components": [{"ref": "F1", "terms": [focus]}],
                    "source_quote_proposition": {"source_id": "F1", "quote": source}}], "material_obligations": [
                        {"id": "O1", "ref": "F1", "quote": focus, "dimension": "condition",
                         "target_ids": ["condition"], "evidence_level": "source_recognition"}]}
            value = complete_mock_component_fulfillments(request, value)
            return SimpleNamespace(
                value=parse_canned_source_plan_response(
                    parser, json.dumps(value, ensure_ascii=False), messages
                ),
                attempt_count=1,
            )

    journal, model = Journal(), QuoteModel([])
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)(lesson, {"f1": fact})
    coverage = result.audit["coverage"]
    assert coverage["material_inventory_present"] is True
    assert coverage["material_obligation_count"] == 1
    assert coverage["unresolved_obligation_ids"] == (["O1"] if cycle_rejects else [])
    assert coverage["covered_obligations_by_level"] == {
        "source_recognition": 0 if cycle_rejects else 1, "operational_decision": 0}
    # Condition recognition alone cannot close the explicit operational duty.
    assert coverage["requires_review"] is True
    assert result.audit["source_plan"]["plan"]["source_coverage_errors"] == [{
        "ref": "F1", "reason": "prescriptive_source_without_operational_action",
        "required_evidence_level": "operational_decision"}]
    assert len(result.questions) == (0 if cycle_rejects else 1)
    no_model = QuoteModel([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=no_model, journal=journal, checkpoint=checkpoint)(lesson, {"f1": fact})
    assert restored.questions == result.questions and restored.audit["coverage"] == coverage and no_model.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("focus", ["", "закрыть"])
async def test_source_edit_worker_json_checkpoint_restores_without_inference(focus):
    from app.modules.ai.lesson_cycle import LearningTarget, SourceExcerpt
    from app.modules.ai.source_rule_construction import build_rule_spec, construct_rule_options

    rule = "Сотрудник обязан закрыть дверь"
    edits = [{"token_span": [3, 3], "replacement": "открыть"}]
    target = LearningTarget("term", "Закрытие", answer_requirements=((rule,),), source_ids=("f1",),
        component_source_ids=(("f1",),), construction_mode="source_edit_rule", assessed_focus=focus)
    spec = build_rule_spec(target, (SourceExcerpt("f1", rule, rule),))
    options = construct_rule_options(spec, edits, "q1")
    fact = SourceFact("f1", "Завершение", "Действие", rule, "doc_id=d1;part=1")
    lesson = LessonDraft("l1", "m", "Завершение", "Действие", rule, ("f1",), (), 1)
    values = responses()
    values[0]["targets"][0].update(description="Закрытие", construction_mode="source_edit_rule",
        answer_components=[{"ref": "F1", "terms": [rule]}], assessed_focus=focus)
    values[2] = {"questions": [{"id": "q1", "target_ids": ["term"], "intent": "source_edit_rule",
        "alternatives": ["Сотрудник обязан открыть дверь"]}]}
    maps = [{"target_id": "term", "component_id": "term:C1", "source_ref": "S1P1",
             "realizations": [{"part": "answer", "role": "discriminating_answer", "whole_part": True}]}]
    vector = [{"index": index, "relation": "supported" if option == rule else "contradicted",
               "source_ref": "S1P1"} for index, option in enumerate(options)]
    values[3]["reviews"][0].update(options=vector, explanation=rule, component_realizations=maps)
    values[4]["audits"][0].update(options=vector, component_realizations=maps)
    language = [{"index": index, "grammatical": True, "reason": "Грамматика проверена"}
                for index in range(len(options))]
    values[3]["reviews"][0]["option_language"] = language
    values[4]["audits"][0]["option_language"] = language
    journal = Journal()
    model = Model(values)
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)(lesson, {"f1": fact})
    assert len(result.questions) == 1 and result.questions[0].correct_answer == rule
    assert result.questions[0].source_rule_identity == spec.inventory_key
    assert result.questions[0].source_rule_focus == focus
    from app.modules.ai.evidence_engine.quality import question_duplicate_key

    assert question_duplicate_key(result.questions[0]) == spec.inventory_key
    assert model.calls == 5
    stored = [value for key, value in journal.rows.items() if key.startswith("lesson-cycle:")][0]
    assert isinstance(stored["questions"][0]["source_edits"], list)
    no_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=no_model, journal=journal, checkpoint=checkpoint)(lesson, {"f1": fact})
    assert restored.questions == result.questions and no_model.calls == 0


@pytest.mark.parametrize("environment,flag,enabled", [
    ("render-development", True, True), ("render-development-worker", True, True),
    ("kz-production", True, False), ("production", True, False), ("local", True, False),
    ("render-development-worker", False, False),
])
def test_only_exact_dev_runtime_can_select_new_pipeline(environment, flag, enabled):
    result = create_dev_lesson_assessor(settings=SimpleNamespace(DEPLOYMENT_ENVIRONMENT=environment,
        APP_ENV="production", AI_LESSON_CYCLE_DEV_ENABLED=flag, AI_LESSON_CYCLE_DEV_TENANTS=["qa"]), tenant_id="qa", job_id="job",
        client=Model([]), session_factory=None, checkpoint=checkpoint)
    assert (result is not None) == enabled
    if result is not None:
        # Native DEV acceptance must use the teaching/language mode exercised
        # by the full local course diagnostic, not the constructor's legacy default.
        assert result.learner_language_gate is True


def test_other_dev_tenants_keep_the_existing_pipeline():
    result = create_dev_lesson_assessor(settings=SimpleNamespace(DEPLOYMENT_ENVIRONMENT="render-development-worker",
        AI_LESSON_CYCLE_DEV_ENABLED=True, AI_LESSON_CYCLE_DEV_TENANTS=["qa"]), tenant_id="another", job_id="job",
        client=Model([]), session_factory=None, checkpoint=checkpoint)
    assert result is None


@pytest.mark.asyncio
async def test_worker_automatically_plans_reviews_saves_and_restores_without_more_model_calls():
    journal = Journal()
    model = Model(responses())
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert result.questions[0].correct_answer == "15 рабочих дней"
    assert result.questions[0].source_rule_identity == ""
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["coverage"]["material_inventory_present"] is False
    assert result.audit["terminal_status"] == "review_required"
    assert model.calls == 5
    restored_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=restored_model, journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert restored.questions == result.questions
    assert restored_model.calls == 0


@pytest.mark.asyncio
async def test_worker_preserves_complete_literal_operational_proposition_through_checkpoint():
    proposition = (
        "Перед уходом сотрудник обязан проверить рабочее место, отключить все электроприборы "
        "и закрыть окна помещения."
    )
    wrong = (
        "Перед уходом сотрудник обязан оставить электроприборы включенными "
        "и окна помещения открытыми."
    )
    fact = SourceFact("f1", "Уход", "Полная операция", proposition, "doc_id=d1;part=1")
    lesson = LessonDraft("l1", "m", "Уход", "Полная операция", proposition, ("f1",), (), 1)
    values = responses()
    values[0]["targets"][0].update(
        description="Полная операция перед уходом",
        answer_components=[{"ref": "F1", "terms": [proposition]}],
    )
    candidate = values[2]["questions"][0]
    candidate.update(text="Что обязан сделать сотрудник перед уходом?", options=[proposition, wrong])
    component_map = [{
        "target_id": "term", "component_id": "term:C1", "source_ref": "S1P1",
        "realizations": [{"part": "answer", "role": "discriminating_answer", "quote": proposition}],
    }]
    review = values[3]["reviews"][0]
    review.update(
        explanation="Исходная операция приведена полностью.",
        options=[{"index": index, "relation": "supported" if index == 0 else "contradicted",
                  "source_ref": "S1P1"} for index in range(2)],
        option_language=[{"index": index, "grammatical": True,
                          "reason": "Вариант грамматически согласован с вопросом."} for index in range(2)],
        component_realizations=component_map,
    )
    audit = values[4]["audits"][0]
    audit.update(
        options=[{"index": index, "relation": "supported" if index == 0 else "contradicted",
                  "source_ref": "S1P1"} for index in range(2)],
        option_language=[{"index": index, "grammatical": True,
                          "reason": "Вариант грамматически согласован с вопросом."} for index in range(2)],
        target_proofs=[{"target_id": "term", "question_part": "answer", "source_ref": "S1P1"}],
        component_realizations=component_map,
    )
    journal = Journal()

    result = await WorkerLessonAssessor(
        tenant_id="qa", client=Model(values), journal=journal, checkpoint=checkpoint,
    )(lesson, {"f1": fact})
    restored_model = Model([])
    restored = await WorkerLessonAssessor(
        tenant_id="qa", client=restored_model, journal=journal, checkpoint=checkpoint,
    )(lesson, {"f1": fact})

    assert result.questions[0].correct_answer == proposition
    assert result.questions[0].explanation == "Основание в источнике:\n" + proposition
    assert restored.questions == result.questions
    assert restored_model.calls == 0


@pytest.mark.asyncio
async def test_worker_repairs_a_repeated_prior_lesson_question_and_restores_both_without_inference():
    second_rule = "Проверка заявления проводится не более 10 рабочих дней."
    second_fact = SourceFact("f2", "Заявление", "Срок", second_rule, "doc_id=d1;part=2")
    second_lesson = LessonDraft("l2", "m", "Заявления", "Выбрать срок", second_rule, ("f2",), (), 2)
    repeated_prompt = "Какой предельный срок рассмотрения обращения?"
    distinct_prompt = "Какой предельный срок проверки заявления?"
    second_values = [
        {"targets": [{"id": "term2", "description": "Предельный срок проверки",
                       "source_refs": ["F1"], "context": [], "question_format": "",
                       "answer_components": []}],
         "dispositions": [{"ref": "F1", "target_ids": ["term2"], "excluded": ""}]},
        {"admit": True, "target_ids": ["term2"], "source_refs": ["F1"], "errors": [],
         "omissions": []},
        {"questions": [{"id": "q2", "target_ids": ["term2"], "text": repeated_prompt,
                         "options": ["10 рабочих дней", "20 рабочих дней", "30 рабочих дней"]}]},
        {"questions": [{"id": "q2", "target_ids": ["term2"], "text": distinct_prompt,
                         "options": ["10 рабочих дней", "20 рабочих дней", "30 рабочих дней"]}]},
        {"reviews": [{"question_id": "q2", "educational": True, "lesson_answerable": True,
                       "educational_reason": "Проверяет предельный срок проверки заявления.",
                       "unambiguous": True, "explanation_supported": True, "target_ids": ["term2"],
                       "explanation": "Предельный срок проверки — 10 рабочих дней.", "lesson_ref": "L1",
                       "options": [{"index": i, "relation": "supported" if i == 0 else "contradicted",
                                    "source_ref": "S1P1"} for i in range(3)],
                       "option_language": [{"index": i, "grammatical": True,
                                            "reason": "Вариант грамматически согласован с вопросом."}
                                           for i in range(3)]}]},
        {"audits": [{"question_id": "q2", "admit": True, "reason": "Maximum is explicit.",
                      "options": [{"index": i, "relation": "supported" if i == 0 else "contradicted",
                                   "source_ref": "S1P1"} for i in range(3)],
                      "option_language": [{"index": i, "grammatical": True,
                                           "reason": "Вариант грамматически согласован с вопросом."}
                                          for i in range(3)],
                      "target_proofs": [{"target_id": "term2", "question_part": "answer",
                                         "source_ref": "S1P1"}]}]},
    ]
    journal = Journal()
    model = Model([*responses(), *second_values])
    assessor = WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)

    first = await assessor(LESSON, {"f1": FACT})
    second = await assessor(second_lesson, {"f2": second_fact})

    assert first.questions[0].prompt == repeated_prompt
    assert second.questions[0].prompt == distinct_prompt
    repair = next(row for row in model.requests if row.get("task") == "lesson_assessment_repair")
    assert repair["rejected"][0]["failure"] == {
        "code": "duplicate_previous_question",
        "target_ids": ["term2"],
        "previous_prompt": repeated_prompt,
    }

    # A completed cycle can exist when the separate inventory transaction did
    # not commit. Rebuild it from restored terminal results without inference.
    inventory_key = next(key for key in journal.rows if key.endswith(":version:1"))
    del journal.rows[inventory_key]
    del journal.inputs[inventory_key]
    restored_model = Model([])
    restored = WorkerLessonAssessor(
        tenant_id="qa", client=restored_model, journal=journal, checkpoint=checkpoint)
    restored_first = await restored(LESSON, {"f1": FACT})
    restored_second = await restored(second_lesson, {"f2": second_fact})
    assert restored_first.questions == first.questions
    assert restored_second.questions == second.questions
    assert restored_model.calls == 0


@pytest.mark.asyncio
async def test_final_source_quote_keeps_every_validated_clause_supporting_the_key():
    actor = "Ответственным является руководитель отдела."
    source = RULE + "\n\n" + actor
    fact = SourceFact("f1", "Обращение", "Срок и исполнитель", source, "doc_id=d1;part=1")
    lesson = LessonDraft("l1", "m", "Обращение", "Срок и исполнитель", source, ("f1",), (), 1)
    values = responses()
    values[0]["targets"].append({"id": "actor", "description": "Ответственный", "source_refs": ["F1"],
                                "context": [], "question_format": "", "answer_components": []})
    values[1]["target_ids"].append("actor")
    candidate = values[2]["questions"][0]
    candidate.update(target_ids=["term", "actor"], text="Каковы предельный срок и ответственный?",
                     options=["15 рабочих дней; руководитель отдела", "30 рабочих дней; работник склада"])
    review = values[3]["reviews"][0]
    review.update(target_ids=["term", "actor"], explanation="Срок — 15 рабочих дней; отвечает руководитель отдела.")
    review["options"] = review["options"][:2]
    review["option_language"] = review["option_language"][:2]
    values[4]["audits"][0]["options"] = values[4]["audits"][0]["options"][:2]
    values[4]["audits"][0]["option_language"] = values[4]["audits"][0]["option_language"][:2]
    values[4]["audits"][0]["target_proofs"].append(
        {"target_id": "actor", "question_part": "answer", "source_ref": "S1P2"})
    result = await WorkerLessonAssessor(tenant_id="qa", client=Model(values), journal=Journal(), checkpoint=checkpoint)(
        lesson, {"f1": fact})
    assert len(result.questions) == 1
    assert result.questions[0].explanation == "Основание в источнике:\n" + RULE + "\n" + actor
    assert RULE in result.questions[0].source_quote
    assert actor in result.questions[0].source_quote


@pytest.mark.asyncio
async def test_worker_does_not_advance_after_storage_failure():
    class BrokenJournal(Journal):
        async def save_value(self, key, value):
            raise OSError("storage unavailable")

    model = Model(responses())
    with pytest.raises(OSError):
        await WorkerLessonAssessor(tenant_id="qa", client=model, journal=BrokenJournal(), checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert model.calls == 2


@pytest.mark.asyncio
async def test_worker_rejects_cross_tenant_terminal_checkpoint_on_restart():
    journal = Journal()
    await WorkerLessonAssessor(tenant_id="qa", client=Model(responses()), journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    for key, value in journal.rows.items():
        if key.startswith("lesson-cycle:"):
            value["tenant_id"] = "another-tenant"
    with pytest.raises(ValueError, match="checkpoint_identity_mismatch"):
        await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})


@pytest.mark.asyncio
async def test_worker_propagates_cancellation_before_any_provider_or_storage_work():
    import asyncio

    async def cancelled():
        raise asyncio.CancelledError()

    model = Model([])
    journal = Journal()
    with pytest.raises(asyncio.CancelledError):
        await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=cancelled)(LESSON, {"f1": FACT})
    assert model.calls == 0 and not journal.rows and not journal.inputs


@pytest.mark.asyncio
async def test_partial_plan_saves_verified_questions_but_keeps_vetoed_goal_visible_after_restart():
    values = responses()
    value = values[0]
    value["targets"].append({"id": "actor", "description": "Ответственный за рассмотрение",
                              "source_refs": ["F1"], "context": [], "answer_components": []})
    verdict = {"source_refs": ["F1"], "source_gaps": [], "target_verdicts": [
        {"target_id": "term", "admit": True, "errors": []},
        {"target_id": "actor", "admit": False, "errors": ["Исполнитель не назван в источнике"]}]}
    journal = Journal()
    result = await WorkerLessonAssessor(tenant_id="qa", client=Model(
        [value, verdict, deepcopy(value), deepcopy(verdict), *values[2:]]),
        journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert len(result.questions) == 1
    assert result.audit["terminal_status"] == "review_required"
    assert result.audit["coverage"] == {"requires_review": True, "required_target_count": 2,
        "retained_target_count": 1, "missing_target_ids": ["actor"], "unresolved_source_refs": ["F1"],
        "material_inventory_present": False, "material_obligation_count": 0, "unresolved_obligation_ids": [],
        "covered_obligations_by_level": {"source_recognition": 0, "operational_decision": 0}}
    assert next(iter(journal.inputs.values()))["input"]["lesson"]["content"] == ""
    assert next(iter(journal.inputs.values()))["input"]["facts"][0]["value"] == RULE
    restored_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=restored_model, journal=journal,
                                          checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert restored.questions == result.questions and restored.audit["coverage"] == result.audit["coverage"]
    assert restored_model.calls == 0


def test_checkpoint_namespace_separates_fresh_jobs_but_is_stable_for_restart():
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    first = WorkerCycleJournal("qa", "job-a", None)
    second = WorkerCycleJournal("qa", "job-b", None)
    assert first._owned_key("source-plan:packet") != second._owned_key("source-plan:packet")
    assert first._owned_key("source-plan:packet") == WorkerCycleJournal("qa", "job-a", None)._owned_key("source-plan:packet")
    assert len(first._owned_key("x" * 1000)) < 160


@pytest.mark.asyncio
async def test_rendered_source_heading_overhead_does_not_create_a_late_context_crash():
    context = SourceFact("f2", "Контекст " + "х" * 10000, "Условие", "я" * 50000, "doc_id=d1;part=2")
    class Trace(Model):
        def __init__(self):
            super().__init__(responses())
            self.payloads = []

        async def ainvoke_validated(self, messages, parser, **kwargs):
            self.payloads.append(json.loads(messages[-1]["content"]))
            return await super().ainvoke_validated(messages, parser, **kwargs)

    model = Trace()
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=Journal(),
        checkpoint=checkpoint)(LESSON, {"f1": FACT, "f2": context})
    assert len(result.questions) == 1
    assert any(row["text"] == context.value for row in model.payloads[0]["source_units"])
    authored_sources = model.payloads[2]["sources"]
    assert all(row["text"] != context.value for row in authored_sources)
    assert sum(len(row["text"]) for row in authored_sources) < len(context.value)
    assert model.payloads[3]["sources"] == authored_sources
    counter_sources = model.payloads[4]["sources"]
    assert sum(len(row["text"]) for row in counter_sources) >= len(context.value) + len(context.subject)


@pytest.mark.asyncio
@pytest.mark.parametrize("oversize", ["raw", "rendered"])
async def test_context_budget_rejects_before_any_model_or_journal_call(oversize):
    context = SourceFact("f2", "х" * (16000 if oversize == "rendered" else 10), "Условие",
        "я" * (50000 if oversize == "rendered" else 60000), "doc_id=d1;part=2")
    model, journal = Model([]), Journal()
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal,
        checkpoint=checkpoint)(LESSON, {"f1": FACT, "f2": context})
    assert not result.questions
    assert result.audit["coverage"]["source_context_rejected"]
    assert model.calls == 0 and not journal.rows and not journal.inputs


@pytest.mark.asyncio
async def test_large_canonical_document_uses_local_plan_and_all_counter_shards_then_restores(monkeypatch):
    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.lesson_cycle import LearningTarget
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan

    fact = SourceFact("f1", "Обращение", "Срок", RULE,
        "doc_id=qa;source_revision=document:r1;section=1;part=1")
    others = [SourceFact(f"remote-{index}", "Дополнительный раздел", "Справка", "Данные " * 5000,
        f"doc_id=qa;source_revision=document:r1;section={index + 1};part=1") for index in (1, 2)]
    facts = {row.fact_id: row for row in (fact, *others)}
    assert sum(len(row.value) for row in facts.values()) > 60000

    async def planned(lesson, primary, context, **kwargs):
        assert [row.fact_id for row in primary] == ["f1"]
        assert [row.fact_id for row in context] == ["f1"]
        return SourceAssessmentPlan((LearningTarget("term", "Предельный срок"),),
            {"f1": ("term",)}, {}, 0, 0, admitted_target_ids=("term",))

    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    values = responses()[2:]
    values.append(deepcopy(values[-1]))
    journal, model = Journal(), Model(values)
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal,
        checkpoint=checkpoint)(LESSON, facts)
    assert len(result.questions) == 1 and model.calls == 4
    assert result.audit["source_context"]["mode"] == "projected"
    assert result.audit["source_context"]["coverage_complete"] is True
    counters = [row for row in model.requests if row["task"] == "lesson_assessment_counterexample"]
    assert len(counters) == 2
    assert all(sum(len(row["text"]) for row in request["sources"]) <= 65536 for request in counters)
    packet_inputs = [row["packet"] for key, row in journal.inputs.items() if key.startswith("lesson-cycle:")]
    assert len(packet_inputs) == 1 and len(packet_inputs[0]["counter_source_shards"]) == 2
    plan_input, = [row["input"] for key, row in journal.inputs.items() if key.startswith("source-plan:")]
    assert [row["fact_id"] for row in plan_input["facts"]] == ["f1"]
    assert [row["fact_id"] for row in plan_input["counter_context_facts"]] == list(facts)
    no_calls = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=no_calls, journal=journal,
        checkpoint=checkpoint)(LESSON, facts)
    assert restored.questions == result.questions and no_calls.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["pass", "hold"])
async def test_local_joint_reviewer_worker_export_gate(monkeypatch, verdict):
    import hashlib
    import json

    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.joint_review_capability import JointReviewCapability
    from app.modules.ai.lesson_cycle import LearningTarget, LessonCycleResult, ReviewedQuestion
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan

    component = "пользоваться электронагревательными приборами"
    source = "Сотрудникам запрещается " + component + "."
    fact = SourceFact("f1", "Пожарная безопасность", "Запрет", source, "doc_id=qa;part=1")
    lesson = LessonDraft("fire", "module", "Пожарная безопасность", "Запреты", source, ("f1",), (), 1)
    target = LearningTarget("author-row-7", "Запрет приборов", answer_requirements=((component,),),
                            source_ids=("f1",), component_source_ids=(("f1",),))

    async def planned(*args, **kwargs):
        return SourceAssessmentPlan((target,), {"f1": ("author-row-7",)}, {}, 0, 0,
                                    admitted_target_ids=("author-row-7",))

    async def reviewed(packets, **kwargs):
        packet = packets[0]
        owner = packet.targets[0].component_source_ids[0][0]
        question = ReviewedQuestion(
            "native", ("author-row-7",),
            "Что запрещается сотрудникам ломбарда в помещениях организации?",
            (component, component + " по инструкции"), 0,
            "Источник устанавливает конкретный запрет.", source,
            ({"index": 0, "relation": "supported", "source_id": owner, "quote": source},
             {"index": 1, "relation": "contradicted", "source_id": owner, "quote": source}),
            semantic_audit={"target_proofs": [
                {"target_id": "author-row-7", "source_id": owner, "quote": source}
            ]},
        )
        return [LessonCycleResult(packet.tenant_id, packet.identity(), packet.lesson_id,
                                  "ready_for_methodologist", (question,), (), 4, 0.0, ())]

    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    monkeypatch.setattr(worker, "run_lesson_cycles", reviewed)
    calls = []
    async def joint_review(payload):
        decoded = json.loads(payload)
        calls.append(decoded)
        assert len(decoded["sources"]) == 1
        assert decoded["questions"][0]["question"]["answer"] in decoded["questions"][0]["question"]["options"]
        return {"request_digest": hashlib.sha256(payload).hexdigest(),
                "verdicts": [{"id": row["id"], "verdict": verdict} for row in decoded["questions"]]}
    result = await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=Journal(),
        checkpoint=checkpoint, learner_language_gate=True,
        local_joint_reviewer=JointReviewCapability(joint_review))(lesson, {"f1": fact})
    assert len(calls) == 1
    assert len(result.questions) == (1 if verdict == "pass" else 0)
    assert "available-facts-only" in result.audit["local_joint_review"]
    assert result.audit["coverage"]["requires_review"] is True
    if verdict == "hold":
        assert result.audit["coverage"]["requires_review"] is True
        assert result.audit["local_joint_blocked_target_ids"] == ["author-row-7"]

@pytest.mark.asyncio
async def test_local_joint_reviewer_worker_fails_closed_on_inventory_drift_and_bad_output():
    import hashlib
    from dataclasses import replace

    from app.modules.ai.joint_review_capability import JointReviewCapability
    fact = SourceFact("f1", "subject", "kind", "original", "doc_id=qa;part=1")
    facts = {"f1": fact}
    lesson = LessonDraft("l", "m", "title", "objective", "content", ("f1",), (), 1)
    question = {"text": "q", "options": ["a", "b"], "answer": "a"}
    async def drifting(payload):
        facts["f1"] = replace(fact, value="changed")
        return {"request_digest": hashlib.sha256(payload).hexdigest(), "verdict": "pass"}
    assessor = WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=Journal(), checkpoint=checkpoint,
                                   local_joint_reviewer=JointReviewCapability(drifting))
    assert not await assessor._local_joint_review_question(lesson, facts, question)
    async def malformed(_):
        return {"verdict": "pass"}
    assessor = WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=Journal(), checkpoint=checkpoint,
                                   local_joint_reviewer=JointReviewCapability(malformed))
    assert not await assessor._local_joint_review_question(lesson, facts, question)

@pytest.mark.asyncio
async def test_local_joint_timeout_and_cancellation_are_distinct(monkeypatch):
    import asyncio

    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.joint_review_capability import JointReviewCapability
    fact = SourceFact("f1", "subject", "kind", "original", "doc_id=qa;part=1")
    lesson = LessonDraft("l", "m", "title", "objective", "content", ("f1",), (), 1)
    question = {"text": "q", "options": ["a", "b"], "answer": "a"}
    async def never(_):
        await asyncio.Event().wait()
    assessor = WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=Journal(), checkpoint=checkpoint,
                                   local_joint_reviewer=JointReviewCapability(never))
    task = asyncio.create_task(assessor._local_joint_review_question(lesson, {"f1": fact}, question))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    real_wait_for = worker.asyncio.wait_for
    async def timeout(awaitable, timeout):
        awaitable.close()
        raise TimeoutError()
    monkeypatch.setattr(worker.asyncio, "wait_for", timeout)
    assert not await assessor._local_joint_review_question(lesson, {"f1": fact}, question)
    monkeypatch.setattr(worker.asyncio, "wait_for", real_wait_for)

@pytest.mark.asyncio
async def test_local_batch_cold_restore_rechecks_and_vetoes_without_changing_native_journal():
    import hashlib
    import json
    from copy import deepcopy

    from app.modules.ai.joint_review_capability import JointReviewCapability

    journal = Journal()
    calls = []
    async def reviewer(payload):
        data = json.loads(payload)
        calls.append(data)
        verdict = "pass" if len(calls) == 1 else "hold"
        return {"request_digest": hashlib.sha256(payload).hexdigest(),
                "verdicts": [{"id": row["id"], "verdict": verdict} for row in data["questions"]]}
    first = await WorkerLessonAssessor(tenant_id="qa", client=Model(responses()), journal=journal,
        checkpoint=checkpoint, local_joint_reviewer=JointReviewCapability(reviewer))(LESSON, {"f1": FACT})
    assert len(first.questions) == 1
    native_before = deepcopy(journal.rows)
    cold_model = Model([])
    second = await WorkerLessonAssessor(tenant_id="qa", client=cold_model, journal=journal,
        checkpoint=checkpoint, local_joint_reviewer=JointReviewCapability(reviewer))(LESSON, {"f1": FACT})
    assert cold_model.calls == 0 and len(calls) == 2
    assert len(second.questions) == 0
    assert second.audit["coverage"]["requires_review"] is True
    assert journal.rows == native_before


@pytest.mark.asyncio
async def test_local_batch_worker_mixed_verdicts_and_sibling_isolation(monkeypatch):
    import hashlib
    import json
    from dataclasses import replace

    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.joint_review_capability import JointReviewCapability
    from app.modules.ai.lesson_cycle import LearningTarget, LessonCycleResult, ReviewedQuestion
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan

    component = "пользоваться электронагревательными приборами"
    source = "Сотрудникам запрещается " + component + "."
    fact = SourceFact("f1", "Пожарная безопасность", "Запрет", source, "doc_id=qa;part=1")
    lesson = LessonDraft("fire", "module", "Пожарная безопасность", "Запреты", source, ("f1",), (), 1)
    target = LearningTarget("author-row-7", "Запрет приборов", answer_requirements=((component,),),
                            source_ids=("f1",), component_source_ids=(("f1",),))

    async def planned(*args, **kwargs):
        second = replace(target, target_id="author-row-8")
        return SourceAssessmentPlan((target, second), {"f1": ("author-row-7", "author-row-8")}, {}, 0, 0,
                                    admitted_target_ids=("author-row-7", "author-row-8"))

    async def reviewed(packets, **kwargs):
        packet = packets[0]
        owner = packet.targets[0].component_source_ids[0][0]
        question = ReviewedQuestion(
            "native", ("author-row-7",),
            "Что запрещается сотрудникам ломбарда в помещениях организации?",
            (component, component + " по инструкции"), 0,
            "Источник устанавливает конкретный запрет.", source,
            ({"index": 0, "relation": "supported", "source_id": owner, "quote": source},
             {"index": 1, "relation": "contradicted", "source_id": owner, "quote": source}),
            semantic_audit={"target_proofs": [
                {"target_id": "author-row-7", "source_id": owner, "quote": source}
            ]},
        )
        second = replace(question, question_id="second", target_ids=("author-row-8",),
            text="Second question?", semantic_audit={"target_proofs": [
                {"target_id": "author-row-8", "source_id": owner, "quote": source}]})
        return [LessonCycleResult(packet.tenant_id, packet.identity(), packet.lesson_id,
                                  "ready_for_methodologist", (question, second), (), 4, 0.0, ())]

    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    monkeypatch.setattr(worker, "run_lesson_cycles", reviewed)
    calls = []
    async def reviewer(payload):
        data = json.loads(payload)
        calls.append(data)
        verdicts = [{"id": row["id"], "verdict": "hold" if data["lesson"] == "fire" and
                     row["question"]["text"] == "Second question?" else "pass"}
                    for row in data["questions"]]
        return {"request_digest": hashlib.sha256(payload).hexdigest(), "verdicts": verdicts}
    assessor = WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=Journal(), checkpoint=checkpoint,
        learner_language_gate=True, local_joint_reviewer=JointReviewCapability(reviewer))
    first = await assessor(lesson, {"f1": fact})
    second = await assessor(replace(lesson, lesson_id="sibling"), {"f1": fact})
    assert len(calls) == 2 and all(len(row["questions"]) == 2 for row in calls)
    assert len(first.questions) == 1 and len(second.questions) == 2
    assert first.audit["local_joint_blocked_target_ids"] == ["author-row-8"]
    assert second.audit["local_joint_blocked_target_ids"] == []
    assert first.audit["coverage"]["requires_review"] and second.audit["coverage"]["requires_review"]


@pytest.mark.asyncio
async def test_worker_remote_unresolved_edge_keeps_question_but_requires_review(monkeypatch):

    from app.modules.ai import worker_lesson_cycle as worker
    from app.modules.ai.lesson_cycle import LearningTarget, LessonCycleResult, ReviewedQuestion
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan

    component = "пользоваться электронагревательными приборами"
    source = "Сотрудникам запрещается " + component + "."
    fact = SourceFact("f1", "Пожарная безопасность", "Запрет", source, "doc_id=qa;source_revision=rev;section=1;part=1")
    lesson = LessonDraft("fire", "module", "Пожарная безопасность", "Запреты", source, ("f1",), (), 1)
    target = LearningTarget("author-row-7", "Запрет приборов", answer_requirements=((component,),),
                            source_ids=("f1",), component_source_ids=(("f1",),))

    async def planned(*args, **kwargs):
        return SourceAssessmentPlan((target,), {"f1": ("author-row-7",)}, {}, 0, 0,
                                    admitted_target_ids=("author-row-7",))

    async def reviewed(packets, **kwargs):
        packet = packets[0]
        owner = packet.targets[0].component_source_ids[0][0]
        question = ReviewedQuestion(
            "native", ("author-row-7",),
            "Что запрещается сотрудникам ломбарда в помещениях организации?",
            (component, component + " по инструкции"), 0,
            "Источник устанавливает конкретный запрет.", source,
            ({"index": 0, "relation": "supported", "source_id": owner, "quote": source},
             {"index": 1, "relation": "contradicted", "source_id": owner, "quote": source}),
            semantic_audit={"target_proofs": [
                {"target_id": "author-row-7", "source_id": owner, "quote": source}
            ]},
        )
        return [LessonCycleResult(packet.tenant_id, packet.identity(), packet.lesson_id,
                                  "ready_for_methodologist", (question,), (), 4, 0.0, ())]

    monkeypatch.setattr(worker, "MAX_RAW_SOURCE_CHARS", 1600)
    monkeypatch.setattr(worker, "MAX_RENDERED_SOURCE_CHARS", 1800)
    monkeypatch.setattr(worker, "build_source_assessment_plan", planned)
    monkeypatch.setattr(worker, "run_lesson_cycles", reviewed)
    facts = {"f1": fact}
    for i in range(2, 5):
        text = ("See section 999. " if i == 2 else "Other. ") + "x" * 600
        facts[f"f{i}"] = SourceFact(f"f{i}", "section", "rule", text,
            f"doc_id=qa;source_revision=rev;section={i};part=1")
    journal = Journal()
    result = await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=journal,
        checkpoint=checkpoint, learner_language_gate=True)(lesson, facts)
    assert len(result.questions) == 1
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["unresolved_dependency_edge_count"] == 1
    assert set(result.audit["source_context"]["counter_union_fact_ids"]) == set(facts)
    cold = await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=journal,
        checkpoint=checkpoint, learner_language_gate=True)(lesson, facts)
    assert len(cold.questions) == 1 and cold.audit["coverage"]["requires_review"]
    assert cold.audit["source_context"]["source_digest_sha256"] == result.audit["source_context"]["source_digest_sha256"]
    from dataclasses import replace
    changed_facts = dict(facts)
    changed_facts["f2"] = replace(facts["f2"], value=facts["f2"].value.replace("999", "998"))
    changed = await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=journal,
        checkpoint=checkpoint, learner_language_gate=True)(lesson, changed_facts)
    assert len(changed.questions) == 1 and changed.audit["coverage"]["requires_review"]
    assert changed.audit["source_context"]["source_digest_sha256"] != result.audit["source_context"]["source_digest_sha256"]


def test_vm_worker_assessor_preserves_allowlisted_dev_tenant_behavior():
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    values = dict(DEPLOYMENT_ENVIRONMENT='vm-development-worker', AI_QA_LUNA_DEV_ENABLED=True,
                  AI_LESSON_CYCLE_DEV_ENABLED=True, AI_LESSON_CYCLE_DEV_TENANTS=[str(QA_TENANT)])
    def make(tenant, **overrides):
        return create_dev_lesson_assessor(settings=SimpleNamespace(**{**values, **overrides}), tenant_id=tenant,
            job_id='job', client=Model([]), session_factory=None, checkpoint=checkpoint)
    assert make(str(QA_TENANT)) is not None
    assert make('another', AI_LESSON_CYCLE_DEV_TENANTS=['another']) is not None
    assert make('another') is None
    assert make(str(QA_TENANT), AI_QA_LUNA_DEV_ENABLED=False) is not None
    assert make(str(QA_TENANT), AI_LESSON_CYCLE_DEV_ENABLED=False) is None
    assert make(str(QA_TENANT), AI_LESSON_CYCLE_DEV_TENANTS=[]) is None
