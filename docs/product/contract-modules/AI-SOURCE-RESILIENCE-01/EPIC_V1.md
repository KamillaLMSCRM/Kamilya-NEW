# AI-SOURCE-RESILIENCE-01: resilient large-source generation

Status: Accepted for implementation; release acceptance remains open.
Document version: V1. Template: V2. Supersedes: None.
Decision date: 2026-09-10.
Approved by: product owner (current request to plan and implement); Astra root
owns bounded technical decisions, integration and release gates. No new provider,
billing, infrastructure, customer mutation or production deployment is authorized
by this contract itself.
Change control: module owner proposes -> root reviews/tests -> root accepts a
versioned addendum within existing authority; product owner approves material
scope/authority changes or cancellation. Accepted predecessors are retained.

## Objective, roles and acceptance

An authorized methodologist can generate and inspect a saved course and assessment
from the representative large Excel without losing the document tail, restarting
successful map batches, or failing solely because navigation summaries exceed an
arbitrary 320-character allocation.

- Product owner: Kamilya owner; business scope, privacy and release authority.
- Root/module owner: Astra; mapper, caller integration, combined tests and decision.
- Checkpoint module owner: bounded Terra worker; assigned two new files only.
- Reviewer: independent Luna worker after assembly, then root acceptance.
- Immediate root critical path: mapper contract/red tests and consumer integration.
- Sidecar: implement bounded job-scoped checkpoint storage while root repairs mapper.

States: selected -> converted -> batches mapped (with per-batch validated checkpoints)
-> overview assembled -> architecture -> lessons/questions -> saved draft -> inspected.
Failure/cancellation never publishes or silently skips sources. Retry within a job
can reuse only matching validated checkpoints. New job cannot reuse old job data.

Success requires representative full-input map PASS, repeated real provider test,
saved modules/lessons/quiz/questions, source-grounded spot checks, requested language,
browser readback and synthetic cleanup. AI-COURSE-01 remains mandatory. Mechanical
chunk coverage is not proof that every fact is taught.

Exclusions: Excel parser redesign, automatic customer-document reindex/publication,
provider ordering/keys, quotas, embeddings, UI, new tables/migrations, infinite retry,
cross-job/shared cache, source text in logs, raw response logging, silent truncation.

## Directed modules and impact matrix

Pipeline -> DirectSource architect -> SourceTopicMap -> LLM client.
Pipeline -> job-scoped MapCheckpointStore -> existing internal Redis.
Mapper -> optional load/save callbacks -> MapCheckpointStore.
Detailed map -> bounded architect overview; lesson writer still reads original corpus.

| Existing module | Class / change | Negative-space invariant | Check |
|---|---|---|---|
| source_topic_map | Invariant: separate extraction and overview bounds; precise failures; one local retry | exact IDs, original text, deadline/concurrency/request caps | mapper interface tests |
| direct_source | Compatible optional checkpoint argument | small-source path and grounding | direct-source tests |
| pipeline | Compatible wiring and terminal cleanup | job authorization, quota/refund/save semantics | pipeline/cancellation tests |
| llm_client | Compatible read-only route fingerprint | provider selection, secrets, transport unchanged | fingerprint + failover tests |
| Redis checkpoint adapter | New internal ephemeral state | no API exposure, no other keys | synthetic adapter tests |
| documents/embeddings/assessment/auth/UI | None | conversion, vector provenance, quality and roles | AI-COURSE-01 + neighbor suites |

Unlisted impact stops work until a versioned addendum. No new table/migration.

## MAP mini-spec V1 (core and applicable extended fields)

Responsibility: bounded source navigation preserving complete source-ID association.
Non-responsibilities: factual assessment, document conversion, authorization, publishing.
Contribution: robust navigation for large-source architecture, without 320-char veto.
Interface: existing build_source_topic_map(corpus, llm, check_cancelled=...) -> immutable
SourceTopicMap, extended with optional checkpoint load/save callbacks. Existing callers
remain valid. compose_architect_overview(map) -> bounded string, no new LLM calls.
Inputs: same authorized immutable corpus, tenant-scoped LLM, optional scoped store.
Outputs: detailed records plus exact source metadata, then separate compact overview.
Data owner: mapper owns local records; checkpoint adapter owns ephemeral copies.
Readers: direct-source architect and same-job retry only. Original chunks remain in corpus.
State: each batch pending -> validated -> checkpointed; complete map only after all pass.
Idempotency: request digest covers actual source/metadata, prompt/parser version,
output configuration and batch identity. Storage namespace adds tenant/job/config route.
Revalidate every cached response. Invalid cache is a miss, never accepted as source truth.
Invariants: all IDs exactly once, no foreign/duplicate/missing IDs, no new facts, no raw
source clipping, same maximum 64 batches/24k request/3 parallel/90 seconds. At most two
application calls per uncached batch (existing provider transport retries unchanged).
Detailed output bounded independently: <=8000 chars, <=2048 output tokens, <=3 records,
<=16 topics/record, <=160 chars/topic, <=1600 summary chars, <=6000 aggregate chars.
Overview: <=24k chars; prefer complete detailed form if it fits, otherwise deterministic
topics-only representation retaining EVERY topic and EVERY source association and
explicitly marking omitted summaries. If even that does not fit, precise terminal
overview-budget error, not prefix sampling or unseen LLM summarization. Detailed map
remains available during the job; original corpus remains writer's factual source.
Error modes: safe reason codes for JSON/schema/topic/summary/content/coverage/budget;
one bounded full-source retry only for formatting/length, never foreign/missing IDs,
auth/transport exhaustion or cancellation. Repair cannot silently drop source IDs.
Security: source/metadata/generated strings untrusted; escape delimiter-like text,
JSON-safe overview records, no raw provider payloads or keys in error messages.
Observability: safe reason, batch/attempt counts; no tenant payload or key values.
Dependencies: injected llm.ainvoke and optional scoped storage only.
Forbidden: DB/provider configuration writes, UI changes, unbounded reduction calls.
Read/write: root owns source_topic_map.py, direct_source.py, pipeline.py, llm_client.py
and their proportional tests. Experimental prompt-only changes are superseded through
reviewed edits, not reset of the dirty checkout.
Ready: reproduced failure classes, caller inspected, contract accepted. Done: interface,
neighbor and full representative live gates pass, with evidence labels kept distinct.

## CHECKPOINT mini-spec V1 (core and applicable extended fields)

Responsibility/contribution: preserve validated batch outputs for same-job recovery.
Non-responsibilities: provider invocation, accepting output, source authorization.
Interface: SourceMapCheckpointStore(tenant_id, job_id, config_digest, client=None);
async load(batch_digest)->str|None; save(batch_digest, content)->None; clear()->None.
Inputs: canonical UUID tenant/job, lowercase SHA256 config/batch digests, bounded text.
Outputs: opaque cached text or miss; mapper always performs schema/coverage validation.
Data owner/writer: this adapter; reader same authorized pipeline job. One Redis hash
key per tenant/job/config, digest fields; maximum 64 fields enforced atomically or
store uses bounded fixed per-batch keys instead. No key enumeration outside namespace.
Retention: 1 hour TTL via atomic write+expiry; clear on success/cancellation, failure
retains until TTL to permit same-job retry. Terminal cleanup failure must not mask success.
No tables, schema changes or API serialization. Existing internal Redis only.
State: absent -> bounded entry -> hit/expiry/clear. Concurrency: atomic writes/TTL,
idempotent clear; no blocking sync IO. Not a cross-worker job execution lock.
Performance: per-operation async deadline <=1 second; Redis unavailable/corrupt ->
miss or no-op, not course failure; cancellation propagates. No logs of content/errors.
Security: strict IDs/digests, values <=32KiB UTF-8, no secrets/source file contents;
tenant/job/config namespaces disjoint. Constructor gets no credential values.
Client from existing settings, lazy redis.asyncio with short socket timeouts; injected
fake for tests. Close owned clients, never close caller-owned fake/shared clients.
Read scope: this contract, core/redis_progress.py pattern, config REDIS_URL name only.
Write scope: apps/api/app/modules/ai/source_map_checkpoint.py and
apps/api/tests/unit/test_source_map_checkpoint.py only (Terra worker).
Forbidden: .env, network, Redis server, DB, production, dependencies, neighboring files.
Checks: isolation for tenant/job/config, digest validation, corrupt/oversized data,
expiry atomicity, repeated writes/clear, timeout/outage fallback, cancellation/close.
Stop: new dependency/table or unlisted write required. Ready: contract frozen.
Done: tests and root review PASS; real Redis gate separately NOT VERIFIED until run.

## Verification, rollout and cleanup

1. Pin local baseline and preserve unrelated dirt. Red synthetic regression reproduces
   actual >4 topics/>320 chars and selective retry before repair.
2. Focused mapper/store/consumer tests; malformed response, duplicate/missing IDs,
   932-source tail coverage, overview fallback, cache poisoning, isolation, cancellation.
3. Neighbor direct-source, pipeline, assessment and failover tests; quality baseline.
4. Run exact AI-COURSE-01 tests and DEV gate using approved Supabase (no local Docker DB).
5. Real provider bounded 932-source probe, then full disposable course acceptance with
   explicit time/call budgets. Reuse only owned source fixture; remove generated artifacts.
6. Independent review, AST update/impact comparison, changelog, release candidate gates.
7. Only then exact-SHA authorized production release and independent business readback.

Rollback: previous product image, no schema rollback; new optional cache keys expire.
Stop on source loss, unsafe cache scope, unacceptable latency, failed representative
test or new authority boundary. Root records evidence and disposition. Client GO is
withheld until complete user-flow acceptance, not merely compilation or deployment.
