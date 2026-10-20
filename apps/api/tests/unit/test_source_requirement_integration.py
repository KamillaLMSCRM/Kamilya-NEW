"""A recognized source requirement owns its stem, every audit, and coverage."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    assessment_source_requirement,
    derive_assessment_axes,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.operational_requirements import project_source_requirement
from app.modules.ai.evidence_engine.semantic_assessment import (
    _axis_answer_domain,
    _axis_author_payload,
    _unsupported_replacement_advice,
    generate_block_assessment,
)

KEYS = (
    "Расположение электрических кабелей и различных проводов должно исключать их повреждение, "
    "поражение работников электрическим током, а также они не должны мешать передвижению по помещению.",
    "Все помещения офисного здания ломбарда оснащаются планами эвакуации, в соответствии с которыми "
    "в случае пожара и других чрезвычайных ситуаций обеспечивается организованная эвакуация персонала.",
)


def requirement_axis(key):
    fact = SourceFact("f", "Правила безопасности", "положение", "2.7. " + key, "doc_id=synthetic;part=1")
    lesson = LessonDraft("l", "Правила безопасности", "Требования", "Применять требования", "", ("f",), (), 1)
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id="b") if a.correct_value == key)
    return axis, fact


@pytest.mark.parametrize("key", KEYS)
def test_complete_requirement_is_a_source_owned_stem_and_typed_domain(key):
    axis, _ = requirement_axis(key)
    contract = assessment_source_requirement(axis)
    assert contract is not None
    assert axis.required_prompt == contract.required_prompt
    assert axis.correct_value == key
    domain = _axis_answer_domain(axis)
    assert domain is not None and domain["kind"] == contract.kind
    assert domain["required_components"] == list(contract.required_components)
    payload = _axis_author_payload(axis)
    assert payload["answer_domain"] == domain and payload["required_prompt"] == axis.required_prompt
    assert payload["source_claim"] == key


@pytest.mark.parametrize("key", KEYS)
def test_changed_prompt_or_unrelated_source_cannot_claim_requirement_domain(key):
    axis, _ = requirement_axis(key)
    assert assessment_source_requirement(replace(axis, required_prompt="Какие другие правила действуют?")) is None
    assert assessment_source_requirement(replace(axis, distractor_constraints=())) is None
    peers = tuple(replace(c, relation="other_axis") for c in axis.distractor_constraints)
    assert assessment_source_requirement(replace(axis, distractor_constraints=peers)) is None


def test_source_bound_reviewed_provision_can_have_a_replacement_misconception():
    axis, fact = requirement_axis(KEYS[1])
    q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "В части помещений планы эвакуации заменяют устным объяснением, а сами планы там не размещают.",
        "Планами эвакуации обеспечивают только отдельные помещения, в остальных планы не требуются.",
    )))
    assert q is not None and q.correct_answer == KEYS[1]
    assert not _unsupported_replacement_advice(replace(q, semantic_reviewed=True), [fact])
    assert _unsupported_replacement_advice(q, [fact])
    assert _unsupported_replacement_advice(replace(q, semantic_reviewed=True, source_quote="Другой источник"), [fact])
    table = replace(fact, source_locator="doc_id=synthetic;sheet=Каталог;row=1;column=2")
    assert _unsupported_replacement_advice(replace(q, semantic_reviewed=True), [table])


@pytest.mark.asyncio
@pytest.mark.parametrize("key", KEYS)
async def test_an_omitted_known_requirement_is_explicitly_incomplete_not_success(key):
    axis, fact = requirement_axis(key)
    lesson = LessonDraft("l", "Правила безопасности", "Требования", "Применять требования", "", ("f",), (), 1)

    class EmptyAuthor:
        calls = 0

        async def ainvoke_validated(self, messages, parser, **kwargs):
            self.calls += 1
            assert json.loads(messages[-1]["content"])["task"] == "assessment_generate"
            return SimpleNamespace(value=parser('{"questions":[]}'), attempt_count=1, failure_reasons=(), model_id="fixture")

    client = EmptyAuthor()
    result = await generate_block_assessment([lesson], {"f": fact}, client)
    assert result.questions == () and client.calls == 1
    assert result.audit["terminal_status"] == "review_required"
    assert result.audit["coverage"]["requires_review"]
    actual_axis_id = next(row["axis_id"] for row in result.audit["axis_outcomes"] if row["primary_fact_id"] == "f")
    assert actual_axis_id in result.audit["coverage"]["critical_missing_axis_ids"]
    assert result.audit["required_response_contract_coverage"] == [{
        "axis_id": actual_axis_id, "primary_fact_id": "f",
        "kind": assessment_source_requirement(axis).kind, "complete": False,
    }]


@pytest.mark.asyncio
async def test_overlength_recognized_requirement_stays_unassessable_beside_retained_question():
    long_key = KEYS[0].replace("различных проводов", "различных " + "соединительных " * 14 + "проводов")
    assert len(long_key) > 240 and project_source_requirement(long_key) is not None
    facts = {
        "long": SourceFact("long", "Безопасность", "положение", long_key, "doc_id=synthetic;part=1"),
        "other": SourceFact("other", "Безопасность", "положение", "Учебный журнал хранится в закрытом шкафу на учебном посту.", "doc_id=synthetic;part=2"),
    }
    lesson = LessonDraft("l", "Безопасность", "Требования", "Применять правила", "", tuple(facts), (), 1)

    class NeighborClient:
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request["task"] == "assessment_generate":
                payload = {"questions": [{"axis_id": a["axis_id"], "prompt": "Где хранится учебный журнал?", "distractors": [
                    "Учебный журнал хранится в открытом ящике на общем учебном столе.",
                    "Учебный журнал остается на стойке свободного доступа в учебном холле.",
                ]} for a in request["axes"]]}
            elif request["task"] == "assessment_review":
                payload = {"reviews": [{"question_id": q["question_id"], "question_supported": True, "educational": True,
                    "explanation_supported": True, "options_distinct": True, "options": [
                        {"index": i, "answers_question": True, "correct": i == 0, "plausible_error": i != 0,
                         "contradicted_by_source": i != 0, "same_practical_task": True} for i in range(len(q["options"]))
                    ]} for q in request["questions"]]}
            elif request["task"] == "assessment_constraints":
                payload = {"rules": [{"fact_id": f["fact_id"], "quote": f["value"], "kind": "required"} for f in request["facts"]],
                    "reviews": [{"question_id": q["question_id"], "reason": "Synthetic fixture checks coverage, not model truth.",
                        "distinct_errors": True, "options": [{"index": i, "relation": "entailed" if i == 0 else "contradicted",
                        "invented_constraint": False, "realistic_error": i != 0} for i in range(len(q["options"]))]
                    } for q in request["questions"]]}
            else:
                raise AssertionError("No repair should be needed for the neighboring fixture")
            return SimpleNamespace(value=parser(json.dumps(payload)), attempt_count=1, failure_reasons=(), model_id="fixture")

    result = await generate_block_assessment([lesson], facts, NeighborClient())
    assert len(result.questions) == 1 and result.questions[0].fact_id == "other"
    long_outcome = next(row for row in result.audit["axis_outcomes"] if row["primary_fact_id"] == "long")
    assert long_outcome["state"] == "unassessable"
    assert long_outcome["reason"] == "unatomizable_source_contract"
    assert "long" in result.audit["coverage"]["unatomizable_fact_ids"]
    assert result.audit["coverage"]["audit_incomplete"] and result.audit["coverage"]["requires_review"]
    assert result.audit["terminal_status"] == "review_required"
