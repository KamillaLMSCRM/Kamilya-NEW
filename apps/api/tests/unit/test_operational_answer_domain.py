from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import materialize_assessment
from app.modules.ai.evidence_engine.models import AssessmentAxis, AuthoredAssessment, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    AUTHOR_PROMPT,
    CAPABILITY_OPTION_POLICY,
    COHERENT_ERROR_POLICY,
    CONSTRAINT_PROMPT,
    PROHIBITION_QUESTION_POLICY,
    REVIEW_PROMPT,
    _axis_author_payload,
    _constraint_request,
    _review_request,
)


def test_nonexclusive_capability_policy_is_identical_in_author_and_both_blind_reviewers():
    for prompt in (AUTHOR_PROMPT, REVIEW_PROMPT, CONSTRAINT_PROMPT):
        assert CAPABILITY_OPTION_POLICY in prompt
    assert "contradicted_by_source=false" in CAPABILITY_OPTION_POLICY
    assert "relation=undetermined" in CAPABILITY_OPTION_POLICY
    assert "where the source says ONLY X" in CAPABILITY_OPTION_POLICY


def test_prohibition_does_not_establish_a_permitted_location_in_any_stage():
    for prompt in (AUTHOR_PROMPT, REVIEW_PROMPT, CONSTRAINT_PROMPT):
        assert PROHIBITION_QUESTION_POLICY in prompt
    assert "question_supported=false or answers_question=false" in PROHIBITION_QUESTION_POLICY
    assert "full source key" in PROHIBITION_QUESTION_POLICY


def test_author_containment_feedback_covers_action_negation_without_granting_truth():
    assert "literal key-containing option in an ordinary MCQ" in AUTHOR_PROMPT
    assert "Never shorten, negate or otherwise edit the immutable source_claim" in AUTHOR_PROMPT
    assert "the author cannot invent such a pair" in AUTHOR_PROMPT


def test_outcome_constraints_and_coherent_misconceptions_reach_both_blind_reviews():
    for prompt in (AUTHOR_PROMPT, REVIEW_PROMPT, CONSTRAINT_PROMPT):
        assert COHERENT_ERROR_POLICY in prompt
    assert "A non-obstructing" in CAPABILITY_OPTION_POLICY
    assert "plausible_error=false" in COHERENT_ERROR_POLICY
    assert "realistic_error=false" in COHERENT_ERROR_POLICY


def _axis(kind: str) -> AssessmentAxis:
    if kind == "notice":
        prompt = ("Кого и когда сменный эксперт-оценщик обязан поставить в известность "
                  "при условии «Если имущество вызывает сомнения»?")
        key = "сменный эксперт-оценщик обязан сразу поставить в известность АУП РД."
    else:
        prompt = ("Какое действие в отношении «залоговый билет с отметкой о согласовании» "
                  "выполняет «согласовавшее лицо» при условии «Если АУП РД согласовывает микрокредит» "
                  "в срок «в день оформления и выдачи микрокредита»?")
        key = "подписывает залоговый билет с отметкой о согласовании"
    return AssessmentAxis("axis-test", "lesson", "block", "fact", ("fact",),
                          "Операция", "Порядок", prompt, key, key.casefold(), (), "rule_value")


@pytest.mark.parametrize("kind,expected_kind", [("notice", "recipient_and_timing"),
                                               ("signing", "action_on_object")])
def test_server_domain_is_identical_in_author_and_both_blind_review_requests(kind, expected_kind):
    axis = _axis(kind)
    author = _axis_author_payload(axis)
    domain = author["answer_domain"]
    assert domain["kind"] == expected_kind
    assert author["source_claim"] == axis.correct_value
    assert "correct_index" not in domain and "correct_answer" not in domain
    alternatives = (("Отдел аудита — сразу", "АУП РД — через день") if kind == "notice" else
                    ("Отказывается подписывать залоговый билет с отметкой о согласовании",
                     "Подписывает залоговый билет без отметки о согласовании"))
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, axis.required_prompt, alternatives,
    ))
    assert question is not None
    fact = SourceFact("fact", "Операция", "Порядок", axis.correct_value, "doc_id=synthetic")
    domains = {question.question_id: domain}
    review = _review_request("block", [question], [fact], answer_domains=domains)
    constraints = _constraint_request({"block_id": "block", "facts": [], "axes": [author]}, [question])
    assert review["questions"][0]["answer_domain"] == domain
    assert constraints["questions"][0]["answer_domain"] == domain
    for request in (review, constraints):
        assert "correct_index" not in request["questions"][0]
        assert "correct_answer" not in request["questions"][0]


def test_notification_contract_requires_both_recipient_and_timing_without_fixing_wrong_values():
    domain = _axis_author_payload(_axis("notice"))["answer_domain"]
    assert domain["required_components"] == ["recipient", "timing"]
    assert domain["bound_operation"] == "поставить в известность"
    assert "АУП РД" not in str(domain)


def test_signing_domain_preserves_the_exact_object_and_rejects_unknown_prompt_shape():
    axis = _axis("signing")
    domain = _axis_author_payload(axis)["answer_domain"]
    assert domain["bound_object"] == "залоговый билет с отметкой о согласовании"
    assert domain["required_components"] == ["action", "object"]
    assert _axis_author_payload(replace(axis, required_prompt="Что делают с документом?"))["answer_domain"] is None
    assert _axis_author_payload(replace(axis, correct_value="проверяет другой документ"))["answer_domain"] is None


def test_provider_wording_cannot_create_an_unknown_domain_in_blind_review():
    axis = _axis("signing")
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, axis.required_prompt,
        ("Отказывается подписывать залоговый билет с отметкой о согласовании",
         "Подписывает залоговый билет без отметки о согласовании"),
    ))
    assert question is not None
    fact = SourceFact("fact", "Операция", "Порядок", axis.correct_value, "doc_id=synthetic")
    assert _review_request("block", [question], [fact])["questions"][0]["answer_domain"] is None
    assert _constraint_request({"block_id": "block", "facts": []}, [question])["questions"][0]["answer_domain"] is None


def test_signing_response_cannot_introduce_a_different_workflow_prerequisite():
    axis = _axis("signing")
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "Отказывается подписывать залоговый билет до согласования по телефону",
        "Подписывает залоговый билет без отметки о согласовании",
    )))
    assert question is None


def test_signing_preserves_two_safe_action_choices_after_rejecting_conditional_extra():
    axis = _axis("signing")
    safe = ("Отказывается подписывать залоговый билет с отметкой о согласовании",
            "Подписывает залоговый билет без отметки о согласовании")
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        *safe, "Подписывает залоговый билет только после согласования по телефону",
    )))
    assert question is not None and question.options == (axis.correct_value, *safe)


@pytest.mark.parametrize("off_domain", [
    "Составляет акт несоответствия стандартам по выдаче микрокредитов",
    "Подписывает акт несоответствия с отметкой о согласовании",
    "Проставляет в залоговом билете отметку НЕ СОГЛАСОВАН",
])
def test_signing_action_and_base_object_cannot_be_replaced_by_a_different_task(off_domain):
    axis = _axis("signing")
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        off_domain, "Подписывает залоговый билет без отметки о согласовании",
    )))
    assert question is None


def test_object_core_is_a_literal_phrase_not_an_arbitrary_substring():
    axis = _axis("signing")
    axis = replace(axis, required_prompt=axis.required_prompt.replace(
        "залоговый билет с отметкой о согласовании", "акт"),
        correct_value="подписывает акт", normalized_correct_value="подписывает акт")
    assert materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "Подписывает контракт", "Отказывается подписывать акт",
    ))) is None


def test_preliminary_executor_domain_discloses_two_counterfactual_types_not_invented_roles():
    axis = replace(_axis("signing"),
        required_prompt="Кем выполняется именно предварительное согласование по телефону для «Удалённый пункт»?",
        correct_value="эксперт-оценщиком", normalized_correct_value="эксперт-оценщиком", axis_kind="attribute")
    author = _axis_author_payload(axis)
    domain = author["answer_domain"]
    assert domain["kind"] == "preliminary_phone_executor"
    assert len(domain["misconception_targets"]) == 2
    assert "source-named final approval authority" in domain["misconception_targets"][0]
    assert "deny that anyone must perform" in domain["misconception_targets"][1]
    assert "both source reviews remain binding" in domain["scope"]
    assert author["distractor_token_limit"] == 5
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt,
        ("региональным руководителем", "никем: согласование не требуется")))
    assert question is not None
    fact = SourceFact("fact", "Удалённый пункт", "Порядок", axis.correct_value, "doc_id=synthetic")
    assert _review_request("block", [question], [fact], answer_domains={question.question_id: domain})["questions"][0]["answer_domain"] == domain
    assert _constraint_request({"block_id": "block", "facts": [], "axes": [author]}, [question])["questions"][0]["answer_domain"] == domain
