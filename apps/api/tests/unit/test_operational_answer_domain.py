from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import materialize_assessment
from app.modules.ai.evidence_engine.models import AssessmentAxis, AuthoredAssessment, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _axis_author_payload,
    _constraint_request,
    _review_request,
)


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
