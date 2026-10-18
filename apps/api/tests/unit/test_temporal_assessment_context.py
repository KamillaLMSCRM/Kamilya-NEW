from __future__ import annotations

import json
from dataclasses import replace

from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    AUTHOR_PROMPT,
    CONSTRAINT_PROMPT,
    REVIEW_PROMPT,
    _parse_constraint_reviews,
)

FACTS = [
    SourceFact(
        "checkbeforeissuance",
        "Equipment",
        "Before issuance",
        "До выдачи оборудования проверьте его комплектность по учебному перечню.",
        "doc_id=equipment;section=procedure;item=1",
    ),
    SourceFact(
        "recordinventory+issuedate",
        "Equipment",
        "Issue log",
        "Запишите условный инвентарный номер и дату выдачи в журнал учебного подразделения.",
        "doc_id=equipment;section=procedure;item=2",
    ),
    SourceFact(
        "incompleteORdamaged",
        "Equipment",
        "Stop condition",
        "Если комплект неполный или оборудование повреждено, остановите выдачу и обратитесь к ответственному руководителю.",
        "doc_id=equipment;section=procedure;item=3",
    ),
    SourceFact(
        "afterreturnrecheck/log",
        "Equipment",
        "After return",
        "После возврата проверьте комплектность повторно и отметьте возврат в журнале.",
        "doc_id=equipment;section=procedure;item=4",
    ),
]

KEY = "До выдачи оборудования проверьте его комплектность по учебному перечню."
QUESTION = "Что нужно сделать с оборудованием до его выдачи?"


def _question(options: tuple[str, ...]) -> QuestionDraft:
    return QuestionDraft(
        question_id="q-equipment-before-issue",
        lesson_id="lesson-equipment",
        kind="single_choice",
        prompt=QUESTION,
        options=options,
        correct_answer=KEY,
        explanation="Проверка комплектности выполняется до выдачи.",
        fact_id="checkbeforeissuance",
        evidence_fact_ids=("checkbeforeissuance",),
    )


def _review_payload(question: QuestionDraft, *, second_relation: str) -> dict:
    return {
        "rules": [
            {"fact_id": fact.fact_id, "quote": fact.value, "kind": "required"}
            for fact in FACTS
        ],
        "reviews": [
            {
                "question_id": question.question_id,
                "reason": "The options preserve the requested before-issuance action.",
                "distinct_errors": True,
                "options": [
                    {"index": 0, "relation": "entailed", "invented_constraint": False, "realistic_error": False},
                    {"index": 1, "relation": "contradicted", "invented_constraint": False, "realistic_error": True},
                    {"index": 2, "relation": second_relation, "invented_constraint": False, "realistic_error": True},
                ],
            }
        ],
    }


def test_undetermined_temporal_distractor_rejects_when_only_one_real_wrong_remains():
    question = _question((
        KEY,
        "Выдать оборудование, а комплектность проверить после возврата по учебному перечню.",
        "Проверить комплектность оборудования по учебному перечню после записи в журнал выдачи.",
    ))

    result = _parse_constraint_reviews(json.dumps(_review_payload(question, second_relation="undetermined")), [question], FACTS)

    assert result[question.question_id] is False


def test_corrected_temporal_distractor_is_accepted_without_changing_key():
    question = _question((
        KEY,
        "Выдать оборудование, а комплектность проверить после возврата по учебному перечню.",
        "Проверить комплектность оборудования до выдачи, не сверяя её с учебным перечнем.",
    ))

    result = _parse_constraint_reviews(json.dumps(_review_payload(question, second_relation="contradicted")), [question], FACTS)

    assert result[question.question_id] is True
    assert question.correct_answer == KEY


def test_explicit_source_dependency_allows_real_order_reversal_distractor():
    ordered_facts = [replace(FACTS[0], value=KEY + " Проверку выполните до записи в журнал выдачи."), *FACTS[1:]]
    question = _question((
        KEY,
        "Выдать оборудование, а комплектность проверить после возврата по учебному перечню.",
        "Проверить комплектность оборудования по учебному перечню после записи в журнал выдачи.",
    ))
    raw = _review_payload(question, second_relation="contradicted")
    raw["rules"][0]["quote"] = ordered_facts[0].value

    assert _parse_constraint_reviews(json.dumps(raw), [question], ordered_facts)[question.question_id] is True


def test_temporal_prompt_contract_requires_order_and_undetermined_review_language():
    for prompt in (AUTHOR_PROMPT, REVIEW_PROMPT, CONSTRAINT_PROMPT):
        assert "before X" in prompt
        assert "after Y" in prompt
        assert "Numbered" in prompt
        assert "undetermined" in prompt
        assert "only the constraint auditor emits relation=undetermined" in prompt
        assert "contradicted_by_source=false" in prompt
        assert "complete the check before making the journal entry" in prompt
