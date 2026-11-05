# Narrow A review notes — 2026-11-05

Candidate: `feat/whole-lms-visual-v2`, base `739cc5fd4a7dd5a384662918366fcceec6611ddf`,
linked worktree `learning-visual-prod-20261102`. Local candidate only; no push,
deployment, flag activation or formal release approval.

Independent reviewers were asked not to edit files. Both used
`deepseek-v41-flash-tensorfold/DeepSeek-V4.1-Flash-1017` (effort default);
billing is unknown and is not asserted as zero. Root integrated corrections and
re-ran the affected checks.

## Critic

Verdict before corrections: `BLOCKING FINDINGS`.

| Severity | Finding | Resolution |
|---|---|---|
| Blocking | Explicit `job_id` could override a newly started generation on reload; a later restore could replace the displayed failure context | Fixed: hook keeps an applied explicit job and page removes `job_id` when starting/retrying/resetting; regression test added |
| Major | Dashboard/training-log catalogue reads were silently capped at 20 courses | Fixed: reads request `per_page=100`; dashboard and selectors show a first-100 notice when the page is full; A0 updated |
| Major | Course URL filter was one-way; same-route/back navigation could diverge from state | Fixed: catalogue state synchronizes from the query; deep-link test retained |
| Major | Job stage labels used a false “preparation” fallback for real stages | Fixed: canonical stage/status labels added; unknown fallback is “unknown stage”; regression test added |
| Major | Jobs API failure rendered a confirmed-empty generation list; mandatory failure hid metrics instead of showing unavailable | Fixed: jobs show an unavailable message; mandatory metrics show `—`; regression test added |
| Minor | Weak-question hint had `order-last`, so visual and DOM order differed | Fixed: hint moved after the metric group in DOM order |
| Major | A3 Back relies on the journal’s existing `router.replace` pattern | Closed in independent root review: discrete choices push history; Back/Forward browser regression for journal and catalogue |
| Minor | C0 said the reviewer-safe DTO strips provenance | Corrected: the backend reviewer projection retains source refs/validation; the frontend `projectReviewSnapshot` drops them before rendering |
| Minor | A0 described admin as read-only on approval | Corrected: admin may configure the policy and read requests/reviews |
| Major | A4 dirty guard covers lesson text, not module-title edits | Closed in independent root review: workspaceDirty covers module title, navigation, readiness and publish; Cancel retains title; revert-to-saved unit regression |
| Minor | Evidence matrix was partial | Improved: editor added to the four-width matrix; axe extended to documents and training-log; locale dates asserted |

## Designer

Verdict before corrections: `READY FOR ROOT REVIEW`, with major corrections
recommended.

| Severity | Finding | Resolution |
|---|---|---|
| Major | Dashboard used “preparation” for real job stages | Fixed with canonical stage labels and unknown fallback |
| Major | Jobs unavailable looked like a confirmed empty list | Fixed with an unavailable-specific message |
| Minor | More than five relevant jobs are silently omitted | Deferred: visible list remains bounded; counts are shown separately and the full list is not claimed |
| Minor | Weak-question hint order | Fixed |
| Minor | Course URL state could diverge on same-route navigation | Fixed with query synchronization |
| Minor | Empty/failed course catalogue still told the user to select a course | Fixed: loading/empty/error hints are conditional |
| Minor | Candidate course-list failure had no retry; disabled invite had no reason | Fixed: course-list retry and visible name-required hint added |
| Minor | Evidence/documentation trail stale | Fixed: final app run recorded below and in `TEST_RUN_LEDGER.md`; Stage 1 status updated; this note added |

## Final verification

Final source state includes the review corrections and the last QA fixes:
deterministic RU/KK `dd.MM.yyyy` candidate dates (Chromium's `kk-KZ`
short-date default is ISO-like; EN keeps `dd/mm/yyyy`), a foreground token for
the training-log CSV-scope note (muted text measured 4.31:1 on the tinted
panel), and missing-job notice reset when the `job_id` query is removed.

- Full web suite on the final source: 188 files / 1611 tests PASS
  (`vitest run --maxWorkers=2`, 2026-11-05).
- `npm run typecheck` and `npm run lint` PASS.
- Production build PASS: 67/67 pages with
  `NEXT_PUBLIC_API_URL=http://127.0.0.1:3027`.
- Built-app Narrow A Playwright PASS 13/13 in 29.2 s against that rebuilt
  candidate on loopback3027. Tooling: Playwright 1.61.1 with Chromium
  `148.0.7778.96` (revision 1223, explicit executable path).
- Axe on dashboard, documents, training-log and candidate assessment: no
  serious or critical findings.
- 40 screenshots retained in
  `docs/testing/screenshots/narrow-a-20261105/` across 390/768/1270/1440,
  RU/KK/EN, candidate states, dark/reduced-motion, deep links and dirty guard.
  Candidate state captures are full-page. The only equal-hash pairs are the
  intentional axe/visual pairs (`1440-candidate-assessments.png` ↔
  `1440-candidate-axe.png`, `1440-training-log-axe.png` ↔
  `1440-training-log.png`), captured from the same frame before the axe run.
- The loopback server was stopped after the run; no external network, DB or
  provider traffic is part of this evidence.

## Historical gaps from the first application run

- CodeGraph preflight is `NOT_READY` in this checkout; A0/C0 use bounded source
  inspection.
- Playwright 1.61.1 expects Chromium 1228; QA used explicit Chromium 1223.
- Browser evidence is synthetic, methodologist-focused and local loopback only.
  Admin/student/superadmin boundaries were source-checked, not browser-run.
- Axe covers dashboard, documents, training-log and candidate assessment; editor
  and staff are source/DOM-checked, not axe-checked in this run.
- No real-device/assistive-technology, zoom/scale, long-string or user-research
  acceptance; these remain open external gates.
- No backend/DB/RLS/provider mutation, push, deployment, flag activation or
  release/tag.

## Independent root review and repair — 2026-11-05

Root independently inspected all17 OCR-previewed application/config files;
behavioral tests, fixtures and docs were reviewed outside OCR's default test/doc
exclusions. OCR delegate preview/rules used no external LLM. CodeGraph preflight
remained NOT_READY (missing checkout runtime); bounded source fallback used.
Original audit/prototype and owner corrections preserved.

Confirmed defects were reproduced, not accepted as deferred: Back reached
about:blank instead of the prior journal filter; module-title navigation showed
no dialog; stale explicit job restore replaced a new job in a deterministic unit
test. All three now have regressions and fixes.

First100: full-page course summaries are unknown (`—`), not tenant totals.
99/100 boundary tests cover complete vs possibly truncated input. Jobs explicitly
describe loaded-list scope and max5 visible items. Weak-question copy no longer
claims journal filters fetch missing catalogue rows. Candidate course selector
also discloses first100. This is honest bounded functionality, not full pagination.

The previous Chromium environment gap is no longer present: this review used
the default installed revision1228, Chromium149.0.7827.55, Playwright1.61.1;
no browser installation or revision substitution was needed.

New evidence is kept separately in
`docs/testing/screenshots/narrow-a-independent-20261105/`; exact final commands,
results and residual limits are in RUN-20261105-NARROW-A-INDEPENDENT-02 in the
existing TEST_RUN_LEDGER.md. Earlier run results above remain historical.

Additional source inspected during closure: shared AsyncOperationStatus,
GenerationProgressPanel and authorWorkspaceCopy. Expanded built-page axe found
real generation recovery contrast issues (4.31/4.44/3.34:1); corrected foreground
tokens/message opacity, then verified on the rebuilt candidate. Readiness copy
now describes course changes rather than falsely calling module-title edits
lesson edits.

Final browser closure:21/21 Narrow A tests PASS36.5s, author-neighbor2/2 PASS3.4s.
All8 touched surfaces axe: dashboard, courses, documents, training-log,
candidate-assessments, staff, course editor, failed-generation recovery; zero
serious/critical findings for the tested states. The suite covers four widths,
candidate RU/KK/EN and dark/reduced-motion sample, active-role denial including
assigned-but-inactive methodologist, admin read-only report controls, first100
scope and both dirty module/lesson paths. These are not all viewport×locale×role
combinations, backend authorization or a complete WCAG audit.

52 final PNGs retained separately (50 Narrow A plus2 author-neighbor); root
visually inspected desktop first100 scope, module-dirty Cancel, mobile editor,
staff and generation recovery captures. Previous40 screenshots preserved.

Residual external gates: backend tenant/RLS negative integration, real-device/AT,
full locale/dark/zoom combinations, user-task measures and release/CI/runtime
readback. First100 and five visible jobs remain explicitly bounded; no complete
pagination is claimed. The local mismatches raised for this packet are closed;
the local verdict is not release GO. No new agent/provider inference, browser
installation, commit, push, deployment or real tenant mutation in this review.
