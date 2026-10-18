"""Real source adapter -> lesson planner -> pre-provider selection regressions."""
from __future__ import annotations

import json

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine import semantic_assessment
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.assessment_axes import operational_claim_priority
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _unsupported_replacement_advice,
    generate_block_assessment,
)
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason

EQUIPMENT = """Учебная инструкция: выдача рабочего оборудования

Синтетический материал для видеоинструкции Камили. Все правила и названия вымышлены. Персональных данных и сведений клиентов нет.

1. До выдачи оборудования проверьте его комплектность по учебному перечню.
2. Запишите условный инвентарный номер и дату выдачи в журнал учебного подразделения.
3. Если комплект неполный или оборудование повреждено, остановите выдачу и обратитесь к ответственному руководителю.
4. После возврата проверьте комплектность повторно и отметьте возврат в журнале.

Конец учебного материала.
"""

QA_BUTTONS_20261018 = """QA BUTTONS 20261018 — Приём учебного оборудования

Это полностью вымышленная инструкция для тестирования Kamilya LMS.
Маркер набора: KAMILYA_CABINET_ACTIONS_20261018.

Цель: принять учебный прибор в демонстрационный кабинет.

1. До включения сравните номер прибора с карточкой поставки. При несовпадении номера остановите приём и обратитесь к руководителю учебного кабинета. Не включайте прибор до разрешения расхождения.
2. Осмотрите корпус и кабель. При трещине корпуса ИЛИ повреждении кабеля остановите приём и сообщите руководителю учебного кабинета. Подключать такой прибор запрещено.
3. Если номер совпадает и повреждений нет, запишите в журнале номер прибора и дату приёма. Только после записи передайте прибор на учебный стол.
4. После занятия отключите прибор от сети и верните его в подписанный шкаф. Отметьте возврат в том же журнале.

Названия людей, компаний и оборудования не относятся к реальным клиентам. Документ не устанавливает юридических обязанностей и используется только для проверки программного обеспечения.
"""

def equipment_plan(text: str = EQUIPMENT):
    chunk = DirectSourceChunk(
        chunk_id="equipment-chunk", doc_id="equipment", doc_name="equipment.txt",
        title="Выдача оборудования", headings=(), text=text,
        source_revision="document:equipment-fixture", chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="synthetic-tenant", documents=(DirectSourceDocument(
            doc_id="equipment", title="Выдача оборудования", filename="equipment.txt",
            category="training_material", source_revision="document:equipment-fixture",
            chunks=(chunk,),
        ),), total_chars=len(text), total_chunks=1,
    )
    bundle = build_evidence_source(corpus)
    result = EvidenceCourseEngine().generate_from_document(bundle.document)
    return result.course.lessons, {fact.fact_id: fact for fact in result.admitted_facts}


class SelectionProbe:
    """Observe real pre-provider targets; never pretend an author/reviewer passed."""
    def __init__(self):
        self.requests = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        if request.get("task") == "assessment_generate":
            self.requests.append(request)
        raise AllProvidersFailedError("offline-selection-probe", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE])


@pytest.mark.asyncio
async def test_equipment_selection_excludes_preamble_and_prioritizes_stop_rule():
    lessons, facts = equipment_plan()
    probe = SelectionProbe()
    await generate_block_assessment(list(lessons), facts, probe)
    claims = [axis["source_claim"] for request in probe.requests for axis in request["axes"]]
    assert claims, "The real adapter and planner must produce business assessment targets"
    assert all("Синтетический материал" not in claim and "Конец учебного" not in claim for claim in claims)
    assert any("остановите выдачу" in claim and "руководител" in claim for claim in claims)
    first_attempt = {axis["axis_id"] for request in probe.requests for axis in request["axes"]}
    assert len(first_attempt) <= 3, "Selection must preserve the existing density cap, not pad a quota"


@pytest.mark.asyncio
async def test_qa_buttons_exact_source_prioritizes_work_steps_over_metadata():
    lessons, facts = equipment_plan(QA_BUTTONS_20261018)
    probe = SelectionProbe()

    result = await generate_block_assessment(list(lessons), facts, probe)

    claims = list(dict.fromkeys(
        axis["source_claim"] for request in probe.requests for axis in request["axes"]
    ))
    assert len(claims) == 3, "The existing per-lesson density ceiling remains three"
    assert any("несовпадении номера остановите приём" in claim for claim in claims)
    assert any("повреждении кабеля остановите приём" in claim for claim in claims)
    assert any("запишите в журнале номер прибора" in claim for claim in claims)
    assert all("Цель:" not in claim for claim in claims)
    assert all("юридических обязанностей" not in claim for claim in claims)
    assert all("KAMILYA_CABINET_ACTIONS_20261018" not in claim for claim in claims)

    return_fact_ids = {
        fact.fact_id for fact in facts.values()
        if "верните его в подписанный шкаф" in fact.value
    }
    assert return_fact_ids, "The fourth working step must remain an eligible source fact"
    selection = result.audit["narrative_selection_coverage"][0]
    assert return_fact_ids <= set(selection["eligible_fact_ids"])
    assert return_fact_ids <= set(selection["unassessed_fact_ids"])
    assert not return_fact_ids & set(selection["selected_fact_ids"])


@pytest.mark.asyncio
@pytest.mark.parametrize("text,critical", [
    (
        "При ознакомлении раздел описывает общую схему работы.\n\n"
        "Когда описывается склад, раздел содержит общие сведения.\n\n"
        "Если речь об оборудовании, раздел перечисляет его категории.\n\n"
        "При повреждении оборудования остановите выдачу и сообщите руководителю.",
        "остановите выдачу",
    ),
    (
        "When reading the introduction, this section describes the workflow.\n\n"
        "If discussing the warehouse, this section describes its categories.\n\n"
        "When describing equipment, this section contains general background.\n\n"
        "If equipment is damaged, stop issuing it and notify the supervisor.",
        "stop issuing",
    ),
    (
        "Бұл бөлімде жұмыс тәртібі туралы жалпы ақпарат берілген.\n\n"
        "Бұл бөлімде қойманың санаттары туралы ақпарат берілген.\n\n"
        "Бұл бөлімде жабдықтың түрлері туралы жалпы мәлімет берілген.\n\n"
        "Егер жабдық зақымдалса, беруді тоқтатыңыз және басшыға хабарлаңыз.",
        "тоқтатыңыз",
    ),
    (
        "When reading the introduction, this section describes the workflow.\n\n"
        "If discussing the warehouse, this section describes its categories.\n\n"
        "When describing equipment, this section contains general background.\n\n"
        "If equipment is damaged, contact the supervisor.",
        "contact the supervisor",
    ),
    (
        "Бұл бөлімде жұмыс тәртібі туралы жалпы ақпарат берілген.\n\n"
        "Бұл бөлімде қойманың санаттары туралы ақпарат берілген.\n\n"
        "Бұл бөлімде жабдықтың түрлері туралы жалпы мәлімет берілген.\n\n"
        "Егер жабдық зақымдалса, басшыға жүгініңіз.",
        "жүгініңіз",
    ),
])
async def test_critical_stop_rule_outranks_conditional_background(text, critical):
    lessons, facts = equipment_plan(text)
    probe = SelectionProbe()
    result = await generate_block_assessment(list(lessons), facts, probe)
    claims = [axis["source_claim"] for request in probe.requests for axis in request["axes"]]
    assert any(critical in claim for claim in claims)
    critical_ids = {
        fact.fact_id for fact in facts.values() if critical in fact.value
    }
    assert critical_ids <= set(result.audit["coverage"]["critical_missing_fact_ids"])


@pytest.mark.asyncio
async def test_missing_critical_question_cannot_be_hidden_by_complete_topic_coverage(monkeypatch):
    lessons, facts = equipment_plan()
    monkeypatch.setattr(semantic_assessment, "assess_topic_coverage", lambda *args, **kwargs: {
        "missing_fact_ids": [], "requires_review": False, "audit_incomplete": False,
    })
    result = await generate_block_assessment(list(lessons), facts, SelectionProbe())
    critical = [fact.fact_id for fact in facts.values() if "остановите выдачу" in fact.value]
    assert critical
    assert result.audit["coverage"]["critical_missing_fact_ids"] == critical
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["terminal_status"] == "review_required"
    selection = result.audit["narrative_selection_coverage"][0]
    assert len(selection["eligible_fact_ids"]) == 4
    assert len(selection["selected_fact_ids"]) == 3
    assert selection["assessed_fact_ids"] == []
    assert selection["complete"] is False


@pytest.mark.asyncio
async def test_density_limit_keeps_omitted_critical_rule_visible():
    text = "\n\n".join([
        "1. Если комплект неполный, остановите выдачу и сообщите руководителю.",
        "2. Если журнал недоступен, остановите выдачу и сообщите руководителю.",
        "3. Если номер отсутствует, остановите выдачу и сообщите руководителю.",
        "4. Если пломба повреждена, остановите выдачу и сообщите руководителю.",
    ])
    lessons, facts = equipment_plan(text)
    result = await generate_block_assessment(list(lessons), facts, SelectionProbe())
    selection = result.audit["narrative_selection_coverage"][0]
    assert len(selection["critical_fact_ids"]) == 4
    assert len(selection["selected_fact_ids"]) == 3
    assert set(selection["critical_fact_ids"]) - set(selection["selected_fact_ids"])
    assert len(result.audit["coverage"]["critical_missing_fact_ids"]) == 4
    assert result.audit["coverage"]["requires_review"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("actions,prohibition", [
    (
        "Проверьте наличие документа.\n\nЗапишите номер в журнал.\n\nОтметьте дату в карточке.",
        "Ломбард не вправе принимать недействительный документ.",
    ),
    (
        "Проверьте наличие документа.\n\nЗапишите номер в журнал.\n\nОтметьте дату в карточке.",
        "Если документ недействителен, выдача запрещена.",
    ),
    (
        "Check that the document is present.\n\nRecord its number in the log.\n\nVerify its date on the card.",
        "The employee must not accept an invalid document.",
    ),
    (
        "Құжаттың бар екенін тексеріңіз.\n\nНөмірді журналға жазыңыз.\n\nКүнін карточкада белгілеңіз.",
        "Жарамсыз құжатты қабылдауға тыйым салынады.",
    ),
])
async def test_explicit_prohibition_outranks_routine_actions(actions, prohibition):
    lessons, facts = equipment_plan(actions + "\n\n" + prohibition)
    probe = SelectionProbe()
    result = await generate_block_assessment(list(lessons), facts, probe)
    claims = [axis["source_claim"] for request in probe.requests for axis in request["axes"]]
    assert any(prohibition in claim for claim in claims)
    prohibited_ids = {fact.fact_id for fact in facts.values() if prohibition in fact.value}
    assert prohibited_ids
    assert prohibited_ids <= set(result.audit["coverage"]["critical_missing_fact_ids"])


@pytest.mark.parametrize("claim", [
    "Инструкция должна содержать номер версии.",
    "The document must contain a revision number.",
    "Equipment may not be available.",
    "Құжатта нұсқа нөмірі болуы керек.",
])
def test_positive_obligation_is_not_automatically_critical(claim):
    assert operational_claim_priority(claim)[0] == 0


@pytest.mark.asyncio
async def test_prohibition_span_wins_over_routine_action_in_same_fact():
    prohibition = "Если документ недействителен, выдача запрещена."
    lessons, facts = equipment_plan("Проверьте наличие документа. " + prohibition)
    probe = SelectionProbe()
    await generate_block_assessment(list(lessons), facts, probe)
    claims = [axis["source_claim"] for request in probe.requests for axis in request["axes"]]
    assert prohibition in claims


CRITICAL_EQUIPMENT_RULE = (
    "Если комплект неполный или оборудование повреждено, остановите выдачу "
    "и обратитесь к ответственному руководителю."
)
REPLACEMENT_COUNTERFACTUAL = (
    "Самостоятельно заменить повреждённую деталь и продолжить выдачу "
    "без обращения к руководителю."
)


def _replacement_question(
    fact: SourceFact,
    *,
    reviewed: bool = True,
    source_quote: str | None = None,
) -> QuestionDraft:
    return QuestionDraft(
        question_id=f"question-{fact.fact_id}",
        lesson_id="lesson-equipment",
        kind="single_choice",
        prompt="Как поступить при проблеме с комплектом?",
        options=(fact.value, REPLACEMENT_COUNTERFACTUAL),
        correct_answer=fact.value,
        explanation=fact.value,
        fact_id=fact.fact_id,
        evidence_fact_ids=(fact.fact_id,),
        source_quote=source_quote or fact.value,
        semantic_block_id="block-equipment",
        semantic_reviewed=reviewed,
    )


def test_reviewed_narrative_stop_rule_allows_meaningful_replacement_counterfactual():
    fact = SourceFact(
        fact_id="equipment-critical",
        subject="Выдача оборудования",
        attribute="положение",
        value=CRITICAL_EQUIPMENT_RULE,
        source_locator="doc_id=equipment;section=rules;part=3",
    )

    assert _unsupported_replacement_advice(_replacement_question(fact), [fact]) is False


@pytest.mark.parametrize(
    "fact,question",
    [
        (
            SourceFact(
                fact_id="catalog-attribute",
                subject="Деталь",
                attribute="материал",
                value="Сталь",
                source_locator="doc_id=equipment;sheet=Каталог;row=2;column=3",
            ),
            None,
        ),
        (
            SourceFact(
                fact_id="unreviewed-action",
                subject="Выдача оборудования",
                attribute="положение",
                value=CRITICAL_EQUIPMENT_RULE,
                source_locator="doc_id=equipment;section=rules;part=3",
            ),
            "unreviewed",
        ),
        (
            SourceFact(
                fact_id="unsupported-key",
                subject="Выдача оборудования",
                attribute="положение",
                value="Остановите выдачу при повреждении оборудования.",
                source_locator="doc_id=equipment;section=rules;part=3",
            ),
            "wrong-source-quote",
        ),
        (
            SourceFact(
                fact_id="nonnarrative-action",
                subject="Выдача оборудования",
                attribute="положение",
                value=CRITICAL_EQUIPMENT_RULE,
                source_locator="doc_id=equipment;section=rules",
            ),
            "nonnarrative",
        ),
    ],
)
def test_replacement_counterfactual_guard_remains_for_unsupported_cases(fact, question):
    if question is None:
        draft = _replacement_question(fact)
    elif question == "unreviewed":
        draft = _replacement_question(fact, reviewed=False)
    elif question == "wrong-source-quote":
        draft = _replacement_question(fact, source_quote="Другой источник без этого правила.")
    else:
        draft = _replacement_question(fact)

    assert _unsupported_replacement_advice(draft, [fact]) is True
