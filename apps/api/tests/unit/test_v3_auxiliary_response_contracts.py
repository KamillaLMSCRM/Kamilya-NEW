from __future__ import annotations

import pytest

from app.modules.ai.v3.auxiliary_response_contracts import (
    citation_review_format,
    explanation_repair_format,
    length_repair_format,
    matches_auxiliary_response,
    option_repair_format,
    prose_repair_format,
)
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract


def test_auxiliary_formats_are_registered_and_request_bound() -> None:
    fmt = explanation_repair_format(["v1", "v2"])
    assert response_contract(fmt) == "aux:explanation_repair"
    assert matches_response_contract(
        {
            "repairs": [
                {"variant_id": "v1", "explanation": "one"},
                {"variant_id": "v2", "explanation": "two"},
            ]
        },
        fmt,
    )
    assert not matches_auxiliary_response({"repairs": [{"variant_id": "foreign", "explanation": "two"}]}, fmt)


@pytest.mark.parametrize(
    "value",
    [
        {"repairs": [{"variant_id": "v1", "explanation": "one"}, {"variant_id": "v1", "explanation": "two"}]},
        {"repairs": [{"variant_id": "v1", "explanation": ""}, {"variant_id": "v2", "explanation": "two"}]},
        {"repairs": [{"variant_id": "v1", "explanation": "one"}]},
    ],
)
def test_auxiliary_repair_rejects_duplicate_missing_or_blank(value: dict) -> None:
    assert not matches_response_contract(value, explanation_repair_format(["v1", "v2"]))


def test_option_and_citation_contracts_reject_wrong_method_shape() -> None:
    option_fmt = option_repair_format(["v1"])
    assert not matches_response_contract(
        {
            "repairs": [
                {
                    "variant_id": "v1",
                    "correct": "ok",
                    "distractors": [{"text": "a", "category": "role_confusion"}],
                    "explanation": "why",
                }
            ]
        },
        option_fmt,
    )
    citation_fmt = citation_review_format(["q1"])
    assert not matches_response_contract(
        {"items": [{"id": "q1", "verdict": "COMPLETE", "unsupported": [], "summary": "ok", "extra": "reject"}]},
        citation_fmt,
    )


def test_real_prose_and_length_consumer_shapes_are_closed() -> None:
    prose = prose_repair_format(["v1"])
    assert matches_response_contract({"repairs": [{"id": "v1", "old": "old", "new": "new"}]}, prose)
    assert not matches_response_contract({"repairs": [{"id": "v1", "old": "old"}]}, prose)
    length = length_repair_format(["v1"])
    distractors = [
        {"text": text, "category": category}
        for text, category in (("a", "role_confusion"), ("b", "timing_violation"), ("c", "threshold_error"))
    ]
    assert matches_response_contract({"repairs": [{"variant_id": "v1", "distractors": distractors}]}, length)
    assert not matches_response_contract(
        {"repairs": [{"variant_id": "v1", "distractors": distractors, "correct": "wrong"}]}, length
    )
