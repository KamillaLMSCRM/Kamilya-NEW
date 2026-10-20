from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import materialize_assessment
from app.modules.ai.evidence_engine.models import AssessmentAxis, AuthoredAssessment, SourceFact
from app.modules.ai.evidence_engine.operational_control import project_control_responsibility
from app.modules.ai.evidence_engine.quality import filter_acceptable_questions
from app.modules.ai.evidence_engine.semantic_assessment import (
    _author_shape_rejection_reasons,
    _axis_author_payload,
    _constraint_request,
    _review_request,
)


def _fixture():
    value = ("Руководитель офиса, начальники подразделений, старшие специалисты "
             "контролируют соблюдение Правил пожарной безопасности подчиненными им работниками.")
    projection = project_control_responsibility(value)
    assert projection is not None
    key, prompt = projection
    axis = AssessmentAxis("axis-control", "lesson", "block", "fact", ("fact",),
                          "Контроль", "Ответственные", prompt, key, key.casefold(), (), "rule_value")
    fact = SourceFact("fact", "Контроль", "Ответственные", value, "doc_id=synthetic")
    return axis, fact


def test_complete_control_scope_is_shared_by_author_and_both_blind_reviewers():
    axis, fact = _fixture()
    author = _axis_author_payload(axis)
    domain = author["answer_domain"]
    assert domain is not None and domain["kind"] == "complete_actor_scope"
    assert domain["required_components"] == ["complete_actor_set"]
    assert domain["bound_operation"].startswith("контролируют соблюдение")
    assert "bare substring" in domain["scope"]
    assert axis.correct_value not in str(domain)
    wrong = ("Только начальники подразделений, без руководителя офиса и старших специалистов",
             "Только руководитель офиса, без начальников подразделений и старших специалистов")
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, wrong))
    assert question is not None
    review = _review_request("block", [question], [fact], answer_domains={question.question_id: domain})
    constraint = _constraint_request({"block_id": "block", "facts": [], "axes": [author]}, [question])
    assert review["questions"][0]["answer_domain"] == domain
    assert constraint["questions"][0]["answer_domain"] == domain
    assert "correct_answer" not in review["questions"][0]
    assert "correct_answer" not in constraint["questions"][0]


def test_complete_control_contract_does_not_relax_containment_for_bare_actor_subset():
    axis, _ = _fixture()
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "начальники подразделений",
        "Только руководитель офиса, без начальников подразделений и старших специалистов",
    )))
    assert question is not None
    assert filter_acceptable_questions([replace(question, semantic_reviewed=True)]) == []


def test_complete_control_contract_is_not_inferred_from_provider_or_unrecognized_prompts():
    axis, _ = _fixture()
    assert _axis_author_payload(replace(axis, required_prompt="Кто отвечает за контроль?"))["answer_domain"] is None
    unsafe = axis.required_prompt.replace("контролируют", "должны контролировать")
    assert _axis_author_payload(replace(axis, required_prompt=unsafe))["answer_domain"] is None


@pytest.mark.parametrize("key,prompt,kind", [
    ("составляется Акт несоответствия правилам с расчетом реальной суммы операции",
     "Какой документ оформляется и что он должен содержать при условии «Если проверка отклонена»?",
     "document_and_contents"),
    ("решение по предоставлению операции должно быть предварительно согласовано по телефону.",
     "Как необходимо предварительно согласовать решение при условии «Если операция после 18:00»?",
     "prior_approval_channel"),
    ("проставляет об этом отметку в программном обеспечении организации",
     "Как «согласовавшее лицо» фиксирует решение в программном обеспечении организации при условии «Если операция согласована»?",
     "recorded_decision"),
])
def test_strict_operational_domains_bind_required_response_components_without_truth_exemption(key, prompt, kind):
    axis, _ = _fixture()
    axis = replace(axis, correct_value=key, normalized_correct_value=key.casefold(), required_prompt=prompt)
    domain = _axis_author_payload(axis)["answer_domain"]
    assert domain is not None and domain["kind"] == kind
    assert domain["required_components"]
    assert "correct_answer" not in domain
    assert _axis_author_payload(replace(axis, correct_value="другая несвязанная операция"))["answer_domain"] is None


def test_software_mark_target_does_not_invent_an_unstated_delay_as_a_wrong_answer():
    axis, _ = _fixture()
    key = "проставляет об этом отметку в программном обеспечении организации"
    prompt = "Как «согласовавшее лицо» фиксирует решение в программном обеспечении организации при условии «Если операция согласована»?"
    axis = replace(axis, correct_value=key, normalized_correct_value=key.casefold(), required_prompt=prompt)
    delayed = "Проставляет отметку о согласовании в программном обеспечении организации после истечения первого рабочего дня"
    safe = ("Проставляет отметку об отказе в программном обеспечении организации",
            "Не проставляет отметку о согласовании в программном обеспечении организации")
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, prompt, (delayed, *safe)))
    assert question is not None
    assert "option_1:outside_recorded_decision_scope" in _author_shape_rejection_reasons(question, axis)
    admitted_shape = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, prompt, safe))
    assert admitted_shape is not None
    assert not _author_shape_rejection_reasons(admitted_shape, axis)


def test_preliminary_phone_executor_does_not_use_a_qualified_same_role_as_wrong_option():
    axis, _ = _fixture()
    key = "эксперт-оценщиком"
    prompt = "Кем выполняется именно предварительное согласование по телефону для «Операции по II категории вне населённого пункта»?"
    axis = replace(axis, correct_value=key, normalized_correct_value=key.casefold(), required_prompt=prompt)
    domain = _axis_author_payload(axis)["answer_domain"]
    assert domain is not None and domain["kind"] == "preliminary_phone_executor"
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, prompt, (
        "сменный эксперт-оценщик", "АУП РД", "руководитель подразделения",
    )))
    assert question is not None
    assert "option_1:role_scope_overlaps_key" in _author_shape_rejection_reasons(question, axis)
    assert "окончательное" not in prompt


def test_derived_multiword_executor_rejects_only_complete_role_overlap():
    from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
    from app.modules.ai.evidence_engine.models import LessonDraft

    value = ("Операции по VII категории при расположении пункта вне границ округа "
             "предварительно согласовываются выездным оценщиком по телефону.")
    fact = SourceFact("remote", "Категория операции", "согласование", value,
                      "doc_id=synthetic;source_revision=v2;section=approval;part=7")
    lesson = LessonDraft("lesson", "", "", "", "", (fact.fact_id,), (), 1)
    axis = next(axis for axis in derive_assessment_axes(lesson, [fact], block_id="block")
                if axis.correct_value == "выездным оценщиком")
    assert _axis_author_payload(axis)["answer_domain"]["kind"] == "preliminary_phone_executor"
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "старший выездной оценщик", "сменный оценщик",
        "никем: предварительное согласование не требуется",
    )))
    assert question is not None
    assert _author_shape_rejection_reasons(question, axis) == ("option_1:role_scope_overlaps_key",)


def test_unsupported_preliminary_executor_role_morphology_fails_closed():
    axis, _ = _fixture()
    key = "комиссией"
    prompt = "Кем выполняется именно предварительное согласование по телефону для «Операции категории»?"
    axis = replace(axis, correct_value=key, normalized_correct_value=key, required_prompt=prompt)
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, prompt, (
        "руководителем", "никем: согласование не требуется",
    )))
    assert question is not None
    assert "preliminary_executor_role_shape_unsupported" in _author_shape_rejection_reasons(question, axis)
