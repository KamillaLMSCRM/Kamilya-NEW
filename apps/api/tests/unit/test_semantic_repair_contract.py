from __future__ import annotations

import json

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions


def test_repair_keeps_server_question_identity_without_model_repair_of_and_allows_grounded_citation_refinement():
    """A repair is correlated by the server, not by an LLM-generated identifier."""
    first_fact = SourceFact(
        "f1", "Privacy", "rule", "Use only an approved channel.", "doc_id=d1;section=privacy"
    )
    second_fact = SourceFact(
        "f2", "Privacy", "exception", "Urgency is not an exception.", "doc_id=d1;section=privacy"
    )
    lesson = LessonDraft(
        "l1", "Work", "Privacy", "Apply the approved-channel rule", first_fact.value,
        ("f1", "f2"), (), 1,
    )
    original = _parse_questions(
        json.dumps({"questions": [{
            "prompt": "How should personal data be sent urgently?",
            "options": ["Use an approved channel.", "Use any channel.", "Do not respond."],
            "correct_index": 0,
            "explanation": "Approved channels remain required.",
            "evidence": [{"fact_id": "f1", "quote": first_fact.value}],
        }]}),
        lesson_id=lesson.lesson_id, facts=[first_fact, second_fact], maximum=1, block_id="privacy",
    )[0]

    repaired = _parse_questions(
        json.dumps({"questions": [{
            "prompt": "What channel should be used to send personal data when urgent?",
            "options": ["Only an approved channel.", "Any channel because it is urgent.", "A personal messenger."],
            "correct_index": 0,
            "explanation": "Urgency is not an exception to the approved-channel rule.",
            "evidence": [
                {"fact_id": "f1", "quote": first_fact.value},
                {"fact_id": "f2", "quote": second_fact.value},
            ],
        }]}),
        lesson_id=lesson.lesson_id, facts=[first_fact, second_fact], maximum=1, block_id="privacy",
        repair_targets={original.question_id: original},
    )[0]

    assert repaired.question_id == original.question_id
    assert repaired.repaired_prompt == original.prompt
    assert repaired.fact_id == original.fact_id
    assert repaired.evidence_fact_ids == ("f1", "f2")
