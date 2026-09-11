# Adaptive and resumable AI course generation

**Status:** local implementation and isolated DEV migration/RLS complete; production acceptance pending
**Baseline:** `5b423ec184bfa9184cdb30179ad7dedd6debfd2b` (`origin/master`)
**Scope:** course structure planning, durable per-lesson checkpoints, bounded
resume, actual learning-duration readback, and representative acceptance.

## Observed failures

The production synthetic Excel exercise established two distinct failures:

1. `automatic` stopped during structure construction with
   `direct_source_structure_invalid`.
2. `standard` produced most of a 25-lesson course and then stopped with
   `SoftTimeLimitExceeded`; generated lessons existed only in worker memory and
   could not be resumed.

The preflight also displayed the same 1895-minute estimate for different course
formats. That value was derived from technical source chunks rather than the
actual planned lessons and is not a valid learning-duration estimate.

## Product contract

### Adaptive scope

Course format is a depth and coverage preference, not a minimum content quota.
The planner must intersect three constraints:

1. source-supported capacity;
2. the selected format's maximum scope;
3. an optional methodologist override that may reduce scope but may not force
   unsupported filler.

A tiny source may therefore produce one to three lessons under any format. A
larger source may produce progressively more coverage under `brief`, `standard`,
or `detailed`, up to finite format caps. The current technical inputs
(`total_chunks`, `document_count`) are capacity proxies, not semantic topic
counts; reason codes and UI wording must say so. Semantic topic capacity is a
future enhancement and must not be claimed before it is measured.

### Learning duration

Preflight returns a range derived from the recommended lesson count and format.
After generation, the authoritative duration is the sum of every lesson's
server-calculated duration. Source size alone never becomes course duration.

### Partial completion and resume

One user-visible generation remains one logical job. A later queue delivery may
resume it, but must use the same immutable plan revision and source identity.
After each completed lesson, quality review, and assessment the worker stores a
tenant-scoped checkpoint. If 15 of 25 lessons are complete, the durable state is
15 complete content items and 10 missing content items. A later queue delivery
continues the same logical job and claims only missing or expired items. It does
not rerun the architect or regenerate completed content, reviews, or assessments.

No partially generated `Course`, `Module`, `Lesson`, `Quiz`, `Question`, or
`QuizChoice` becomes learner-visible. Final course persistence remains one
transaction and is allowed only when all planned lessons and required
assessments are complete. Cancellation remains terminal and blocks final save.

## Implementation phases and gates

| Phase | Change | Verifiable exit gate |
|---|---|---|
| A | Pure adaptive scope planner | Tiny sources are not padded; results are deterministic and monotonic; large-source caps satisfy `brief < standard < detailed`; manual overrides cannot exceed source capacity |
| B | Preflight and UI contract | API and UI show recommended total lessons, hard maximum, duration range, and stable reason codes; old clients retain existing fields |
| C | Durable generation/run checkpoints | Additive migration has one head; tables are tenant-scoped with RLS and FORCE RLS; plan identity is immutable; runtime cannot delete checkpoints; duplicate item completion is idempotent |
| D | Checkpointed content, review, and assessment loops | A deterministic 25-item test stops after content item 15; resume makes writer calls only for 16-25, performs each still-missing downstream review and assessment exactly once, and leaves completed payloads/order unchanged |
| E | Interruption and resume operation | Soft time limit produces `interrupted`, not generic failure; a bounded resume delivery reclaims only missing/expired work; cancellation cannot resume or save |
| F | Finalization and actual duration | Incomplete plans cannot create or replace a draft; a complete plan creates exactly one ordered course tree; displayed duration equals the sum of lesson durations |
| G | Quality and acceptance | Tiny, medium, and large synthetic sources pass; questions remain source-grounded; no self-referential questions; one bounded Supabase DEV run proves 15/25 resume and cleanup |

## Local implementation readback

- Adaptive capacity planning no longer treats a profile range as a minimum:
  tiny sources remain one to three lessons; large sources are bounded by the
  selected profile.
- The accepted whole-course lesson limit is propagated through the queue,
  semantic architect, and direct-source architect and validated before writing.
- Migration `0158` adds tenant-scoped immutable plans plus per-lesson content,
  quality-review, and assessment checkpoints. Atomic stage-ordered leases are
  acquired before provider calls and released only by the current delivery.
  The runtime role has no checkpoint-delete privilege.
- Soft time limits now produce `interrupted`; the same logical job can be
  queued again without a second quota or budget charge. The frontend preserves
  that job and offers `Continue from saved progress`.
- A deterministic orchestration test interrupts a 25-lesson run immediately
  after content checkpoint 15. The second delivery reuses the plan, makes
  exactly ten further writer calls, then performs every still-missing review
  and assessment once. A third replay makes zero architect, writer, reviewer,
  or assessment provider calls.
- Current local verification: the complete backend unit suite passed (1,240
  tests); the complete frontend suite passed (110 files, 572 tests); frontend
  typecheck and lint passed. The focused backend regression set for admission,
  checkpoints, resume loops, and pipeline integration passed (35 tests).

## Isolated Supabase DEV readback

Migration `0158` was applied, downgraded, and reapplied in a randomly named
disposable schema on the canonical Supabase DEV project. The gate used the
restricted `lms_app` runtime credential, not a local PostgreSQL instance.

The live PostgreSQL run proved:

- both checkpoint tables have RLS and FORCE RLS;
- `lms_app` has no checkpoint `DELETE` grant;
- a second tenant cannot read the first tenant's plan, and an unset tenant
  context sees no plans;
- two concurrent deliveries produce exactly one lease winner;
- an expired lease can be reclaimed with an incremented attempt count;
- content, review, and assessment checkpoints reach one complete ordered plan;
- cancellation remains terminal when it races with resume, and a late worker
  update cannot resurrect the cancelled job.

The first live run exposed an asyncpg bind-type ambiguity in owner-guarded
checkpoint completion; the nullable lease owner is now explicitly cast. The
next run exposed stale SQLAlchemy identity-map state after a concurrent cancel;
locked job reads now use `populate_existing` so `FOR UPDATE` refreshes the row
after waiting. A regression test fixes that contract in the unit suite.

The final gate passed all checks, removed its disposable schema, and confirmed
that the shared public migration revision remained `0156` before and after.

PostgreSQL concurrency, RLS, lease expiry, and cancel/resume are now proven in
the isolated DEV schema. A bounded architect correction now also covers the
exact large-Excel failure in which the first model response contains the wrong
module count; a second invalid response remains terminal. Production provider
and browser readback remain release gates.

## Test matrix

Unit and contract tests do not call external models. Deterministic adapters
simulate successful calls, malformed structure, timeout after lesson 15,
provider fallback, retry, cancellation, and lease expiry.

Required assertions:

- no lesson inflation for 1, 2, and 4 source-capacity units;
- stable plans for repeated identical inputs;
- monotonic but bounded scope as source capacity grows;
- exact propagation of the accepted plan into the worker;
- unique stable lesson keys even when titles repeat;
- exact-item provider leases and immutable checkpoint completion under duplicate deliveries;
- resume does not call the writer for completed lessons;
- quality reviews and assessments resume independently from lesson content;
- incomplete checkpoint sets cannot finalize;
- final course duration equals the sum of persisted lesson durations;
- cross-tenant checkpoint reads and writes fail;
- cancelled jobs cannot be resumed or finalized;
- `direct_source_structure_invalid` remains a bounded terminal contract for a
  genuinely invalid structure, not a retry loop.

Focused checks precede the full backend suite. Database/RLS verification uses the
approved isolated Supabase DEV/test procedure; local Docker PostgreSQL is not
used. Production deployment and customer-facing confirmation require a separate
exact release packet, CI/image/DB/worker parity, and browser acceptance.

## Ownership

- Root orchestrator owns interfaces, integration, canonical documentation,
  final review, Git, and release decisions.
- Adaptive-planner worker owns only planner implementation and focused tests.
- Checkpoint-storage worker owns only the additive migration, persistence model,
  repository module, and their focused tests.
- A separate read-only reviewer evaluates the integrated diff after both writer
  scopes are closed.
