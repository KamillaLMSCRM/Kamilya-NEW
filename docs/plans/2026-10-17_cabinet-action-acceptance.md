# Cabinet actions and source ownership acceptance

Status: IN PROGRESS. Owner request2026-10-17. Production publication NOT AUTHORIZED.

## Scope and boundaries

- Fix source-policy owner selection, reported422 and repeated profile403.
- Test actual cabinet actions by role/section; source inventory is not a click PASS.
- Writes only to identified synthetic QA data. No real employee/course changes,
  mail sends, paid generation, provider settings, destructive purge or credentials.
- Root owns diagnosis, integration and final acceptance. One read-only independent
  inventory/review worker; no delegated external access.
- Baseline linked checkout HEAD3fa090eef781b6e7d893cf0a292b1781eccfe571;
  unrelated interactive-authoring work preserved. CodeGraph preflight NOT_READY
  (checkout-local runtime missing); Graphify graph absent. Bounded source fallback.

## Findings and repairs

| ID | Observable failure | Cause / repair | Verification status |
|---|---|---|---|
| OWNER-01 | Only self-assignment; no other owner choice | Add selector backed by existing tenant-scoped paginated users API; keep active primary-role methodologist eligibility | Frontend RED/GREEN |
| OWNER-02 | Self-assignment422 in tenant preview | Platform actor is not an eligible tenant user; hide self action during preview, choose actual methodologist | Frontend RED/GREEN; backend guard unchanged |
| AUTH-01 | Repeated users/me403 | Layout focus/visibility heartbeat requests profile explicitly forbidden during impersonation; skip only that call, retain expiry and API401 handling | RED/GREEN including deadline expiry |
| OWNER-03 | Previous save closes a newly opened source dialog | Async completion has no dialog identity; generation guards on open/save/analyze/decision | Deferred-request RED/GREEN |
| OWNER-04 | Existing policy clear/update500 in live DEV | onupdate timestamp serialized without async refresh; add refresh before response | Unit RED/GREEN; real isolated Supabase MissingGreenlet RED then clear/reassign GREEN |
| STAFF-01 | Optional department demanded by empty-form error | Validation already allows no department, stale RU/KK/EN copy | RED/GREEN copy regression |

## Current environment evidence

- Read-only production normal methodologist login: exact retained QA tenant
  83552ce6-8058-4561-abe3-cfbda14e030a, ordinary role, users/me200,
  actuality200, team200, active primary methodologists3. Reported family ID exists.
  Its current title differs from screenshot; do not conflate screenshots with
  current family/catalog metadata or claim the exact historical request captured.
- Public health: DEV API da21bb3b60869174a6756edc155454277588ce06 / render-development;
  production API f6f1bc945e627287f8d5a9cf9040bcae1f73ea4a / kz-production.
- Chrome user's old session returned to login. Nonblocking ordinary QA login
  requested; no credentials exposed, reset or substituted into browser storage.
- Live DEV browser ordinary methodologist in persistent QA
  a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0, fixture marker verified through canonical
  fixture + visible tenant + API identity. D57-RU-CONFLICT-05 family
  b86f3431-02ad-4579-9e99-684a668da063 was initially unowned/dates empty.
  Self-assignment succeeded and displayed QA methodologist; clear500 in UI and
  ordinary API. Do not repeat or use direct owner DML: restoration remains open
  until the normal API update is repaired. No learning history changed.

## Action matrix

Each row needs button-level expansion and observable readback. NOT RUN is not PASS.
Form-open/cancel and empty validation do not prove successful mutations.

Additional live result: navigation plus help-open/help-close PASS for all17 sidebar
sections of the ordinary DEV methodologist. Other actions below retain their
individual NOT RUN/PARTIAL status. Captured button lists are initial-render samples,
not a complete stateful inventory. Evidence: ignored
`.release-evidence/cabinet-actions-20261017/dev-navigation-help.json`.
Actual D57-RU-CONFLICT-05 download produced a6404-byte `.md` with SHA256
19df7c3bd1d3a29b6f8a1fbabd1594ac26cfe998b006216a8d34cdc78bdfd9b1.
Filename/output observed; independent original-byte equality NOT VERIFIED.

| Role / route | Actions / acceptance | Current live status |
|---|---|---|
| Methodologist /dashboard | Refresh, filters, action cards, destination context, help | NOT RUN |
| /documents | Upload/open/cancel/validation; YouTube; search/status/purpose filters; download; new version; reindex; delete preview; actuality ownership/dates/review decisions; help | PARTIAL: upload form/cancel/empty disable; owner self success/clear500 |
| /ai/generate | Source selection/compatibility; options; generation/resume/cancel; preview; edit/review/publish; help | NOT RUN; paid generation separate gate |
| /courses and /courses/[id]/edit | Create/edit/preview; lessons/reorder/media; quizzes; review/publish/archive/delete; help | NOT RUN |
| /quizzes | Select/create quiz; question/answer types/edit/delete/reorder; learner preview; save/reload; help | NOT RUN |
| /learning-paths | Create/edit/version/publish; sequence; assignments/cancel; learner view; help | NOT RUN |
| /assignments | Course/audience selection; due date/access; preview/confirm; link/PIN; copy; revoke/repeat; rules/reminders; help | NOT RUN; no outbound messages |
| /methodologist-workbench | Document dialog/history/source download; assignment preview/confirm; correction/apply/reload; help | NOT RUN; model/resource state untouched |
| /learning-cycles | Create/edit/version/schedule/activate/deactivate; filters/pagination; help | NOT RUN |
| /staff | Import stages/file validation/mapping/preview/confirm; schema/roster/filters; create/edit/move/terminate; unit preview/confirm; help | PARTIAL: help; unit form/cancel/empty create disabled; employee form/empty validation/cancel; import tab/no-file analysis disabled |
| /positions and /positions/[id] | Create/edit; JD attach/analyze; qualification/instruction/tests; versions/restore; help | NOT RUN |
| /cohorts | Create/edit; search/select/save members; reload; help | NOT RUN |
| /candidate-assessments | Create/edit campaign; preview/activate/close; invite/copy link; CSV; help | NOT RUN; no candidate mail |
| /mandatory-training | Search/filters/scope/status/paging; learner/course destination; help | NOT RUN |
| /training-log | Filters/history; current occurrence; CSV/PDF/ZIP; signed-copy review; restricted share/revoke; help | NOT RUN; no retained-record edits |
| /training-procedures | Draft/edit/validation; activate/version; delete preview; help | NOT RUN; no irreversible delete |
| /training-retention | Policy form/save; dry-run; purge/legal-hold; help | NOT RUN; purge forbidden in this pass |
| Contextual /competencies,/training-rules,/invitations,/surveys,/announcements,/course-review | Context links; forms/validation/preview/submit/readback; help | NOT RUN; no external communication |
| Shared /profile + shell | Profile form; help/support; notifications/read; language; palette; sidebar; guide; logout | PARTIAL: staff help only; support submission NOT RUN |
| Admin /admin,/admin/team | Navigation/onboarding; create/role/activate/deactivate; validation; help | NOT RUN; security-sensitive grants separate approval |
| Admin /admin/kiosks,/settings | Kiosk/create/print/link/PIN/delete; tenant settings/save; help | NOT RUN |
| Admin /admin/settings/integrations,/admin/settings/ai | Forms/status/test/save; provider/model routing | NOT RUN; external settings unchanged |
| Admin /admin/certificates/settings,/admin/training-evidence/settings,/admin/audit,/admin/course-approvals | Templates/preview/download/save; audit filters; approval configuration | NOT RUN |
| Student /student,/my-courses,/my-quizzes,/learning-paths,/certificates,/courses/[id],/surveys | Open assigned course, progress/reload, failed/successful quiz, completion, PDF/certificate, survey | NOT RUN; do not reset retained completed learning |
| Superadmin /admin/super,/admin/super/tenants,/admin/super/operations,/admin/providers | Tenant navigation/preview; forms/validation/readback; operations/provider controls | NOT RUN; no tenant deletion/plan/billing/reserve changes |

## Gates and next

Local verification so far: final owner/session focused21PASS; full frontend
166files/1212tests PASS (before the final copy-only change, separately18tests PASS);
lint/typecheck PASS; build67/67 PASS including that copy change. Initial unrestricted
parallel full run had one learningInsightsJournal timeout; focused rerun PASS,
bounded maxWorkers2 full rerun PASS without changing its fixture or timeout.
Backend focused21PASS, full API4204PASS/526environment SKIP, quality baseline
ruff1008/mypy2201 PASS. Real isolated
Supabase gate22checks PASS with pinned DEV project digest5b535773… and schema cleanup
/public neutrality. Independent front-end and backend/gate reviews accepted with
public DEV deployment and normal-API fixture restoration still open. CodeGraph/Graphify remain
unavailable in this checkout; no graph savings or runtime claims inferred.

1. Correct OWNER-04 with real isolated Supabase ORM/router update coverage;
   retain failed receipts and require owned-schema cleanup/public neutrality.
2. Final focused and risk-proportionate regression, lint, typecheck, build,
   independent review, changelog/error-journal update.
3. Approved DEV rollout/current-code live owner choice/save/clear/reload,
   browser all-section matrix with synthetic fixture ledger.
   Current branch includes separately owned staff DEV changes; keep this fix as
   an isolated commit for reviewed integration, never promote the entire branch
   to production merely to deliver this repair. Prior worker-parity infrastructure
   failure is not waived or repaired under this task.
4. Production publication remains withheld; request exact release agreement
   only after candidate/DEV gates. Do not call the whole cabinet accepted.
