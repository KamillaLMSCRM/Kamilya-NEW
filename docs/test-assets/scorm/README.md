# SCORM 1.2 — test assets and QA instructions

Generated fixtures + how to do real-package QA.

## What's here

| File | What it tests |
|---|---|
| `minimal.zip` | Smallest valid SCORM 1.2 package — `imsmanifest.xml` + `index.html`. Use as a baseline "does the import → launch → commit flow work?" test. |
| `with_assets.zip` | Multi-asset package (CSS, JS, PNG, sub-folder page). Confirms asset proxy loads all linked files and the iframe sandbox does not block them. |
| `query_entrypoint.zip` | Resource `href` ends in `?loadcss=1` (iSpring quirk). Confirms parser keeps the query string and resolves the bare path. |
| `hash_entrypoint.zip` | Resource `href` ends in `#section-2`. Confirms fragment handling. |
| `scorm_2004_namespace_only.zip` | SCORM 2004 declared via `adlcp2004` namespace only (no schemaversion). Import must reject with "Only SCORM 1.2 is supported". Regression for the `_walk()` fix in commit `5fa0e4c`. |
| `malicious_title.zip` | Manifest `<title>` contains `"><script>alert(document.domain)</script>`. Import succeeds, launch HTML escapes the title so it renders as text. Regression for the html.escape() security fix. |

## Regenerating the fixtures

The fixtures are reproducible — they are produced by
`apps/api/tests/fixtures/scorm_qa_harness.py`:

```bash
cd apps/api
python tests/fixtures/scorm_qa_harness.py all        # write all 6
python tests/fixtures/scorm_qa_harness.py minimal    # one at a time
```

The script is also usable as a library: import the `BUILDERS` dict to
get the raw ZIP bytes for unit tests.

## How to do real-package QA

For full production confidence, you also want to validate against real
authoring-tool outputs. None of these are checked in (they are
proprietary, large, or version-specific):

### iSpring Suite

- Export from PowerPoint via iSpring → "Publish → LMS → SCORM 1.2".
- Default options already use `index.html?loadcss=1` in the resource href,
  which the parser handles. Disable "Optimize for SCORM 1.2 strict mode"
  to also get assets outside the entrypoint directory.

### Articulate Storyline

- "Publish → LMS → SCORM 1.2".
- Pick "Report status to LMS as: Completed / Passed" (not just Visited).
- Storyline bundles everything under `story.html` and a `mobile/`
  sub-folder. Confirm the asset proxy serves both.

### Adobe Captivate

- "Publish → LMS → SCORM 1.2".
- Captivate prepends `index_lms.html` and includes the player shim in
  `scormdriver.js`. Asset proxy must serve `.js`, `.css`, `.swf`, `.png`.

### Chamilo 2.0 export (rare but possible)

- "Learnpath → Export → SCORM 1.2".
- Chamilo wraps everything in a `content/` sub-directory; the manifest
  references `content/index.html`. Confirms sub-folder resolution.

### Manual flow

1. Upload the ZIP via `/courses` (admin) or via SCORM Import tab.
2. Click "Запустить" on the course card → iframe loads.
3. In the SCORM player, click "Complete lesson" (or whatever your
   content triggers).
4. Backend should: receive `cmi.core.lesson_status=completed`,
   transition enrollment to `completed`, issue a certificate.
5. Verify the course appears as completed in `/my-courses` and in the
   admin training log with `computed_status=completed` and
   `progress_percent=100`.

### Negative cases

- SCORM 2004 package → import returns 400 with a Russian error message
  mentioning "Only SCORM 1.2 is supported". Confirmed by `scorm_2004_*`
  fixtures above.
- Manifest with `<resource href="../../etc/passwd">` → 400 "unsafe
  launch path".
- Manifest referencing a file not in the ZIP → import succeeds but
  `entrypoint_exists=False` (the runtime iframe will 404).
- Title with HTML special chars → renders as text, not as script.