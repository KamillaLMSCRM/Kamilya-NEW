"""Audited target fields bound material repair to the rejected semantic surface."""

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.source_assessment_plan import (
    AUDIT,
    EXTRACT,
    LOCAL_STRUCTURAL_REPAIR,
    SourcePlanError,
    _audited_target_repair_operations,
    _audited_zero_admission_repairable,
    _material_repair_system,
    _parse,
    build_source_assessment_plan,
)
from tests.source_plan_audit_fixture import (
    parse_canned_source_plan_response,
    with_canned_complete_target_context_audit,
)

SOURCE = (
    "Сотрудник обязан проверить документ. "
    "При нарушении срока сотрудник несёт ответственность."
)
CHECK = "Сотрудник обязан проверить документ"
CONDITION = "При нарушении срока"
OUTCOME = "сотрудник несёт ответственность"
FACT = SourceFact("fact-1", "Проверка", "Обязанности", SOURCE, "doc_id=d1;part=1")
LESSON = LessonDraft("lesson-1", "module", "Проверка", "Решение", SOURCE, ("fact-1",), (), 1)


class TraceModel:
    def __init__(self, *responses: dict, adapt_audit: bool = True):
        self.responses = iter(responses)
        self.adapt_audit = adapt_audit
        self.system_prompts: list[str] = []
        self.requests: list[dict] = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        self.system_prompts.append(messages[0]["content"])
        self.requests.append(json.loads(messages[1]["content"]))
        serialized = json.dumps(next(self.responses), ensure_ascii=False)
        if self.adapt_audit:
            value = parse_canned_source_plan_response(parser, serialized, messages)
        elif messages[0]["content"] == AUDIT:
            # Supply only the mandatory context envelope while preserving the
            # deliberately malformed target-verdict transport under test.
            original = json.loads(serialized)
            adapted = with_canned_complete_target_context_audit(
                original, self.requests[-1]
            )
            if "target_verdicts" in original:
                adapted["target_verdicts"] = original["target_verdicts"]
            else:
                adapted.pop("target_verdicts", None)
            value = parser(json.dumps(adapted, ensure_ascii=False))
        else:
            value = parser(serialized)
        return SimpleNamespace(
            value=value,
            attempt_count=1,
        )


def _target(tid: str, component: str, *, include_bindings: bool = True) -> dict:
    row = {
        "id": tid,
        "description": "Проверить документ" if tid == "check" else "Определить последствие",
        "source_refs": ["F1"],
        "context": [],
        "construction_mode": "",
        "answer_components": [{"ref": "F1", "terms": [component]}],
    }
    if include_bindings:
        row["governing_bindings"] = []
    return row


def _plan(*, liability_component: str = OUTCOME, include_bindings: bool = True) -> dict:
    return {
        "material_obligations": [
            {"id": "O1", "ref": "F1", "quote": CHECK, "dimension": "action",
             "target_ids": ["check"], "evidence_level": "operational_decision"},
            {"id": "O2", "ref": "F1", "quote": OUTCOME, "dimension": "outcome",
             "target_ids": ["liability"], "evidence_level": "operational_decision"},
        ],
        "targets": [
            _target("check", CHECK, include_bindings=include_bindings),
            _target("liability", liability_component, include_bindings=include_bindings),
        ],
        "excluded_units": [],
    }


def _audit(*, repair_fields: list[str], liability_admit: bool = False,
           final_binding: bool = False) -> dict:
    return {
        "source_refs": ["F1"],
        "target_verdicts": [
            {"target_id": "check", "admit": True, "errors": [], "repair_fields": []},
            {"target_id": "liability", "admit": liability_admit,
             "errors": [] if liability_admit else ["missing governing grounds"],
             "repair_fields": [] if liability_admit else repair_fields},
        ],
        "facet_verdicts": (
            [{"facet_id": "G1", "admit": True, "errors": []}]
            if final_binding else []
        ),
        "source_gaps": [],
    }


def _partial_patch(field: str, value) -> dict:
    return {
        "targets": [{"id": "liability", field: value}],
        "material_obligations": [],
        "excluded_units": [],
    }


@pytest.mark.parametrize("effect", ["none", "scopes_action"])
def test_whole_answer_cannot_be_a_static_actor_or_scope_premise(effect):
    plan = _plan()
    plan["targets"][0]["governing_bindings"] = [{"ref": "F1", "quote": CHECK,
        "role": "actor", "branch_effect": effect}]
    _, _, canonical = _parse(json.dumps(plan), {"F1": FACT}, {"F1"})
    assert canonical["target_validation_errors"]["check"].startswith(
        "source_plan_answer_disclosing_governing_binding:")
    assert "liability" not in canonical["target_validation_errors"]


def test_partial_actor_overlap_stays_owned_without_becoming_the_whole_answer():
    plan = _plan()
    plan["targets"][0]["governing_bindings"] = [{"ref": "F1", "quote": "Сотрудник",
        "role": "actor", "branch_effect": "none"}]
    _, _, canonical = _parse(json.dumps(plan), {"F1": FACT}, {"F1"})
    assert not canonical["target_validation_errors"]


@pytest.mark.asyncio
async def test_answer_bearing_actor_is_repaired_before_authorship_with_full_fresh_plan_audit():
    initial = _plan()
    initial["targets"][0]["governing_bindings"] = [{"ref": "F1", "quote": CHECK,
        "role": "actor", "branch_effect": "none"}]
    repaired = _target("check", CHECK)
    repaired["governing_bindings"] = [{"ref": "F1", "quote": "Сотрудник",
        "role": "actor", "branch_effect": "none"}]
    model = TraceModel(initial, {"targets": [repaired], "material_obligations": [], "excluded_units": []},
        _audit(repair_fields=[], liability_admit=True, final_binding=True))
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)
    assert model.system_prompts == [EXTRACT, LOCAL_STRUCTURAL_REPAIR, AUDIT]
    assert [row["id"] for row in model.requests[1]["previous_plan"]["targets"]] == ["check"]
    assert set(model.requests[1]["feedback"]["target_validation_errors"]) == {"check"}
    final = model.requests[2]["plan"]
    assert final["targets"][1]["answer_components"] == initial["targets"][1]["answer_components"]
    assert {target.target_id for target in result.targets} == {"check", "liability"}
    assert set(result.admitted_target_ids) == {"check", "liability"}
    assert result.model_calls == 3


@pytest.mark.asyncio
async def test_binding_only_repair_overlays_partial_row_and_preserves_short_component():
    binding = [{"ref": "F1", "quote": CONDITION, "role": "condition",
                "branch_effect": "scopes_action"}]
    model = TraceModel(
        _plan(),
        _audit(repair_fields=["governing_bindings"]),
        _partial_patch("governing_bindings", binding),
        _audit(repair_fields=[], liability_admit=True, final_binding=True),
    )

    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert model.system_prompts == [
        EXTRACT,
        AUDIT,
        _material_repair_system(model.requests[2]),
        AUDIT,
    ]
    assert "genuinely NEW target IDs use this FULL-row schema" not in model.system_prompts[2]
    assert "EXISTING IDs: return only id plus changed fields" in model.system_prompts[2]
    request = model.requests[2]
    assert request["repair_operations"] == [{
        "target_id": "liability", "repair_fields": ["governing_bindings"],
    }]
    assert [row["id"] for row in request["repair_targets"]] == ["liability"]
    repaired = next(row for row in result.evidence["plan"]["targets"] if row["id"] == "liability")
    assert repaired["answer_components"] == [{"ref": "F1", "terms": [OUTCOME]}]
    assert repaired["governing_bindings"] == binding
    assert set(result.admitted_target_ids) == {"check", "liability"}


@pytest.mark.asyncio
@pytest.mark.parametrize("healthy_peer", [False, True])
async def test_facet_only_rejection_authorizes_only_owning_binding_repair_and_fresh_audit(healthy_peer):
    initial = _plan()
    initial["targets"][1]["governing_bindings"] = [{
        "ref": "F1", "quote": CONDITION, "role": "actor", "branch_effect": "scopes_action",
    }]
    if not healthy_peer:
        initial["targets"] = initial["targets"][1:]
        initial["material_obligations"] = initial["material_obligations"][1:]
    first = _audit(repair_fields=[], liability_admit=True, final_binding=True)
    first["facet_verdicts"][0] = {"facet_id": "G1", "admit": False,
        "errors": ["A condition was mislabeled as an actor"]}
    final = _audit(repair_fields=[], liability_admit=True, final_binding=True)
    if not healthy_peer:
        first["target_verdicts"] = first["target_verdicts"][1:]
        final["target_verdicts"] = final["target_verdicts"][1:]
    binding = [{"ref": "F1", "quote": CONDITION, "role": "condition", "branch_effect": "scopes_action"}]
    model = TraceModel(initial, first, _partial_patch("governing_bindings", binding), final)
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)
    assert model.system_prompts == [
        EXTRACT,
        AUDIT,
        _material_repair_system(model.requests[2]),
        AUDIT,
    ]
    assert model.requests[2]["repair_operations"] == [{"target_id": "liability", "repair_fields": ["governing_bindings"]}]
    assert [target["id"] for target in model.requests[2]["repair_targets"]] == ["liability"]
    assert set(result.admitted_target_ids) == ({"check", "liability"} if healthy_peer else {"liability"})
    assert result.model_calls == 4
    assert next(row for row in result.evidence["plan"]["targets"] if row["id"] == "liability")["answer_components"] == [
        {"ref": "F1", "terms": [OUTCOME]}]


def test_facet_repair_scope_unions_only_validated_negative_fields_and_withheld_owners():
    payload = _plan()
    payload["qualification_facets"] = [{"id": "G1", "target_ids": ["check", "liability"]}]
    payload["qualification_audit"] = [{"facet_id": "G1", "admit": False, "errors": ["bad scope"]}]
    verdict = _audit(repair_fields=["answer_components"])
    assert _audited_target_repair_operations(verdict, payload, ("check",)) == [
        {"target_id": "liability", "repair_fields": ["governing_bindings", "answer_components"]}]
    assert _audited_target_repair_operations(verdict, payload, ()) == [
        {"target_id": "check", "repair_fields": ["governing_bindings"]},
        {"target_id": "liability", "repair_fields": ["governing_bindings", "answer_components"]}]
    payload["qualification_audit"][0] = {"facet_id": "G1", "admit": True, "errors": []}
    positive = _audit(repair_fields=[], liability_admit=True)
    assert not _audited_target_repair_operations(positive, payload, ())


def test_one_rejected_facet_cannot_authorize_repair_of_unrelated_withheld_target():
    payload = _plan()
    payload["qualification_facets"] = [{"id": "G1", "target_ids": ["liability"]}]
    payload["qualification_audit"] = [{"facet_id": "G1", "admit": False, "errors": ["bad scope"]}]
    verdict = _audit(repair_fields=[], liability_admit=True)
    assert not _audited_zero_admission_repairable(verdict, payload)


@pytest.mark.asyncio
async def test_facet_repair_never_reuses_old_target_approval_after_failed_fresh_audit():
    initial = _plan()
    initial["targets"][1]["governing_bindings"] = [{
        "ref": "F1", "quote": CONDITION, "role": "actor", "branch_effect": "scopes_action"}]
    first = _audit(repair_fields=[], liability_admit=True, final_binding=True)
    first["facet_verdicts"][0] = {"facet_id": "G1", "admit": False, "errors": ["bad actor role"]}
    binding = [{"ref": "F1", "quote": CONDITION, "role": "condition", "branch_effect": "scopes_action"}]
    model = TraceModel(initial, first, _partial_patch("governing_bindings", binding), {"target_verdicts": []})
    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)
    assert model.system_prompts == [
        EXTRACT,
        AUDIT,
        _material_repair_system(model.requests[2]),
        AUDIT,
    ]
    assert result.admitted_target_ids == ("check",)
    assert result.requires_review
    assert next(row for row in result.evidence["plan"]["targets"] if row["id"] == "liability")["governing_bindings"] != binding


@pytest.mark.asyncio
async def test_binding_only_repair_rejects_component_rewrite_and_keeps_healthy_peer():
    bad = _partial_patch("governing_bindings", [{
        "ref": "F1", "quote": CONDITION, "role": "condition", "branch_effect": "scopes_action",
    }])
    bad["targets"][0]["answer_components"] = [{"ref": "F1", "terms": [SOURCE]}]
    model = TraceModel(_plan(), _audit(repair_fields=["governing_bindings"]), bad)

    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert model.system_prompts == [
        EXTRACT,
        AUDIT,
        _material_repair_system(model.requests[2]),
    ]
    assert result.admitted_target_ids == ("check",)
    held = next(row for row in result.evidence["plan"]["targets"] if row["id"] == "liability")
    assert held["answer_components"] == [{"ref": "F1", "terms": [OUTCOME]}]
    assert result.evidence["repair_feedback"]["error"] == "source_plan_invalid_material_repair_scope"
    assert result.evidence["repair_feedback"]["scope"] == {
        "authorized_operations": [{"target_id": "liability", "repair_fields": ["governing_bindings"]}],
        "violations": [{"target_id": "liability", "extra_fields": ["answer_components"], "missing_fields": []}],
    }


@pytest.mark.asyncio
async def test_binding_only_repair_cannot_rewrite_the_material_obligation():
    binding = [{"ref": "F1", "quote": CONDITION, "role": "condition",
                "branch_effect": "scopes_action"}]
    repair = _partial_patch("governing_bindings", binding)
    repair["material_obligations"] = [{
        "id": "O2", "ref": "F1", "quote": OUTCOME, "dimension": "outcome",
        "target_ids": [], "evidence_level": "operational_decision",
    }]
    model = TraceModel(_plan(), _audit(repair_fields=["governing_bindings"]), repair)

    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert result.admitted_target_ids == ("check",)
    assert result.evidence["plan"]["material_obligations"][1]["target_ids"] == ["liability"]
    assert result.evidence["repair_feedback"]["error"] == "source_plan_invalid_material_repair_inventory"


@pytest.mark.asyncio
async def test_component_repair_is_allowed_only_when_the_auditor_names_that_field():
    model = TraceModel(
        _plan(liability_component=CONDITION),
        _audit(repair_fields=["answer_components"]),
        _partial_patch("answer_components", [{"ref": "F1", "terms": [OUTCOME]}]),
        _audit(repair_fields=[], liability_admit=True),
    )

    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    repaired = next(row for row in result.evidence["plan"]["targets"] if row["id"] == "liability")
    assert repaired["answer_components"] == [{"ref": "F1", "terms": [OUTCOME]}]
    assert repaired["governing_bindings"] == []
    assert set(result.admitted_target_ids) == {"check", "liability"}


@pytest.mark.asyncio
async def test_scoped_patch_protocol_still_allows_a_full_new_target_for_a_source_gap():
    initial = _plan()
    initial["targets"] = initial["targets"][:1]
    initial["material_obligations"] = initial["material_obligations"][:1]
    gap_audit = {
        "source_refs": ["F1"],
        "target_verdicts": [{"target_id": "check", "admit": True, "errors": [],
                             "repair_fields": []}],
        "facet_verdicts": [],
        "source_gaps": [{"ref": "F1", "missing_source_text": OUTCOME,
                         "reason": "missing material outcome"}],
    }
    new_target = _target("new-liability", OUTCOME)
    new_target["description"] = "Определить последствие"
    repair = {
        "targets": [new_target],
        "material_obligations": [{
            "id": "new-O2", "ref": "F1", "quote": OUTCOME, "dimension": "outcome",
            "target_ids": ["new-liability"], "evidence_level": "operational_decision",
        }],
        "excluded_units": [],
    }
    final_audit = {
        "source_refs": ["F1"],
        "target_verdicts": [
            {"target_id": "check", "admit": True, "errors": [], "repair_fields": []},
            {"target_id": "new-liability", "admit": True, "errors": [], "repair_fields": []},
        ],
        "facet_verdicts": [],
        "source_gaps": [],
    }
    model = TraceModel(initial, gap_audit, repair, final_audit)

    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert model.requests[2]["repair_operations"] == []
    assert model.requests[2]["repair_targets"] == []
    assert set(result.admitted_target_ids) == {"check", "new-liability"}


@pytest.mark.asyncio
@pytest.mark.parametrize("admit,fields", [
    (True, ["governing_bindings"]),
    (False, None),
    (False, []),
    (False, ["unknown"]),
    (False, ["governing_bindings", "governing_bindings"]),
])
async def test_target_local_audit_repair_fields_are_strict(admit, fields):
    verdict = _audit(repair_fields=[])
    row = verdict["target_verdicts"][1]
    row["admit"] = admit
    row["errors"] = [] if admit else ["field defect"]
    if fields is None:
        row.pop("repair_fields")
    else:
        row["repair_fields"] = fields
    model = TraceModel(_plan(), verdict, verdict, verdict, adapt_audit=False)

    with pytest.raises(SourcePlanError, match="source_plan_not_admitted") as caught:
        await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert model.system_prompts == [EXTRACT, AUDIT, AUDIT, AUDIT]
    assert caught.value.evidence["feedback"]["error"] == "source_plan_invalid_target_repair_fields"


@pytest.mark.asyncio
async def test_legacy_plan_without_governing_bindings_accepts_old_audit_shape():
    legacy = _plan(include_bindings=False)
    verdict = {
        "source_refs": ["F1"],
        "target_verdicts": [
            {"target_id": "check", "admit": True, "errors": []},
            {"target_id": "liability", "admit": True, "errors": []},
        ],
        "facet_verdicts": [],
        "source_gaps": [],
    }
    model = TraceModel(legacy, verdict)

    result = await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert set(result.admitted_target_ids) == {"check", "liability"}
    assert model.system_prompts == [EXTRACT, AUDIT]


@pytest.mark.asyncio
async def test_target_local_plan_cannot_use_legacy_whole_plan_audit():
    old = {"source_refs": ["F1"], "admit": True, "errors": [], "omissions": [],
           "target_ids": ["check", "liability"], "source_gaps": [], "facet_verdicts": []}
    model = TraceModel(_plan(), old, old, old, adapt_audit=False)

    with pytest.raises(SourcePlanError, match="source_plan_not_admitted") as caught:
        await build_source_assessment_plan(LESSON, [FACT], [FACT], client=model)

    assert caught.value.evidence["feedback"]["error"] == "source_plan_invalid_target_verdicts"


def test_source_plan_prompts_remain_bounded():
    assert len(AUDIT) < 6500
    assert len(EXTRACT) < 11000


def test_scope_feedback_does_not_echo_untrusted_target_or_field_values():
    from app.modules.ai.source_assessment_plan import _material_scope_feedback

    retained = SimpleNamespace(evidence={"plan": {"targets": [
        {"id": "held", "answer_components": [], "governing_bindings": []}, {"id": "healthy"}]}})
    request = {"repair_operations": [{"target_id": "held", "repair_fields": ["governing_bindings"]}]}
    proposal = {"targets": [
        {"id": "held", "answer_components": ["SECRET_VALUE"], "SECRET_FIELD": "SECRET_VALUE"},
        {"id": "healthy"}, {"id": "SECRET_ID"}, {"id": []}]}
    feedback = _material_scope_feedback(request, proposal, retained)
    assert feedback["violations"] == [
        {"target_id": "held", "extra_fields": ["answer_components"],
         "missing_fields": ["governing_bindings"], "unknown_fields_present": True},
        {"target_id": "healthy", "reason": "target_not_authorized"}]
    assert "SECRET" not in json.dumps(feedback)
