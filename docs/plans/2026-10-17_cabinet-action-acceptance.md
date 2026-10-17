# Cabinet actions and source ownership acceptance

Status: IN PROGRESS. Owner request2026-10-17. Production publication NOT AUTHORIZED.

## Scope and boundaries

- Fix source-policy owner selection, reported422 and repeated profile403.
- Test actual cabinet actions by role/section; source inventory is not a click PASS.
- Writes only to identified synthetic QA data. No real employee/course changes,
  mail sends, paid generation, provider settings, destructive purge or credentials.
- Root owns diagnosis, integration and final acceptance. One read-only independent
  inventory/review worker plus a bounded delta writer/reviewer and the canonical
  DEV release runner. Root owns all browser/data acceptance and source integration.
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

## Initial environment evidence (historical; latest DEV evidence below)

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
| Methodologist /dashboard | Refresh, filters, action cards, destination context, help | PARTIAL: exhausted1row/reset/return; other destination combinations pending |
| /documents | Upload/open/cancel/validation; YouTube; search/status/purpose filters; download; new version; reindex; delete preview; actuality ownership/dates/review decisions; help | OWNER FLOW PASS: other/self/save/clear/reload/date refusal; other actions PARTIAL, named delete cancelled |
| /ai/generate | Source selection/compatibility; options; generation/resume/cancel; preview; edit/review/publish; help | PARTIAL: source preflight/options/default restore; actual generation NOT RUN |
| /courses and /courses/[id]/edit | Create/edit/preview; lessons/reorder/media; quizzes; review/publish/archive/delete; help | PARTIAL: create; empty publication defect/unpublish; guard live pending; search/status/menu/import-empty/cancel; assistant open/close |
| /quizzes | Select/create quiz; question/answer types/edit/delete/reorder; learner preview; save/reload; help | NOT RUN |
| /learning-paths | Create/edit/version/publish; sequence; assignments/cancel; learner view; help | PARTIAL: create/reorder/required/save/reload/publish0audience/v2draft; active audience PASS; actual assignment NOT RUN |
| /assignments | Course/audience selection; due date/access; preview/confirm; link/PIN; copy; revoke/repeat; rules/reminders; help | PARTIAL: course/email/PIN form/empty guards; no new assignments or outbound messages |
| /methodologist-workbench | Document dialog/history/source download; assignment preview/confirm; correction/apply/reload; help | PARTIAL: preview/reload/new-command/history/citation/download; error fix candidate; no model call/confirm/apply |
| /learning-cycles | Create/edit/version/schedule/activate/deactivate; filters/pagination; help | PARTIAL: empty create/repeat disabled, target course/program switch; no rule activation |
| /staff | Import stages/file validation/mapping/preview/confirm; schema/roster/filters; create/edit/move/terminate; unit preview/confirm; help | PARTIAL: help; unit form/cancel/empty create disabled; employee form/empty validation/cancel; import tab/no-file analysis disabled |
| /positions and /positions/[id] | Create/edit; JD attach/analyze; qualification/instruction/tests; versions/restore; help | PARTIAL: form validation/cancel, actual multi-file chooser, refresh and card tabs; no profile/rule/version writes |
| /cohorts | Create/edit; search/select/save members; reload; help | PARTIAL: owned group create/member/save/reload/remove/reset, final0members |
| /candidate-assessments | Create/edit campaign; preview/activate/close; invite/copy link; CSV; help | PARTIAL: course guard/create/start/close/CSV; no candidate/link/mail |
| /mandatory-training | Search/filters/scope/status/paging; learner/course destination; help | PARTIAL: search/apply/empty/restore7, single-page guards; no retained writes |
| /training-log | Filters/history; current occurrence; CSV/PDF/ZIP; signed-copy review; restricted share/revoke; help | PARTIAL: filter/reset/history/answer details/disclosure/CSV; no retained-record edits |
| /training-procedures | Draft/edit/validation; activate/version; delete preview; help | PARTIAL: owned draft/edit/cancel/activation422; no irreversible delete |
| /training-retention | Policy form/save; dry-run; purge/legal-hold; help | READ-ONLY methodologist state PASS; admin mutations NOT RUN, purge forbidden |
| Contextual /competencies,/training-rules,/invitations,/surveys,/announcements,/course-review | Context links; forms/validation/preview/submit/readback; help | NOT RUN; no external communication |
| Shared /profile + shell | Profile form; help/support; notifications/read; language; palette; sidebar; guide; logout | PARTIAL: profile save/reload/restore,17help, support validate/cancel, notifications/palette/sidebar/languages/guide; no support send, logout pending |
| Admin /admin,/admin/team | Navigation/onboarding; create/role/activate/deactivate; validation; help | NOT RUN; security-sensitive grants separate approval |
| Admin /admin/kiosks,/settings | Kiosk/create/print/link/PIN/delete; tenant settings/save; help | NOT RUN |
| Admin /admin/settings/integrations,/admin/settings/ai | Forms/status/test/save; provider/model routing | NOT RUN; external settings unchanged |
| Admin /admin/certificates/settings,/admin/training-evidence/settings,/admin/audit,/admin/course-approvals | Templates/preview/download/save; audit filters; approval configuration | NOT RUN |
| Student /student,/my-courses,/my-quizzes,/learning-paths,/certificates,/courses/[id],/surveys | Open assigned course, progress/reload, failed/successful quiz, completion, PDF/certificate, survey | NOT RUN; do not reset retained completed learning |
| Superadmin /admin/super,/admin/super/tenants,/admin/super/operations,/admin/providers | Tenant navigation/preview; forms/validation/readback; operations/provider controls | NOT RUN; no tenant deletion/plan/billing/reserve changes |

## Gates and next

### Live follow-up9557 and publication candidate

Publication004 exactbd0cac8e RELEASE_OK: CI39016503856 SUCCESS,
Verceldpl_ASx8LnkbYhwkvZQvhsTSaMnHGrWJ,
APIdep-db9itsdg1s2s738sr5f0/workerdep-db9iutrncjis739grr90 all exact/live.
Root independently read controller receipt/API health. Branch previous1e5c798f is
failed-CI ancestry, not an accepted runtime rollback; previous accepted9557 retained.
Root browser empty publish now shows localized actionable refusal; normal API409
course_content_required leaves draft/current release9c03f50d… unchanged. Screenshot
dev-empty-publish-refused-bd0.png. Then created module4e083ac1-ae6e-47ed-8123-2affe47a3d9b
and one own synthetic lesson for positive publication continuation; no assignments.

Later competency finding COMPETENCY-COMMIT-001: owned synthetic competency
42b6ccb9-a3cc-4a00-b565-b364ba02b2d3 created201/detail200. Save's PATCH404;
root independent normal API PATCH of only its marked synthetic description again
returned404, subsequent GET200 proved description persisted. All position/course
links remain empty; no assignment effects. UI unsaved course selection cancelled
and page reloaded. Local transaction response fix and create-selection preservation
prepared. UI2RED/2GREEN; no successful deployed fix claimed yet. No blind recreate.
Position card tabs/profile/instruction/competencies/training/history/refresh and
competency destination opened; existing position rules and versions unchanged.
Own empty-course approval page selection/refresh/help checked, no request created.
Competency candidate gates: focused API5PASS, full4228PASS/526SKIP, quality1008/2201;
full web168files/1226PASS183.21s, focused3PASS, standalonetypecheck/build67/67,
release contracts0183/293PASS. Root accepted API diff independently; API writer
independently reviewed root UI diff; final no-course/no-PUT regression added/passed.
No direct DB DML, force-RLS changes or Docker DB. Fresh DEV readback remains required.

Publication packet003/1e5c798f stopped at CI39015879637: frontend test TS2352
in coursePublicationError.test.ts:15, reproduced locally. No bypass/retry; use
direct typed property instead of invalid Record cast. Runtime API still9557.
Keep failed ignored receipt release-publish-003-blocked.json; missing controller
success receipt is not evidence of release. A new exact packet is required.

Later action results: dashboard exhausted-attempt link opens exact filtered1row,
reset filter/return to overview works. Profile permits optional blank first name
per current API contract; save/reload and restoration to original QA both verified.
Workbench exact preview for empty QA DIALOGUE54 rejected409/audience_empty but
showed raw HTTP text (WORKBENCH-ERROR-001). Nonempty department preview plan
36304fdb-3985-4816-85ac-1b19ba040e76 retained same release/course/department/date
after reload, New command removes URL context; never confirmed, no notification.
Recent document task5413a35c-c271-4581-92bf-47c19e36c16a opens existing RU/KK
history, citation and fragment; actual source download H57-RU-V9-01 (1).txt,
5602bytes SHA2560baa5a420c956a99d4774d6f620600fd00f8d522c6f21315ef9adf1b708da199.
No new model request. Browser download byte-oracle match NOT VERIFIED.
New workbench local patch maps canonical/detail errors, retains command and
unknown-confirmation lock; truthful postimplementation tests, no RED claim.
Final source: full web167files/1223PASS, standalone typecheck and build67/67 PASS,
release contracts0183/292PASS. Root reviewed bounded UI delta independently of
writer. API unchanged from4223PASS/526SKIP. Video guide opens, step disclosure and
step3 seek sets currentTime15.667 without media error; audio/content fidelity not
re-listened. SCORM no-file import refuses with choose-ZIP message/cancel; no ZIP
uploaded. Own-course catalog search/status/menu open/close work. No archive yet.

REL-DEV-CABINET-ACTIONS-20261017-002 RELEASE_OK: exact9557d137 all three services,
CI39014500919, Verceldpl_GTcCQ97NPaPX78dTYmcaoWRhGuB1,
APIdep-db9ieh61egvs73fd86vg/workerdep-db9ifgdg1s2s738rbi3g; unchanged tiers/schema.
Root normal API exact actor/tenant: all departments5 versus active3, both archived
excluded; assignment with archived ID422/departments_outside_tenant and before/
after assignments empty. Browser program v2 offered3 active units, named document
deletion confirmation/cancel and quiz title PASS. No DELETE or retained PIN reset.

Additional real actions, not whole-route acceptance:

| Area | Result and boundary |
|---|---|
| Mandatory learning | Impossible search/apply0, clear/apply7; one-page navigation disabled; no retained writes |
| Retention | Methodologist read-only/empty policy state, no purge |
| Positions | Empty create disabled/cancel; JD actual multi-file chooser opened, no file/AI submission; refresh |
| Candidates | Empty/non-approved-course guard; create approved-course draft9350957d-52ce-4d30-9944-59c918a3a627; CSV0rows; start/close; no invite/mail |
| Journal | Open completed answer details, collapse/close and reset filters; no grade/signed-record mutation |
| Shared shell | Support validation/category/cancel without send; empty notifications; palette destination; collapse/expand; RU/KK/EN then RU restored |
| Staff | Schema/unit1employee, breadcrumb3active, list/schema; import no-file disabled; no real HR write |
| AI form | Source preflight; brief/KK/manual-count controls then defaults restored; no generation or provider call |
| Assignments | Published course picker, email/PIN form switch, empty assignment/repeat disabled; no existing PIN reset or notifications |
| Manual course | Created97cad6b2-3e70-474f-b1b6-ba38c869d234, empty publication incorrectly succeeded; ordinary UI unpublished, API confirms draft/0modules |

Candidate CSV69bytes/0rows SHA256
e9eb578bd8dbeb8347610ac2e12ba48a5fb5720dec8c118247204612290381ae.
Candidate and course use QA BUTTONS20261017 / KAMILYA_CABINET_ACTIONS_20261017.
All owned fixtures retained visibly marked; immutable publication audit preserved.
Empty course retained current_release_id9c03f50d-3a90-4e65-83db-bef4212e6822 after
unpublishing; fresh rejection must leave it unchanged before adding actual content.

COURSE-CONTENT-001 local guard covers live and frozen snapshots before writes;
legacy/backfill default remains off, persisted native type cannot be bypassed by
snapshot metadata. Decorative metadata is not content. RED/GREEN retained;
API4223PASS/526SKIP, web167files/1219PASS, build67/67 and quality1008/2201 PASS.
Independent review accepted after withdrawing an unsupported literal canonical_url
field hypothesis: no such field contract exists in the persisted/renderer source;
no speculative field expansion made. Real DEV empty-refusal/nonempty-success
remain acceptance gates.
Admin/student/contextual actions and remaining matrix completions are NOT RUN,
not implicitly accepted by navigation. No production writes or deployment.

### Live DEV update2026-10-17

Owner repair bacc4d0ad0731b2b7de3a3e515dd0a565f8f3dd3 is deployed to all three
existing DEV services. CI39013191234, Verceldpl_F1bU3tr1RG51uJQCq4mnKPhffxBf,
APIdep-db9i52uq1p3s738bbmpg and workerdep-db9i5v61egvs73fc8p0g exact/LIVE.
Controller RELEASE_OK; Free/Free/Hobby unchanged, no schema/configuration change.
Previous da21 worker failures are retained, not retried in a blind loop. Separate
bounded provider/proxy read-only diagnosis found connect timeouts, no observed
auth/host-pin/OOM/MaxStartups denial; failing network node remains unlocalized.
New bacc rollout succeeded with the same transport, without a policy/key change.

Root normal QA browser passed owner removal (old500 repaired), selection of
DOCUMENT58 Temporary QA, Save, reload retention, self-assignment, final clear and
reload. Inverted dates are rejected. Browser calendar fill needed native keyboard
change events before React accepted the date; initial fill-only run did not prove
date validation and is not counted as PASS. Independent normal API exact actor/
tenant readback proves owner_id/reviewed_at/next_review_at all NULL at baseline.
Screenshot: ignored dev-owner-selector-accepted.png. No production writes.

Additional actual action results (not whole-route PASS):

| Area | Actual actions/result | Retained synthetic fixture |
|---|---|---|
| Documents | Search exact source; three lifecycle tabs; YouTube empty/check disabled/cancel; new-version no-file upload disabled/cancel; delete confirmation/cancel, no DELETE | Original sources preserved |
| Groups | New/reset/empty create disabled; create; edit description; select QA learner; save; reload same member/description; remove member/save; reset form | 770984bb-b606-4ab6-9ed9-f0b359afd07b, QA BUTTONS20261017, final0members/no owner/no assignment |
| Programs | Four wizard stages; add2/reorder both directions/change required; save/reload; remove course; audience tabs; publish0audience; create next version | 27336ade-3110-41ef-ad4e-8aa4ea4ea191 publishedv1/1course/0learners; next draft under same QA title; no notifications |
| Cycles | Empty create/repeat disabled; course/program type switch and explanatory program-link state | No rule, period or notification created |
| Procedures | New form; type/retention selectors; expand settings; save draft; edit/cancel; activation without approval/commission metadata422 | cbb79362-f7ce-4cb3-9ac5-d300418808b9, QA BUTTONS20261017 draft, not a real attestation |
| Journal | Actual CSV file; completed filter1row; history checked; open answer analytics | CSV3616bytes/7data rows; retained learning unchanged |

CSV local Downloads training-log-2026-10-17-07-37-34.csv SHA256
6ed922a980b526cfc8970a1ec16d25cabc5650b1a6ec4e820fec450d298e28c5.
Owned QA group/program/procedure intentionally retained for continuation; no
irreversible deletion attempted. Marker KAMILYA_CABINET_ACTIONS_20261017.

New findings repaired locally: archived program audience (PROGRAM-AUDIENCE-001),
course-title label in quiz form, and unnamed document deletion confirmation.
Independent review accepted source and strengthened tests; final focused5files/
52webtests PASS, focused54API PASS, build67/67 PASS including lint/types, release
contracts PASS (schema0183,290journal entries). Next exact DEV rollout pending. Remaining
matrix actions/roles, external sends, paid generation, purge and protected retained
learning mutations remain NOT RUN; this update does not convert them to PASS.

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
