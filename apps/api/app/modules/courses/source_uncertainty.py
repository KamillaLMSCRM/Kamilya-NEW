"""Fail-closed guard for server-owned unresolved source uncertainty.

No resolution API is provided. Any presence of the reserved marker blocks approval
and publication, including malformed values; a missing marker retains legacy behavior.
"""
from copy import deepcopy
from datetime import UTC
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


def compute_source_uncertainty_content_hash(source_analysis: dict[str, Any] | None) -> str:
    """Computes deterministic SHA256 of course source analysis content excluding resolution metadata."""
    import hashlib
    import json

    cleaned = deepcopy(source_analysis or {})
    cleaned.pop(SOURCE_UNCERTAINTY_KEY, None)
    cleaned.pop("source_uncertainty_resolution", None)
    cleaned.pop("resolutions_history", None)
    serialized = json.dumps(cleaned, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_active_source_violations(source_analysis: dict[str, Any] | None) -> list[str]:
    """Extracts all active semantic violations and defects from course source analysis."""
    if not isinstance(source_analysis, dict):
        return []
    violations: list[str] = []

    for key in ("evidence_v3", "diagnostics", "evidence_v2"):
        sub = source_analysis.get(key)
        if isinstance(sub, dict):
            v_list = sub.get("violations")
            if isinstance(v_list, list):
                violations.extend(str(v) for v in v_list if v)
            val_rep = sub.get("validation_report")
            if isinstance(val_rep, dict):
                rep_v = val_rep.get("violations")
                if isinstance(rep_v, list):
                    violations.extend(str(v) for v in rep_v if v)

    direct_v = source_analysis.get("violations")
    if isinstance(direct_v, list):
        violations.extend(str(v) for v in direct_v if v)

    return list(dict.fromkeys(v.strip() for v in violations if v and v.strip()))


def resolve_source_uncertainty(
    source_analysis: dict[str, Any] | None,
    *,
    reason: str,
    methodologist_user_id: object,
    expected_content_hash: str | None = None,
    verified_revision: str | None = None,
    acknowledged_defects: list[str] | None = None,
) -> dict[str, Any]:
    """Authorized methodologist action: clears unresolved_source_uncertainty hold after manual verification.

    Binds the resolution to the verified content hash and ensures that active defects/violations
    cannot be silently bypassed without explicit methodologist acknowledgment.
    Preserves all previous resolutions in resolutions_history without overwriting.
    """
    from datetime import datetime

    if not methodologist_user_id or not str(methodologist_user_id).strip():
        raise ValueError("methodologist_user_id is required")
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ValueError("reason must be a non-empty string of at least 10 characters")

    result = deepcopy(source_analysis or {})
    if SOURCE_UNCERTAINTY_KEY not in result:
        raise ValueError("У курса отсутствует активная блокировка неопределенности первоисточника (unresolved_source_uncertainty)")

    # 1. Content hash verification (protects against concurrent edits or stale reviews)
    current_hash = compute_source_uncertainty_content_hash(result)
    if expected_content_hash and expected_content_hash.strip().lower() != current_hash.lower():
        raise ValueError(
            f"Несоответствие версии содержания курса: ожидался хэш {expected_content_hash}, "
            f"но актуальный хэш {current_hash}. Содержание изменилось с момента проверки."
        )

    # 2. Binding to active semantic defects / violations
    active_violations = get_active_source_violations(result)
    ack_list = [str(d).strip() for d in (acknowledged_defects or []) if str(d).strip()]
    if active_violations:
        if not ack_list:
            raise ValueError(
                f"Невозможно снять блокировку неопределенности: обнаружены неисправленные замечания/нарушения ({len(active_violations)}). "
                f"Методолог должен явно подтвердить их в запросе (acknowledged_defects): {active_violations}"
            )
        unacknowledged = [v for v in active_violations if not any(v in a or a in v for a in ack_list)]
        if unacknowledged:
            raise ValueError(
                f"Не все критические нарушения подтверждены методологом: остались неподтвержденными {unacknowledged}"
            )

    # 3. Create resolution entry
    resolution_entry = {
        "status": "resolved",
        "resolved_by": str(methodologist_user_id).strip(),
        "resolved_at": datetime.now(UTC).isoformat(),
        "reason": reason.strip(),
        "content_hash": current_hash,
        "verified_revision": (verified_revision or "").strip(),
        "acknowledged_defects": ack_list,
    }

    # 4. Update source_analysis
    result.pop(SOURCE_UNCERTAINTY_KEY, None)
    history = list(result.get("resolutions_history") or [])
    if "source_uncertainty_resolution" in result and result["source_uncertainty_resolution"] not in history:
        history.append(result["source_uncertainty_resolution"])
    history.append(resolution_entry)
    result["resolutions_history"] = history
    result["source_uncertainty_resolution"] = resolution_entry

    if "evidence_v3" in result and isinstance(result["evidence_v3"], dict):
        result["evidence_v3"]["acknowledged_defects"] = ack_list
    if "diagnostics" in result and isinstance(result["diagnostics"], dict):
        result["diagnostics"]["acknowledged_defects"] = ack_list

    return result


def is_qa_source_tenant(tenant_id: object) -> bool:
    from app.core.config import get_settings
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    return (get_settings().DEPLOYMENT_ENVIRONMENT == "render-development"
            and str(tenant_id) == str(QA_TENANT))
