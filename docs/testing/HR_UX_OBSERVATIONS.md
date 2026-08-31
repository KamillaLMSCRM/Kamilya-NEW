# Kamilya HR and Methodologist UX Observations

This append-only journal stores sanitized workflow findings produced by the
persistent Kamilya Test & Evidence Runner while acting as an ordinary HR employee,
tenant administrator, methodologist, or learner. It is not a product backlog,
runtime source of truth, or authority for implementation.

Rules:

- append only; correct an accepted entry with a new linked entry;
- one finding per stable ID in the form `UX-YYYYMMDD-NNN`;
- do not duplicate an open finding unless new evidence changes its severity or
  scope;
- never store secrets, `.env` values, PII, contact data, tenant payloads, or raw
  production logs;
- identify synthetic tenants and users only with safe descriptive labels;
- root independently reviews findings before promotion to backlog, tests, docs,
  code, `ERRORS.md`, or a reusable skill.

Entry template:

```text
## UX-YYYYMMDD-NNN — Short title

- Related run: `RUN-ID`
- Environment / exact SHA: `environment` / `sha`
- Route / role: `route` / `role`
- State: `OPEN | ACCEPTED | FIXED | NOT_ACTIONABLE | BLOCKED`
- Severity: `LOW | MEDIUM | HIGH | CRITICAL`
- Observation: what the user saw or could not understand
- User impact: likely consequence for an ordinary employee
- Evidence: sanitized browser/API/test evidence and evidence label
- Recommendation: smallest product or documentation improvement
- Verification gate: exact check that closes the finding
```

## UX-20260828-001 — Group-targeted program publication returns not found

- Related run: `RUN-20260828-PLUS-FULLFLOW-02`
- Environment / exact SHA: `kz-production` / `f71da2a0af9da4c94c82622450cc78daa7ad22b8` (root-supplied runtime; packet SHA differed)
- Route / role: `/learning-paths` / methodologist
- State: `BLOCKED`
- Severity: `HIGH`
- Observation: A one-course program with one existing synthetic group selected as its audience failed both publication and draft save with visible `Не удалось сохранить` and `404: Learning program not found`; the program list remained empty.
- User impact: A methodologist cannot use the normal group-targeted learning workflow, so course distribution to a group is blocked even though individual assignment works.
- Evidence: Two materially identical production UI failures after the publish and same-object draft-save actions; `RUNTIME-DERIVED`.
- Recommendation: Restore the learning-program create/save identity contract and verify publication creates assignments for the selected group without requiring a nonexistent program ID.
- Verification gate: Create one single-course program targeting one existing synthetic group, save it, publish it, and read back one program plus the expected group assignments with no 404 or 5xx.

## UX-20260828-004 — Published learning program does not complete group assignment

- Related run: `RUN-20260828-PLUS-FULLFLOW-02` narrow retest
- Environment / exact SHA: `kz-production` / `8f53120a32f0fd91013968d45e9464d706645210` (`PROVIDER-CONFIRMED`, root runtime readback)
- Page/role/action: `/learning-paths`, methodologist, publish one existing-course program targeting one existing synthetic group
- Observed behavior: Program changed to `Опубликована`, but the immediate assignment step displayed `Программа опубликована, но назначение не выполнено` and `Internal server error`; current assignments showed none.
- User impact: Methodologist can publish a program but cannot rely on the same flow to distribute it to the selected group.
- Severity: HIGH
- Evidence: one visible production UI failure after successful draft save and publish; `RUNTIME-DERIVED`.
- Expected behavior: Publish should create and read back the selected group assignment, or provide a recoverable explicit assignment action with a useful error.
- Suggested product correction: Trace the post-publish group-assignment transaction and return a stable, actionable error; add an end-to-end regression covering publish plus group assignment.
- Status: OPEN / escalated to root after first failure; no identical retry performed.

## UX-20260828-005 — Manual confirmation requires signed file for completed learner

- Related run: `RUN-20260828-PLUS-FULLFLOW-02`, fixed-release retest
- Environment / exact SHA: `kz-production` / `4f694f02a99eb0215bc9b8f352be886fb10a75f8` (`PROVIDER-CONFIRMED`)
- Page/role/action: `/training-log`, methodologist, completed synthetic learner result
- Observed behavior: Result displayed 100% progress and 100% best score but remained `Ожидает подтверждения`; UI required a signed PDF/JPEG/PNG scan, up to 10 MB, before confirmation/export/certificate state can advance.
- User impact: Completion is recorded, but no certificate is available without a separately prepared signed business document.
- Severity: MEDIUM
- Evidence: visible training-journal row and upload gate; `RUNTIME-DERIVED`.
- Expected behavior: Clearly explain the manual confirmation lifecycle and certificate outcome, including a safe no-email path.
- Suggested product correction: Provide explicit methodologist guidance and a non-fabricating demo-safe confirmation workflow or clearly label certificate issuance as pending external signed evidence.
- Status: OPEN

## UX-20260828-002 — No-email learner completion has no electronic certificate path

- Related run: `RUN-20260828-PLUS-FULLFLOW-02`
- Environment / exact SHA: `kz-production` / `f71da2a0af9da4c94c82622450cc78daa7ad22b8` (root-supplied runtime; packet SHA differed)
- Route / role: `/courses/quiz/*`, `/certificates` / learner via personal link/PIN
- State: `OPEN`
- Severity: `MEDIUM`
- Observation: The synthetic learner completed all six lessons and passed all six tests at 100%, but each result remained `Ожидает подтверждения`; the Certificates page showed no certificate. The UI offered manual PDF confirmation because the learner has no email.
- User impact: A demo or ordinary learner without email can complete training, but cannot receive an electronic certificate through the tested path and must use a manual confirmation process.
- Evidence: `6 из 6 уроков (100%)`, six visible `100%` test results, Certificates page with no issued certificates, and the no-email confirmation explanation; `RUNTIME-DERIVED`.
- Recommendation: Provide an explicit no-email certificate state and a clear methodologist-controlled issuance/download path, or explain the manual confirmation lifecycle in the learner and methodologist views.
- Verification gate: Complete the same no-email personal-link journey and verify an intentional certificate/manual-confirmation outcome is visible in both learner and methodologist views.

## UX-20260828-003 — Public health identity was unavailable in browser verification

- Related run: `RUN-20260828-PLUS-FULLFLOW-02`
- Environment / exact SHA: `kz-production` / `f71da2a0af9da4c94c82622450cc78daa7ad22b8` (root-supplied runtime)
- Route / role: public `/health` / read-only browser check
- State: `BLOCKED`
- Severity: `MEDIUM`
- Observation: Direct browser navigation to the public API health endpoint was blocked by the browser client, so the runner could not independently verify the expected SHA and deployment environment from the browser surface.
- User impact: A browser-only E2E report cannot independently bind the tested UI session to the exact production release without separate runtime evidence.
- Evidence: Browser navigation was blocked before a response body could be read; root supplied independent runtime identity evidence; `NOT VERIFIED` for browser health.
- Recommendation: Keep an approved public, browser-readable health/readback route or include an equivalent release identity signal in the authenticated application diagnostics surface.
- Verification gate: Read public health successfully from the allowed browser surface and confirm exact release SHA, `kz-production`, and expected service identity.

## UX-20260828-006 — Resolution of program save and publish 404

- Related finding: `UX-20260828-001`
- Related run: `RUN-20260828-PLUS-FULLFLOW-02`
- Environment / exact SHA: `kz-production` / `8f53120a32f0fd91013968d45e9464d706645210` (`PROVIDER-CONFIRMED`)
- State: `FIXED`
- Evidence: The preserved draft accepted the existing published course, saved with `Траектория сохранена`, and published as one v1 one-course program. No additional duplicate was created; `RUNTIME-DERIVED`.
- Resolution: Program detail is built while the transaction-local tenant RLS context is active and committed only after the response has been materialized.
- Verification gate: `PASS`; save and publish succeeded through the normal methodologist UI on the exact fixed release.

## UX-20260828-007 — Resolution of impersonated group assignment failure

- Related finding: `UX-20260828-004`
- Related run: `RUN-20260828-PLUS-FULLFLOW-02`
- Environment / exact SHA: `kz-production` / `4f694f02a99eb0215bc9b8f352be886fb10a75f8` (`PROVIDER-CONFIRMED`)
- State: `FIXED`
- Evidence: Exactly one normal UI assignment attempt returned `Программа назначена`; the published program read back two active synthetic group assignments. Post-release API evidence recorded one successful assignment request and zero assignment 500, author-tenant, foreign-key, or integrity errors; `RUNTIME-DERIVED`.
- Resolution: Platform-superadmin impersonation no longer writes the platform user as a tenant-owned assignment author. Normal tenant methodologists retain their author identity, while the real impersonating operator remains attributable through the impersonation audit trail.
- Verification gate: `PASS`; group assignment and immediate readback succeeded without duplicate programs or assignments.

## UX-20260829-006 — Superadmin audit verification requires separate credentials

- Related run: `RUN-20260829-PLUS-READONLY-0bd6ecc`
- Environment / exact SHA: `kz-production` / `0bd6eccce1fe841595a2842034e1396643ac1f5e` (`PROVIDER-CONFIRMED`)
- Page/role/action: Plus methodologist workspace; visible superadmin handoff for read-only platform audit navigation
- Observed behavior: Handoff opened platform operator login requiring email and password; the existing signed-in session did not expose `/admin/audit`.
- User impact: Platform audit filter acceptance cannot be completed from the approved tenant session without another authorized session.
- Severity: MEDIUM
- Evidence: visible credential login with no authenticated continuation; `RUNTIME-DERIVED`.
- Expected behavior: Provide an explicit authorized session handoff or documented safe route for audit verification.
- Suggested product correction: Preserve an approved platform-session handoff for audit-only checks without credential re-entry.
- Status: BLOCKED / NOT VERIFIED

## UX-20260829-007 — Four requested safe checks remained unverified

- Related run: `RUN-20260829-PLUS-READONLY-0bd6ecc`
- Environment / exact SHA: `kz-production` / `0bd6eccce1fe841595a2842034e1396643ac1f5e` (`PROVIDER-CONFIRMED`)
- Page/role/action: Plus methodologist read-only acceptance continuation
- Observed behavior: The bounded session did not safely reach the employee termination modal, assignment email-mode explanation, completed learner final screen, or lesson-editor resize control; no mutation or workaround was attempted.
- User impact: These four acceptance criteria remain unverified and require a subsequent authenticated methodologist session.
- Severity: MEDIUM
- Evidence: `NOT VERIFIED`; no product behavior inferred.
- Expected behavior: Each control should be independently inspectable without saving or submitting.
- Suggested product correction: None until the controls are observed in a valid session.
- Status: NOT VERIFIED

## UX-20260831-008 — Methodologist navigation follows HR tasks

- Related run: `RUN-20260831-METHODOLOGIST-DEV-13E43E4`
- Environment / exact SHA: `development` / `13e43e497ef76b9e6909e32c0aaa9f85c2da7829`
- State: `FIXED`
- Severity: `HIGH`
- Observation: Staff and employee groups were previously separated by unrelated functions, while page, menu, and help terminology also diverged.
- User impact: An ordinary HR methodologist had to understand the product's internal module structure instead of following the sequence create, assign, manage people, and review results.
- Resolution: The sidebar now groups courses/materials, learning assignment, employees/candidates, and results. Staff and groups are adjacent. Page titles and help use `Создать курс из материалов`, `Тесты и вопросы`, `Тестирование кандидатов`, `Подтверждение обучения`, and `Сроки хранения результатов` consistently.
- Evidence: all 13 methodologist routes and help dialogs passed normal-browser acceptance on the exact dev SHA; `RUNTIME-DERIVED` and `PROVIDER-CONFIRMED`.
- Verification gate: `PASS`.

## UX-20260831-009 — Course generation has no recoverable rate-limit path

- Related run: `RUN-20260831-METHODOLOGIST-DEV-13E43E4`
- Environment / exact SHA: `development` / `13e43e497ef76b9e6909e32c0aaa9f85c2da7829`
- State: `BLOCKED`
- Severity: `HIGH`
- Observation: After thematic analysis, structure recommendation, and duplicate-source reason selection all succeeded, two bounded generation submissions separated by a substantial pause returned only `Rate limit exceeded`.
- User impact: The methodologist completes the full setup but cannot tell whether the limit is per minute, daily, tenant-wide, or recoverable, and cannot estimate when work can continue.
- Evidence: two visible `429` outcomes with no created job; no third unchanged retry; `RUNTIME-DERIVED`.
- Recommendation: Return a localized explanation with limit scope, remaining allowance, and `retry_after`; display the next safe retry time and prevent an early repeat client-side.
- Verification gate: submit one approved synthetic job below quota, read back its job ID, then exhaust a disposable quota and verify deterministic `retry_after` guidance without duplicate job creation.

## UX-20260831-010 — Generated answers reveal the correct option by length

- Related run: `RUN-20260831-METHODOLOGIST-DEV-13E43E4`
- Environment / course: synthetic dev course generated from the QA service standard
- State: `OPEN`
- Severity: `HIGH`
- Observation: Across the inspected single-choice tests, the correct option was repeatedly the most detailed and often reproduced source wording, while distractors were shorter and less specific.
- User impact: A learner can improve the score by selecting the longest answer instead of understanding the material, invalidating assessment quality.
- Evidence: browser review of the existing generated course and nine lesson quizzes; `RUNTIME-DERIVED`.
- Recommendation: Add generation constraints and a deterministic quality gate for answer-length distribution, lexical overlap, implausible distractors, and positional bias. Regenerate only flagged questions and expose the methodologist assistant for targeted revision.
- Verification gate: evaluate a fixed multilingual corpus and require no statistically dominant correct-answer length/position cue while preserving factual correctness and source grounding.

## UX-20260831-011 — Training log is not an employee learning profile

- Related run: `RUN-20260831-METHODOLOGIST-DEV-13E43E4`
- Environment / exact SHA: `development` / `13e43e497ef76b9e6909e32c0aaa9f85c2da7829`
- State: `OPEN`
- Severity: `MEDIUM`
- Observation: The journal provides a strong cross-employee list and filters, but opening the course title leads to course content rather than an employee-centric summary.
- User impact: HR cannot quickly answer how one employee performs over time, which topics are weak, how attempts compare, or which required training remains outstanding.
- Evidence: normal methodologist browser traversal of the training log; `RUNTIME-DERIVED`.
- Recommendation: Add an employee learning profile aggregating assignments, completion, attempts, scores, confirmations, certificates, overdue items, and comparisons over a selected period, with drill-down to source records.
- Verification gate: from a journal employee row, open one profile and reconcile every aggregate against the underlying immutable training records.

## UX-20260831-012 — Admin audit and team-form safety are available on dev

- Related run: `RUN-20260831-METHODOLOGIST-DEV-13E43E4`
- Environment / exact frontend SHA: `development` / `13e43e497ef76b9e6909e32c0aaa9f85c2da7829`
- State: `FIXED`
- Severity: `MEDIUM`
- Observation: Earlier production acceptance could not reach the audit route, and the create-team-member form lacked an explicit safe close path.
- Resolution: An authorized dev admin session read back audit filters and attributable actions. The team dialog now has a title, close control, Cancel button, optional-password explanation, and an inert backdrop.
- Evidence: normal-browser admin readback plus focused component tests; `RUNTIME-DERIVED`.
- Verification gate: `PASS` on dev; production remains a separate release and acceptance gate.

## UX-20260831-008 — Valid certificate conflicts with pending confirmation

- **Severity:** HIGH
- **Status:** OPEN
- **Evidence:** After the synthetic learner completed all 9 lessons and quizzes, the learner certificate list and public verification page reported a valid certificate. At the same time, the methodologist training journal showed `Ожидает подтверждения`, requested a signed scan and disabled export until confirmation.
- **Impact:** A methodologist cannot explain whether training is legally complete, whether the certificate is final, or why a signed artifact is still required after issuance.
- **Recommended contract:** Either issue the certificate only after the configured confirmation procedure is complete, or clearly label it provisional and prevent public `valid` status until confirmation. Use one authoritative lifecycle state across learner, journal, export and verification surfaces.

## UX-20260831-009 — Last lesson keeps a no-op “Следующий урок” action

- **Severity:** MEDIUM
- **Status:** OPEN
- **Evidence:** At 9 of 9 lessons and after the final quiz passed, the last lesson still displayed `Следующий урок`. One normal click produced no visible state change.
- **Impact:** The learner is left unsure whether the course is actually finished or another required action is missing.
- **Recommended contract:** Replace the action on the terminal lesson with an explicit `Завершить курс` or `Перейти к результату` action and read back the persisted completion state.

## UX-20260831-010 — Personal access cannot be revoked from assignments

- **Severity:** HIGH
- **Status:** OPEN
- **Evidence:** After completion, the methodologist assignment row showed an active personal access expiry and only `Перевыпустить доступ`. No revoke/delete/disable action was available.
- **Impact:** A leaked or no-longer-needed link/PIN remains usable until expiry; reissuing is not equivalent to an explicit auditable revocation.
- **Recommended contract:** Add `Отозвать доступ` with confirmation, audit event, immediate token invalidation and persisted readback. Keep course assignment and learner results unchanged.

## UX-20260831-011 — Correct-answer verbosity remains a strong quiz cue

- **Severity:** HIGH
- **Status:** OPEN
- **Evidence:** In a measured 35-question first-attempt sample, the first answer was the unique longest option in 25 questions. Selecting the first option without understanding still passed six of seven sampled quizzes at 80–100%, although another quiz correctly failed that strategy at 20%.
- **Impact:** Learners can often infer answers from structure and verbosity rather than knowledge; nominal passing scores overstate learning quality.
- **Recommended contract:** Add generation and publication gates for answer-length balance, randomized correct-answer position, semantic distractor plausibility, source grounding and leakage detection. Track regeneration requests and failed quality checks by prompt/model/version.
