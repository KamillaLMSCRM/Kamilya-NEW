"""SCORM 1.2 QA harness — generates minimal reproducible ZIP fixtures.

Why this exists
---------------
We need real-package QA for the SCORM import → launch → completion flow
without depending on third-party authoring tools (iSpring, Articulate,
Captivate, Chamilo) being installed. The fixtures here reproduce the
common authoring output shapes:

- minimal: just imsmanifest.xml + index.html, no assets.
- with_assets: imsmanifest.xml + index.html + style.css + lesson.js +
  image.png + sub/page.html. Index references CSS/JS/image. Real
  authoring tools emit exactly this structure.
- query_entrypoint: index.html?loadcss=1 — iSpring-specific quirk.
  Confirms the parser keeps the query string and resolves the bare path.
- hash_entrypoint: index.html#section-2 — confirms fragment handling.
- scorm_2004_namespace_only: declared as SCORM 2004 via the
  adlcp2004 namespace only (no schemaversion). Must be rejected by
  /scorm/packages/import with "Only SCORM 1.2 is supported".
- malicious_title: title contains `<script>alert(1)</script>`. Import
  succeeds, but the launch HTML must escape the title so it renders as
  text not as executable script.

Usage
-----
    python apps/api/tests/fixtures/scorm_qa_harness.py all
    python apps/api/tests/fixtures/scorm_qa_harness.py minimal
    python apps/api/tests/fixtures/scorm_qa_harness.py with_assets
    ...

Each fixture writes a ZIP into docs/test-assets/scorm/<name>.zip. The
ZIPs can be uploaded via /courses → SCORM import → launch → commit to
exercise the full flow end-to-end. They can also be passed directly to
the unit/integration tests via ZipFile(BytesIO(...)).

Note on real-world QA
---------------------
For full confidence, also import a real iSpring / Articulate / Captivate
export. See docs/test-assets/scorm/README.md for instructions.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path


# SCORM 1.2 manifest template. `resource_href` is the entrypoint we point
# the default organization at; we re-use the same path for the file inside
# the ZIP so /scorm/packages/import's `entrypoint_exists` check passes.
MANIFEST_12_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{manifest_id}" version="1.0"
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
</manifest>
"""

# SCORM 2004 manifest with namespace declaration only — no schemaversion.
# Used to confirm parser detects it via _walk() over el.attrib keys.
MANIFEST_2004_NAMESPACE_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="MANIFEST-2004" version="1.0"
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:adlcp2004="http://www.adlnet.org/xsd/adlcp_v1p3">
  <metadata>
    <schema>ADL SCORM</schema>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>SCORM 2004 via namespace only</title>
      <item identifier="ITEM-1" identifierref="RES-1">
        <title>Lesson 1</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp2004:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>
"""


# Minimal index.html that calls LMSInitialize + LMSSetValue(lesson_status,
# completed) + LMSCommit + LMSFinish in the right order. Matches what
# iSpring emits by default.
MINIMAL_INDEX_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>SCORM 1.2 Lesson</title></head>
<body>
  <h1>Minimal SCORM 1.2 lesson</h1>
  <p>Click to complete.</p>
  <button onclick="finish()">Complete lesson</button>
  <script>
    function finish() {
      if (window.API && window.API.LMSInitialize) {
        window.API.LMSInitialize('');
        window.API.LMSSetValue('cmi.core.lesson_status', 'completed');
        window.API.LMSCommit('');
        window.API.LMSFinish('');
      }
    }
  </script>
</body>
</html>
"""


def _make_zip(files: dict[str, str | bytes]) -> bytes:
    """Build an in-memory ZIP from a {path: content} dict."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(path, data)
    return buf.getvalue()


def _write(name: str, data: bytes, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{name}.zip"
    out_path.write_bytes(data)
    return out_path


def build_minimal(outdir: Path) -> Path:
    """Just imsmanifest.xml + index.html. No assets."""
    files = {
        "imsmanifest.xml": MANIFEST_12_TEMPLATE.format(
            manifest_id="MANIFEST-MIN", title="Minimal SCORM", resource_href="index.html"
        ),
        "index.html": MINIMAL_INDEX_HTML,
    }
    return _write("minimal", _make_zip(files), outdir)


def build_with_assets(outdir: Path) -> Path:
    """Multi-asset package: CSS, JS, image, sub-folder page."""
    files = {
        "imsmanifest.xml": MANIFEST_12_TEMPLATE.format(
            manifest_id="MANIFEST-ASSETS",
            title="SCORM with assets",
            resource_href="index.html",
        ),
        "index.html": (
            '<!doctype html><html><head>'
            '<meta charset="utf-8">'
            '<link rel="stylesheet" href="style.css">'
            '<title>SCORM with assets</title></head>'
            "<body>"
            '<h1>Lesson</h1>'
            '<img src="logo.png" alt="logo">'
            '<script src="lesson.js"></script>'
            '<a href="sub/page.html">Next page</a>'
            "</body></html>"
        ),
        "style.css": "body { font-family: system-ui; padding: 20px; }",
        "lesson.js": "console.log('lesson.js loaded');",
        "logo.png": b"\x89PNG\r\n\x1a\n"  # PNG magic bytes — minimal valid header
        + b"\x00" * 32,
        "sub/page.html": (
            "<!doctype html><html><body><h2>Page 2</h2></body></html>"
        ),
    }
    return _write("with_assets", _make_zip(files), outdir)


def build_query_entrypoint(outdir: Path) -> Path:
    """iSpring-style: resource href includes ?loadcss=1."""
    files = {
        "imsmanifest.xml": MANIFEST_12_TEMPLATE.format(
            manifest_id="MANIFEST-QUERY",
            title="SCORM with query entrypoint",
            resource_href="index.html?loadcss=1",
        ),
        "index.html": MINIMAL_INDEX_HTML,
    }
    return _write("query_entrypoint", _make_zip(files), outdir)


def build_hash_entrypoint(outdir: Path) -> Path:
    """Resource href with hash fragment."""
    files = {
        "imsmanifest.xml": MANIFEST_12_TEMPLATE.format(
            manifest_id="MANIFEST-HASH",
            title="SCORM with hash entrypoint",
            resource_href="index.html#section-2",
        ),
        "index.html": MINIMAL_INDEX_HTML,
    }
    return _write("hash_entrypoint", _make_zip(files), outdir)


def build_scorm_2004_rejected(outdir: Path) -> Path:
    """SCORM 2004 detected via namespace only. /scorm/packages/import
    must reject with 'Only SCORM 1.2 is supported'."""
    files = {
        "imsmanifest.xml": MANIFEST_2004_NAMESPACE_ONLY,
        "index.html": MINIMAL_INDEX_HTML,
    }
    return _write("scorm_2004_namespace_only", _make_zip(files), outdir)


def build_malicious_title(outdir: Path) -> Path:
    """Title contains <script>. Import succeeds, launch HTML escapes the
    title so it renders as text. Negative-control for the security fix."""
    files = {
        "imsmanifest.xml": MANIFEST_12_TEMPLATE.format(
            manifest_id="MANIFEST-XSS",
            title='"><script>alert(document.domain)</script>',
            resource_href="index.html",
        ),
        "index.html": MINIMAL_INDEX_HTML,
    }
    return _write("malicious_title", _make_zip(files), outdir)


BUILDERS = {
    "minimal": build_minimal,
    "with_assets": build_with_assets,
    "query_entrypoint": build_query_entrypoint,
    "hash_entrypoint": build_hash_entrypoint,
    "scorm_2004_rejected": build_scorm_2004_rejected,
    "malicious_title": build_malicious_title,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    outdir = Path("docs/test-assets/scorm")
    if cmd == "all":
        for name, builder in BUILDERS.items():
            p = builder(outdir)
            print(f"  wrote {p}")
        return 0
    if cmd not in BUILDERS:
        print(f"unknown fixture: {cmd}. known: {', '.join(BUILDERS)}")
        return 2
    p = BUILDERS[cmd](outdir)
    print(f"  wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))