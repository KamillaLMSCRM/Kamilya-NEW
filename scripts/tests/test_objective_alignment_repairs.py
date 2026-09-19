"""Generation orchestration preserves valid work when one question needs repair."""
import json

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft
from scripts.dev.objective_alignment.engine import generate
from scripts.tests.test_objective_alignment import FACTS, FakeClient, dump, plan, quiz, teaching


def audit(items):
    return dump({"plan_issues": [], "teaching_issues": [], "missing_decisions": [],
                 "items": [{"objective_id": identifier, "supported_answers": [0],
                            "remove_options": [], "duplicate_groups": [], "status": status,
                            "reason": "synthetic review"} for identifier, status in items]})


@pytest.mark.asyncio
async def test_question_only_repair_preserves_teaching_and_good_question():
    raw_plan = plan(omitted=[])
    raw_plan["objectives"].append({**raw_plan["objectives"][0], "id": "o2",
                                   "decision": "Inspect the seal before using the device",
                                   "evidence": [{"fact_id": "f2", "quote": FACTS["f2"].value}]})
    raw_teaching = teaching()
    raw_teaching["blocks"].append({**raw_teaching["blocks"][0], "objective_id": "o2",
                                    "explanation": "Inspect the seal before each use of the device."})
    raw_quiz = quiz()
    raw_quiz["items"].append({**raw_quiz["items"][0], "objective_id": "o2",
                                "prompt": "Which check is needed before using this device?",
                                "taught_quote": "Inspect the seal before each use"})
    corrected = {"items": [{**raw_quiz["items"][1],
                             "prompt": "What should you inspect before each use of the device?"}], "unassessable": []}
    client = FakeClient([dump(raw_plan), dump(raw_teaching), dump(raw_quiz),
                         audit([("o1", "usable"), ("o2", "rewrite")]),
                         dump(corrected), audit([("o1", "usable"), ("o2", "usable")])])
    lesson = LessonDraft("l1", "M", "Title", "old", "", ("f1", "f2"), (), 5)
    result = await generate([lesson], FACTS, client, contract_retries=0)
    tasks = [json.loads(call[0][-1]["content"])["task"] for call in client.calls]
    assert tasks.count("objective_teaching") == 1
    assert tasks == ["objective_plan", "objective_teaching", "objective_assessment",
                     "blind_audit", "objective_assessment_repair", "blind_audit"]
    assert result["realized_assessment"]["questions"][0]["prompt"] == raw_quiz["items"][0]["prompt"]
    assert len(result["realized_assessment"]["questions"]) == 2
    assert not any(result["packs"][0]["unresolved"].values())
