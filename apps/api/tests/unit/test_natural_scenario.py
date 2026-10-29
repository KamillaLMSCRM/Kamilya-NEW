"""Natural learner scenarios preserve exact qualifications without displaying raw legal prose."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.ai.lesson_cycle import (
    LearningTarget,
    LessonPacket,
    SourceExcerpt,
    _assessed_stem,
    _component_validation,
    _ordinary_surface_valid,
    _parse_candidate_batch,
    run_lesson_cycles,
)
from app.modules.ai.natural_scenario import (
    NATURAL_SCENARIO_QUESTION,
    canonicalize_qualification_realizations,
    premise_wire_fragments,
    qualification_realizations_valid,
    qualification_repair_failures,
)
from tests.unit.component_contract_fixture import parse_mock_component_response

ACTOR = "коллектив и его члены"
LONG_GROUND = (
    "за осуществление неверной оценки (нарушение внутренних инструкций и стандартов "
    "по выдаче краткосрочных займов, по проведению экспертизы и оценки залогового "
    "имущества либо отступление от утвержденных и действующих расценок и Правил предоставления "
    "микрокредитов) залогового имущества, включая изделия из драгоценных металлов "
    "с драгоценными камнями и изделия из серебра"
)
DAMAGE = "причинившей Работодателю прямой действительный ущерб"
COMPONENT = "несут солидарную ответственность"
PREMISE = (
    "Коллектив и его члены неверно оценили залоговое имущество, нарушив внутренние "
    "инструкции и стандарты выдачи краткосрочных займов, проведения экспертизы и "
    "оценки залога; ошибка причинила работодателю прямой "
    "действительный ущерб."
)
INCOMPLETE_PREMISE = PREMISE.replace(", проведения экспертизы и оценки залога", "")


def _packet() -> LessonPacket:
    source = f"{ACTOR} {COMPONENT} {LONG_GROUND}, {DAMAGE}."
    bindings = tuple(
        {
            "facet_id": facet_id,
            "source_id": "source",
            "quote": quote,
            "role": role,
            "branch_effect": effect,
            "quote_start": source.index(quote),
            "quote_end": source.index(quote) + len(quote),
        }
        for facet_id, quote, role, effect in (
            ("actor", ACTOR, "actor", "none"),
            ("grounds", LONG_GROUND, "condition", "scopes_action"),
            ("damage", DAMAGE, "condition", "scopes_action"),
        )
    )
    target = LearningTarget(
        "liability",
        "Солидарная ответственность",
        answer_requirements=((COMPONENT,),),
        source_ids=("source",),
        component_source_ids=(("source",),),
        qualification_bindings=bindings,
    )
    return LessonPacket(
        "qa",
        "natural-scenario",
        "Ответственность",
        source,
        (SourceExcerpt("source", source, source),),
        (target,),
        "test",
        learner_language_gate=True,
    )


def _row() -> dict:
    return {
        "id": "q1",
        "target_ids": ["liability"],
        "intent": "natural_scenario",
        "premise": PREMISE,
    }


def _wire_receipts(packet: LessonPacket) -> list[dict]:
    target = packet.targets[0]
    rows = []
    for index, binding in enumerate(sorted(target.qualification_bindings,
                                            key=lambda value: (value["source_id"], value["quote_start"], value["facet_id"])), 1):
        rows.append({
            "binding_id": f"B{index}",
            "relation": "entailed_specialization" if binding["facet_id"] == "grounds" else "equivalent",
            "preserved": True,
            "premise_spans": [{"ref": "P1"}],
            "reason": "The visible scenario preserves this exact governing fact.",
        })
    return rows


def test_long_material_scope_uses_authored_nonexempt_scenario_and_zero_credit_surface():
    packet = _packet()
    candidates, failures = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False),
        packet,
        author_protocols={"liability": "natural_scenario"},
    )

    assert failures == [] and len(candidates) == 1
    question = candidates[0]
    assert question.question_form == "natural_scenario"
    assert question.learner_premise == PREMISE
    assert question.options == (COMPONENT, "не несут солидарную ответственность")
    assert question.text == f"Ситуация: {PREMISE}\n{NATURAL_SCENARIO_QUESTION}"
    assert LONG_GROUND not in question.text
    assert "действующих расценок" not in question.text  # Unselected source OR branch.
    assert "изделия из серебра" not in question.text  # Unselected illustrative object.
    assert _assessed_stem(packet, question) == NATURAL_SCENARIO_QUESTION
    assert _ordinary_surface_valid(packet, question)


def test_contextual_application_frame_cannot_itself_prove_a_current_case():
    from app.modules.ai.application_evidence import application_proof_issue
    from app.modules.ai.lesson_cycle import _allowed_application_case_text, _critic_question_view

    packet = _packet()
    packet = replace(packet, targets=(replace(packet.targets[0], assessment_level="operational_decision"),))
    candidates, failures = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )
    assert not failures
    question = candidates[0]
    assert question.intent == "scenario"
    view = _critic_question_view(question, packet)
    assert view["intent"] == "scenario"
    assert view["allowed_application_case_text"] == PREMISE
    assert "описанной ситуации" in question.text
    assert "соответствует правилу" not in question.text
    case = _allowed_application_case_text(packet, question)
    assert case == PREMISE
    receipt = {"target_id": "liability", "applied": True, "premise_quote": NATURAL_SCENARIO_QUESTION,
               "action_quote": COMPONENT, "reason": "Synthetic citation custody only; not semantic approval."}
    assert application_proof_issue([receipt], ("liability",), case, COMPONENT) == "application_premise_invalid"
    receipt["premise_quote"] = PREMISE
    assert application_proof_issue([receipt], ("liability",), case, COMPONENT) is None


def test_old_recognition_envelope_cannot_reuse_current_case_surface_identity():
    from app.modules.ai.lesson_cycle import _allowed_application_case_text

    packet = _packet()
    candidates, failures = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )
    assert not failures
    stale = replace(candidates[0], text=f"Ситуация: {PREMISE}\nКакой вариант полностью соответствует правилу?")
    assert not _ordinary_surface_valid(packet, stale)
    assert _allowed_application_case_text(packet, stale) == ""


def test_natural_scenario_rejects_author_owned_options_or_extra_fields():
    packet = _packet()
    candidates, failures = _parse_candidate_batch(
        json.dumps({"questions": [_row() | {
            "options": [COMPONENT, "несут долевую ответственность", "не несут ответственности"],
        }]}, ensure_ascii=False),
        packet,
        author_protocols={"liability": "natural_scenario"},
    )

    assert candidates == []
    assert failures[0]["reason"] == "lesson_cycle_natural_scenario_schema"


def test_every_binding_is_canonicalized_and_bound_to_visible_premise_spans():
    packet = _packet()
    question = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )[0][0]

    canonical = canonicalize_qualification_realizations(
        _wire_receipts(packet), packet.targets[0].qualification_bindings,
        question.text, question.learner_premise, question.options,
    )

    assert {row["facet_id"] for row in canonical} == {"actor", "grounds", "damage"}
    assert all(row["source_id"] == "source" and row["source_quote"] for row in canonical)
    assert next(row for row in canonical if row["facet_id"] == "grounds")["relation"] == "entailed_specialization"
    assert qualification_realizations_valid(
        canonical, packet.targets[0].qualification_bindings, question.text, question.learner_premise,
        question.options,
    )


def test_native_premise_reference_equals_exact_whole_quote_without_semantic_approval():
    from app.modules.ai.lesson_cycle import _critic_question_view

    packet = _packet()
    question = _parse_candidate_batch(json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
                                     author_protocols={"liability": "natural_scenario"})[0][0]
    assert premise_wire_fragments(question.text, PREMISE) == ({"ref": "P1", "text": PREMISE},)
    view = _critic_question_view(question, packet)
    assert view["premise_fragments"] == [{"ref": "P1", "text": PREMISE}]
    assert not {"correct_index", "qualification_realizations", "semantic_audit"} & view.keys()
    wire = [dict(row, premise_spans=[{"ref": "P1"}]) for row in _wire_receipts(packet)]
    canonical = canonicalize_qualification_realizations(wire, packet.targets[0].qualification_bindings,
        question.text, PREMISE, question.options)
    start = len("Ситуация: ")
    assert all(row["premise_spans"] == [{"start": start, "end": start + len(PREMISE), "quote": PREMISE}]
               for row in canonical)
    assert qualification_realizations_valid(canonical, packet.targets[0].qualification_bindings,
        question.text, PREMISE, question.options)
    wire[1].update(relation="broader", preserved=False)
    rejected = canonicalize_qualification_realizations(wire, packet.targets[0].qualification_bindings,
        question.text, PREMISE, question.options)
    assert not qualification_realizations_valid(rejected, packet.targets[0].qualification_bindings,
        question.text, PREMISE, question.options)


@pytest.mark.parametrize("spans", [
    [{"ref": "P2"}], [{"ref": []}], [{"ref": True}], [{"ref": "P1", "quote": PREMISE}],
    [{"ref": "P1"}, {"ref": "P1"}], [{"ref": "P1"}, {"quote": PREMISE}],
    [{"quote": PREMISE}],
    [{"quote": PREMISE.replace("выдачи краткосрочных займов", "по краткосрочным займам")}],
])
def test_premise_reference_rejects_foreign_mixed_duplicate_or_rewritten_citations(spans):
    packet = _packet()
    question = _parse_candidate_batch(json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
                                     author_protocols={"liability": "natural_scenario"})[0][0]
    rows = _wire_receipts(packet)
    rows[1]["premise_spans"] = spans
    with pytest.raises(ValueError, match="qualification"):
        canonicalize_qualification_realizations(rows, packet.targets[0].qualification_bindings,
            question.text, PREMISE, question.options)


def test_saved_v161_counter_quote_rewrite_stays_invalid_but_native_address_resolves_exact_bytes():
    premise = (
        "Коллектив и его члены допустили неверную оценку залогового имущества при нарушении "
        "внутренних инструкций и стандартов по выдаче краткосрочных займов, проведению экспертизы "
        "и оценки залогового имущества, включая ювелирные изделия из драгоценных металлов "
        "с драгоценными камнями и изделия из серебра, что причинило Работодателю прямой "
        "действительный ущерб."
    )
    packet = _packet()
    question = _parse_candidate_batch(json.dumps({"questions": [_row() | {"premise": premise}]},
        ensure_ascii=False), packet, author_protocols={"liability": "natural_scenario"})[0][0]
    wire = [dict(row, premise_spans=[{"ref": "P1"}]) for row in _wire_receipts(packet)]
    wire[1]["premise_spans"] = [{"quote": premise[
        premise.index("допустили"):premise.index(", что")
    ].replace("по выдаче краткосрочных займов", "по краткосрочным займам")}]
    with pytest.raises(ValueError, match="qualification"):
        canonicalize_qualification_realizations(wire, packet.targets[0].qualification_bindings,
            question.text, premise, question.options)
    wire[1]["premise_spans"] = [{"ref": "P1"}]
    receipt = canonicalize_qualification_realizations(wire, packet.targets[0].qualification_bindings,
        question.text, premise, question.options)
    assert all(row["premise_spans"][0]["quote"] == premise for row in receipt)
    assert all(question.text[row["premise_spans"][0]["start"]:row["premise_spans"][0]["end"]] == premise
               for row in receipt)


def test_stored_receipts_reject_nonunique_visible_quotes_and_duplicate_ranges():
    from copy import deepcopy

    packet = _packet()
    question = _parse_candidate_batch(json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
                                     author_protocols={"liability": "natural_scenario"})[0][0]
    canonical = canonicalize_qualification_realizations(_wire_receipts(packet),
        packet.targets[0].qualification_bindings, question.text, question.learner_premise, question.options)
    duplicate = deepcopy(canonical)
    duplicate[0]["premise_spans"].append(dict(duplicate[0]["premise_spans"][0]))
    assert not qualification_realizations_valid(duplicate, packet.targets[0].qualification_bindings,
        question.text, question.learner_premise, question.options)
    from app.modules.ai.natural_scenario import render_natural_scenario, visible_candidate_sha256

    repeated = question.learner_premise + " " + canonical[0]["premise_spans"][0]["quote"]
    text = render_natural_scenario(repeated)
    updated = deepcopy(canonical)
    for row in updated:
        row["candidate_sha256"] = visible_candidate_sha256(text, question.options)
    assert not qualification_realizations_valid(updated, packet.targets[0].qualification_bindings,
        text, repeated, question.options)

    tampered = [dict(row) for row in canonical]
    tampered[0] = {**tampered[0], "candidate_sha256": "0" * 64}
    assert not qualification_realizations_valid(
        tampered, packet.targets[0].qualification_bindings, question.text,
        question.learner_premise, question.options,
    )


@pytest.mark.parametrize("mutation", ["missing", "negative", "duplicate", "foreign", "outside"])
def test_qualification_receipts_fail_closed(mutation):
    packet = _packet()
    question = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )[0][0]
    rows = _wire_receipts(packet)
    if mutation == "missing":
        rows.pop()
    elif mutation == "negative":
        rows[0].update(relation="broader", preserved=False)
    elif mutation == "duplicate":
        rows[1]["binding_id"] = rows[0]["binding_id"]
    elif mutation == "foreign":
        rows[0]["binding_id"] = "B99"
    else:
        rows[0]["premise_spans"][0] = {"quote": "Ситуация:"}

    if mutation == "negative":
        canonical = canonicalize_qualification_realizations(
            rows, packet.targets[0].qualification_bindings, question.text, question.learner_premise,
            question.options,
        )
        assert not qualification_realizations_valid(
            canonical, packet.targets[0].qualification_bindings, question.text, question.learner_premise,
            question.options,
        )
    else:
        with pytest.raises(ValueError, match="qualification"):
            canonicalize_qualification_realizations(
                rows, packet.targets[0].qualification_bindings, question.text, question.learner_premise,
                question.options,
            )


def test_qualification_repair_feedback_contains_only_failed_binding_and_negative_evidence():
    packet = _packet()
    question = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )[0][0]
    rows = _wire_receipts(packet)
    rows[1] = {**rows[1], "relation": "broader", "preserved": False,
               "reason": "The current premise omits a required ground."}
    canonical = canonicalize_qualification_realizations(
        rows, packet.targets[0].qualification_bindings, question.text, question.learner_premise,
        question.options,
    )

    failures = qualification_repair_failures(
        canonical, packet.targets[0].qualification_bindings, question.text,
        question.learner_premise, question.options,
    )

    assert failures == ({
        "binding_id": "B2",
        "source_quote": LONG_GROUND,
        "relation": "broader",
        "reason": "The current premise omits a required ground.",
    },)
    tampered = [dict(row) for row in canonical]
    tampered[1]["candidate_sha256"] = "0" * 64
    assert qualification_repair_failures(
        tampered, packet.targets[0].qualification_bindings, question.text,
        question.learner_premise, question.options,
    ) == ()


@pytest.mark.parametrize(
    "relation,preserved",
    [("broader", True), ("unknown", True), ("equivalent", False), ("entailed_specialization", False)],
)
def test_qualification_relation_and_preserved_flag_must_agree(relation, preserved):
    packet = _packet()
    question = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )[0][0]
    rows = _wire_receipts(packet)
    rows[1].update(relation=relation, preserved=preserved)

    with pytest.raises(ValueError, match="qualification"):
        canonicalize_qualification_realizations(
            rows, packet.targets[0].qualification_bindings, question.text,
            question.learner_premise, question.options,
        )


@pytest.mark.parametrize("relation", [[], {}])
def test_malformed_qualification_relation_is_a_finite_contract_failure(relation):
    packet = _packet()
    question = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )[0][0]
    wire = _wire_receipts(packet)
    wire[0]["relation"] = relation
    with pytest.raises(ValueError, match="qualification_realizations_invalid"):
        canonicalize_qualification_realizations(
            wire, packet.targets[0].qualification_bindings, question.text,
            question.learner_premise, question.options,
        )

    canonical = canonicalize_qualification_realizations(
        _wire_receipts(packet), packet.targets[0].qualification_bindings, question.text,
        question.learner_premise, question.options,
    )
    canonical[0]["relation"] = relation
    assert not qualification_realizations_valid(
        canonical, packet.targets[0].qualification_bindings, question.text,
        question.learner_premise, question.options,
    )
    assert qualification_repair_failures(
        canonical, packet.targets[0].qualification_bindings, question.text,
        question.learner_premise, question.options,
    ) == ()


def test_natural_scenario_is_opt_in_and_premise_cannot_earn_component_credit():
    packet = _packet()
    disabled = replace(packet, learner_language_gate=False)
    candidates, failures = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), disabled,
        author_protocols={"liability": "natural_scenario"},
    )
    assert not candidates and failures[0]["reason"] == "lesson_cycle_natural_scenario_ineligible"

    question = _parse_candidate_batch(
        json.dumps({"questions": [_row()]}, ensure_ascii=False), packet,
        author_protocols={"liability": "natural_scenario"},
    )[0][0]
    quote = "Коллектив и его члены"
    result = _component_validation(packet, question, 0, ("liability",), {"source"}, [{
        "target_id": "liability",
        "component_id": "liability:C1",
        "source_ref": "S1P1",
        "realizations": [{"part": "stem", "role": "fixed_context", "quote": quote}],
    }])
    assert result.failures == ({"code": "server_scope_has_no_assessment_credit"},)


class _Store:
    value = None

    async def load(self, tenant_id, identity):
        return self.value

    async def save(self, tenant_id, identity, value):
        self.value = value


class _Model:
    def __init__(self):
        self.requests = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.requests.append(payload)
        task = payload["task"]
        if task == "lesson_assessment_author":
            assert payload["targets"][0]["author_protocol"] == "natural_scenario"
            assert payload["targets"][0]["server_scope_prefix"] == ""
            assert not payload.get("reserved_question_ids")
            value = {"questions": [_row()]}
        elif task == "learner_language_review":
            item = payload["questions"][0]
            value = {"language_reviews": [{
                "question_id": item["question_id"],
                "acceptable": True,
                "grammatical": True,
                "idiomatic": True,
                "cue_free": True,
                "comparable": True,
                "reason": "The complete learner-visible scenario is natural and comparable.",
            }]}
        else:
            question = payload["questions"][0]
            assert {row["binding_id"] for row in question["qualification_requirements"]} == {"B1", "B2", "B3"}
            assert LONG_GROUND in payload["sources"][0]["text"]
            common = {
                "question_id": question["question_id"],
                "options": [
                    {"index": 0, "relation": "supported", "source_ref": "S1P1"},
                    {"index": 1, "relation": "contradicted", "source_ref": "S1P1"},
                ],
                "component_realizations": [{
                    "target_id": "liability",
                    "component_id": "liability:C1",
                    "source_ref": "S1P1",
                    "realizations": [{"part": "answer", "role": "discriminating_answer", "whole_part": True}],
                }],
                "qualification_realizations": _wire_receipts(_packet()),
            }
            if task == "lesson_assessment_review":
                value = {"reviews": [common | {
                    "educational": True,
                    "educational_reason": "The learner chooses the liability outcome under the complete case.",
                    "lesson_answerable": True,
                    "unambiguous": True,
                    "explanation_supported": True,
                    "target_ids": ["liability"],
                    "explanation": "The complete source rule establishes joint liability.",
                    "lesson_ref": "L1",
                }]}
            else:
                value = {"audits": [common | {
                    "admit": True,
                    "reason": "All governing facts remain visible and exactly one outcome is supported.",
                    "target_proofs": [{
                        "target_id": "liability", "question_part": "answer", "source_ref": "S1P1",
                    }],
                }]}
        return SimpleNamespace(value=parse_mock_component_response(parser, json.dumps(value, ensure_ascii=False), messages), attempt_count=1)


@pytest.mark.asyncio
async def test_natural_scenario_uses_four_existing_calls_and_binds_both_receipts_on_restore():
    packet, store, model = _packet(), _Store(), _Model()

    result = (await run_lesson_cycles([packet], client=model, store=store))[0]

    assert result.status == "ready_for_methodologist" and result.logical_model_calls == 4
    assert [request["task"] for request in model.requests] == [
        "lesson_assessment_author", "learner_language_review",
        "lesson_assessment_review", "lesson_assessment_counterexample",
    ]
    question = result.questions[0]
    assert question.question_form == "natural_scenario" and question.learner_premise == PREMISE
    assert len(question.qualification_realizations) == 3
    assert len(question.semantic_audit["qualification_realizations"]) == 3

    no_calls = _Model()
    assert (await run_lesson_cycles([packet], client=no_calls, store=store))[0] == result
    assert no_calls.requests == []

    store.value = replace(result, questions=(replace(question, learner_premise=PREMISE + " Иное."),))
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        await run_lesson_cycles([packet], client=no_calls, store=store)


def _mixed_packet() -> LessonPacket:
    first = _packet()
    peer_text = "Отчёт направляют не позднее 3 рабочих дней."
    return replace(
        first,
        content=first.content + "\n" + peer_text,
        sources=(*first.sources, SourceExcerpt("peer-source", peer_text, peer_text)),
        targets=(*first.targets, LearningTarget("peer", "Срок отчёта", source_ids=("peer-source",))),
    )


def _qualification_rows_for_premise(packet: LessonPacket, premise: str, *, failed: bool) -> list[dict]:
    if not failed:
        return _wire_receipts(packet)
    rows = _wire_receipts(packet)
    rows[1] = {
        **rows[1],
        "relation": "broader",
        "preserved": False,
        "premise_spans": [{"ref": "P1"}],
        "reason": "The selected path omits the required appraisal modifier.",
    }
    assert premise == INCOMPLETE_PREMISE
    return rows


class _QualificationRepairModel:
    def __init__(self):
        self.requests = []
        self.review_calls = 0

    async def ainvoke_validated(self, messages, parser, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.requests.append(payload)
        task = payload["task"]
        if task == "lesson_assessment_author":
            value = {"questions": [
                _row() | {"premise": INCOMPLETE_PREMISE},
                {"id": "q2", "target_ids": ["peer"], "intent": "rule",
                 "text": "Каков максимальный срок направления отчёта?",
                 "options": ["3 рабочих дня", "10 рабочих дней"]},
            ]}
        elif task == "lesson_assessment_repair":
            assert payload["repair_mode"] == "natural_scenario_qualification"
            assert [row["target_id"] for row in payload["targets"]] == ["liability"]
            assert payload["qualification_failures"] == [{
                "question_id": payload["qualification_failures"][0]["question_id"],
                "target_id": "liability",
                "failures": [{
                    "binding_id": "B2",
                    "source_quote": LONG_GROUND,
                    "relation": "broader",
                    "reason": "The selected path omits the required appraisal modifier.",
                }],
            }]
            serialized = json.dumps(payload, ensure_ascii=False)
            assert "correct_index" not in serialized and '"review"' not in serialized
            value = {"questions": [_row() | {"id": payload["qualification_failures"][0]["question_id"]}]}
        elif task == "learner_language_review":
            value = {"language_reviews": [{
                "question_id": row["question_id"],
                "acceptable": True,
                "grammatical": True,
                "idiomatic": True,
                "cue_free": True,
                "comparable": True,
                "reason": "The visible question is natural and has comparable options.",
            } for row in payload["questions"]]}
        elif task == "lesson_assessment_review":
            self.review_calls += 1
            rows = []
            for question in payload["questions"]:
                liability = question["target_ids"] == ["liability"]
                source_ref = "S1P1" if liability else "S2P1"
                common = {
                    "question_id": question["question_id"],
                    "options": [
                        {"index": 0, "relation": "supported", "source_ref": source_ref},
                        {"index": 1, "relation": "contradicted", "source_ref": source_ref},
                    ],
                    "component_realizations": ([{
                        "target_id": "liability",
                        "component_id": "liability:C1",
                        "source_ref": source_ref,
                        "realizations": [{"part": "answer", "role": "discriminating_answer",
                                          "whole_part": True}],
                    }] if liability else []),
                    "educational": True,
                    "educational_reason": "Tests the source decision under the stated case.",
                    "lesson_answerable": True,
                    "unambiguous": not (liability and self.review_calls == 1),
                    "explanation_supported": True,
                    "target_ids": question["target_ids"],
                    "explanation": "The source establishes exactly one of the visible choices.",
                    "lesson_ref": "L1",
                }
                if liability:
                    common["qualification_realizations"] = _qualification_rows_for_premise(
                        _packet(), INCOMPLETE_PREMISE if self.review_calls == 1 else PREMISE,
                        failed=self.review_calls == 1,
                    )
                rows.append(common)
            value = {"reviews": rows}
        else:
            assert task == "lesson_assessment_counterexample"
            assert {tuple(row["target_ids"]) for row in payload["questions"]} == {("liability",), ("peer",)}
            rows = []
            for question in payload["questions"]:
                liability = question["target_ids"] == ["liability"]
                source_ref = "S1P1" if liability else "S2P1"
                row = {
                    "question_id": question["question_id"],
                    "admit": True,
                    "reason": "Exactly one choice follows from the complete visible case.",
                    "options": [
                        {"index": 0, "relation": "supported", "source_ref": source_ref},
                        {"index": 1, "relation": "contradicted", "source_ref": source_ref},
                    ],
                    "component_realizations": ([{
                        "target_id": "liability", "component_id": "liability:C1",
                        "source_ref": source_ref,
                        "realizations": [{"part": "answer", "role": "discriminating_answer",
                                          "whole_part": True}],
                    }] if liability else []),
                    "target_proofs": [{"target_id": "liability" if liability else "peer",
                                       "question_part": "answer", "source_ref": source_ref}],
                }
                if liability:
                    row["qualification_realizations"] = _wire_receipts(_packet())
                rows.append(row)
            value = {"audits": rows}
        return SimpleNamespace(value=parse_mock_component_response(parser, json.dumps(value, ensure_ascii=False), messages), attempt_count=1)


@pytest.mark.asyncio
async def test_negative_qualification_repairs_only_premise_then_rechecks_language_and_both_critics():
    model = _QualificationRepairModel()

    result = (await run_lesson_cycles([_mixed_packet()], client=model, store=_Store()))[0]

    assert result.status == "ready_for_methodologist" and result.logical_model_calls == 7
    assert [request["task"] for request in model.requests] == [
        "lesson_assessment_author", "learner_language_review", "lesson_assessment_review",
        "lesson_assessment_repair", "learner_language_review", "lesson_assessment_review",
        "lesson_assessment_counterexample",
    ]
    assert {question.target_ids for question in result.questions} == {("liability",), ("peer",)}
    assert all(question.question_id.startswith("auth-") for question in result.questions)
    assert next(question for question in result.questions if question.target_ids == ("liability",)).learner_premise == PREMISE
