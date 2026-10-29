"""Fail-closed guard for server-owned unresolved source uncertainty.

No resolution API is provided. Any presence of the reserved marker blocks approval
and publication, including malformed values; a missing marker retains legacy behavior.
"""
from copy import deepcopy
from typing import Any

from fastapi import HTTPException

SOURCE_UNCERTAINTY_KEY = "unresolved_source_uncertainty"


def qa_source_holds_enabled(tenant_id: object) -> bool:
    """Apply experimental source holds only to the opted-in DEV QA tenant."""
    from app.core.config import get_settings
    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    if str(tenant_id) != str(QA_TENANT):
        return False
    settings = get_settings()
    if settings.AI_QA_LUNA_DEV_ENABLED is not True:
        return False
    if (settings.DEPLOYMENT_ENVIRONMENT not in {"render-development", "render-development-worker", "vm-development-worker"}
            or settings.AI_LESSON_CYCLE_DEV_ENABLED is not True
            or str(QA_TENANT) not in settings.AI_LESSON_CYCLE_DEV_TENANTS):
        raise HTTPException(status_code=503, detail={"code": "dev_qa_source_hold_misconfigured"})
    return True


def preserve_source_uncertainty(old: object, new: dict[str, Any] | None) -> dict[str, Any]:
    """Never allow a source-analysis replacement to remove an existing hold."""
    result = dict(new or {})
    # Replacement content is not authorized to create or clear this server-owned key.
    result.pop(SOURCE_UNCERTAINTY_KEY, None)
    if isinstance(old, dict) and SOURCE_UNCERTAINTY_KEY in old:
        result[SOURCE_UNCERTAINTY_KEY] = deepcopy(old[SOURCE_UNCERTAINTY_KEY])
    return result


def require_source_uncertainty_clear(source_analysis: object) -> None:
    if not isinstance(source_analysis, dict):
        raise HTTPException(status_code=409, detail={"code": "source_uncertainty_review_required"})
    if isinstance(source_analysis, dict):
        evidence = source_analysis.get("evidence_v2")
        if (SOURCE_UNCERTAINTY_KEY in source_analysis
                or ("evidence_v2" in source_analysis and (
                    not isinstance(evidence, dict)
                    or not isinstance(evidence.get("quality_status"), str)
                    or evidence.get("quality_status") not in {
                        "source_needs_review", "lesson_surface_needs_review",
                        "degraded_needs_review", "assessment_needs_review", "validated_draft"}))
                or (isinstance(evidence, dict) and evidence.get("quality_status") in {
                    "source_needs_review", "lesson_surface_needs_review"})):
            raise HTTPException(status_code=409, detail={"code": "source_uncertainty_review_required"})


def preserve_generated_source_uncertainty(
    old: object, new: dict[str, Any] | None, *, source_review_required: bool
) -> dict[str, Any]:
    """Persist an internal generation hold; never clear an existing hold.

    Only the server-owned generation save may call this helper. User-provided
    source-analysis values must continue to use preserve_source_uncertainty.
    """
    if type(source_review_required) is not bool:
        raise TypeError("source_review_required must be a bool")
    result = preserve_source_uncertainty(old, new)
    if source_review_required and SOURCE_UNCERTAINTY_KEY not in result:
        result[SOURCE_UNCERTAINTY_KEY] = {"status": "review_required", "origin": "generation"}
    return result


def require_persisted_source_hold_clear(source_analysis: object) -> None:
    """Block only an existing server-owned marker, including malformed values.

    This narrow guard can run for every tenant while keeping marker-free legacy
    courses usable. The separate QA guard continues to inspect other statuses.
    """
    if isinstance(source_analysis, dict) and SOURCE_UNCERTAINTY_KEY in source_analysis:
        raise HTTPException(status_code=409, detail={"code": "source_uncertainty_review_required"})


def is_qa_source_tenant(tenant_id: object) -> bool:
    from app.core.config import get_settings
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    return (get_settings().DEPLOYMENT_ENVIRONMENT == "render-development"
            and str(tenant_id) == str(QA_TENANT))
