# Assignment reload and isolated validation addendum V1

Status: Accepted by root, 2026-10-01, under owner's "продолжай".
Extends ASSIGNMENT_EXECUTION_ADDENDUM_V1; predecessor remains unchanged.
Owner/integration/migration decisions: root. UI writer: workbench_plan_reload;
independent acceptance: Test & Evidence Runner, root final review.

## Responsibility and scope

Restore an owned preview or succeeded receipt after a browser reload, without
automatic confirmation, repeated assignments, client-persisted authority or PII.
Existing workbench/auth/enrollment/notification interfaces remain authoritative.
Only workbench UI/client/tests/page, owned DEV gate, owned backend tests and
canonical plan/index/changelog/handoff/error evidence may change. No production,
public DEV migration, delivery, provider, billing, AI, voice or retention mutation.

## URL and state contract

`/methodologist-workbench?plan=<UUID>` stores only the opaque plan locator.
No instruction, credentials, employee names, audience, fingerprint or receipt in
URL/Web Storage. The locator grants no access: authenticated owned-plan GET
checks tenant, actor and active role and returns no-store preview/receipt.

Creating a preview replaces the plan locator; successful confirmation retains
it so a reload restores the receipt. Clarification, explicit new command,
context editing, invalid locator or denied/missing/expired read clears it.
Reload never issues POST. Loading/error states prevent confirming absent state;
all late responses are canceled/ignored on context or session changes. Restored
preview shows server timezone/scope/notify and says original instruction was
not stored. Receipt reload cannot resurrect an actionable preview.

## Isolated runtime validation

Root extends `scripts/ops/workbench_assignment_dev_gate.py`, using the same
canonical Supabase DEV identity, owner/runtime roles and exact disposable
`workbench_<12hex>` schema. Fixtures have synthetic activated learner accounts
and `.invalid` addresses. No invitation preparation or mail dispatch is tested.

Existing public enqueue is SECURITY DEFINER with fixed public search_path:
do NOT call it from an isolated schema. Extract its accepted body from migration
0097 via Python AST plus the exact nullable-actor correction from0154; compare
with read-only live `pg_proc.prosrc` before use. A mismatch blocks the gate.
Install only that enqueue function into the owned schema with fixed owned
search_path, owner-scoped FORCE RLS outbox and no direct application/recovery
table access. Verify unqualified runtime function resolution is owned, not public.
No delivery/recovery functions, Celery dispatch or discovery interface is installed.
This is actual PostgreSQL application/queue atomicity evidence, NOT worker,
provider delivery or production notification acceptance.

Test notify=true rollback and commit, one outbox per enrollment, exact receipt
binding, replay with zero dispatch IDs, receipt GET, two distinct preview plans
competing for one audience, and an overlapping existing manual enrollment.
The stale plan must fail; manual deadline/history remain untouched.
New hires after the guarded re-read are outside this one-time audience; this
does not create an automatic rule or claim serializable organization mutations.

## Gates, stop and rollback

UI transport/reload/session/error fixtures, targeted lint/typecheck, owned and
neighbor API tests, independent read-only review and extended isolated runtime
gate must pass. Keep original failures and classify harness/source/access drift.
Cleanup drops only the exact validated owned schema and independently confirms
absence plus unchanged public revision/table inventory. No broad cleanup.

Retained runtime evidence does not close metadata retention, invite/activation,
full production-neighbor RLS, browser DEV acceptance or release gates. Both flags
remain off. Rollback reverts owned source changes or leaves flags off; no deletion
of durable business assignments/history. A new data/ownership/provider boundary
requires another root-approved addendum, and exact owner authority where required.
