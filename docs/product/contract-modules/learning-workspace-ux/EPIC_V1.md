# Learning workspace UX V1

Status: Accepted for presentation-first implementation. Version1, standard V2,
ADR-0024/0025. Product owner: requesting owner. Root/module integration owner:
OpenCode. Independent reviewer: assigned after implementation, not the writer.
Approved by: owner selected real application implementation on2026-11-01;
root accepted the interface map on2026-11-01 after two bounded source inventories.

## Outcome and negative space

Authorized methodologists prepare and inspect real document-bound learning,
understand publication blockers, review exact versions, preview recipient scope,
and reconcile learning results. Learners see the next assignment, readable lessons,
mandatory-test outcomes and the correct remaining completion/confirmation step.
The12 reference screens are design inputs, not runtime data or new authority.

No prototype fixtures/simulate buttons enter product. No new roles, canonical
routes, grading decisions, source truth, automatic approval, certificate issuance,
reset learning history, email/OTP bypass, paid provider calls, tier/configuration
changes or deployment. Existing auth/tenant context and server mutations remain
authoritative. No migration is planned. No version bump/tag/release here.

## Directed module map

`existing tenant-scoped APIs -> existing web adapters -> workspace presentation`

`user action -> existing guarded command -> authoritative readback -> visible state`

### UX-LEARNING V1

- Responsibility/interface: present server-owned assignment/progress/quiz/evidence
  state on `/student`, `/my-courses`, `/courses/[id]`, `/courses/quiz/[quizId]`.
- Inputs: authenticated active role, existing student dashboard/structure/progress,
  quiz metadata/attempts, completion/evidence APIs. Outputs: readable UI and only
  existing commands. No new enrollment/progress owner.
- States: loading/error/retry/confirmed empty/ready; material vs passed quiz vs
  completed enrollment vs confirmation remain distinct. A failed metadata read
  cannot mean no quiz; successful quiz submission must precede completion.
- Preserve pinned course/assignment/attempt identity, kiosks, SCORM1.2, preview
  isolation, concurrent/session safety and purpose-bound confirmation.
- Design: next-step cards, focused learner layout, mobile/keyboard outline,
  contextual help on demand, clear pass/fail/exhausted/confirmation outcomes.
- Read/write: named learner routes and their owned feature helpers/tests; layout
  changes are root-owned unless explicitly transferred in the worker packet.

### UX-CONTENT V1

- Responsibility/interface: inspect real sources and durable generation results,
  edit lessons/questions and review exact saved versions using existing APIs.
- Inputs: document/extraction/provenance metadata, generation journal/job status,
  course structure/content/review status, quiz and review snapshots. Outputs:
  presentation, existing validated edit/retry/resume/review/publication commands.
- States: unavailable source != verified absence; saved partial != failed/no draft;
  saved correction != accepted semantic content; accepted old version != approval
  of current version. Publication blockers name the existing server cause.
- Design: source beside learner text, existing rendering for preview, accessible
  formatting controls retaining the canonical text format, lesson/test navigation,
  explicit saved/dirty state, readiness checklist, snapshot-focused review.
- Data ownership: documents, AI jobs, lessons/quizzes and approval services stay
  canonical. Do not invent a UI OCR-correction write or mark semantics verified.
- Read/write: existing documents/ai-generate/course-editor/quizzes/review routes,
  their feature components and tests, only as enumerated in final packets.

### UX-OPERATIONS V1

- Responsibility/interface: real actionable work queue and real audience/result
  reconciliation using existing dashboard/action/enrollment/log interfaces.
- Inputs: active methodologist scope, action cards, published course version,
  audience preview and training-log rows/summary/export filters. Outputs: existing
  scoped navigation and explicit commands, never parallel recipient computation.
- States: plan preview/confirm/stale/failed; existing assignments/completed records
  are retained; CSV and summaries use the same authorized filter scope; retry never
  erases an authoritative result or broadens tenant visibility.
- Design: task-first queue, stepwise assignment preview, mobile recipient/log cards,
  explicit current/history/confirmation/progress states, concrete next actions.
- Data ownership: no browser-synthesized completion or journal; no publish->assign
  implicit command. No cross-tenant IDs accepted just because a card renders them.
- Read/write: existing dashboard/assignments/training-log routes and related owned
  helpers/tests, only as enumerated in final packets.

## Shared module contracts and impact

All modules consume existing UI primitives and i18n RU/KK/EN. New copy must not
create duplicate business-state vocabulary. Shared presentation/state helpers may
derive labels from confirmed fields but must not create grants or quality votes.
No manifests/global styling overhaul: reuse current brand tokens and responsive
spacing. Preserve route registry and active-role separation.

| Existing owner | Impact | Required protection |
|---|---|---|
| Web auth/roles/layout | Consumer/layout only | Role-route, logout/session, keyboard/mobile checks |
| Documents/AI workers/providers | Consumer only | No paid inference, no source rewrite/requeue by render |
| Courses/lessons/quizzes | Consumer only | Unsaved, stale scope, question keys, mandatory quiz negatives |
| Course approval | Consumer only | Exact snapshot, stale/foreign/duplicate decision negatives |
| Enrollments/audiences | Consumer only | Server preview; explicit confirm; no history reset |
| Evidence/confirmation | Consumer only | No methodologist impersonation; OTP retained |
| Dashboard/actions/log/export | Consumer only | Same tenant/filter/current-vs-history denominator |
| DB/schema/retention/billing/deployment | None | Diff gate: unchanged |

If an existing API cannot support a prototype detail, stop that seam, record the
exact gap and an impact addendum. Do not silently add another data source, render
fake success or label a partial delivery complete.

## Verification, readiness and rollout

- Ready: exact checkout/HEAD/primary guard, source/API/test owners identified,
  disjoint packets, required existing fixtures available. Graph navigation gap is
  explicit and bounded source reads replace it, never tests.
- Edit loop: focused Vitest/policy/RTL, including loading/error/empty/retry, dirty
  navigation, stale role/tenant/version and exact protected states.
- Assembly: user journeys cross the real production components with synthetic
  intercepted API fixtures, desktop/mobile/keyboard; real-file export when touched.
- Candidate: full web suite once after freeze, typecheck/lint/build, applicable
  AI-COURSE-01/CORPORATE-READINESS-01 deterministic backend neighbors, independent
  requirements/correctness/security/complexity review and final diff.
- Test authorization: no real tenant/provider/DB writes, no paid model calls.
  Mocked browser coverage is not deployed DEV/production acceptance.
- Done: actual UI changes, executable regression evidence, exact commit and
  review packet with no hidden unsupported prototype behaviour. Current external
  release gates are stated separately in PRODUCTION_READINESS.md.
- Rollback: revert the isolated frontend commit(s); existing schema/API payloads,
  records, release snapshots and job/attempt history remain compatible. No data
  cleanup or backfill is needed for a presentation rollback.
- Root owns scope changes/shared interfaces/final GO. Writers stop at an unlisted
  path, needed API/state ownership change, unavailable required gate, unrelated
  changes or secret/provider/release boundary. Reviewer is read-only until a
  specific write transfer. No merge/release without current owner approval.

## Accepted implementation packets / prototype adaptation

All12 screens are covered as improvements of existing routes, not new duplicate
routes or a promise of every synthetic capability. Scope is frontend consumers;
backend invariants are not changed to imitate a mock.

| Reference | Existing owner | Accepted implementation boundary |
|---|---|---|
| Student dashboard/list | student/my-courses | Existing occurrence/deadline/can_resume, no invented confirmation counts |
| Lesson | courses/[id] | Focus/mobile/keyboard/content/quiz/assistant presentation, guarded handlers retained |
| Learner result | courses/quiz/[quizId] | Aggregate-only result, real evidence panel/OTP where event exists, attempt limits |
| Author/readiness | courses/[id]/edit | Formatting on canonical text, real statuses and links; no guessed semantic GO |
| Documents | documents | Real processing/original/version/usage controls; no unsupported OCR correction or fake extracted pages |
| Generation | ai/generate | Real job/resume/saved-review-draft states, not a fabricated per-artifact ledger |
| Questions | quizzes | Existing IDs, quiz settings/assistant proposals and lesson context; no invented A/B or source quotes |
| Review | course-review, course-review-requests, approval components | Real snapshot/assigned reviewer/decision; no unsupported author!=reviewer assertion or fabricated current diff |
| Assign | assignments | Existing exact-user preview/explicit server command; department workbench remains separate, no invented overlapping-group service |
| Methodologist queue | dashboard | Existing action-center/count/drilldown owners; unavailable != zero |
| Training journal | admin/training-log shared by training-log | Same server scope/query/summary/CSV, existing detail/history; CSV is ALL filtered rows, not current page |

Existing source gaps above are not filled by assertions. Extraction correction,
variant/source-evidence DTO extension, exact current-vs-frozen review diff,
arbitrary group-audience plans and new confirmation reporting filters require a
separate accepted interface extension. They are not silently claimed in V1.

Writer L owns student/page, my-courses/page, courses/[id]/page,
courses/quiz/[quizId]/page, components/layout/Layout and their named tests/new
learner-only helpers. Writer C owns courses/[id]/edit/page, quizzes/page and their
named tests/new author-only helpers. Root owns documents/generation/assignments/
dashboard/journal/review/shared components, all canonical docs, integration and
verification. Locale changes use owned feature copy or an explicit serialized
root transfer; no concurrent edits to shared locale/route/schema/config files.

### Integration addendum R1 — evidence and identity

Root owns `features/training-evidence/EvidenceConfirmationPanel.tsx` and the
learner evidence adapter after leaf completion. Optional identity-checked
`initialEvent` avoids a duplicate initial fetch. `not_required` hides only OTP,
not PDF/signed-copy controls. Owned-event validation and stale actor/event async
continuations remain fail-closed; OTP request/verify payloads do not change.

Credential refresh for the same actor is transport continuity, not a new quiz or
assignment. Preserve entered answers/timer/confirmed result on token-only refresh;
reset on actor/tenant/role/assignment identity change. Existing expired-assignment
HTTP409 is presented using the authoritative access-window response, not as a
generic missing course. Independent review found these conditions; focused
negative tests precede acceptance. No API/DB state or capability change.

### Integration addendum R2 — one evidence read owner

Supersedes R1's optional `initialEvent` proposal only. The shared confirmation
panel owns the single event read through the existing API client, validates
event ID/procedure/status and retains PDF/signed-copy UI for `not_required`.
The learner adapter only enforces active student/session presence. No duplicate
raw-fetch transport or speculative seed interface remains. Actor/tenant/role/
event changes reset the panel; same-actor credential refresh does not erase OTP
or results. Stale downloads and callbacks are rejected after unmount.

### Integration addendum R3 — author continuity and final review boundaries

The same-actor credential continuity requirement also applies to dirty author
lessons/questions. Volatile question recovery is unsaved user input, not another
saved-content owner: compare its saved baseline with the fresh server question,
block an overwrite on mismatch, and provide explicit discard/reload. No durable
browser persistence, schema or server mutation contract is added.

Final root review additionally binds post-assignment readback to the confirmed
selection, suppresses report download/feedback after unmount, distinguishes
unconfirmed enrollment counts from zero, keeps PDF errors visible without OTP,
derives an open source inspector from the latest catalog row, and binds review
completion receipts to their capability. Spent scoped-token removal may retain
its success receipt; a new capability may not inherit it. Deferred-response
regressions cover these boundaries; runtime acceptance remains a separate gate.

## Reviewer and release handoff

Final visual addendum R4: the shared evidence panel uses canonical RU/KK/EN
copy for retained PDF/signed-copy actions, fallback errors and manual return.
`not_required` and already-confirmed headings must not instruct another email
code. This is presentation-only; the existing purpose-bound OTP and file/API
contracts are unchanged. Focused locale/panel/player regressions cover the delta.
Source inspection additionally shares the document workspace's stable actor/
tenant/role/session boundary: old catalogs cannot be inspected under a new actor,
and delayed original-file downloads/usage responses stop after unmount. Token
refresh alone does not discard an upload form. A deferred-download regression
covers the exact boundary; no document API or lifecycle state is changed.

1. Compare this branch with its recorded master base, not the independent engine
   branch. Confirm VERSION/API/schema/route registry/provider settings are unchanged.
2. Review author/session/deferred-response negatives and run the full web/type/
   lint/build gates. For synthetic browser acceptance, start a dedicated local
   build with `NEXT_PUBLIC_API_URL=/api` on127.0.0.1:3024, then use
   `PLAYWRIGHT_SKIP_WEBSERVER=1` and `playwright.workspace.config.ts`. Optionally
   point `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` at an existing browser binary.
   This test configuration never starts a server or permits live API passthrough.
3. Inspect desktop/mobile/keyboard journeys and the downloaded synthetic CSV;
   check actual question Back/Forward recovery, not only modal Cancel/unload.
4. After code review/CI and separate DEV authorization, validate one retained
   synthetic non-demo tenant through normal roles: assignment, failed/passed
   mandatory quiz, completion, real PDF, OTP where required, signed-copy review,
   report/current-history/CSV reconciliation. Preserve already completed learning.
5. Only after that acceptance, approve the release/version/production packet and
   exact-SHA runtime readback separately. Do not infer release authority from this
   document, local mocks, credentials or a green build.

Stop/reject on cross-scope content, answer-key exposure, lost dirty input on
credential refresh, unsupported simulated capabilities, changed retention/roles/
OTP/history, unapproved paid/provider activity or failed required external gates.
Frontend rollback is an isolated source revert; retained learning records and
server snapshots remain authoritative and must not be reset.
