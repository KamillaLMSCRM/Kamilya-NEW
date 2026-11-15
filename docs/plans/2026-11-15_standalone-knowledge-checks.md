# Standalone knowledge checks V1

Approved by: product owner, direct instruction 2026-11-15: create standalone
employee knowledge checks, assign, preserve results, DEV then conditional production.
Root owns contracts, integration, migrations, release and readback. Bounded backend
and frontend writers own disjoint paths; a separate reviewer reviews their delta.
Changes to scope/interfaces require root impact addendum here before implementation.

## Objective and module identity

`knowledge_checks/v1` owns an employee assessment independently of courses,
lessons, enrollments and candidates. Methodologist creates choice questions,
publishes a revision, assigns employees; an assigned student completes it and
both can read retained attempts/results. No course/lesson is created.

Non-responsibilities: AI generation, candidate hiring, old course quizzes,
certificates, recurring cycles, email delivery, SCORM, new question kinds, billing.
Existing MCQ/multiple_choice/true_false answer semantics are reused: full correct
choice set earns question points, percentage is rounded, pass_score inclusive.
No prerequisite source approval for manually authored standalone questions.

## Interface and inputs/outputs

All endpoints `/api/v1/knowledge-checks`; UUID IDs, tenant/session from auth.
Author role: active methodologist (and platform superadmin with tenant context).
Student endpoints require active student; own assignment only, other IDs ->404.

Content: `{title, instructions, pass_score, attempt_limit, time_limit_minutes,
questions:[{id,text,type,points,explanation,choices:[{id,text,is_correct}]}]}`.
Question/choice IDs stable UUIDs; nonblank text, positive points, >=2 choices,
single-answer MCQ/true_false exactly one key, multi >=1 but not all correct;
true_false exactly two choices. Output bounds are safety schema bounds, not
runtime tunables. No model calls/provider configuration.

- GET `/` author list summaries; POST `/` `{id, ...content}` idempotent by
  caller-owned UUID, same content replay returns existing, conflicting reuse409.
- GET `/{id}` author detail, including draft content and revision.
- PUT `/{id}` `{expected_revision,...content}` optimistic replace increments
  revision, status=draft; preserves old assignments. Stale edit409.
- POST `/{id}/publish` `{expected_revision}` validates complete keys, marks
  published; repeat same revision idempotent. Never edits old snapshots.
- POST `/{id}/assign` `{expected_revision,user_ids,due_at?}`: published revision
  only; all audience IDs must be active tenant employees with primary role student, invalid audience404
  with no partial writes. Unique(check,revision,user) skips exact repeat.
- GET `/{id}/results` author: assignment summaries with employee label and all
  attempt result records; includes revision/due/status; retained failed attempts.
- GET `/my` student own assignment summaries, latest score, attempt count.
- GET `/assignments/{id}` student own summary and attempts; no keys/explanations.
- POST `/assignments/{id}/start`: row lock; return existing active attempt on
  repeat/reload; completed passed or exhausted409; overdue assignment409.
  Freezes assignment snapshot into attempt, server started_at and deadline_at
  (earlier of due_at and start+optional time_limit). No client timing trust.
- GET `/attempts/{id}` own student: frozen public questions/choices, saved answers,
  server start/deadline, result only if complete. Never return answer keys or
  explanations, including completed attempt, before further retries.
- PUT `/attempts/{id}/answers` `{answers}` save validated partial draft under lock;
  no grading/key leak; closed/expired409. A question at most once, choices unique
  and belong to that question; single-answer cardinality enforced.
- POST `/attempts/{id}/submit` `{answers}` under lock; normal complete answers
  required. Expired attempt grades only previously saved answers, missing=wrong,
  never accepts late answers. Same normalized submitted answers return original
  result, different replay409. Expiration replay returns same finalized result.

Result shape: attempt `{id,assignment_id,number,status,started_at,deadline_at,
completed_at,score_percent,passed,earned_points,total_points}` plus saved answers.
Author and employee get persistent results, not correctness keys during retries.
Summary: assignment `{id,check_id,title,revision,due_at,status,attempt_limit,
attempts_count,score_percent,passed}`. Status assigned/in_progress/passed/failed.

## Data ownership and state

New tables (all tenant_id, FORCE RLS): `knowledge_checks` (current editable
content/revision/status/created_by/timestamps), `knowledge_check_assignments`
(check_id/user_id/assigned_by/revision/immutable snapshot+sha/due_at/created_at),
`knowledge_check_attempts` (assignment_id/number/frozen snapshot+sha/started_at/
deadline_at/draft answers/normalized submission hash/result/completed_at).
Root owns migration0188 after existing0187; additive only. Old reader rollback
ignores new tables. No drop of retained learning data. No delete route in V1.
Tenant/user FKs RESTRICT; cross-tenant guards on DB writes as well as API. Unique
(tenant_id,id) parent FK keys and assignment(check,revision,user), attempt number.
Tenant-bound foreign user IDs must fail even under lms_app direct insertion.
Runtime role lms_app no BYPASSRLS. Assignment snapshot and completed attempts
immutable at DB boundary. Draft answers editable only before completion.

State: check draft -> published -> edit(next revision,draft) -> published;
assignment assigned -> in_progress -> passed or failed, failed may retry until
attempt_limit; each attempt started -> submitted/expired terminal.
Assignment row lock serializes starts; attempt row lock serializes save/submit;
completed attempt immutable. Existing active expired attempt must be submitted
before next start; no regeneration/replacement on reload or transport retry.

## Impact map / dependencies

SOURCE-DERIVED: UI -> knowledge_checks API -> new aggregate tables + existing
tenant employees/auth/session. No background worker/LLM dependency. Existing
quizzes supply proven choice semantics; new snapshot scoring is pure and tested
against manually calculated oracle. Existing APIs unchanged.
Consumer impacts: employee selector, workspace panels, auth/session, shared UI.
Interface impacts: main router registration, ORM loading, rolePolicy/routeRegistry
add canonical author/player routes; /courses exposes entry; /my-quizzes exposes
standalone assignments without blocking course quizzes. Existing sidebar five
sections remain. Ownership/invariant changes elsewhere: none.
Forbidden: old quiz, course, generation, candidate and retention data mutations;
duplicate menus; candidate identities; fake courses; paid resources.
Navigation preflight NOT_READY (checkout-local CodeGraph runtime missing);
bounded source inspection is the explicit fallback, no graph-derived claims.

## Errors, privacy, performance, observability

422 invalid content/answers;404 absent/cross-tenant/not owned;403 wrong role;
409 stale revision/expired/exhausted/conflicting replay. No partial audience writes.
UI retains local unsaved edits, explains disabled actions, server errors visible,
no automatic retry of unknown create/assign/submit mutations. Session/tenant change
clears loaded data and stale responses are ignored. Accessible radio/checkbox
questions, keyboard focus, mobile390 layout. List responses bounded/paginated
explicitly; no false totals. No answers/key content logged; evidence synthetic.
Use current database transactions and request logs, no separate workers/telemetry.

## Verification / rollout / stop conditions

Ready: accepted API/schema, module ownership, role/tenant boundaries above.
Local pure/schema/API tests: all three question types, hand-scored results,
partial/duplicate/foreign answers, no keys, stale edits/idempotency, timing/retry.
Real Supabase isolated migration/RLS tests: cross-tenant and foreign user negative,
concurrent starts/submits, immutable snapshot/results, current schema preserved and
approved cleanup. No local Docker PostgreSQL.
Frontend tests/built browser: create+publish+select audience+assign, student
start/save/reload/submit/history, author results, retries, new version with old
result preserved, session isolation, mobile and failure recovery. Preserve old
course quiz suite; complete required baseline/release gates.
DEV ordinary permanent synthetic tenant: full real role/API/UI chain and retained
course/lesson counts. Production only exact CI/image/schema/worker/native evidence,
rollback ready, then same full synthetic ordinary-role journey. Keep QA fixtures.
No model calls. Stop unsafe migration/RLS, unknown mutation or failing gate;
reconcile by owned GET rather than blind retry. Done only actual DEV and production
acceptance with saved evidence, not local tests or technical deployment alone.

## Accepted integration amendments (2026-11-15)

- List and result responses `{items,has_more}` with limit50/max100 and offset;
  author list summaries omit question bodies/keys. Author detail contains content.
  Assignment results include employee_label/user_id/attempts. Attempts expose
  public content as `snapshot`, answer selections as `selected_choice_ids`.
- `knowledge_checks.create_sha256` stores the immutable initial content hash so
  retrying a lost create after subsequent edits never overwrites a later revision.
- Audience V1 is primary role student, is_active=true, status=active. Existing
  UserResponse exposes optional persisted status (legacy absence is null, never
  interpreted as active). This is an additive read interface impact; no user writes.
- Assignment UPDATE(id) privilege exists solely for PostgreSQL row locking;
  immutable trigger still rejects updates. Ordinary DELETE denied by per-command
  policies. Existing explicit superadmin whole-tenant deletion may remove the three
  children in dependency order; admin service deletion list is the only additional
  ownership consumer. No standalone delete route. Old rollback cannot delete a
  tenant containing new evidence until the new purge-aware application is restored;
  it fails safely rather than removing learning history.
- Personal course-link authentication remains enrollment-scoped and is rejected
  by new learner routes. Ordinary account/kiosk role validation is unchanged.
- Downgrade locks new tables, temporarily obtains owner visibility and restores
  FORCE before its decision; refuses populated data. Rollout is additive, old
  application rollback retains0188 and all new evidence.
- New deterministic unit files are under apps/api/tests/unit so ordinary CI runs
  them. Isolated real DB gate additionally asserts source hashes did not change
  during execution. No model-processing ledger run exists: zero inference.
