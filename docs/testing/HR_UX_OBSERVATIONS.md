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
