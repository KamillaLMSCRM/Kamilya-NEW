from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


class OrderIndependentClient:
    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        task = request["task"]
        facts = request.get("facts", [])

        if task in {"assessment_generate", "assessment_repair"}:
            questions = []
            for axis in request["axes"]:
                claim = axis["source_claim"]
                number = next(
                    (int(token) for token in claim.replace(".", " ").split() if token.isdigit()),
                    10,
                )
                questions.append(
                    {
                        "axis_id": axis["axis_id"],
                        "prompt": axis["required_prompt"]
                        or f"Какое значение установлено для {axis['subject']}?",
                        "distractors": [f"{number + 5} дней", f"{number + 10} дней"],
                    }
                )
            payload = {"questions": questions}
        elif task == "assessment_review":
            fact_values = [_normalized(str(fact["value"])) for fact in facts]
            payload = {
                "reviews": [
                    {
                        "question_id": question["question_id"],
                        "question_supported": True,
                        "educational": True,
                        "explanation_supported": True,
                        "options_distinct": True,
                        "options": [
                            {
                                "index": index,
                                "answers_question": True,
                                "correct": any(_normalized(option) in value for value in fact_values),
                                "plausible_error": not any(
                                    _normalized(option) in value for value in fact_values
                                ),
                                "contradicted_by_source": not any(
                                    _normalized(option) in value for value in fact_values
                                ),
                                "same_practical_task": True,
                            }
                            for index, option in enumerate(question["options"])
                        ],
                    }
                    for question in request["questions"]
                ]
            }
        elif task == "assessment_constraints":
            fact_values = {
                str(fact["fact_id"]): _normalized(str(fact["value"])) for fact in facts
            }
            payload = {
                "rules": [
                    {"fact_id": fact["fact_id"], "quote": fact["value"], "kind": "attribute"}
                    for fact in facts
                ],
                "reviews": [
                    {
                        "question_id": question["question_id"],
                        "reason": "Exact source-backed duration.",
                        "distinct_errors": True,
                        "options": [
                            {
                                "index": index,
                                "relation": (
                                    "entailed"
                                    if any(
                                        _normalized(option) in fact_values[fact_id]
                                        for fact_id in question["evidence_fact_ids"]
                                    )
                                    else "contradicted"
                                ),
                                "invented_constraint": False,
                                "realistic_error": True,
                            }
                            for index, option in enumerate(question["options"])
                        ],
                    }
                    for question in request["questions"]
                ],
            }
        else:
            raise AssertionError(f"Unexpected task: {task}")

        return SimpleNamespace(
            value=parser(json.dumps(payload, ensure_ascii=False)),
            attempt_count=1,
            failure_reasons=(),
            model_id="order-independent-fixture",
        )


def _fixture() -> tuple[list[LessonDraft], dict[str, SourceFact]]:
    facts = {
        "appeal": SourceFact(
            "appeal",
            "Ответ на обращение",
            "срок",
            "Срок ответа на обращение составляет 15 дней.",
            "doc_id=d1;section=appeals",
        ),
        "storage": SourceFact(
            "storage",
            "Хранение документов",
            "срок",
            "Срок хранения документов составляет 30 дней.",
            "doc_id=d1;section=storage",
        ),
    }
    lessons = [
        LessonDraft(
            "lesson-appeal",
            "Правила",
            "Ответы на обращения",
            "Применять срок ответа",
            facts["appeal"].value,
            ("appeal",),
            (),
            1,
        ),
        LessonDraft(
            "lesson-storage",
            "Правила",
            "Хранение документов",
            "Применять срок хранения",
            facts["storage"].value,
            ("storage",),
            (),
            1,
        ),
    ]
    return lessons, facts


@pytest.mark.asyncio
async def test_assessment_result_is_independent_of_lesson_traversal_order() -> None:
    lessons, facts = _fixture()

    forward = await generate_block_assessment(lessons, facts, OrderIndependentClient())
    reverse = await generate_block_assessment(
        list(reversed(lessons)),
        dict(reversed(list(facts.items()))),
        OrderIndependentClient(),
    )

    def questions(result):
        return sorted(
            (
                question.lesson_id,
                question.prompt,
                question.correct_answer,
                tuple(sorted(question.options)),
                tuple(sorted(question.evidence_fact_ids)),
            )
            for question in result.questions
        )

    def outcomes(result):
        return sorted(
            (row["axis_id"], row["state"], row["reason"])
            for row in result.audit["axis_outcomes"]
        )

    assert questions(forward) == questions(reverse)
    assert outcomes(forward) == outcomes(reverse)
    assert forward.audit["contract_coverage"] == reverse.audit["contract_coverage"]
