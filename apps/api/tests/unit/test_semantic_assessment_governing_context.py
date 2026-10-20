"""Regression contracts for complete source context in semantic review."""

from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    CONSTRAINT_PROMPT,
    REVIEW_PROMPT,
    _constraint_request,
    _review_request,
)


def _fact(fact_id: str, value: str) -> SourceFact:
    return SourceFact(
        fact_id=fact_id,
        subject="employees",
        attribute="fire safety duty",
        value=value,
        source_locator="doc_id=r18&section=6",
    )


def _question() -> QuestionDraft:
    return QuestionDraft(
        question_id="q-last-employee",
        lesson_id="lesson-fire",
        kind="single_choice",
        prompt="What must the last employee do before leaving?",
        options=("Close windows and switch off lights", "Tidy the workplace and deenergize appliances"),
        correct_answer="Close windows and switch off lights",
        explanation="The cited special-role rule requires this closing checklist.",
        fact_id="special-role",
        evidence_fact_ids=("special-role",),
        source_quote="close windows and switch off lights",
    )


def test_review_payload_keeps_full_governing_context_separate_from_citations() -> None:
    cited = _fact("special-role", "The last employee must close windows and switch off lights.")
    universal = _fact("universal", "Every employee must tidy the workplace and deenergize appliances when necessary.")

    payload = _review_request("block-1", [_question()], [cited], [cited, universal])

    assert [row["fact_id"] for row in payload["governing_facts"]] == ["special-role", "universal"]
    assert payload["questions"][0]["evidence_fact_ids"] == ("special-role",)


def test_constraint_payload_exposes_universal_duty_without_granting_key_citation() -> None:
    request = {
        "block_id": "block-1",
        "facts": [{"fact_id": "special-role", "value": "special"}],
    }
    governing = [
        {"fact_id": "special-role", "value": "special"},
        {"fact_id": "universal", "value": "universal"},
    ]

    payload = _constraint_request(request, [_question()], governing_facts=governing)

    assert payload["facts"] == request["facts"]
    assert payload["governing_facts"] == governing


def test_prompts_do_not_treat_universal_special_role_overlap_as_false_distractor() -> None:
    assert "universal obligation" in REVIEW_PROMPT
    assert "special role" in REVIEW_PROMPT
    assert "partial compound duty" in REVIEW_PROMPT
    assert "universal duty" in CONSTRAINT_PROMPT
    assert "ambiguous/undetermined" in CONSTRAINT_PROMPT
