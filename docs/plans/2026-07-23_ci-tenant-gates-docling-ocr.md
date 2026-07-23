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
Configured Docling PDF conversion with `do_ocr=True`, EasyOCR `ru,en`, table
recognition, and an OCR-capable dependency extra. Health now exposes the OCR
engine and language configuration.

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

**What changed:** Pushed `afab37a`. GitHub Actions run `30008558066`
completed successfully across all seven jobs, including the pgvector-backed
pytest/coverage job. Render deployment `dep-d9h0t1rtqb8s73ed6a40` is live on
that revision and `/health` returns HTTP 200.

**Production exception:** The standalone Docling service cannot yet receive
the OCR revision. Its public hostname fails TLS negotiation and the saved VPS
password is rejected; no valid private key is present on this workstation.
The repository-side OCR configuration is tested, but production OCR must not
be reported as enabled until VPS access is restored, dependencies are installed,
the service is restarted, and an image-only PDF smoke test returns its text.

**Status:** ⚠️ partial — API/CI complete; Docling VPS access required
