"""Unit tests for SCORM manifest parser (apps/api/app/modules/scorm/router.py).

P0.1 first-tenant hardening.

Covers edge cases that real SCORM packages hit:
- SCORM 1.2 with explicit schemaversion="1.2"
- SCORM 1.2 with no schemaversion, no 2004 namespace
- SCORM 2004 detected via schemaversion="2004 3rd Edition"
- SCORM 2004 detected via adlcp_v1p3 namespace in tag names (the
  bug that commit 0481f57 fixed)
- Resource href with query string (?param=value) — packages like
  iSpring declare their entry as `index.html?loadcss=...`
- Resource href with hash fragment
- Resource href pointing to a nested directory
- Resource href that doesn't exist in the zip → entrypoint_exists=False
"""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app.modules.scorm.router import _parse_manifest


def _make_zip(manifest_xml: str, extra_files: list[tuple[str, bytes]] | None = None) -> bytes:
    """Build an in-memory ZIP with the given manifest and optional extra files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        for name, content in extra_files or []:
            zf.writestr(name, content)
    return buf.getvalue()


def _zip_with_manifest(manifest_xml: str):
    """Return a (zipfile.ZipFile, names) tuple ready for _parse_manifest."""
    data = _make_zip(manifest_xml)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = [n.replace("\\", "/") for n in zf.namelist() if n and not n.endswith("/")]
    return zf, names


# Standard SCORM 1.2 manifest template
def _scorm12_manifest(resource_href: str = "index.html") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="MANIFEST-1" version="1.0"
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
      <title>Test course</title>
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
</manifest>
"""


# SCORM 2004 manifest — explicit schemaversion
def _scorm2004_manifest_via_version(resource_href: str = "index.html") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="MANIFEST-1" version="1.0"
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:adlcp2004="http://www.adlnet.org/xsd/adlcp_v1p3"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>2004 3rd Edition</schemaversion>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>Test SCORM 2004</title>
      <item identifier="ITEM-1" identifierref="RES-1">
        <title>Lesson 1</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp2004:scormtype="sco" href="{resource_href}">
      <file href="{resource_href}"/>
    </resource>
  </resources>
</manifest>
"""


# SCORM 2004 manifest — schemaversion MISSING, only namespace declares it.
# This is the case that commit 0481f57 fixed: the previous code looked for
# "adlcp_v1p3" inside `root.attrib` (which ElementTree never populates for
# namespace declarations) and silently accepted the package as SCORM 1.2.
def _scorm2004_manifest_via_namespace(resource_href: str = "index.html") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="MANIFEST-1" version="1.0"
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:adlcp2004="http://www.adlnet.org/xsd/adlcp_v1p3">
  <metadata>
    <schema>ADL SCORM</schema>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>2004 via namespace only</title>
      <item identifier="ITEM-1" identifierref="RES-1">
        <title>Lesson 1</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp2004:scormtype="sco" href="{resource_href}">
      <file href="{resource_href}"/>
    </resource>
  </resources>
</manifest>
"""


# ───────────────────────────────────────────────────────────────────
# Happy path
# ───────────────────────────────────────────────────────────────────


def test_scorm12_explicit_schemaversion_detected():
    zf, names = _zip_with_manifest(_scorm12_manifest("index.html"))
    manifest = _parse_manifest(zf, names)
    assert manifest["version"] == "scorm_1_2"
    assert manifest["entrypoint"] == "index.html"
    assert manifest["entrypoint_exists"] is True
    assert manifest["title"] == "Test course"


def test_scorm12_no_schemaversion_no_namespace_detected_as_12():
    """A bare SCORM 1.2 package with no metadata/schemaversion must still
    be detected as 1.2 (default for non-2004 packages)."""
    xml = """<?xml version="1.0"?>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>Bare 1.2</title>
      <item identifier="ITEM-1" identifierref="RES-1"/>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" href="index.html"/>
  </resources>
</manifest>"""
    zf, names = _zip_with_manifest(xml)
    manifest = _parse_manifest(zf, names)
    assert manifest["version"] == "scorm_1_2"


# ───────────────────────────────────────────────────────────────────
# SCORM 2004 detection (regression: bug fixed in 0481f57)
# ───────────────────────────────────────────────────────────────────


def test_scorm2004_explicit_schemaversion_detected():
    zf, names = _zip_with_manifest(_scorm2004_manifest_via_version())
    manifest = _parse_manifest(zf, names)
    assert manifest["version"] == "scorm_2004"


def test_scorm2004_namespace_only_detected():
    """Regression test for commit 0481f57: when schemaversion is missing
    but the manifest declares the adlcp_v1p3 namespace, we must still
    detect SCORM 2004 (not silently classify it as 1.2)."""
    zf, names = _zip_with_manifest(_scorm2004_manifest_via_namespace())
    manifest = _parse_manifest(zf, names)
    assert manifest["version"] == "scorm_2004"


# ───────────────────────────────────────────────────────────────────
# Resource href edge cases
# ───────────────────────────────────────────────────────────────────


def test_resource_href_with_query_string():
    """iSpring/Articulate packages commonly declare `index.html?foo=bar`
    in the resource href. The parser must accept this without crashing
    and the entrypoint_exists check must compare against the bare path."""
    zf, names = _zip_with_manifest(
        _scorm12_manifest("index.html?loadcss=1"),
        extra_files=[("index.html", b"<html></html>")],
    )
    manifest = _parse_manifest(zf, names)
    assert manifest["entrypoint"] == "index.html?loadcss=1"
    assert manifest["entrypoint_exists"] is True


def test_resource_href_with_hash_fragment():
    zf, names = _zip_with_manifest(
        _scorm12_manifest("index.html#section-2"),
        extra_files=[("index.html", b"<html></html>")],
    )
    manifest = _parse_manifest(zf, names)
    assert manifest["entrypoint"] == "index.html#section-2"
    assert manifest["entrypoint_exists"] is True


def test_resource_href_in_subdirectory():
    """When the manifest lives in a subdir and references `content/index.html`,
    the entrypoint should be `content/index.html` (relative to archive root)."""
    sub_manifest = _scorm12_manifest("content/index.html").replace(
        "<manifest identifier=", "<manifest identifier="
    )
    # Build a ZIP with manifest.xml at root and content/index.html inside
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", sub_manifest)
        zf.writestr("content/index.html", b"<html></html>")
    zf2 = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    names = [n.replace("\\", "/") for n in zf2.namelist() if n and not n.endswith("/")]
    manifest = _parse_manifest(zf2, names)
    assert manifest["entrypoint"] == "content/index.html"
    assert manifest["entrypoint_exists"] is True


def test_resource_href_not_in_zip_marks_entrypoint_missing():
    """If the resource href doesn't match any file in the archive,
    entrypoint_exists should be False (not raise)."""
    zf, names = _zip_with_manifest(_scorm12_manifest("missing.html"))
    manifest = _parse_manifest(zf, names)
    assert manifest["entrypoint"] == "missing.html"
    assert manifest["entrypoint_exists"] is False


# ───────────────────────────────────────────────────────────────────
# Manifest errors
# ───────────────────────────────────────────────────────────────────


def test_manifest_missing_imsmanifest_raises():
    """No imsmanifest.xml at all → 400."""
    from fastapi import HTTPException

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("index.html", b"<html></html>")
    zf2 = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    names = ["index.html"]
    with pytest.raises(HTTPException) as ei:
        _parse_manifest(zf2, names)
    assert ei.value.status_code == 400
    assert "imsmanifest.xml" in ei.value.detail


def test_manifest_invalid_xml_raises():
    """Garbage in imsmanifest.xml → 400, not 500."""
    from fastapi import HTTPException

    zf, names = _zip_with_manifest("<not-xml>")
    with pytest.raises(HTTPException) as ei:
        _parse_manifest(zf, names)
    assert ei.value.status_code == 400
    assert "valid XML" in ei.value.detail


def test_manifest_no_launchable_resource_raises():
    """Resources section exists but no href → 400."""
    from fastapi import HTTPException

    xml = """<?xml version="1.0"?>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <item identifier="ITEM-1" identifierref="RES-1"/>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1"/>
  </resources>
</manifest>"""
    zf, names = _zip_with_manifest(xml)
    with pytest.raises(HTTPException) as ei:
        _parse_manifest(zf, names)
    assert ei.value.status_code == 400


def test_manifest_unsafe_href_raises():
    """Path traversal in resource href → 400, not silently imported."""
    from fastapi import HTTPException

    xml = """<?xml version="1.0"?>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <item identifier="ITEM-1" identifierref="RES-1"/>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" href="../../etc/passwd"/>
  </resources>
</manifest>"""
    zf, names = _zip_with_manifest(xml)
    with pytest.raises(HTTPException) as ei:
        _parse_manifest(zf, names)
    assert ei.value.status_code == 400
    assert "unsafe" in ei.value.detail.lower()