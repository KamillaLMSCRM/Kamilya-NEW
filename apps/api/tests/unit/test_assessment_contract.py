from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact


def _lesson(*facts: SourceFact) -> LessonDraft:
    return LessonDraft(
        lesson_id="collection-comparison",
        module_title="Collections",
        title="Collection characteristics",
        objective="Identify a collection's stated attribute",
        content="",
        fact_ids=tuple(fact.fact_id for fact in facts),
        supporting_fact_ids=(),
        duration_minutes=2,
    )


def _axis_for(fact_id: str, *facts: SourceFact):
    return next(
        axis
        for axis in derive_assessment_axes(_lesson(*facts), list(facts), block_id="collections")
        if axis.primary_fact_id == fact_id
    )


def test_contract_rejects_true_source_value_from_another_function() -> None:
    bed = SourceFact(
        "chicago-bed",
        "Chicago Street",
        "Bed availability",
        "The collection has no beds.",
        "sheet=Collections;row=13;column=D",
    )
    dresser = SourceFact(
        "chicago-dresser",
        "Chicago Street",
        "Chest characteristics",
        "The collection includes a four-drawer chest.",
        "sheet=Collections;row=13;column=D",
    )
    axis = _axis_for(bed.fact_id, bed, dresser)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="Are beds available in Chicago Street?",
            distractors=(
                "The collection includes a four-drawer chest.",
                "Beds are available only on request.",
            ),
        ),
    )

    assert candidate is None


def test_contract_rejects_paraphrased_source_value_from_another_function() -> None:
    bed = SourceFact(
        "chicago-bed",
        "Chicago Street",
        "Bed availability",
        "The collection has no beds.",
        "sheet=Collections;row=13;column=D",
    )
    dresser = SourceFact(
        "chicago-dresser",
        "Chicago Street",
        "Chest characteristics",
        "The collection includes a four-drawer chest.",
        "sheet=Collections;row=13;column=D",
    )
    axis = _axis_for(bed.fact_id, bed, dresser)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="Are beds available in Chicago Street?",
            distractors=(
                "The collection has a chest with four drawers.",
                "Beds are available only on request.",
            ),
        ),
    )

    assert candidate is None


def test_contract_keeps_free_form_counterfactuals_on_the_target_axis() -> None:
    bed = SourceFact(
        "chicago-bed",
        "Chicago Street",
        "Bed availability",
        "The collection has no beds.",
        "sheet=Collections;row=13;column=D",
    )
    dresser = SourceFact(
        "chicago-dresser",
        "Chicago Street",
        "Chest characteristics",
        "The collection includes a four-drawer chest.",
        "sheet=Collections;row=13;column=D",
    )
    axis = _axis_for(bed.fact_id, bed, dresser)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="Are beds available in Chicago Street?",
            distractors=(
                "Beds are available only on request.",
                "Beds are available only in custom sizes.",
            ),
        ),
    )

    assert candidate is not None
    assert candidate.options[1:] == (
        "Beds are available only on request.",
        "Beds are available only in custom sizes.",
    )


def test_contract_rejects_the_exact_key_used_as_a_distractor() -> None:
    bed = SourceFact(
        "chicago-bed",
        "Chicago Street",
        "Bed availability",
        "The collection has no beds.",
        "sheet=Collections;row=13;column=D",
    )
    dresser = SourceFact(
        "chicago-dresser",
        "Chicago Street",
        "Chest characteristics",
        "The collection includes a four-drawer chest.",
        "sheet=Collections;row=13;column=D",
    )
    axis = _axis_for(bed.fact_id, bed, dresser)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="Are beds available in Chicago Street?",
            distractors=(
                "The collection has no beds.",
                "Beds are available only on request.",
            ),
        ),
    )

    assert candidate is None


def test_contract_keeps_same_axis_counterfactual_that_changes_one_value() -> None:
    collateral = SourceFact(
        "collateral",
        "Loan rules",
        "Collateral",
        "Loans are provided against movable property intended for personal use.",
        "doc_id=rules;section=general;part=1",
    )
    axis = _axis_for(collateral.fact_id, collateral)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="What property may secure a loan under the rules?",
            distractors=(
                "Immovable property intended for personal use.",
                "Movable property intended for business use.",
            ),
        ),
    )

    assert candidate is not None


def test_contract_rejects_prompt_bound_to_a_different_axis() -> None:
    facade = SourceFact(
        "chicago-facade",
        "Chicago Street",
        "Facade material",
        "MDF facade.",
        "sheet=Collections;row=8;column=D",
    )
    axis = _axis_for(facade.fact_id, facade)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="What is the opening mechanism?",
            distractors=(
                "Laminated chipboard facade.",
                "Solid oak facade.",
            ),
        ),
    )

    assert candidate is not None
    assert candidate.prompt != "What is the opening mechanism?"
    assert "Facade material" in candidate.prompt


def test_contract_rejects_a_different_clause_of_the_same_compound_fact() -> None:
    rooms = SourceFact(
        "chicago-rooms",
        "Chicago Street",
        "Covered rooms",
        "Bedroom, hallway, and living room. Beds are not included in the line.",
        "sheet=Collections;row=13;column=D",
    )
    axis = _axis_for(rooms.fact_id, rooms)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="Which rooms are covered by Chicago Street?",
            distractors=(
                "Beds are not included in the line.",
                "The line covers only the kitchen.",
            ),
        ),
    )

    assert candidate is None


def test_contract_does_not_equate_partial_overlap_with_a_long_other_rule() -> None:
    refusal = SourceFact(
        "refusal",
        "Application",
        "Applicant right",
        "The applicant may refuse to conclude the loan agreement.",
        "doc_id=rules;section=application;part=1",
    )
    spouse = SourceFact(
        "spouse",
        "Application",
        "Refusal grounds",
        "The lender may refuse an application when the information is incomplete, "
        "documents are missing, collateral is insufficient, or spousal consent is "
        "absent for a loan above the statutory threshold.",
        "doc_id=rules;section=application;part=2",
    )
    axis = _axis_for(refusal.fact_id, refusal, spouse)

    candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="What may the applicant do before concluding the agreement?",
            distractors=(
                "The applicant may refuse only with spousal consent.",
                "The applicant must always conclude the agreement after approval.",
            ),
        ),
    )

    assert candidate is not None


def test_same_attribute_source_value_requires_an_explicit_target_collection() -> None:
    chicago = SourceFact(
        "chicago-facade",
        "Chicago Street",
        "Facade material",
        "MDF facade.",
        "sheet=Collections;row=8;column=D",
    )
    phoenix = SourceFact(
        "phoenix-facade",
        "Phoenix",
        "Facade material",
        "Laminated chipboard facade.",
        "sheet=Collections;row=8;column=B",
    )
    axis = _axis_for(chicago.fact_id, chicago, phoenix)
    authored = AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="What is the facade material?",
        distractors=(
            "Laminated chipboard facade.",
            "Solid oak facade.",
        ),
    )

    assert materialize_assessment(axis, authored) is None

    explicit_candidate = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="What is the facade material of Chicago Street?",
            distractors=authored.distractors,
        ),
    )

    assert explicit_candidate is not None
    assert explicit_candidate.correct_answer == "MDF facade."
    assert explicit_candidate.evidence_fact_ids == (chicago.fact_id,)


def test_axis_source_owned_identity_and_target_fields_are_immutable() -> None:
    fact = SourceFact(
        "phoenix-facade",
        "Phoenix",
        "Facade material",
        "Laminated chipboard facade.",
        "sheet=Collections;row=8;column=B",
    )
    axis = _axis_for(fact.fact_id, fact)

    with pytest.raises(FrozenInstanceError):
        axis.subject = "Chicago Street"  # type: ignore[misc]
