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
CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v26"
DOMAIN_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v27"
SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v28"
SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v29"
SOURCE_CORE_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v30"
EDITORIAL_PRACTICAL_REVIEW_POLICY = "v3-practical-source-review-v31"
CANONICAL_EDITORIAL_REVIEW_POLICY = "v3-practical-source-review-v32"
AUTONOMOUS_EDITORIAL_REVIEW_POLICY = "v3-practical-source-review-v33"
JOINT_EDITORIAL_REVIEW_POLICY = "v3-practical-source-review-v34"
COHERENT_EDITORIAL_REVIEW_POLICY = "v3-practical-source-review-v35"
FOCUSED_EDITORIAL_REVIEW_POLICY = "v3-practical-source-review-v36"
SIMPLE_COURSE_REVIEW_POLICY = "v3-simple-course-editor-v1"
SIMPLE_COURSE_REVIEW_V2_POLICY = "v3-simple-course-editor-v2"
SIMPLE_COURSE_REVIEW_V3_POLICY = "v3-simple-source-units-editor-v3"
SIMPLE_COURSE_REVIEW_V4_POLICY = "v3-simple-source-units-delta-editor-v4"
SIMPLE_COURSE_REVIEW_V5_POLICY = "v3-simple-source-units-addressed-editors-v5"
SIMPLE_COURSE_REVIEW_V6_POLICY = "v3-simple-semantic-units-addressed-editors-v6"
SIMPLE_COURSE_REVIEW_V7_POLICY = "v3-simple-source-reading-addressed-editors-v7"
SIMPLE_COURSE_REVIEW_V8_POLICY = "v3-simple-unit-reading-addressed-editors-v8"
SIMPLE_COURSE_REVIEW_V9_POLICY = "v3-simple-unit-review-joint-block-editor-v9"
SIMPLE_COURSE_REVIEW_V10_POLICY = "v3-simple-unit-review-joint-post-card-editor-v10"
PRACTICAL_MAX_OUTPUT_TOKENS = 16384


def is_editorial_policy(value: object) -> bool:
    return type(value) is str and value in (EDITORIAL_PRACTICAL_REVIEW_POLICY, CANONICAL_EDITORIAL_REVIEW_POLICY,
                                          AUTONOMOUS_EDITORIAL_REVIEW_POLICY, JOINT_EDITORIAL_REVIEW_POLICY,
                                          COHERENT_EDITORIAL_REVIEW_POLICY, FOCUSED_EDITORIAL_REVIEW_POLICY,
                                          SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY,
                                          SIMPLE_COURSE_REVIEW_V3_POLICY, SIMPLE_COURSE_REVIEW_V4_POLICY, SIMPLE_COURSE_REVIEW_V5_POLICY, SIMPLE_COURSE_REVIEW_V6_POLICY, SIMPLE_COURSE_REVIEW_V7_POLICY, SIMPLE_COURSE_REVIEW_V8_POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY, SIMPLE_COURSE_REVIEW_V10_POLICY)


def is_autonomous_editorial_policy(value: object) -> bool:
    return type(value) is str and value in (AUTONOMOUS_EDITORIAL_REVIEW_POLICY, JOINT_EDITORIAL_REVIEW_POLICY,
                                          COHERENT_EDITORIAL_REVIEW_POLICY, FOCUSED_EDITORIAL_REVIEW_POLICY,
                                          SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY,
                                          SIMPLE_COURSE_REVIEW_V3_POLICY, SIMPLE_COURSE_REVIEW_V4_POLICY, SIMPLE_COURSE_REVIEW_V5_POLICY, SIMPLE_COURSE_REVIEW_V6_POLICY, SIMPLE_COURSE_REVIEW_V7_POLICY, SIMPLE_COURSE_REVIEW_V8_POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY, SIMPLE_COURSE_REVIEW_V10_POLICY)


def is_scoped_policy(value: object) -> bool:
    return type(value) is str and value in {LEGACY_POLICY, POLICY}


def is_practical_policy(value: object) -> bool:
    return type(value) is str and (is_editorial_policy(value) or value in {PREVIOUS_PRACTICAL_REVIEW_POLICY, SCOPED_PRACTICAL_REVIEW_POLICY, CONCISE_PRACTICAL_REVIEW_POLICY, PRACTICAL_REVIEW_POLICY, ARBITRATED_PRACTICAL_REVIEW_POLICY, STANDALONE_PRACTICAL_REVIEW_POLICY, TYPED_PRACTICAL_REVIEW_POLICY, COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY, EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY, QUESTION_BANK_PRACTICAL_REVIEW_POLICY, OWNED_AUDIT_PRACTICAL_REVIEW_POLICY, EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY, CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY, ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY, MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY, SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY, SOURCE_CORE_PRACTICAL_REVIEW_POLICY})


def stamp_policy(analysis: dict[str, Any], *, practical: bool = False) -> dict[str, Any]:
    return {**analysis, KEY: POLICY, REVIEW_KEY: SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY if practical else REVIEW_POLICY}


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


SOURCE_CORE_QA_MARKER = 'native-source-core-qa-v1'
SOURCE_CORE_QA_KEY = 'v3_source_core_qa_marker'
EDITORIAL_QA_MARKER = 'native-editorial-qa-v1'
EDITORIAL_MANAGED_QA_MARKER = 'managed-editorial-qa-v1'
EDITORIAL_QA_KEY = 'v3_editorial_qa_marker'


def source_core_qa_admission(*, settings: Any, marker: str | None, tenant_id: Any,
                             user_id: Any, course_id: Any) -> bool:
    from uuid import UUID

    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    return (marker is None and isinstance(user_id, UUID) and tenant_id == QA_TENANT
            and practical_qa_admission(settings=settings, marker=marker, tenant_id=tenant_id, course_id=course_id))


def editorial_qa_admission_marker(*, settings: Any, marker: str | None, tenant_id: Any,
                                  user_id: Any, course_id: Any) -> str | None:
    from uuid import UUID

    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY

    if source_core_qa_admission(settings=settings, marker=marker, tenant_id=tenant_id,
                                user_id=user_id, course_id=course_id):
        return EDITORIAL_QA_MARKER
    if (tenant_id == QA_TENANT and isinstance(user_id, UUID) and course_id is None and marker == MANAGED_POLICY
            and getattr(settings, 'DEPLOYMENT_ENVIRONMENT', None) == 'render-development'
            and getattr(settings, 'AI_QA_LUNA_DEV_ENABLED', None) is True
            and getattr(settings, 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED', None) is True
            and getattr(settings, 'AI_MANAGED_LUNA_QA_DEV_ENABLED', None) is True
            and getattr(settings, 'AI_DIRECT_LUNA_QA_DEV_ENABLED', None) is False):
        return EDITORIAL_MANAGED_QA_MARKER
    return None


def editorial_qa_worker_valid(*, settings: Any, tenant_id: Any, user_id: Any, course_id: Any,
                              stored: Any, dispatched: Any, qa_stored: Any = None, qa_dispatched: Any = None) -> bool:
    from uuid import UUID

    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY, check_worker_marker

    if stored == dispatched == EDITORIAL_MANAGED_QA_MARKER and qa_stored == qa_dispatched == MANAGED_POLICY:
        try:
            return check_worker_marker(settings=settings, tenant_id=tenant_id, user_id=user_id,
                                       stored=qa_stored, dispatched=qa_dispatched, course_id=course_id)
        except ValueError:
            return False

    return (tenant_id == QA_TENANT and isinstance(user_id, UUID) and course_id is None
            and stored == dispatched == EDITORIAL_QA_MARKER and qa_stored is None and qa_dispatched is None
            and getattr(settings, 'DEPLOYMENT_ENVIRONMENT', None) in {'render-development-worker', 'vm-development-worker'}
            and all(getattr(settings, name, None) is False for name in (
                'AI_QA_LUNA_DEV_ENABLED', 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED',
                'AI_DIRECT_LUNA_QA_DEV_ENABLED', 'AI_MANAGED_LUNA_QA_DEV_ENABLED')))



EDITORIAL_ORDINARY_KEY = 'v3_editorial_ordinary_marker'
EDITORIAL_ORDINARY_MARKER = 'native-editorial-ordinary-v1'
EDITORIAL_ORDINARY_EXTENDED_MARKER = 'native-editorial-ordinary-v2'


def editorial_route_worker_valid(*, settings: Any, tenant_id: Any, user_id: Any, course_id: Any,
                                 stored: Any, dispatched: Any, qa_stored: Any = None,
                                 qa_dispatched: Any = None, ordinary_stored: Any = None,
                                 ordinary_dispatched: Any = None) -> bool:
    """Validate an existing QA pair or the separately stamped ordinary native route."""
    from uuid import UUID

    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    if ordinary_stored is None and ordinary_dispatched is None:
        return editorial_qa_worker_valid(settings=settings, tenant_id=tenant_id, user_id=user_id,
                                         course_id=course_id, stored=stored, dispatched=dispatched,
                                         qa_stored=qa_stored, qa_dispatched=qa_dispatched)
    return (isinstance(tenant_id, UUID) and tenant_id != QA_TENANT and isinstance(user_id, UUID)
            and course_id is None and stored is None and dispatched is None
            and qa_stored is None and qa_dispatched is None
            and ordinary_stored == ordinary_dispatched
            and ordinary_stored in (EDITORIAL_ORDINARY_MARKER, EDITORIAL_ORDINARY_EXTENDED_MARKER))

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
        CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY,
        DOMAIN_PRACTICAL_REVIEW_POLICY,
        SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY,
        SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
        SOURCE_CORE_PRACTICAL_REVIEW_POLICY,
        EDITORIAL_PRACTICAL_REVIEW_POLICY,
        CANONICAL_EDITORIAL_REVIEW_POLICY,
        AUTONOMOUS_EDITORIAL_REVIEW_POLICY,
        JOINT_EDITORIAL_REVIEW_POLICY,
        COHERENT_EDITORIAL_REVIEW_POLICY,
        FOCUSED_EDITORIAL_REVIEW_POLICY,
        SIMPLE_COURSE_REVIEW_POLICY,
        SIMPLE_COURSE_REVIEW_V2_POLICY,
        SIMPLE_COURSE_REVIEW_V3_POLICY,
        SIMPLE_COURSE_REVIEW_V4_POLICY,
        SIMPLE_COURSE_REVIEW_V5_POLICY,
        SIMPLE_COURSE_REVIEW_V6_POLICY,
        SIMPLE_COURSE_REVIEW_V7_POLICY,
        SIMPLE_COURSE_REVIEW_V8_POLICY,
        SIMPLE_COURSE_REVIEW_V9_POLICY,
        SIMPLE_COURSE_REVIEW_V10_POLICY,
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
