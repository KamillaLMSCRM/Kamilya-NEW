# Executive client HTML presentation — 2026-07-23

## 1. Confirm product evidence and safe demo boundaries
**What I will do:** Read the current handoff, product context, internal documentation, ADR-0012 and relevant plans; use Graphify before code exploration; identify only implemented, read-only flows suitable for executive screenshots.
**Verification:** Documentation references recorded below; no secret values, write actions, or AI jobs used.
**Status:** ✅ done

**Evidence reviewed:** `AGENTS.md`, `PROJECT.md`, `docs/CODEX_HANDOFF.md`, `docs/PROJECT-CONTEXT.md`, `docs/PROJECT_INTERNAL_DOCUMENTATION.md`, `docs/adr/0012-rbac-admin-vs-methodologist.md`, `docs/LESSONS.md`, and `docs/plans/2026-07-09_p0_p1_product_hardening_plan.md`. Graphify was run in `--code-only` mode after semantic indexing reported no configured LLM key; it identified the student dashboard, training-log and role-navigation implementation paths. Product claims in the deck were cross-checked against the current product documents and the authenticated demo.

## 2. Capture and prepare authentic evidence
**What I will do:** Use the authorized browser session and existing demo data to capture role-appropriate screens. Mask/crop any personal or confidential data while preserving authentic UI.
**Verification:** Each asset is checked visually and its non-secret source URL, role and date are recorded privately in this plan.
**Status:** ✅ done

**Verified read-only demo sources and final assets (2026-07-23, Chrome capture):**

- `https://app.kml.kz/staff?tab=structure` — learning-management role — `assets/staff-structure.png`; loaded organizational-structure view, no personal data.
- `https://app.kml.kz/courses` — learning-management role — `assets/course-library-published.png`; literal crop of published demo course cards, without internal smoke-test entries.
- `https://app.kml.kz/admin/training-log` — learning-management role — `assets/training-log.png`; literal crop of summary cards and filters, excluding the row with personal data.
- `https://app.kml.kz/certificates` — learner role — `assets/certificate-verification.png`; literal crop of the certificate-number verification form. The test number and returned identity were masked; the asset is framed only as verification capability, not as a learner-completion claim.

Weak loading-state, empty-state, personally identifying, and internal-test captures were deleted. No generated or reconstructed UI appears in the client deck.

## 3. Build the portable Russian executive deck
**What I will do:** Create a 10–14 slide local HTML/CSS/JS presentation with 16:9 layout, navigation, progress, print styles and locally stored assets. Claims will be tied only to verified product behavior; pilot indicators will be framed as measures to establish.
**Verification:** Open locally without a build server; inspect asset paths and browser console.
**Status:** ✅ done

**What I did:** Rebuilt `deliverables/kamilya-executive-presentation/index.html`: 12 Russian executive slides, four privacy-safe authentic product captures, keyboard and button navigation, progress, 16:9 desktop layout, responsive rules, and print styles. Client-facing language uses business Russian only: no source-control policy, infrastructure, repository, role-code, or implementation references. Pilot measures are explicitly framed as measures to establish.

## 4. Visual QA and handoff
**What I will do:** Review every slide at presentation resolution and one smaller viewport; test controls and print layout; record results and deliver paths, outline, changed files and limitations.
**Verification:** Browser screenshots and a completed plan log.
**Status:** ✅ done

**Checks completed:** local temporary HTTP viewer at `http://127.0.0.1:4173/index.html`; visual review of all 12 slides at 1600×900 and 1024×768; keyboard arrow navigation, buttons and progress bar; all local image paths; no text overflow or broken asset observed. A print PDF generated from the browser contains exactly 12 nonblank 16:9 pages (1152×648 pt), rendered and visually reviewed as a 12-page contact sheet. Print CSS explicitly applies `flex-direction: column` to every printed slide and removes the last-page break.

**Kazakhstan audience audit:** The deck is written for middle and senior management in Kazakhstan in neutral Russian B2B language. It contains no Russia-specific legal claims, regulatory assertions, currency, market assumptions, examples, or visual cues. Product claims remain limited to verified implemented behavior; no Kazakhstan legal/compliance claim is made.
