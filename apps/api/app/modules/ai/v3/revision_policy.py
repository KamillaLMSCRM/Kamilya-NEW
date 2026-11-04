"""Server-owned fresh revision protocol marker."""
from typing import Any

KEY = "v3_revision_policy"
LEGACY_POLICY = "v3-scoped-revision-v1"
POLICY = "v3-scoped-revision-v2"
REVIEW_KEY = "v3_review_policy"
LEGACY_REVIEW_POLICY = "v3-batched-decision-review-v1"
PREVIOUS_REVIEW_POLICY = "v3-batched-decision-review-v2"
BUCKET_REVIEW_POLICY = "v3-batched-decision-review-v3"
AUXILIARY_REVIEW_POLICY = "v3-batched-decision-review-v4"
REVIEW_POLICY = "v3-batched-decision-review-v5"
PREVIOUS_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v11"
SCOPED_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v12"
CONCISE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v13"
PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v14"
ARBITRATED_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v15"
STANDALONE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v16"
TYPED_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v17"
COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v18"
EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v19"
QUESTION_BANK_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v20"
OWNED_AUDIT_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v21"
EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v22"
CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v23"
ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v24"
MATERIALITY_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v25"
PRACTICAL_MAX_OUTPUT_TOKENS = 16384


def is_scoped_policy(value: object) -> bool:
    return type(value) is str and value in {LEGACY_POLICY, POLICY}


def is_practical_policy(value: object) -> bool:
    return type(value) is str and value in {PREVIOUS_PRACTICAL_REVIEW_POLICY, SCOPED_PRACTICAL_REVIEW_POLICY, CONCISE_PRACTICAL_REVIEW_POLICY, PRACTICAL_REVIEW_POLICY, ARBITRATED_PRACTICAL_REVIEW_POLICY, STANDALONE_PRACTICAL_REVIEW_POLICY, TYPED_PRACTICAL_REVIEW_POLICY, COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY, EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY, QUESTION_BANK_PRACTICAL_REVIEW_POLICY, OWNED_AUDIT_PRACTICAL_REVIEW_POLICY, EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY, CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY, ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY, MATERIALITY_PRACTICAL_REVIEW_POLICY}


def stamp_policy(analysis: dict[str, Any], *, practical: bool = False) -> dict[str, Any]:
    return {**analysis, KEY: POLICY, REVIEW_KEY: MATERIALITY_PRACTICAL_REVIEW_POLICY if practical else REVIEW_POLICY}


def practical_qa_admission(*, settings: Any, marker: str | None, tenant_id: Any, course_id: Any) -> bool:
    """Select practical only from the server-authenticated managed or strict native DEV QA route."""
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY

    if marker == MANAGED_POLICY:
        return True
    return (marker is None and tenant_id == QA_TENANT and course_id is None
            and getattr(settings, 'DEPLOYMENT_ENVIRONMENT', None) == 'render-development'
            and all(getattr(settings, name, None) is False for name in (
                'AI_QA_LUNA_DEV_ENABLED', 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED',
                'AI_DIRECT_LUNA_QA_DEV_ENABLED', 'AI_MANAGED_LUNA_QA_DEV_ENABLED')))


def read_review_policy(analysis: Any) -> str | None:
    if not isinstance(analysis, dict):
        raise ValueError("v3_review_analysis_invalid")
    if REVIEW_KEY not in analysis:
        return None
    if type(analysis[REVIEW_KEY]) is not str or analysis[REVIEW_KEY] not in {
        LEGACY_REVIEW_POLICY, PREVIOUS_REVIEW_POLICY, BUCKET_REVIEW_POLICY, AUXILIARY_REVIEW_POLICY, REVIEW_POLICY,
        PREVIOUS_PRACTICAL_REVIEW_POLICY, SCOPED_PRACTICAL_REVIEW_POLICY, CONCISE_PRACTICAL_REVIEW_POLICY, PRACTICAL_REVIEW_POLICY,
        ARBITRATED_PRACTICAL_REVIEW_POLICY,
        STANDALONE_PRACTICAL_REVIEW_POLICY,
        TYPED_PRACTICAL_REVIEW_POLICY,
        COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY,
        EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY,
        QUESTION_BANK_PRACTICAL_REVIEW_POLICY,
        OWNED_AUDIT_PRACTICAL_REVIEW_POLICY,
        EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY,
        CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY,
        ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY,
        MATERIALITY_PRACTICAL_REVIEW_POLICY,
    }:
        raise ValueError("v3_review_policy_invalid")
    return str(analysis[REVIEW_KEY])


def read_policy(analysis: Any) -> str | None:
    if not isinstance(analysis, dict):
        raise ValueError("v3_revision_analysis_invalid")
    if KEY not in analysis:
        return None
    if not is_scoped_policy(analysis[KEY]):
        raise ValueError("v3_revision_policy_invalid")
    return str(analysis[KEY])


def policy_matches(analysis: Any, expected: str | None) -> bool:
    try:
        return read_policy(analysis) == expected
    except ValueError:
        return False
