# CI tenant gates and Docling OCR

1. Reproduce the current GitHub Actions failures and inspect every flagged query against the tenant boundary.
2. Add explicit tenant scoping to authenticated and kiosk queries; document only the genuinely public certificate lookup exception.
3. Verify the Docling service configuration and run a scanned-document OCR smoke test; enable OCR explicitly if the current converter does not.
4. Run focused tests and the repository CI gates, update the Graphify index, then commit and push.
5. Wait for green GitHub Actions, deploy the resulting revision to production services, and repeat health/OCR smoke checks.

## Step 1 — diagnosis

**What changed:** Confirmed GitHub Actions run `29997030091` failed only in
`Release and tenant security gates`. Reproduced nine stale/unscoped ORM
lookups. Inspected the Docling converter and production endpoint.

**Checks:** The public `docling.kml.kz` endpoint fails TLS negotiation with
`TLS alert internal error`; the host resolves directly to `173.249.51.164`.
The saved VPS password is rejected and no local private key is available.

**Status:** ✅ done

## Step 2 — tenant isolation and explicit OCR

**What changed:** Added direct tenant predicates to AI rewrite, kiosk,
certificate, and quiz queries. Replaced the line-number CI allowlist with
review annotations located at the three genuinely pre-tenant/public lookups.
Configured Docling PDF conversion with `do_ocr=True`, Tesseract CLI
`kaz,rus,eng`, and table recognition. Health now exposes the OCR engine and
language configuration.

**Checks:** `tenant-gate.sh` reports 142 checked queries and zero violations.
The Docling configuration has hermetic unit coverage.

**Status:** ✅ done

## Step 3 — local verification

**What changed:** Added unit coverage for converter and health configuration.

**Checks:** 36/36 no-DB unit tests pass; focused certificate/kiosk/Docling
tests pass 16/16; shell quality, release contract, compileall, and diff checks
pass. DB-backed tests cannot start because local PostgreSQL is unavailable;
the GitHub workflow provisions its own pgvector PostgreSQL container.

**Status:** ✅ done

## Step 4 — publish and production

**What changed:** Corrected the VPS target to the credentials selected by
`VPS_URL` and `vps_root_password`. Backed up the previous service and Caddy
configuration under `/opt/kamilya-backups/docling-20260723-150131`. Added the
`docling.kml.kz` Caddy virtual host and obtained a valid public TLS certificate.
Installed Tesseract with Kazakh, Russian, and English language data. Protected
`/convert` with a shared API key while leaving `/health` public. Configured
Render to use `https://docling.kml.kz` and the matching key.

During the Render environment update, diagnosed a replace-all pagination
failure that had omitted variables after the first 20 entries. Recovered the
original production values from the still-running Render instance, including
the existing master encryption key, and restored all 45 service variables.

**Checks:** Commit `d94ad20` passed GitHub Actions run `30010487198`. Render
deployment `dep-d9h1fi3bc2fs739g99og` is live and API health returns `ok`.
Docling and Caddy are active. Public Docling health reports
`tesseract-cli` with `kaz,rus,eng`; unauthenticated conversion returns HTTP 401.
An authenticated three-page image-only PDF returned all English, Russian, and
Kazakh marker text, including `ҚАУІПСІЗДІК`, with all three pages detected.
The conversion completed on CPU in approximately 31 seconds and the service
used about 1.2 GiB RAM.

**Status:** ✅ done
