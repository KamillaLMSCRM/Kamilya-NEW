"""A distractor must contradict permission scope, not merely omit its adjective."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _has_ambiguous_authorization_omission,
    generate_block_assessment,
)

KEY = (
    "отключить все приборы за исключением разрешенных устройств непрерывного действия, "
    "а также дежурного и аварийного освещения"
)


class _AuthorizationScopeClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        task = request["task"]
        if task in {"assessment_generate", "assessment_repair"}:
            if task == "assessment_repair":
                payload = {"questions": []}
            else:
                axis = request["axes"][0]
                payload = {"questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": "Какое действие требуется выполнить с приборами?",
                    "distractors": [
                        (
                            "Отключить все приборы, кроме дежурного и аварийного освещения, "
                            "оставив устройства непрерывного действия подключенными"
                        ),
                        "Оставить все приборы включенными без проверки.",
                    ],
                }]}
        elif task == "assessment_review":
            payload = {"reviews": [{
                "question_id": question["question_id"],
                "reason": "Synthetic review accepted the candidate.",
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
        elif task == "assessment_constraints":
            facts_by_id = {fact["fact_id"]: fact for fact in request["facts"]}
            payload = {
                "rules": [{
                    "fact_id": fact_id,
                    "quote": facts_by_id[fact_id]["value"],
                    "kind": "forbidden",
                } for fact_id in facts_by_id],
                "reviews": [{
                    "question_id": question["question_id"],
                    "reason": "Synthetic constraint review accepted the options.",
                    "distinct_errors": True,
                    "options": [{
                        "index": index,
                        "relation": "entailed" if index == 0 else "contradicted",
                        "invented_constraint": False,
                        "realistic_error": True,
                    } for index in range(len(question["options"]))],
                } for question in request["questions"]],
            }
        else:
            raise AssertionError(f"unexpected assessment task: {task}")
        return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1)


def test_reordered_exception_does_not_make_an_omitted_permission_clearly_wrong() -> None:
    option = (
        "Отключить все приборы, кроме дежурного и аварийного освещения, "
        "оставив устройства непрерывного действия подключенными"
    )
    assert _has_ambiguous_authorization_omission(KEY, option)


@pytest.mark.parametrize("option", [
    "Отключить все приборы, включая устройства непрерывного действия и аварийное освещение",
    "Отключить все приборы, кроме дежурного освещения",
    "Отключить все приборы, кроме дежурного и аварийного освещения, оставив любые устройства непрерывного действия подключенными",
    "Отключить все приборы, кроме дежурного и аварийного освещения, оставив устройства непрерывного действия подключенными без разрешения",
])
def test_explicitly_changed_or_denied_exception_still_goes_to_semantic_review(option: str) -> None:
    assert not _has_ambiguous_authorization_omission(KEY, option)


@pytest.mark.asyncio
async def test_ambiguous_authorization_distractor_is_repaired_then_omitted() -> None:
    fact = SourceFact(
        "authorization-rule",
        "Приборы",
        "Порядок отключения",
        KEY,
        "doc_id=synthetic;section=authorization",
    )
    lesson = LessonDraft(
        "authorization-lesson",
        "Безопасность",
        "Отключение приборов",
        "Применять правило отключения",
        "",
        (fact.fact_id,),
        (),
        2,
    )
    client = _AuthorizationScopeClient()

    result = await generate_block_assessment([lesson], {fact.fact_id: fact}, client)

    assert result.questions == ()
    assert [request["task"] for request in client.requests] == [
        "assessment_generate",
        "assessment_review",
        "assessment_constraints",
        "assessment_repair",
    ]
    repair = client.requests[-1]
    assert repair["rejected"][0]["rejection_reasons"] == [
        "option_1:authorization_scope_ambiguous",
    ]
    assert repair["rejected"][0]["rejected_options"] == [{
        "index": 1,
        "text": repair["rejected"][0]["options"][1],
        "reasons": ["option_1:authorization_scope_ambiguous"],
    }]
    axis_outcome = result.audit["axis_outcomes"][0]
    assert axis_outcome["primary_fact_id"] == fact.fact_id
    assert axis_outcome["state"] == "omitted"
    assert axis_outcome["reason"] == "option_1:authorization_scope_ambiguous"
    assert result.audit["block_outcomes"][0]["outcome"] == "quality_omitted"
