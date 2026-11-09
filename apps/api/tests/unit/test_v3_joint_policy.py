"""Fresh joint admission does not reinterpret the existing autonomous protocol."""
import pytest

from app.modules.ai.v3.revision_policy import (
    AUTONOMOUS_EDITORIAL_REVIEW_POLICY,
    COHERENT_EDITORIAL_REVIEW_POLICY,
    JOINT_EDITORIAL_REVIEW_POLICY,
    REVIEW_KEY,
    is_autonomous_editorial_policy,
    is_editorial_policy,
    is_practical_policy,
    read_review_policy,
)


@pytest.mark.parametrize('policy', [AUTONOMOUS_EDITORIAL_REVIEW_POLICY, JOINT_EDITORIAL_REVIEW_POLICY, COHERENT_EDITORIAL_REVIEW_POLICY])
def test_both_autonomous_versions_remain_explicitly_readable(policy):
    assert read_review_policy({REVIEW_KEY: policy}) == policy
    assert is_editorial_policy(policy) and is_practical_policy(policy)
    assert is_autonomous_editorial_policy(policy)
    assert AUTONOMOUS_EDITORIAL_REVIEW_POLICY != JOINT_EDITORIAL_REVIEW_POLICY


def test_unrecognized_future_joint_policy_does_not_gain_authority():
    policy = 'v3-practical-source-review-v37'
    with pytest.raises(ValueError, match='policy_invalid'):
        read_review_policy({REVIEW_KEY: policy})
    assert not is_autonomous_editorial_policy(policy)
