from __future__ import annotations

import pytest

from app.modules.scorm.cmi_policy import (
    CmiCommitPolicy,
    CmiPolicyError,
    CmiPolicyLimits,
)


def test_validate_accepts_and_normalizes_supported_scorm_12_fields() -> None:
    existing = {"cmi.core.lesson_location": "page-1"}
    raw = {
        "cmi.core.lesson_status": " Completed ",
        "cmi.core.score.raw": "100",
        "cmi.suspend_data": "resume-state",
        "cmi.objectives.0.status": "passed",
        "cmi.interactions.0.correct_responses.0.pattern": "A",
    }

    result = CmiCommitPolicy().validate(raw, existing)

    assert result.patch["cmi.core.lesson_status"] == "completed"
    assert result.merged["cmi.core.lesson_location"] == "page-1"
    assert result.merged["cmi.core.score.raw"] == "100"
    assert existing == {"cmi.core.lesson_location": "page-1"}
    assert raw["cmi.core.lesson_status"] == " Completed "


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"unknown": "value"}, "unsupported_cmi_key"),
        ({"cmi.core.lesson_status": {"nested": "value"}}, "invalid_cmi_value_type"),
        ({"cmi.core.lesson_status": ["completed"]}, "invalid_cmi_value_type"),
        ({"cmi.core.lesson_status": 1}, "invalid_cmi_value_type"),
        ({"cmi.core.lesson_status": "invented"}, "invalid_lesson_status"),
        ({"cmi.core.score.raw": "not-a-number"}, "invalid_cmi_score"),
        ({"cmi.objectives.0.score.raw": "NaN"}, "invalid_cmi_score"),
        ({"cmi.objectives.\u0661.status": "passed"}, "unsupported_cmi_key"),
        ({"cmi.objectives.0.status": "invented"}, "invalid_lesson_status"),
    ],
)
def test_validate_rejects_unsupported_or_non_scalar_input(raw: dict, code: str) -> None:
    with pytest.raises(CmiPolicyError) as caught:
        CmiCommitPolicy().validate(raw, {})

    assert caught.value.code == code
    assert caught.value.status_code == 422


def test_validate_enforces_entry_key_and_value_budgets() -> None:
    policy = CmiCommitPolicy(
        CmiPolicyLimits(
            max_entries=1,
            max_key_bytes=16,
            max_value_bytes=4,
            max_suspend_data_bytes=8,
            max_raw_bytes=1024,
            max_persisted_bytes=2048,
        )
    )

    with pytest.raises(CmiPolicyError) as caught:
        policy.validate({"cmi.core.exit": "", "cmi.core.lesson_status": "passed"}, {})
    assert caught.value.code == "too_many_cmi_entries"
    assert caught.value.status_code == 413

    with pytest.raises(CmiPolicyError) as caught:
        policy.validate({"cmi.core.lesson_status": "passed"}, {})
    assert caught.value.code == "cmi_key_too_large"

    value_policy = CmiCommitPolicy(CmiPolicyLimits(max_value_bytes=4))
    with pytest.raises(CmiPolicyError) as caught:
        value_policy.validate({"cmi.comments": "12345"}, {})
    assert caught.value.code == "cmi_value_too_large"

    suspend_policy = CmiCommitPolicy(CmiPolicyLimits(max_suspend_data_bytes=4))
    with pytest.raises(CmiPolicyError) as caught:
        suspend_policy.validate({"cmi.suspend_data": "12345"}, {})
    assert caught.value.code == "cmi_value_too_large"


def test_validate_enforces_raw_and_cumulative_budgets() -> None:
    raw_policy = CmiCommitPolicy(CmiPolicyLimits(max_raw_bytes=16))
    with pytest.raises(CmiPolicyError) as caught:
        raw_policy.validate({"cmi.comments": "value"}, {})
    assert caught.value.code == "cmi_request_too_large"
    assert caught.value.status_code == 413

    persisted_policy = CmiCommitPolicy(CmiPolicyLimits(max_persisted_bytes=48))
    with pytest.raises(CmiPolicyError) as caught:
        persisted_policy.validate(
            {"cmi.comments": "new-value"},
            {"cmi.core.lesson_location": "existing-value"},
        )
    assert caught.value.code == "cmi_state_too_large"


def test_validate_rejects_large_declared_body_before_policy_merge() -> None:
    with pytest.raises(CmiPolicyError) as caught:
        CmiCommitPolicy(CmiPolicyLimits(max_raw_bytes=128)).validate(
            {"cmi.core.lesson_status": "completed"},
            {},
            raw_content_length=129,
        )

    assert caught.value.code == "cmi_request_too_large"
    assert caught.value.status_code == 413


def test_validate_is_idempotent_for_same_patch() -> None:
    policy = CmiCommitPolicy()
    first = policy.validate({"cmi.core.lesson_location": "page-2"}, {})
    second = policy.validate(first.patch, first.merged)

    assert second.merged == first.merged


@pytest.mark.parametrize("value", ["0", "100", "-1", "+42.5", ".75", "12."])
def test_validate_accepts_finite_decimal_score_forms(value: str) -> None:
    result = CmiCommitPolicy().validate({"cmi.core.score.raw": value}, {})

    assert result.patch == {"cmi.core.score.raw": value}


def test_validate_normalizes_objective_status() -> None:
    result = CmiCommitPolicy().validate({"cmi.objectives.0.status": " Passed "}, {})

    assert result.patch == {"cmi.objectives.0.status": "passed"}
