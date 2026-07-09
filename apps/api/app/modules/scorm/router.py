from __future__ import annotations

import hashlib
import json
import mimetypes
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, decode_token, get_current_user, require_role
from app.core.db import get_db
from app.core.storage import get_storage
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.certificates.service import issue_certificate
from app.modules.scorm.models import ScormAttempt, ScormPackage
from app.modules.scorm.schemas import (
    ScormCommitRequest,
    ScormCommitResponse,
    ScormImportResponse,
    ScormLaunchInfo,
)

router = APIRouter(
    prefix="/scorm",
    tags=["scorm"],
)

MAX_SCORM_ZIP_BYTES = 250 * 1024 * 1024
MAX_SCORM_FILES = 5000
SCORM_LAUNCH_TOKEN_MINUTES = 180


def _safe_zip_names(zf: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for info in zf.infolist():
        raw = info.filename.replace("\\", "/").strip()
        if not raw or raw.endswith("/"):
            continue
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail="SCORM ZIP contains unsafe file paths")
        names.append(raw)
    if len(names) > MAX_SCORM_FILES:
        raise HTTPException(status_code=400, detail=f"SCORM ZIP contains more than {MAX_SCORM_FILES} files")
    return names


def _text_of(root: ET.Element, xpath: str, ns: dict[str, str]) -> str | None:
    el = root.find(xpath, ns)
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _parse_manifest(zf: zipfile.ZipFile, names: list[str]) -> dict[str, Any]:
    manifest_name = next((name for name in names if name.lower().endswith("imsmanifest.xml")), None)
    if not manifest_name:
        raise HTTPException(status_code=400, detail="SCORM package must contain imsmanifest.xml")

    try:
        root = ET.fromstring(zf.read(manifest_name))
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="imsmanifest.xml is not valid XML")

    ns = {
        "imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
        "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
        "adlcp2004": "http://www.adlnet.org/xsd/adlcp_v1p3",
    }
    default_org = root.find("imscp:organizations", ns)
    default_org_id = default_org.attrib.get("default") if default_org is not None else None
    org = None
    if default_org is not None and default_org_id:
        org = default_org.find(f"imscp:organization[@identifier='{default_org_id}']", ns)
    if org is None and default_org is not None:
        org = default_org.find("imscp:organization", ns)

    title = _text_of(org, "imscp:title", ns) if org is not None else None
    item = org.find(".//imscp:item", ns) if org is not None else None
    resource_id = item.attrib.get("identifierref") if item is not None else None
    resource = None
    if resource_id:
        resource = root.find(f".//imscp:resource[@identifier='{resource_id}']", ns)
    if resource is None:
        resource = root.find(".//imscp:resource[@href]", ns)
    if resource is None:
        raise HTTPException(status_code=400, detail="SCORM manifest has no launchable resource")

    href = (resource.attrib.get("href") or "").strip()
    if not href:
        raise HTTPException(status_code=400, detail="SCORM launch resource has no href")
    if PurePosixPath(href).is_absolute() or ".." in PurePosixPath(href).parts:
        raise HTTPException(status_code=400, detail="SCORM manifest contains unsafe launch path")

    # SCORM 2004 manifests always reference the adlcp_v1p3 namespace; ElementTree
    # stores namespace URIs inside tag names (e.g. "{http://www.adlnet.org/xsd/adlcp_v1p3}..."),
    # NOT in element.attrib. The original fallback searched `root.attrib`, which never
    # contained the namespace, so SCORM 2004 packages without an explicit schemaversion
    # were silently accepted as SCORM 1.2. Walk all tag names to find the 2004 marker.
    version = "unknown"
    schema_version = _text_of(root, "imscp:metadata/imscp:schemaversion", ns)
    if schema_version:
        lowered = schema_version.lower()
        if "2004" in lowered:
            version = "scorm_2004"
        elif "1.2" in lowered or "1,2" in lowered:
            version = "scorm_1_2"
    if version == "unknown":
        def _walk(el: ET.Element) -> bool:
            tag = el.tag if isinstance(el.tag, str) else ""
            if "adlcp_v1p3" in tag or "adlcp2004" in tag:
                return True
            return any(_walk(child) for child in list(el))
        version = "scorm_2004" if _walk(root) else "scorm_1_2"

    manifest_dir = str(PurePosixPath(manifest_name).parent)
    entrypoint = href if manifest_dir == "." else f"{manifest_dir}/{href}"
    if entrypoint not in names:
        # Some packages reference a URL with query/hash. The runtime step will handle
        # that; for import, keep the declared href but warn through manifest metadata.
        entrypoint_exists = False
    else:
        entrypoint_exists = True

    return {
        "manifest_file": manifest_name,
        "title": title or "SCORM курс",
        "version": version,
        "entrypoint": entrypoint,
        "entrypoint_exists": entrypoint_exists,
        "default_organization": default_org_id,
        "resource_id": resource_id,
        "file_count": len(names),
    }


def _assert_scorm_12(version: str) -> None:
    if version != "scorm_1_2":
        raise HTTPException(status_code=400, detail="Only SCORM 1.2 is supported")


def _make_launch_token(user: User, package: ScormPackage) -> str:
    return create_access_token(
        {
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "type": "scorm_launch",
            "package_id": str(package.id),
            "course_id": str(package.course_id),
        },
        expires_delta=timedelta(minutes=SCORM_LAUNCH_TOKEN_MINUTES),
    )


def _decode_launch_token(token: str, package_id: str | None = None) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "scorm_launch":
        raise HTTPException(status_code=401, detail="Invalid SCORM launch token")
    if package_id and payload.get("package_id") != package_id:
        raise HTTPException(status_code=403, detail="SCORM token does not match package")
    return payload


async def _get_package_for_user(db: AsyncSession, course_id: UUID, user: User) -> ScormPackage:
    result = await db.execute(
        select(ScormPackage)
        .join(Course, ScormPackage.course_id == Course.id)
        .where(
            ScormPackage.course_id == course_id,
            ScormPackage.tenant_id == user.tenant_id,
            Course.tenant_id == user.tenant_id,
            Course.delivery_type == "scorm",
        )
    )
    package = result.scalar_one_or_none()
    if not package:
        raise HTTPException(status_code=404, detail="SCORM package not found")
    _assert_scorm_12(package.version)
    return package


async def _get_or_create_attempt(db: AsyncSession, package: ScormPackage, user_id: str) -> ScormAttempt:
    user_uuid = UUID(user_id)
    result = await db.execute(
        select(ScormAttempt).where(
            ScormAttempt.tenant_id == package.tenant_id,
            ScormAttempt.package_id == package.id,
            ScormAttempt.user_id == user_uuid,
            ScormAttempt.completed_at.is_(None),
        )
    )
    attempt = result.scalar_one_or_none()
    if attempt:
        return attempt
    attempt = ScormAttempt(
        tenant_id=package.tenant_id,
        course_id=package.course_id,
        package_id=package.id,
        user_id=user_uuid,
        cmi_json={},
    )
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


def _asset_bytes(package: ScormPackage, asset_path: str) -> tuple[bytes, str]:
    path = asset_path.split("?", 1)[0].split("#", 1)[0].lstrip("/").replace("\\", "/")
    if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise HTTPException(status_code=400, detail="Unsafe SCORM asset path")
    archive = get_storage().get_bytes(package.storage_key)
    if not archive:
        raise HTTPException(status_code=404, detail="SCORM package archive not found")
    with zipfile.ZipFile(BytesIO(archive)) as zf:
        names = _safe_zip_names(zf)
        if path not in names:
            raise HTTPException(status_code=404, detail="SCORM asset not found")
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return zf.read(path), content_type


async def _complete_from_scorm(db: AsyncSession, attempt: ScormAttempt, user_id: str) -> dict[str, str | None]:
    user = await db.get(User, UUID(user_id))
    course = await db.get(Course, attempt.course_id)
    if not user or not course or user.tenant_id != attempt.tenant_id:
        raise HTTPException(status_code=404, detail="SCORM user/course not found")
    result = await db.execute(
        select(Enrollment).where(
            Enrollment.user_id == user.id,
            Enrollment.course_id == course.id,
            Enrollment.tenant_id == attempt.tenant_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        enrollment = Enrollment(
            user_id=user.id,
            course_id=course.id,
            tenant_id=attempt.tenant_id,
            status="enrolled",
            source="manual",
        )
        db.add(enrollment)
        await db.flush()
    if enrollment.status != "completed":
        enrollment.status = "completed"
        enrollment.completed_at = datetime.now(timezone.utc)
    cert = await issue_certificate(
        db=db,
        user_id=user.id,
        course_id=course.id,
        tenant_id=attempt.tenant_id,
        user_name=f"{user.first_name} {user.last_name}".strip() or user.email or "",
        course_title=course.title,
    )
    return {"certificate_id": str(cert.id), "certificate_number": cert.certificate_number}


def _is_scorm_completed(cmi: dict[str, Any]) -> bool:
    status = (
        cmi.get("cmi.core.lesson_status")
        or cmi.get("lesson_status")
        or cmi.get("cmi.lesson_status")
        or ""
    )
    return str(status).lower() in {"completed", "passed"}


@router.post("/packages/import", response_model=ScormImportResponse, status_code=201)
async def import_scorm_package(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    status: str = Form(default="draft"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "teacher")),
):
    from app.core.trial_limits import assert_can_create_courses

    if status not in {"draft", "published"}:
        raise HTTPException(status_code=422, detail="status must be draft or published")
    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a SCORM .zip package")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="SCORM ZIP is empty")
    if len(data) > MAX_SCORM_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="SCORM ZIP is too large")

    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = _safe_zip_names(zf)
            manifest = _parse_manifest(zf, names)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP")
    _assert_scorm_12(manifest["version"])

    await assert_can_create_courses(db, user.tenant_id)

    course_title = (title or manifest["title"]).strip()[:255] or "SCORM курс"
    course = Course(
        tenant_id=user.tenant_id,
        title=course_title,
        description=f"Импортированный SCORM-пакет: {filename}",
        status=status,
        delivery_type="scorm",
        created_by=user.id,
        review_status="approved",
        reviewed_by=user.id,
    )
    db.add(course)
    await db.flush()

    digest = hashlib.sha256(data).hexdigest()[:16]
    storage_key = f"scorm/{user.tenant_id}/{course.id}/{digest}.zip"
    get_storage().put_bytes(storage_key, data, content_type="application/zip")

    package = ScormPackage(
        tenant_id=user.tenant_id,
        course_id=course.id,
        version=manifest["version"],
        title=course_title,
        entrypoint=manifest["entrypoint"],
        storage_key=storage_key,
        manifest_json={**manifest, "original_filename": filename, "sha256": hashlib.sha256(data).hexdigest()},
        uploaded_by=user.id,
    )
    db.add(package)
    await db.flush()
    await db.refresh(package)

    await log_action(
        db,
        user.tenant_id,
        "import",
        "scorm_package",
        resource_id=str(package.id),
        user_id=user.id,
        details={
            "course_id": str(course.id),
            "filename": filename,
            "version": package.version,
            "entrypoint": package.entrypoint,
            "size_bytes": len(data),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"course_id": course.id, "package": package}


@router.get("/courses/{course_id}/launch", response_model=ScormLaunchInfo)
async def get_scorm_launch_info(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    package = await _get_package_for_user(db, course_id, user)
    token = _make_launch_token(user, package)
    base = str(request.base_url).rstrip("/")
    return {
        "course_id": package.course_id,
        "package_id": package.id,
        "launch_url": f"{base}/api/v1/scorm/packages/{package.id}/launch?token={token}",
        "version": "scorm_1_2",
        "title": package.title,
    }


@router.get("/packages/{package_id}/launch", response_class=HTMLResponse)
async def launch_scorm_package(
    package_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    payload = _decode_launch_token(token, package_id=package_id)
    package = await db.get(ScormPackage, package_id)
    if not package or str(package.tenant_id) != payload.get("tenant_id"):
        raise HTTPException(status_code=404, detail="SCORM package not found")
    _assert_scorm_12(package.version)
    attempt = await _get_or_create_attempt(db, package, payload["sub"])
    await db.commit()
    entrypoint = package.entrypoint
    asset_url = f"/api/v1/scorm/packages/{package.id}/assets-token/{token}/{entrypoint}"
    commit_url = f"/api/v1/scorm/attempts/{attempt.id}/commit?token={token}"
    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{package.title}</title>
  <style>
    html, body, iframe {{ width: 100%; height: 100%; margin: 0; border: 0; background: #fff; }}
    .bar {{ height: 36px; display: flex; align-items: center; gap: 12px; padding: 0 12px; border-bottom: 1px solid #ddd; font: 13px system-ui, sans-serif; color: #555; }}
    .dot {{ width: 8px; height: 8px; border-radius: 999px; background: #999; }}
    .dot.saved {{ background: #16a34a; }}
    .dot.error {{ background: #dc2626; }}
    iframe {{ height: calc(100% - 37px); display: block; }}
  </style>
</head>
<body>
  <div class="bar"><span id="status-dot" class="dot"></span><span id="status-text">SCORM 1.2 runtime готов</span></div>
  <iframe id="sco" src="{asset_url}" allow="fullscreen"></iframe>
  <script>
    const commitUrl = {json.dumps(commit_url)};
    const cmi = {{}};
    let initialized = false;
    let lastError = "0";
    const dot = document.getElementById("status-dot");
    const statusText = document.getElementById("status-text");
    function setStatus(text, kind) {{
      statusText.textContent = text;
      dot.className = "dot" + (kind ? " " + kind : "");
    }}
    function ok() {{ lastError = "0"; return "true"; }}
    function fail(code) {{ lastError = code || "101"; return "false"; }}
    async function commit() {{
      try {{
        setStatus("Сохранение прогресса...", "");
        const res = await fetch(commitUrl, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ cmi }})
        }});
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        setStatus(data.completed ? "Курс завершён" : "Прогресс сохранён", "saved");
        return true;
      }} catch (e) {{
        console.error("SCORM commit failed", e);
        setStatus("Не удалось сохранить прогресс", "error");
        return false;
      }}
    }}
    window.API = {{
      LMSInitialize: function() {{ initialized = true; return ok(); }},
      LMSFinish: function() {{ if (!initialized) return fail("301"); initialized = false; commit(); return ok(); }},
      LMSGetValue: function(key) {{ if (!initialized) return ""; lastError = "0"; return cmi[key] || ""; }},
      LMSSetValue: function(key, value) {{ if (!initialized) return fail("301"); cmi[key] = String(value); return ok(); }},
      LMSCommit: function() {{ if (!initialized) return fail("301"); commit(); return ok(); }},
      LMSGetLastError: function() {{ return lastError; }},
      LMSGetErrorString: function(code) {{
        const map = {{ "0": "No error", "101": "General exception", "301": "Not initialized" }};
        return map[String(code)] || "SCORM runtime error";
      }},
      LMSGetDiagnostic: function(code) {{ return this.LMSGetErrorString(code); }}
    }};
    window.addEventListener("beforeunload", function() {{
      navigator.sendBeacon && navigator.sendBeacon(commitUrl, new Blob([JSON.stringify({{ cmi }})], {{ type: "application/json" }}));
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/packages/{package_id}/assets/{asset_path:path}")
async def get_scorm_asset(
    package_id: str,
    asset_path: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    payload = _decode_launch_token(token, package_id=package_id)
    package = await db.get(ScormPackage, package_id)
    if not package or str(package.tenant_id) != payload.get("tenant_id"):
        raise HTTPException(status_code=404, detail="SCORM package not found")
    content, content_type = _asset_bytes(package, asset_path)
    return Response(content=content, media_type=content_type)


@router.get("/packages/{package_id}/assets-token/{token}/{asset_path:path}")
async def get_scorm_asset_by_token_path(
    package_id: str,
    token: str,
    asset_path: str,
    db: AsyncSession = Depends(get_db),
):
    payload = _decode_launch_token(token, package_id=package_id)
    package = await db.get(ScormPackage, package_id)
    if not package or str(package.tenant_id) != payload.get("tenant_id"):
        raise HTTPException(status_code=404, detail="SCORM package not found")
    content, content_type = _asset_bytes(package, asset_path)
    return Response(content=content, media_type=content_type)


@router.post("/attempts/{attempt_id}/commit", response_model=ScormCommitResponse)
async def commit_scorm_attempt(
    attempt_id: str,
    req: ScormCommitRequest,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    payload = _decode_launch_token(token)
    attempt = await db.get(ScormAttempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="SCORM attempt not found")
    if str(attempt.tenant_id) != payload.get("tenant_id") or str(attempt.user_id) != payload.get("sub"):
        raise HTTPException(status_code=403, detail="SCORM token does not match attempt")

    cmi = dict(req.cmi or {})
    attempt.cmi_json = {**(attempt.cmi_json or {}), **cmi}
    attempt.lesson_status = cmi.get("cmi.core.lesson_status") or attempt.lesson_status
    attempt.score_raw = cmi.get("cmi.core.score.raw") or attempt.score_raw
    attempt.lesson_location = cmi.get("cmi.core.lesson_location") or attempt.lesson_location
    attempt.total_time = cmi.get("cmi.core.total_time") or attempt.total_time
    attempt.suspend_data = cmi.get("cmi.suspend_data") or attempt.suspend_data
    attempt.last_commit_at = datetime.now(timezone.utc)

    cert_data: dict[str, str | None] = {"certificate_id": None, "certificate_number": None}
    completed = _is_scorm_completed(attempt.cmi_json)
    if completed and attempt.completed_at is None:
        attempt.completed_at = datetime.now(timezone.utc)
        cert_data = await _complete_from_scorm(db, attempt, payload["sub"])

    await db.commit()
    return {
        "status": "completed" if completed else "saved",
        "attempt_id": attempt.id,
        "completed": completed,
        **cert_data,
    }
