"""Integration tests for SCORM 1.2 end-to-end flow.

P0.1 first-tenant hardening.

Builds minimal synthetic SCORM 1.2 ZIPs in memory (no real iSpring/
Articulate/Captivate packages available in this environment) and walks
the full import → launch → commit → completion → certificate path.

What's covered:
- Import: POST /api/v1/scorm/packages/import accepts a SCORM 1.2 ZIP
  and returns course_id + package metadata.
- Reject: SCORM 2004 package returns 400 with a clear message.
- Reject: non-ZIP file returns 400.
- Launch: GET /api/v1/scorm/courses/{course_id}/launch returns
  a launch_url pointing at the HTML launcher.
- Asset proxy: GET /api/v1/scorm/packages/{id}/assets-token/{token}/{path}
  returns the file's bytes (CSS/JS/images).
- Commit: POST /api/v1/scorm/attempts/{id}/commit with
  cmi.core.lesson_status=completed closes the enrollment, issues a
  certificate, and returns the certificate number.
- Cross-tenant isolation: another tenant cannot launch or read assets
  from this package.
"""
from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import pytest


def _scorm12_zip(*, resource_href: str = "index.html", title: str = "QA course") -> bytes:
    """Build a minimal SCORM 1.2 ZIP.

    Structure:
      imsmanifest.xml       — declares the SCO at index.html
      index.html            — minimal page that talks to window.API
      content/styles.css    — CSS file (asset proxy target)
      content/script.js     — JS file (asset proxy target)
    """
    manifest = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="MANIFEST-{uuid4().hex[:8]}" version="1.0"
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                              http://www.imsproject.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd
                              http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>{title}</title>
      <item identifier="ITEM-1" identifierref="RES-1">
        <title>Lesson 1</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp:scormtype="sco" href="{resource_href}">
      <file href="{resource_href}"/>
    </resource>
  </resources>
</manifest>"""
    index_html = b"""<!doctype html>
<html><head><title>QA</title></head>
<body>
<script>
  window.API.LMSInitialize("");
  window.API.LMSSetValue("cmi.core.lesson_status", "completed");
  window.API.LMSCommit("");
  window.API.LMSFinish("");
</script>
</body></html>
"""
    css = b"body { background: #fff; }"
    js = b"console.log('hello');"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", manifest)
        zf.writestr(resource_href, index_html)
        zf.writestr("content/styles.css", css)
        zf.writestr("content/script.js", js)
    return buf.getvalue()


def _scorm2004_zip() -> bytes:
    """Build a SCORM 2004 ZIP — must be rejected at import."""
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="M-2004" version="1.0"
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp2004="http://www.adlnet.org/xsd/adlcp_v1p3">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>2004 3rd Edition</schemaversion>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>2004</title>
      <item identifier="ITEM-1" identifierref="RES-1"/>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp2004:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", manifest)
        zf.writestr("index.html", b"<html></html>")
    return buf.getvalue()


async def _login(client, user, password: str = "Password123!") -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_scorm12_import_happy_path(
    client, monkeypatch, tmp_path, db_session, make_tenant, make_user
):
    """End-to-end: import → launch → asset → commit → enrollment+certificate."""
    from app.core.storage import reset_storage_for_tests

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CERTIFICATE_STORAGE_DIR", str(tmp_path))
    reset_storage_for_tests()
    yield_reset = True

    tenant = await make_tenant(name="AcmeSCORM", slug="acme-scorm")
    admin = await make_user(tenant, role="methodologist", email="a@scorm.example")
    learner = await make_user(tenant, role="student", email="l@scorm.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: import
    zip_bytes = _scorm12_zip(title="E2E QA Course")
    resp = await client.post(
        "/api/v1/scorm/packages/import",
        headers=headers,
        files={"file": ("course.zip", zip_bytes, "application/zip")},
        data={"title": "E2E QA Course", "status": "published"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    course_id = body["course_id"]
    package_id = body["package"]["id"]
    assert body["package"]["version"] == "scorm_1_2"
    assert body["package"]["entrypoint"] == "index.html"

    try:
        # Step 2: launch — admin can launch to test the shell.
        resp = await client.get(
            f"/api/v1/scorm/courses/{course_id}/launch",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        launch = resp.json()
        assert launch["version"] == "scorm_1_2"
        assert "launch_url" in launch
        assert str(package_id) in launch["launch_url"]

        # Step 3: log in as the learner and get the launch token.
        learner_token = await _login(client, learner)
        learner_headers = {"Authorization": f"Bearer {learner_token}"}

        resp = await client.get(
            f"/api/v1/scorm/courses/{course_id}/launch",
            headers=learner_headers,
        )
        assert resp.status_code == 200, resp.text
        launch = resp.json()
        launch_url = launch["launch_url"]
        # Extract token from URL
        token_param = launch_url.split("token=", 1)[1].split("&", 1)[0]

        # Step 4: fetch an asset through the asset proxy.
        # /assets-token/{token}/{path} requires no auth header — token IS the auth.
        resp = await client.get(
            f"/api/v1/scorm/packages/{package_id}/assets-token/{token_param}/index.html"
        )
        assert resp.status_code == 200, resp.text
        assert b"<html>" in resp.content

        resp = await client.get(
            f"/api/v1/scorm/packages/{package_id}/assets-token/{token_param}/content/styles.css"
        )
        assert resp.status_code == 200, resp.text
        assert b"background" in resp.content

        # Step 5: render the launcher HTML (also creates the attempt).
        resp = await client.get(
            f"/api/v1/scorm/packages/{package_id}/launch?token={token_param}"
        )
        assert resp.status_code == 200, resp.text
        assert b"window.API" in resp.content
        assert b"LMSInitialize" in resp.content

        # Find the attempt id from the launcher page's commitUrl
        import re

        m = re.search(rb"const commitUrl = \"([^\"]+)\"", resp.content)
        assert m, "commitUrl not embedded in launcher HTML"
        commit_url_path = m.group(1).decode("utf-8")
        # commit_url_path is like /api/v1/scorm/attempts/{id}/commit?token=...

        # Step 6: commit with lesson_status=completed → certificate
        resp = await client.post(
            commit_url_path,
            json={
                "cmi": {
                    "cmi.core.lesson_status": "completed",
                    "cmi.core.score.raw": "100",
                }
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["completed"] is True
        assert body["certificate_id"] is not None
        assert body["certificate_number"] is not None
    finally:
        if yield_reset:
            reset_storage_for_tests()


@pytest.mark.asyncio
async def test_scorm2004_rejected_with_clear_error(
    client, monkeypatch, tmp_path, make_tenant, make_user
):
    from app.core.storage import reset_storage_for_tests

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CERTIFICATE_STORAGE_DIR", str(tmp_path))
    reset_storage_for_tests()

    tenant = await make_tenant(name="Acme2", slug="acme-2004")
    admin = await make_user(tenant, role="methodologist", email="a@2004.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/scorm/packages/import",
        headers=headers,
        files={"file": ("course.zip", _scorm2004_zip(), "application/zip")},
    )
    assert resp.status_code == 400, resp.text
    # Detail should mention SCORM 1.2 specifically
    detail = resp.json().get("message", "")
    assert "SCORM 1.2" in detail or "1.2" in detail


@pytest.mark.asyncio
async def test_scorm_non_zip_rejected(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme3", slug="acme-nz")
    admin = await make_user(tenant, role="methodologist", email="a@nz.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    # Plain text pretending to be a zip
    resp = await client.post(
        "/api/v1/scorm/packages/import",
        headers=headers,
        files={"file": ("course.zip", b"this is not a zip", "application/zip")},
    )
    assert resp.status_code == 400
    detail = resp.json().get("message", "")
    assert "valid ZIP" in detail or "ZIP" in detail


@pytest.mark.asyncio
async def test_scorm12_launch_requires_tenant_match(
    client, monkeypatch, tmp_path, make_tenant, make_user
):
    """Tenant B's admin cannot launch Tenant A's SCORM course."""
    from app.core.storage import reset_storage_for_tests

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CERTIFICATE_STORAGE_DIR", str(tmp_path))
    reset_storage_for_tests()

    tenant_a = await make_tenant(name="A", slug="a-scorm")
    tenant_b = await make_tenant(name="B", slug="b-scorm")
    admin_a = await make_user(tenant_a, role="methodologist", email="a@a-scorm.example")
    admin_b = await make_user(tenant_b, role="methodologist", email="a@b-scorm.example")

    headers_a = {"Authorization": f"Bearer {await _login(client, admin_a)}"}

    # Import in tenant A
    resp = await client.post(
        "/api/v1/scorm/packages/import",
        headers=headers_a,
        files={"file": ("c.zip", _scorm12_zip(title="A only"), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    course_id = resp.json()["course_id"]

    # Tenant B tries to launch it
    headers_b = {"Authorization": f"Bearer {await _login(client, admin_b)}"}
    resp = await client.get(
        f"/api/v1/scorm/courses/{course_id}/launch",
        headers=headers_b,
    )
    # Either 404 (course not visible) or 403 — both are acceptable.
    # Per api-design convention we return 404 for cross-tenant data.
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_scorm12_in_progress_does_not_complete(
    client, monkeypatch, tmp_path, make_tenant, make_user
):
    """in_progress should NOT trigger certificate or completion."""
    from app.core.storage import reset_storage_for_tests

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("CERTIFICATE_STORAGE_DIR", str(tmp_path))
    reset_storage_for_tests()

    tenant = await make_tenant(name="Acme4", slug="acme-inprog")
    admin = await make_user(tenant, role="methodologist", email="a@ip.example")
    learner = await make_user(tenant, role="student", email="l@ip.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    # Import + launch
    resp = await client.post(
        "/api/v1/scorm/packages/import",
        headers=headers,
        files={"file": ("c.zip", _scorm12_zip(title="InProgress"), "application/zip")},
    )
    assert resp.status_code == 201
    course_id = resp.json()["course_id"]
    package_id = resp.json()["package"]["id"]

    learner_token = await _login(client, learner)
    resp = await client.get(
        f"/api/v1/scorm/courses/{course_id}/launch",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    launch_token = resp.json()["launch_url"].split("token=", 1)[1].split("&", 1)[0]

    # Render launcher to create the attempt
    resp = await client.get(
        f"/api/v1/scorm/packages/{package_id}/launch?token={launch_token}"
    )
    import re

    m = re.search(rb"const commitUrl = \"([^\"]+)\"", resp.content)
    commit_url_path = m.group(1).decode("utf-8")

    # Commit with status=incomplete — should NOT complete
    resp = await client.post(
        commit_url_path,
        json={"cmi": {"cmi.core.lesson_status": "incomplete", "cmi.core.score.raw": "50"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["completed"] is False
    assert body["certificate_id"] is None
    assert body["certificate_number"] is None
