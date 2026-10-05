# WB-LESSON-CORRECTION-PREVIEW V1

Status: Accepted for local implementation, 2026-10-05. Template V2.
Approved by: product owner "го" after the foundation and next-step report;
root accepts the bounded preview integration. Root/module owner: root. Product
owner: repository owner. Reviewer: read-only leaf plus Test & Evidence Runner.
Preserves LESSON-CORRECTION-FOUNDATION V1 unchanged. Change control: versioned
addendum before application, published revision, legacy-source or runtime changes.
No provider/tier/billing/public-schema/production change is authorized here.

## Responsibility and interface

An active, ordinary methodologist asks for one source-grounded correction to an
existing evidence_v2 draft lesson and can reload the exact before/after proposal.
No text is applied. The new module owns authoritative context resolution,
bounded proposal generation and durable preview identity; the foundation owns
admission policy. Interfaces: create/read correction preview and the existing
structured editor patch/pure correction policy. HTTP additions under existing
workbench: POST `/lesson-correction-previews` and GET
`/lesson-correction-previews/{plan_id}`. Body: request_key UUID, lesson_id UUID,
instruction max4000 and locale ru/kk/en. No tenant/actor/course/source IDs or
provider/approval/publication fields. Independent correction flag defaults OFF
and also requires the existing workbench flag; no apply route exists in V1.

## Context and proposal rules

Join lesson -> module -> course with independent tenant predicates on every row.
Only text lessons in a draft course with no lesson published_at are supported.
Course version is canonical SHA-256 of the current complete release-snapshot
payload, lifecycle/current release, approval policy and revision state/hash set;
lesson version hashes its complete current payload and publication metadata.
Neither updated_at nor an old approved snapshot substitutes for live content.
No source-free, content-block-only, archived or published correction is admitted.

First source adapter is original-document evidence_v2: existing
`build_direct_source_corpus` verifies active tenant ownership and actual blob
SHA256, then existing `build_evidence_source` reconstructs facts. Each stored
lesson reference must have a unique stable fact_id, matching doc_id and exact
source_locator equal to a freshly reconstructed fact. Old writer references
without stable identity fail `lesson_source_provenance_unavailable`, rather than
silently selecting a first chunk or a nearby heading. This intentionally bounded
legacy gap is not a regression/change to existing generation or manual editing.
Only the lesson's admitted facts reach the model; subject/attribute/value form
the evidence text. A short fact locator plus SHA256 of that text is bound to
current document version/SHA/index_revision. No embedding/model request is made
to resolve evidence and no source index is written. Reindexing invalidates the
plan conservatively; active embedding retrieval is a separate future adapter.

No silent clipping: existing original-source conversion bounds remain; at most
five sources/64 facts, maximum24000 source characters, total serialized prompt
32000 characters and lesson before/after bounded by foundation. Model returns
only changed content and unique evidence ordinals, or a closed clarification
code. Code attaches all UUIDs, hashes, exact operations and actual provider/model
provenance. Strict JSON object, duplicate keys/extra fields/types/unknown evidence
and unchanged content are rejected. Reuse validated LLM invocation, no syntax
repair and no extra semantic repair loop, transport retries0 per configured
provider, timeout45seconds. Reuse deterministic `evaluate_lesson_quality` on
exact cited excerpts; its PASS is not semantic entailment. Human source review
and real-provider acceptance remain required. No model-supplied PASS/authority.

## Data ownership, state and concurrency

Workbench owns new `workbench_lesson_correction_plans`: tenant/actor, UUID request
key, request digest, immutable resolved snapshot, created/expiry, status,
normalized proposal/provenance/seal or fixed failure code, finished timestamp.
Document, course, lesson, approval, quiz, release and budget owners do not move.
Only preview module writes its records; lesson/course/test/history writes are
forbidden. Before/after text and instruction are required reviewed draft data,
not logs, audit payloads, URLs or telemetry. No source-body copies in the table.

States: absent -> pending -> ready or failed. Unique tenant/actor/request_key
claim is inserted before provider work. Claim and existing optimistic budget
admission commit atomically. Same-key same-body returns existing result/pending;
same-key different-body conflicts. It never repeats model work or recharges.
No automatic restart of an interrupted pending request; a new deliberate key is
required. Re-resolve authoritative context after model work before ready. Foreign
actor/tenant is404, stale source/content or role change fails safely. Get never
calls the provider, charges budget or writes content. Ready/failure is immutable.
DB owns created/finished times; snapshot carries a maximum15-minute lifetime.

Existing monthly tenant AI budget is preserved; zero is denied explicitly before
the existing helper's default fallback. Use existing10-cent optimistic admission
estimate, refund failed/clarification/stale/cancelled proposals once while closing
the owned pending record. No change to configured budget/spend limits, provider
order/models or pricing; estimate is not actual provider cost. Cross-month refund
or crash reconciliation is NOT implemented by the shared existing helper and is
a recorded external-accounting limitation, not an idempotency promise.

## Migration, security, retention and negative space

Additive0176 table, RLS + FORCE RLS, tenant AND actor read/insert/update eligibility,
runtime lms_app without BYPASSRLS, no broad existing grants. Only terminal proposal/
fingerprint/error state columns may be updated; trigger prevents snapshot/owner/
request/time mutation and terminal overwrite. Downgrade refuses populated table.
Superadmin purge remains exact tenant-scoped; add the table to canonical purge.
No SECURITY DEFINER, new key, role union or impersonation path.

Preview-only records use existing expired-plan metadata lifetime: deletion no
earlier than expiry+24hours. Do not activate a scheduler in this slice. Canonical
synthetic tenant purge removes these records; a future bounded retention runner
requires its own tested invoker/dry-run contract before rollout. Successful apply
receipts will require the separate90-day policy; none exists in this table now.
Public schema and runtime activation remain gated; isolated Supabase DEV tests
must precede any public deployment. No database is created on this workstation.

Directed map: workbench -> read-only courses/approval/documents/source adapters
-> normalized evidence -> validated AI proposal -> pure correction policy
-> owned preview store -> HTTP read. No inverse writer or domain mutation.
Impact/write scope: new correction_context/proposal/schemas/models/service/router
and focused tests;0176 migration; compatible model registry/config/router include
and canonical tenant purge row; current plan/module index/changelog. Consumers:
existing release snapshot, evidence source, lesson quality, budget and validated
LLM interfaces remain unchanged. Auth/editor/generation/workers/queues/UI/learning/
mail/invitations/assignment/publish/landing/providers/infra remain unchanged.

## Verification, errors, Ready/Done and rollout

Safe closed domain errors only; no reflected provider/validation/DB payloads.
Tests cross resolver/proposal/create/read seams with deterministic fakes: foreign
chain/source, live course/approval/lesson/source changes, malformed/missing facts,
exact evidence text/hash, unsupported legacy/published content, prompt budget,
strict model output and quality, no provider on denial/stale/replay, budget zero,
single charge/refund, failed/pending/read/replay, actor loss and immutable seal.
Canonical isolated DEV must prove migration current/empty upgrade, RLS/runtime
ACL/trigger, same-key concurrency, context staleness and exact cleanup/public
neutrality. HTTP tests cover flag OFF, ordinary role/actor, body authority denial,
response/no-store/errors and absence of apply. Keep foundation/editor/workbench
and named AI-COURSE-01 source-quality regressions; sync CodeGraph once after delta.

Ready: exact context/fact identity, durable state/financial limits and write owners
fixed above. Local Done: focused contracts/quality/independent review; NOT release
GO. Feature Done: isolated DEV plus actual source/proposal semantic and browser
acceptance after UI/application addenda. Stop before unlisted writes, semantic
guard weakening, new legacy/published behavior, ownership ambiguity or external
authority/billing expansion. Root records disposition. Rollback disables the new
flag, preserves plans/data, and never drops a populated table. Production remains
unchanged; no release packet exists until the assembled end-user flow passes.
