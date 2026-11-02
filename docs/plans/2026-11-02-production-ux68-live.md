# Production UX68 live acceptance

Owner instruction: exercise all new UX flows in production, especially assignment and learner completion; fix defects, then resume the generation engine.

Runtime under test: frontend 076dba752432b4d161e0a419660ff277bc4c3e3d (0.11.68); API/workers 7c35c798d9ff4e44183a1e499f1b1c1a7cc2fe16. Verify drift before release changes.

Allowed fixture: permanent tenant 83552ce6-8058-4561-abe3-cfbda14e030a, slug kamilya-production-smoke; ordinary methodologist and student credentials from canonical primary .env, in memory only. Tenant notes marker KAMILYA_SYNTHETIC_SMOKE_V1 confirmed in actual superadmin UI. Customer data, historical completions, roles, provider plans and limits remain outside mutation scope.

Owned new course: 8d2ef28b-a4e9-4a72-bcc4-3075094b877e; marker KAMILYA_UX68_LIVE_20261102. Created manually through production UI, no model calls or emails. Retain legitimate completed history; do not hard delete.

Matrix (all initially NOT_RUN):

1. Author editor: two lessons, Markdown toolbar/preview, dirty navigation cancel/discard, save/reload, publication guard.
2. Question editor: creation, unsaved Back/Forward preservation, save/reload and valid answers.
3. Source inspection: actual existing fictional source, original download and accurate processing status.
4. Review: frozen snapshot identity, cancel/confirm separate decision, publication remains separate.
5. Assignment: exact owned course and synthetic learner, preview/cancel, explicit confirmation, persisted receipt, duplicate exclusion; no outbound messages.
6. Reader: lesson outline, keyboard and help/history, direct exit, progress restoration after reload.
7. Quiz: incomplete submit disabled, real submit/result, test success not course completion, retry and full course completion.
8. Evidence: confirmation state, actual PDF/certificate downloads and public verification where enabled.
9. Journal: exact new result, filters/history, summary/CSV agreement, pre-existing history preserved.
10. Responsive: desktop and mobile equivalents of the eight original UX browser scenarios; overflow, navigation and control accessibility.

Evidence: .release-evidence/ux68-live/; append exact outcomes and limitations to docs/testing/TEST_RUN_LEDGER.md. Existing intercepted local 16-browser tests are regression evidence, not production acceptance. Screenshots must be secret-free. No fake API, forced client state, limiter bypass or uncertain model replay.

After UX acceptance, resume the held DEV engine job via reviewed read-only reconciliation, fix saved causes, then full three-course Luna acceptance, DeepSeek and separate production release.

## Fresh observations

- Ordinary methodologist login, tenant marker, manual course/module/two lessons and two four-choice quizzes: actual production UI.
- Dirty lesson blocks publication; next-lesson dialog Cancel preserves text; save and reload recover exact content. Markdown preview renders headings/list/emphasis.
- Unsaved question text, explanation and all four choices survive browser Back/Forward and save successfully.
- Approval request failed after freezing revision 51b35fc7-ba58-4e59-910c-69542f4de6c1 (hash 7ef6ad642a5338cb2097cde38f1b8fbb2c17859a5a189f786236ece0b83d13c1). Independent GET confirms one revision and zero requests/enrollments. No blind resubmission.
- Canonical VM126 trace identifies RuntimeError at course_approval/service.py:262 -> integrations/crypto.py:41: missing MASTER_ENCRYPTION_KEY. Host runtime.env, active green and retained blue API all lack the key. CT125 BEGIN READ ONLY aggregate inventory confirms zero integration/workflow ciphertext rows. No existing ciphertext is overwritten or re-encrypted.
- Canonical release-plane preflight confirms exact green7c35 and blue00e rollback, no rollout lock, active/reserved tasks0 with3 responders, expected timers active. Additive root-only key provision/same-image recreation is in progress; do not run a duplicate.
- CodeGraph SOURCE_FALLBACK: pinned runtime absent in this linked checkout. Exact ApprovalRequestModal -> courseApproval client -> router -> service -> integrations.crypto seams confirmed by bounded source plus actual API trace; no tool installation/rebuild during the incident.
- Read-only API helper initially omitted required Origin and received403; corrected to canonical Origin before one successful identity-bound readback. This harness error is separate from the actual browser500.

## Superseding live readback — frontend69

Production frontend0f31ffd5812f1751fc0f1c98f716e65580b1b2ae deployed by canonical REL-UX69-WEB-20261102 RELEASE_OK; API7c35 unchanged. DEV7a4158e2 ordinary reviewer cancellation/confirmation/receipt passed. Production requesta023f2e1 ordinary reviewer completed and approved, owned course published. Missing encryption key repair and rollback key parity PASS; preserve protected key recovery and SMTP path.

Assignment cancel leaves zero, confirm creates exactly one; reload retains it and removes the learner from candidates. Delivery personal_link, no mail. Wrong PIN rejected once; actual QA student then enters. First test0% with2attempts left, retry100%, course remains50%; second test100%, course only completes through separate Finish course. Completion survives reload. Certificate35aff250-079f-45d3-a3ba-faf2641aafc2 / KML-2026-3A8E6AE19801 valid on public verification. Evidence event1697fc8e-7873-467f-9508-afe9eb507505 PDF2pages and certificate1page downloaded and all pages visually checked. Signature/documentary confirmation remains pending by design; no fake signature or email sent.

Journal CSV34rows: all33baseline rows exactly unchanged, one new completed course100%, three quiz attempts (first fail/retry plus second test). No customer writes or model calls. True390px reader/quiz/outline and question Back/Forward checked, root overflow0. The earlier direct-goto browser-history failure was harness setup, superseded by actual menu navigation; initial editor mobile observation after DEV tab opened was on wrong selected tab and must be repeated with per-tab emulation before claiming that cell.

Two additional actual defects require70: aggregate review grading scope (APPROVAL-006) and outline URL/reload (COURSE-PLAYER-NAV-002). Same-tab draft recovery independently reviewed; cross-device persistence deliberately not claimed. New tests63pass. Full final70 regression and DEV/production readback pending.

## Final production70 acceptance

Exact96a76b8f /0.11.70 and API7c35 unchanged. Canonical controller RELEASE_OK, source/master/tag/CI/native provenance exact.1548full tests,95combined DEVfocused, types/lint, independent source audit, DEV245706ad RELEASE_OK and actual browser acceptance.

| Cell | Actual result |
|---|---|
| Author | Desktop and true390px2L2Q, Markdown toolbar/preview, dirty guard, dialogCancelDiscard, save/reload PASS |
| Question | Desktop and true mobile actual menu Back/Forward recovers draft; save and explicitdiscard PASS |
| Source | Fictional qa-source56 exact original2098bytes/SHA9ec7fb5e... downloaded;2/2 metadata, no fake extraction PASS |
| Review | Ordinary-account route recovered69;70actual2quiz cumulative1/2then reload then2/2 100%;Cancel/Confirm snapshot72bae2ea...PASS |
| Assignment | Exact owned published course/student;Cancel0/Confirm1,reload1,duplicate excluded; personal-link/no mail;new catalog link preservescourse PASS |
| Reader | Actual student2lessons;helpopenClose without model;70outlineURL/reload/BackForward,390pxoutline PASS |
| Quiz | Empty disabled,first0%/2remaining,retry100%,course50%;second100%;separate FinishCourse PASS |
| Evidence | Completion persists;2pageconfirmation+1pagecertificate rendered/visually checked;publicvalid KML-2026-3A8E6AE19801 PASS. Documentary signature pending intentionally; no fake confirmation |
| Journal |34rows,prior33exact unchanged;post70all34exact unchanged;filters/history/CSVcounts matched PASS |
| Visual/responsive | New actual productioncatalogowncoursesfirst;search/empty/reset/templates/actionedit/assignment/deleteCancel,390pxreviewdialog/controls/overflow0 PASS. DEV360/390 computedtheme/dark temporaryoverride restored; local33intercepted scenarios remain regression evidence, not33live flows |

Separate unassigned review QA draft04e61de2/source72bae2ea...remains unpublished. No additional learner histories, no outbound mail, no model calls, no customer writes. Retain both owned courses and actual completed history. Reports/screenshots/CSV/technical cleanup evidence in .release-evidence/ux68-live. Cleanup67 preserved current69/rollback68/extra359/299 and verified offhost restore;70nowcurrent,69and68retained. Engine is not accepted by these manual courses.
