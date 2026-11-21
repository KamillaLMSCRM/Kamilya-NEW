"""Pure snapshot handling: never reveal keys to a learner."""

import hashlib
import json
from typing import Any

from fastapi import HTTPException

from app.modules.knowledge_checks.schemas import Answer


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def normalize_answers(snapshot: dict[str, Any], answers: list[Answer], *, complete: bool = False) -> list[dict[str, Any]]:
    questions = {q["id"]: q for q in snapshot["questions"]}
    result: dict[str, list[str]] = {}
    for answer in answers:
        qid = str(answer.question_id)
        choices = [str(c) for c in answer.selected_choice_ids]
        question = questions.get(qid)
        if question is None or qid in result or len(set(choices)) != len(choices):
            raise HTTPException(422, "Invalid or duplicate answer")
        if not set(choices) <= {c["id"] for c in question["choices"]}:
            raise HTTPException(422, "Choice does not belong to question")
        question_type = question["type"]
        if question_type not in {"multiple_choice", "ordering"} and len(choices) > 1:
            raise HTTPException(422, "Only one choice is allowed")
        if complete and question_type == "ordering" and len(choices) != len(question["choices"]):
            raise HTTPException(422, "Include all steps in the submitted order")
        result[qid] = choices if question_type == "ordering" else sorted(choices)
    if complete and (set(result) != set(questions) or any(not choices for choices in result.values())):
        raise HTTPException(422, "All questions require an answer")
    return [{"question_id": qid, "selected_choice_ids": result[qid]} for qid in sorted(result)]


def grade(snapshot: dict[str, Any], answers: list[dict[str, Any]]) -> dict[str, int | bool]:
    selected = {a["question_id"]: a["selected_choice_ids"] for a in answers}
    total = sum(q["points"] for q in snapshot["questions"])
    earned = 0
    for question in snapshot["questions"]:
        choices = question["choices"]
        actual = selected.get(question["id"], [])
        if question["type"] == "ordering":
            correct = actual == [choice["id"] for choice in choices]
        else:
            correct = set(actual) == {choice["id"] for choice in choices if choice["is_correct"]}
        if correct:
            earned += question["points"]
    percent = round(earned / total * 100)
    return {"earned_points": earned, "total_points": total, "score_percent": percent,
            "passed": percent >= snapshot["pass_score"]}


def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {**{k: v for k, v in snapshot.items() if k != "questions"}, "questions": [
        {**{k: v for k, v in q.items() if k not in {"choices", "explanation"}},
         "choices": [
             {k: v for k, v in c.items() if k != "is_correct"}
             for c in (sorted(q["choices"], key=lambda choice: choice["id"]) if q["type"] == "ordering" else q["choices"])
         ]}
        for q in snapshot["questions"]]}
