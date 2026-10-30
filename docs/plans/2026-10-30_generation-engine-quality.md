# Generation quality implementation, 2026-10-30

## Authority and outcome

Product owner: the requesting owner; implementation approved by `делай` after the
source-to-course audit. Root/module owner and local reviewer: OpenCode. Review in
this session is self-review, not an independent-agent acceptance. Production
release and a new usage-based provider budget require their own current authority.

Follow-up owner approval: one separate commit/branch push for CI, and at most four
control requests through the existing Luna connector with reasoning, within the
current subscription and zero additional monetary cost. Stop before inference if
absence of extra charges cannot be established. No production release follows.

Outcome: original rules survive conversion, lesson writing, assessment and durable
restoration; completion reports actual teaching/assessment gaps. Existing customer
courses, provider routing/billing, roles and completed training are preserved.
Journey: AI-COURSE-01. Source: generation-engine handoff in cabinet-release-20261018.

## Sequence and exit criteria

1. Restore correctness: native empty-repository cold start, policy/type baseline,
   source/lesson/catalog/question revalidation, no repeated author/critic calls for
   committed work; malformed, incomplete and foreign state fails closed. LOCAL/DB
   VERIFIED (ordinary path); independent review and actual worker acceptance OPEN.
2. Independent coverage: original-rule denominator separate from questions, retain
   67 families/16 ambiguities and original-bound errata; teaching, premise-only and
   assessed evidence are distinct. OPEN.
3. Source blocks: preserve full rule/governor/definitions/references/exceptions;
   verify six boundary classes through actual worker seams. OPEN.
4. Teaching and questions: readable explanations, source-complete branches,
   independent per-option entailment, explicit unknowns and scoped repair. OPEN.
5. Resource continuity: durable physical-attempt accounting, bounded repair plus
   final review, worker time boundary and unknown provider/commit outcomes. OPEN.
6. Frozen-candidate acceptance: saved regressions, critical journey, isolated
   Supabase transaction/RLS gate, bounded actual-model control, three complete
   courses and ordinary UI/API readback. OPEN; technical green is not quality GO.

## Restore interface addendum / implementation packet R1

Responsibility: the existing application owns complete ordered lesson realization;
WorkerLessonAssessor owns source-plan and question validation; WorkerCycleJournal
and AIGenerationCheckpointRepository own tenant/job-scoped storage. No new table,
queue route or ownership transfer. Existing source/cycle journals remain canonical.

Directed seam: generate_evidence_course -> restore_realization/read_owned_realization
-> repository; restored body -> native surface/catalog validation -> native
source/lesson-cycle readback -> exact exported questions. The cache must not grant
semantic approval or replace a native validator with an asserted Boolean/hash.

Inputs: tenant/job, immutable source inventory and base lesson, course intent,
ordinal, ordered preceding lesson digest, source/cycle/surface/language policies.
Output: absent checkpoint means normal first generation; complete compatible state
restores exact body/catalog/questions and gaps; every other state is a sanitized
explicit error. A missing plan alone is a cache miss; DB/permission failures are not.

Invariants: no provider call during completed restore; no loss of old negatives;
no cross-tenant/job/source/policy/ordinal/prefix reuse; current native question and
surface validators run; reviewed prose is not re-rendered through an unreviewed
fallback; exact final content determines teaching. Ordered state is reconstructed
before the next lesson. Usage on restore is distinguished from original usage.

Compatibility/rollback: new realization policy identity isolates unaccepted old
snapshots. Ordinary generation without a realization-capable assessor remains
supported. Remove only this packet to return to 0f073 delivery/telemetry baseline;
retain existing source/cycle checkpoints and incomplete-work diagnostics.

Verification: RED cold-start probe at actual repository; native assessor with
forbidden-provider spy; JSON-wire roundtrip, source/body/key/catalog tampering,
partial/cancel/crash/prefix controls; affected suites and canonical Python baseline;
isolated DEV database gate before runtime acceptance. Read scope: AI modules,
related tests/runbooks. Write scope: application, worker adapter, focused tests,
error/changelog/readiness docs, this plan. Shared-contract changes require an
addendum here before implementation. Stop on unrelated source edits, inconsistent
source identity, unapproved provider spend or unavailable native evidence.

## Source/learner projection addendum R2

SOURCE-DERIVED candidate: prepare_source_plan binds the source-only base lesson,
but the writer may legitimately change the learner title/objective. Passing those
new presentation fields back into source planning changes the journal key and
can repeat source extraction or reject the previously prepared plan. Verify this
with the native application/assessor before changing code. The source-plan owner
must retain its prepared base lesson for unchanged exact fact/support IDs; the
question packet must still use the final learner title/body. Changed ownership
must fail before provider work. Direct assessor callers without preparation retain
their old behavior. No source/audit vote, mode or coverage rule is relaxed.

Implemented and TEST-DERIVED: title/objective rewrite -> same source/audit transcript -> native
questions -> JSON restore without model calls; changed fact/support ownership
rejected; existing direct callers and supported semantic path retain their gates.

## Navigation evidence

SOURCE_FALLBACK: realization worktree has no CodeGraph runtime; cabinet preflight
reports changed sources. Prior bounded CodeGraph search resolved the factory
(18ms query body; seven candidates), callees had no usable edges (17ms body).
Graphify query (750-token budget) returned 22/304 nodes from a stale snapshot.
These are navigation limits, not absence of consumers or semantic proof. Exact
producer/consumer source reads establish the restore chain. No tool token/cost
savings measured. Refresh only available local indexes once after source freeze.

Final sync attempted once in this checkout after freeze: pinned runtime missing.
No graph rebuilt or links inferred. All decisive links were checked in source and
native seam tests; no token counters exposed.

## Current evidence and next boundary

Final source fingerprint444db69b70e04d99298ca912ab6bc6d11f55e22c1df523d60da5ae897558a4b2;
3636 unit PASS, eight additional neighbor/gate cases PASS, canonical baseline PASS,
actual isolated Supabase DEV restore/RLS/cleanup/public0183 gate PASS. Exact receipt
and detailed test history are owned by readiness/error log/test ledger.

Remaining source-rule/semantic-block/pedagogy and whole-course work is OPEN. Before
model acceptance, freeze/review the intended packet and obtain a concrete current
provider-use budget; historical8M-token output does not authorize another run.
No source selection, source meaning or quality standard was changed to obtain green.
