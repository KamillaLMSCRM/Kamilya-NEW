from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _has_position_dependent_explanation,
    generate_block_assessment,
)


@pytest.mark.parametrize("explanation", [
    "Вариант 1 меняет механизм, а вариант 2 добавляет ручки.",
    "Первый вариант меняет механизм, второй вариант добавляет ручки.",
    "Option 1 changes the mechanism; option 2 adds handles.",
    "The first option changes the mechanism; the second option adds handles.",
])
def test_position_dependent_explanation_pattern(explanation):
    assert _has_position_dependent_explanation(explanation)


def test_numeric_domain_quantity_is_not_treated_as_option_reference():
    assert not _has_position_dependent_explanation(
        "The source requires a 2-second hold before the Push-to-open action."
    )


def _candidate(prompt: str, explanation: str) -> dict[str, object]:
    return {
        "prompt": prompt,
        "options": ["Use Push-to-open.", "Use handles.", "Use a key."],
        "correct_index": 0,
        "explanation": explanation,
        "evidence": [{"fact_id": "f1", "quote": "Doors use Push-to-open."}],
    }


def _axis_candidate(request, prompt: str) -> dict[str, object]:
    return {
        "axis_id": request["axes"][0]["axis_id"],
        "prompt": prompt,
        "distractors": ["Use handles.", "Use a key."],
    }


class _OrdinalRepairClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        task = request["task"]
        if task == "assessment_generate":
            payload = {"questions": [
                _axis_candidate(request, "How do the doors open?"),
            ]}
        elif task == "assessment_repair":
            payload = {"questions": [
                _axis_candidate(request, "Which opening mechanism is used?"),
            ]}
        elif task == "assessment_review":
            payload = {"reviews": [{
                "question_id": question["question_id"],
                "question_supported": True,
                "educational": True,
                "explanation_supported": True,
                "options_distinct": True,
                "options": [{
                    "index": index,
                    "answers_question": True,
                    "correct": index == 0,
                    "plausible_error": index > 0,
                    "contradicted_by_source": index > 0,
                    "same_practical_task": True,
                } for index in range(len(question["options"]))],
            } for question in request["questions"]]}
        else:
            payload = {
                "rules": [
                    {
                        "fact_id": "f1",
                        "quote": "Doors use Push-to-open.",
                        "kind": "attribute",
                    },
                    {
                        "fact_id": "f2",
                        "quote": "Handles are not used.",
                        "kind": "attribute",
                    },
                ],
                "reviews": [{
                    "question_id": question["question_id"],
                    "reason": "Fixture schema text is not forwarded.",
                    "distinct_errors": True,
                    "options": [{
                        "index": index,
                        "relation": "entailed" if index == 0 else "contradicted",
                        "invented_constraint": False,
                        "realistic_error": True,
                    } for index in range(len(question["options"]))],
                } for question in request["questions"]],
            }
        return SimpleNamespace(value=parser(json.dumps(payload)), attempt_count=1)


@pytest.mark.asyncio
async def test_author_ordinal_explanations_are_replaced_by_verified_quotes_without_retry():
    first = SourceFact("f1", "Doors", "operation", "Doors use Push-to-open.", "doc_id=d1;section=doors")
    second = SourceFact("f2", "Doors", "note", "Handles are not used.", "doc_id=d1;section=doors")
    lesson = LessonDraft(
        "l1", "Module", "Doors", "Know the opening mechanism", first.value, ("f1", "f2"), (), 1,
    )
    client = _OrdinalRepairClient()

    result = await generate_block_assessment([lesson], {"f1": first, "f2": second}, client)

    # Both author explanations normalize without repair; duplicate facts still
    # collapse to one question under the existing coverage policy.
    assert len(result.questions) == 1
    assert all(question.explanation == first.value for question in result.questions)
    repairs = [request for request in client.requests if request["task"] == "assessment_repair"]
    assert not repairs
    assert result.audit["repaired"] == 0
