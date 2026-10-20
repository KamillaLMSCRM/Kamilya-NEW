"""Observed PDF omissions: retain complete scope, not cosmetic MCQ padding."""
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine
from app.modules.ai.evidence_engine.semantic_assessment import _axis_answer_domain


def fixture(value):
    fact = SourceFact("f", "Безопасность", "обязанность", value, "doc_id=synthetic;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Работа с правилами", "Применять правила", "", ("f",), (), 1)
    return fact, lesson


@pytest.mark.parametrize("opening", ["В", "в"])
def test_complete_archive_prohibition_has_one_source_owned_opposite(opening):
    value = opening + " помещениях хранилищ, архива не должно допускаться устройство бытовых комнат для приема пищи."
    fact, lesson = fixture(value)
    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]
    q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, "Что допускается?", ()))
    assert q is not None and q.kind == "true_false"
    assert q.options == (value, opening + " помещениях хранилищ, архива допускается устройство бытовых комнат для приема пищи.")
    assert q.prompt == "Допускается ли в помещениях хранилищ, архива устройство бытовых комнат для приема пищи?"


@pytest.mark.parametrize("tail", [
    ", кроме согласованных исключений", ", за исключением разрешенных случаев",
    ", если помещение свободно", ", но временное размещение разрешено",
    ", однако возможны исключения", ", работники должны покинуть помещение",
    "; хранение продуктов разрешено", " — неверное утверждение",
    " при условии соблюдения правил", " после проверки помещения",
])
def test_qualified_archive_prohibition_never_grants_a_binary_inverse(tail):
    value = "В помещениях хранилищ, архива не должно допускаться устройство бытовых комнат для приема пищи" + tail + "."
    fact, lesson = fixture(value)
    for axis in derive_assessment_axes(lesson, [fact], block_id="b"):
        q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, "Что допускается?", ()))
        assert q is None or q.kind != "true_false"


def test_long_duty_contrasts_only_the_source_verified_appointment_qualification():
    actor = "Ответственные за состояние электроустановок и электросетей сотрудники, назначенные приказом руководителя ломбарда,"
    duty = ("обеспечить организацию и своевременное проведение профилактических осмотров и планово-предупредительных "
            "ремонтов электрооборудования, аппаратуры и электросети, защитного заземления, а также своевременное "
            "устранение нарушений, неисправность которых может привести к пожару")
    fact, lesson = fixture(f"4.2. {actor} обязаны:\n— {duty};\n— контролировать состояние оборудования.")
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id="b") if a.correct_value == actor)
    q = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, ()))
    assert q is not None and q.kind == "true_false"
    assert q.options == (actor, actor.replace(", назначенные приказом", ", не назначенные приказом"))
    assert duty in q.prompt and q.correct_answer == actor
    # A provider-authored/unbound actor cannot acquire the same truth exemption.
    fake = replace(axis, correct_value=actor.replace("ломбарда", "компании"))
    assert materialize_assessment(fake, AuthoredAssessment(fake.axis_id, fake.required_prompt, ())) is None


def test_compound_duty_authoring_names_two_independent_violation_targets():
    claim = "содержать в исправном состоянии системы и средства пожаротушения, не допускать их использования не по назначению"
    fact, lesson = fixture("1.6. Работникам Ломбарда следует:\n— " + claim + ";\n— знать правила безопасности.")
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id="b") if a.correct_value == claim)
    domain = _axis_answer_domain(axis)
    assert domain is not None and domain["kind"] == "readiness_and_intended_use"
    assert len(domain["misconception_targets"]) == 2
    assert domain["required_components"] == ["working_condition", "intended_use"]


def test_lesson_cannot_drop_the_legal_basis_of_an_appointment():
    basis = "в силу действующих нормативных правовых и иных актов"
    value = ("Руководитель Ломбарда назначает лиц, которые по занимаемой должности или по характеру выполняемых работ "
             + basis + " выполняют соответствующие правила пожарной безопасности, либо обеспечивают их соблюдение на определенных участках работ.")
    fact, lesson = fixture(value)
    paraphrase = ("Руководитель назначает лиц, которые по должности или характеру работ выполняют правила пожарной безопасности "
                  "либо обеспечивают их соблюдение на определённых участках.")
    payload = dict(title=lesson.title, objective=lesson.objective, questions=[], blocks=[
        dict(heading="Ответственность руководителя", text=paraphrase, fact_ids=["f"])])
    rendered, _, _ = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=lesson, plan_fact_ids={"f"}, facts_by_id={"f": fact}, seeds=[])
    assert basis in rendered.content


def test_a_faithful_appointment_paraphrase_remains_usable():
    from app.modules.ai.evidence_engine.provider_engine import _loses_normative_qualification

    basis = "в силу действующих нормативных правовых и иных актов"
    fact, _ = fixture("Руководитель назначает лиц, которые " + basis + " обеспечивают соблюдение правил пожарной безопасности.")
    assert not _loses_normative_qualification(
        "Руководитель назначает лиц, обеспечивающих соблюдение правил пожарной безопасности " + basis + ".", [fact])
    assert _loses_normative_qualification("Руководитель назначает лиц для обеспечения соблюдения правил пожарной безопасности.", [fact])
