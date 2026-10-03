"""Bounded V2 assessment-shape regressions at source and review boundaries."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment


def _narrative_corpus(*, markdown_table: bool) -> DirectSourceCorpus:
    separator = "| --- | --- |\n" if markdown_table else ""
    chunk = DirectSourceChunk(
        chunk_id="shape-chunk", doc_id="shape-doc", doc_name="shape.txt",
        title="Shape source", headings=(),
        text=(f"# Department heading\n\n| Условие | Описание |\n{separator}\n"
               "Сотрудник обязан проверить документ перед выдачей.\n\n"
               "Сотрудник обязан сохранить копию документа."),
        source_revision="document:shape-sha", chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="synthetic-tenant",
        documents=(DirectSourceDocument(
            doc_id="shape-doc", title="Shape source", filename="shape.txt",
            category="training_material", source_revision="document:shape-sha", chunks=(chunk,),
        ),),
        total_chars=len(chunk.text), total_chunks=1,
    )


@pytest.mark.parametrize("markdown_table", [True, False])
def test_source_boundary_drops_markdown_heading_and_table_header_but_keeps_rule(
    markdown_table: bool,
) -> None:
    bundle = build_evidence_source(_narrative_corpus(markdown_table=markdown_table))
    facts = list(bundle.all_facts)

    assert all("Department heading" not in fact.value for fact in facts)
    headers = [fact for fact in facts if fact.value == "Условие | Описание"]
    if markdown_table:
        assert headers == []
    else:
        assert len(headers) == 1
        assert headers[0].confidence == 0.0
        assert headers[0].uncertainty == "table_header_fragment"
    assert any("обязан проверить документ" in fact.value for fact in facts)
    rule = next(fact for fact in facts if "обязан проверить" in fact.value)
    lesson = LessonDraft(
        "source-lesson", "Source", "Rules", "Apply rules", rule.value,
        tuple(fact.fact_id for fact in facts), (), 1,
    )
    axes = derive_assessment_axes(lesson, facts, block_id="source-block")
    assert any(axis.primary_fact_id == rule.fact_id for axis in axes)
    assert not {header.fact_id for header in headers}.intersection(
        axis.primary_fact_id for axis in axes
    )


class _ReviewedReplayClient:
    def __init__(self, *, prompt: str, distractors: tuple[str, str], reject_review: bool) -> None:
        self.prompt = prompt
        self.distractors = distractors
        self.reject_review = reject_review
        self.requests: list[dict] = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        task = request["task"]
        if task in {"assessment_generate", "assessment_repair"}:
            payload = {"questions": [{"axis_id": axis["axis_id"], "prompt": self.prompt,
                                       "distractors": list(self.distractors)}
                                      for axis in request["axes"][:1]]}
        elif task == "assessment_review":
            payload = {"reviews": [{
                "question_id": question["question_id"],
                "question_supported": not self.reject_review,
                "educational": not self.reject_review,
                "explanation_supported": not self.reject_review,
                "options_distinct": True,
                "options": [{"index": index, "answers_question": not self.reject_review,
                             "correct": index == 0, "plausible_error": index > 0,
                             "contradicted_by_source": index > 0,
                             "same_practical_task": not self.reject_review}
                            for index in range(len(question["options"]))],
            } for question in request["questions"]]}
        elif task == "assessment_constraints":
            facts_by_id = {fact["fact_id"]: fact for fact in request["facts"]}
            ids = {fact_id for question in request["questions"] for fact_id in question["evidence_fact_ids"]}
            payload = {"rules": [{"fact_id": fact_id, "quote": facts_by_id[fact_id]["value"], "kind": "attribute"} for fact_id in ids],
                       "reviews": [{"question_id": question["question_id"], "reason": "control", "distinct_errors": True,
                                    "options": [{"index": index, "relation": "entailed" if index == 0 else "contradicted",
                                                  "invented_constraint": False, "realistic_error": True}
                                                 for index in range(len(question["options"]))]}
                                   for question in request["questions"]]}
        else:
            raise AssertionError(f"unexpected task: {task}")
        return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1)


def _fact_case(
    value: str, attribute: str = "содержание", *, subject: str = "Заявка",
) -> tuple[LessonDraft, dict[str, SourceFact]]:
    fact = SourceFact("fact-shape", subject, attribute, value, "doc_id=synthetic;section=shape")
    lesson = LessonDraft("lesson-shape", "Synthetic", "Shape lesson", "Apply the source", value, (fact.fact_id,), (), 1)
    return lesson, {fact.fact_id: fact}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "prompt", "distractors"),
    [("Раздел: Приоритеты заявок", "Какие три элемента определяют приоритет?", ("Срочность заявки", "Дата регистрации")),
     ("Как определить приоритет заявки?", "Какой приоритет требуется для заявки?", ("По сроку", "По дате регистрации")),
     ("| Условие | Описание |", "Что указано в условии?", ("Срок исполнения", "Дата регистрации"))],
)
async def test_correct_independent_review_omits_bad_candidates_after_bounded_repair(
    value: str, prompt: str, distractors: tuple[str, str],
) -> None:
    """Permissive-review admission remains a separate diagnostic, not this contract."""
    lesson, facts = _fact_case(value)
    client = _ReviewedReplayClient(prompt=prompt, distractors=distractors, reject_review=True)
    result = await generate_block_assessment([lesson], facts, client)

    assert result.questions == ()
    assert result.audit["dropped"] == 1
    assert [request["task"] for request in client.requests] == [
        "assessment_generate", "assessment_review", "assessment_repair", "assessment_review",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "prompt", "attribute", "subject", "distractors"),
    [
        (
            "Как вас зовут?", "Какой вопрос сотрудник задаёт клиенту при знакомстве?",
            "вопрос для знакомства", "Сотрудник",
            ("Какой срок?", "Какой документ нужен?"),
        ),
        (
            "Отдел сопровождения клиентов", "Какой отдел отвечает за регистрацию заявки?",
            "ответственный отдел", "Заявка",
            ("Отдел кассовых операций", "Отдел закупок"),
        ),
    ],
)
async def test_legitimate_question_and_named_section_remain_accepted(
    value: str, prompt: str, attribute: str, subject: str, distractors: tuple[str, str],
) -> None:
    lesson, facts = _fact_case(value, attribute, subject=subject)
    client = _ReviewedReplayClient(prompt=prompt, distractors=distractors, reject_review=False)
    result = await generate_block_assessment([lesson], facts, client)
    assert len(result.questions) == 1
    assert result.questions[0].correct_answer == value
    assert result.questions[0].prompt == prompt


@pytest.mark.asyncio
async def test_prohibited_expression_preserves_negative_qualifier() -> None:
    lesson, facts = _fact_case("Ломбард не вправе требовать выплаты комиссии.", "запрет")
    client = _ReviewedReplayClient(
        prompt="provider wording is replaced",
        distractors=("Ломбард вправе требовать выплаты комиссии.", "Комиссия обязательна."),
        reject_review=False,
    )
    result = await generate_block_assessment([lesson], facts, client)
    assert len(result.questions) == 1
    assert "не вправе" in result.questions[0].correct_answer
    assert result.questions[0].prompt.startswith("Вправе ли")
