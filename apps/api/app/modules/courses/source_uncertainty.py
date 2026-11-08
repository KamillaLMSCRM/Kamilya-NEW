"""Fail-closed guard for server-owned unresolved source uncertainty.

Human resolution is revision-bound. Reserved markers block approval/publication;
P30 also binds resolution to current learning content, preserving legacy behavior.
"""
from copy import deepcopy
from datetime import UTC
from typing import Any

from fastapi import HTTPException

from app.modules.source_editorial_review.domain import SOURCE_PINS

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
    for key in (SOURCE_UNCERTAINTY_KEY, SOURCE_PINS):
        result.pop(key, None)
        if isinstance(old, dict) and key in old:
            result[key] = deepcopy(old[key])
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
    if new is not None and SOURCE_PINS in new:
        result[SOURCE_PINS] = deepcopy(new[SOURCE_PINS])
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


async def compute_course_content_snapshot_hash(db: Any, course: Any) -> str:
    """Computes authoritative canonical SHA-256 over the complete course learning content snapshot.

    Encompasses course metadata, modules, lessons (content, order, validation status),
    quizzes (questions, options), and source documents.
    Normalizes volatile hold markers in source_analysis to ensure idempotency.
    Fails closed: never falls back to partial hashes if full snapshot generation fails.
    """
    from app.modules.courses.release_service import (
        build_course_release_snapshot,
        canonical_json_sha256,
    )

    if db is None:
        raise ValueError("db session is required to compute authoritative course content snapshot hash")

    snapshot = await build_course_release_snapshot(db, course, version=1, populate_existing=True)
    if not isinstance(snapshot, dict) or "course" not in snapshot:
        raise RuntimeError("Не удалось сформировать полный снимок содержания курса для проверки целостности")

    c_data = snapshot["course"]
    if isinstance(c_data, dict) and "source_analysis" in c_data and isinstance(c_data["source_analysis"], dict):
        cleaned_sa = deepcopy(c_data["source_analysis"])
        cleaned_sa.pop(SOURCE_UNCERTAINTY_KEY, None)
        cleaned_sa.pop("source_uncertainty_resolution", None)
        cleaned_sa.pop("resolutions_history", None)
        c_data["source_analysis"] = cleaned_sa

    from app.modules.courses.draft_review import learning_content_snapshot

    return canonical_json_sha256(learning_content_snapshot(snapshot))


async def require_current_draft_review(db: Any, course: Any) -> None:
    """A prior P30 review never approves changed content or source revisions."""
    from app.modules.courses.draft_review import read_draft_review, resolution_is_current

    try:
        if read_draft_review(course.source_analysis) is None:
            return
        # Same lock order as explicit resolution: Course, then sorted owned
        # Document rows. A concurrent source update cannot slip between checks.
        from app.modules.courses.router import _extract_course_source_revisions

        await _extract_course_source_revisions(db, course, for_update=True)
        actual = await compute_course_content_snapshot_hash(db, course)
        if resolution_is_current(course.source_analysis, actual):
            return
        from app.modules.courses.automated_editorial_acceptance import automatic_acceptance_is_current

        if await automatic_acceptance_is_current(db, course=course, content_hash=actual):
            return
    except (ValueError, TypeError, KeyError):
        pass
    raise HTTPException(status_code=409, detail={'code': 'source_uncertainty_review_required'})


def get_active_source_violations(source_analysis: dict[str, Any] | None) -> list[str]:
    """Extracts all active semantic violations and defects from course source analysis."""
    if not isinstance(source_analysis, dict):
        return []
    violations: list[str] = []

    for key in ("evidence_v3", "diagnostics", "evidence_v2", "validation_report"):
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
    direct_w = source_analysis.get("source_warnings")
    if isinstance(direct_w, list):
        violations.extend(str(v) for v in direct_w if v)

    return list(dict.fromkeys(v.strip() for v in violations if v and v.strip()))


def get_active_source_defects(source_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Returns list of active defects with stable deterministic IDs and descriptions."""
    import hashlib

    from app.modules.courses.draft_review import read_draft_review

    manifest = read_draft_review(source_analysis)
    if manifest is not None:
        return [{'defect_id': row['id'], 'description': row['message'],
                 'target_id': row.get('target_id', ''), 'target_title': row.get('target_title', ''),
                 'source_refs': row['source_refs'], 'evidence': row.get('evidence', {})} for row in manifest['issues']]

    raw_violations = get_active_source_violations(source_analysis)
    defects: list[dict[str, str]] = []
    for v in raw_violations:
        clean_v = v.strip()
        d_id = f"defect-{hashlib.sha256(clean_v.encode('utf-8')).hexdigest()[:8]}"
        defects.append({
            "defect_id": d_id,
            "description": clean_v,
        })
    return defects


def resolve_source_uncertainty(
    source_analysis: dict[str, Any] | None,
    *,
    reason: str,
    methodologist_user_id: object,
    expected_content_hash: str,
    actual_content_hash: str,
    verified_revision: str,
    available_revisions: list[str] | None = None,
    authoritative_document_revisions: dict[str, str] | None = None,
    verified_revisions: dict[str, str] | None = None,
    defect_resolutions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Authorized methodologist action: clears unresolved_source_uncertainty hold after manual verification.

    Binds resolution to authoritative course content snapshot hash and enforces explicit,
    exact defect_id resolutions for all active semantic defects (no arbitrary substring matching).
    Enforces authoritative source revision verification and per-document matching when multiple sources exist.
    Preserves all previous resolutions in resolutions_history without overwriting.
    """
    from datetime import datetime

    if not methodologist_user_id or not str(methodologist_user_id).strip():
        raise ValueError("methodologist_user_id is required")
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ValueError("reason must be a non-empty string of at least 10 characters")

    result = deepcopy(source_analysis or {})
    from app.modules.courses.draft_review import read_draft_review

    draft_manifest = read_draft_review(result)
    if SOURCE_UNCERTAINTY_KEY not in result and draft_manifest is None:
        raise ValueError("У курса отсутствует активная блокировка неопределенности первоисточника (unresolved_source_uncertainty)")

    # 1. Content hash verification (protects against concurrent edits or stale reviews)
    if not expected_content_hash or not str(expected_content_hash).strip():
        raise ValueError("expected_content_hash обязателен для фиксации проверенной версии курса")
    clean_exp_hash = str(expected_content_hash).strip().lower()
    clean_act_hash = str(actual_content_hash).strip().lower()
    if clean_exp_hash != clean_act_hash:
        raise ValueError(
            f"Несоответствие версии содержания курса: ожидался хэш {clean_exp_hash}, "
            f"но актуальный хэш снимка {clean_act_hash}. Курс был изменен после проверки."
        )

    # 2. Authoritative source revision verification (fail-closed if authoritative revisions unknown)
    if not verified_revision or not str(verified_revision).strip():
        raise ValueError("verified_revision обязательна для фиксации проверенной ревизии источника")
    clean_rev = str(verified_revision).strip()

    if not available_revisions:
        raise ValueError("Невозможно подтвердить ревизию: у курса не определены авторитетные ревизии первоисточников")
    clean_avail = [str(r).strip() for r in available_revisions if str(r).strip()]
    if not clean_avail:
        raise ValueError("Невозможно подтвердить ревизию: список авторитетных ревизий источников пуст")
    if clean_rev not in clean_avail:
        raise ValueError(
            f"Указанная ревизия '{clean_rev}' не совпадает с авторитетными ревизиями источников курса: {clean_avail}"
        )

    # Multi-document check: each required document must match its authoritative revision
    if authoritative_document_revisions and len(authoritative_document_revisions) > 1:
        v_revs = verified_revisions or {}
        missing_docs = [doc_id for doc_id in authoritative_document_revisions if doc_id not in v_revs]
        if missing_docs:
            raise ValueError(
                f"Курс основан на нескольких источниках ({len(authoritative_document_revisions)}). "
                f"Необходимо предоставить verified_revisions для каждого документа: отсутствуют {missing_docs}"
            )
        for doc_id, expected_rev in authoritative_document_revisions.items():
            provided_rev = str(v_revs.get(doc_id, "")).strip()
            if provided_rev != str(expected_rev).strip():
                raise ValueError(
                    f"Несоответствие ревизии для документа '{doc_id}': ожидалось '{expected_rev}', передано '{provided_rev}'"
                )

    # 3. Exact defect resolution by stable defect_id (strict; substring matching forbidden)
    active_defects = get_active_source_defects(result)
    resolutions_list = defect_resolutions or []
    if active_defects:
        if not resolutions_list:
            req_defects = [f"{d['defect_id']} ({d['description'][:40]}...)" for d in active_defects]
            raise ValueError(
                f"Невозможно снять блокировку: обнаружены активные дефекты курса ({len(active_defects)}). "
                f"Методолог должен явно предоставить решения по каждому дефекту (defect_resolutions): {req_defects}"
            )
        res_by_id = {str(r.get("defect_id", "")).strip(): r for r in resolutions_list if isinstance(r, dict)}
        if draft_manifest is not None and (
                len(res_by_id) != len(resolutions_list)
                or set(res_by_id) != {d['defect_id'] for d in active_defects}):
            raise ValueError('draft_review_resolution_identity_mismatch')
        missing = []
        for d in active_defects:
            did = d["defect_id"]
            if did not in res_by_id:
                missing.append(did)
            else:
                res_item = res_by_id[did]
                act = res_item.get("action")
                if act not in ("acknowledged_risk", "documented_exception", "manual_verification_passed"):
                    raise ValueError(f"Недопустимое действие '{act}' для дефекта '{did}'")
                rat = (res_item.get("rationale") or "").strip()
                if len(rat) < 10:
                    raise ValueError(f"Обоснование для дефекта '{did}' слишком короткое (минимум 10 символов)")
        if missing:
            raise ValueError(
                f"Не все активные дефекты имеют явное решение методиста: отсутствуют решения для идентификаторов {missing}"
            )

    # 4. Create resolution entry
    resolution_entry = {
        "status": "resolved",
        "resolved_by": str(methodologist_user_id).strip(),
        "resolved_at": datetime.now(UTC).isoformat(),
        "reason": reason.strip(),
        "content_hash": clean_act_hash,
        "verified_revision": clean_rev,
        "verified_revisions": verified_revisions or {},
        "defect_resolutions": resolutions_list,
    }

    # 5. Update source_analysis
    result.pop(SOURCE_UNCERTAINTY_KEY, None)
    history = list(result.get("resolutions_history") or [])
    if "source_uncertainty_resolution" in result and result["source_uncertainty_resolution"] not in history:
        history.append(result["source_uncertainty_resolution"])
    history.append(resolution_entry)
    result["resolutions_history"] = history
    result["source_uncertainty_resolution"] = resolution_entry

    if "evidence_v3" in result and isinstance(result["evidence_v3"], dict):
        result["evidence_v3"]["defect_resolutions"] = resolutions_list
    if "diagnostics" in result and isinstance(result["diagnostics"], dict):
        result["diagnostics"]["defect_resolutions"] = resolutions_list

    return result


def is_qa_source_tenant(tenant_id: object) -> bool:
    from app.core.config import get_settings
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    return (get_settings().DEPLOYMENT_ENVIRONMENT == "render-development"
            and str(tenant_id) == str(QA_TENANT))
