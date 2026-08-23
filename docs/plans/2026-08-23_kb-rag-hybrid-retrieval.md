# KB-RAG hybrid retrieval and knowledge routing

**Created:** 2026-08-23

**State:** ACTIVE

**Objective:** improve tenant document retrieval and agent knowledge routing
without creating a parallel source of truth, mixing embedding spaces, weakening
tenant isolation, or changing production before measured dev evidence exists.

## Evidence contract

Use only `GIT-DERIVED`, `RUNTIME-DERIVED`, `OWNER-CONFIRMED`,
`PROVIDER-CONFIRMED`, `GRAPH-DERIVED`, `INFERRED`, `NOT VERIFIED`, and
`BLOCKED`. Graphify is navigation evidence only. Plans and agent reports are
not runtime truth.

## Global boundaries

- Product retrieval and internal engineering knowledge remain separate
  security domains even when they share an interface.
- No real PII, cross-tenant corpus, production write, provider mutation, model
  switch, reindex, migration, or deployment is implicit in this graph.
- Existing source documents remain canonical. Derived summaries and embeddings
  are replaceable indexes with provenance.
- A repeated report or retrieved passage never becomes a rule, approval, or
  verified fact without the existing root evidence gate.
- One writer owns each file path or external mutation. Agents do not deploy,
  push, alter databases, or activate rules.
- Each node ends with its own tests/evidence and cleanup before the next node
  starts.

## Node summary

| ID | Objective | State | Depends on |
|---|---|---|---|
| HBR-01 | Define a pure embedding-space compatibility contract | DONE | - |
| HBR-02 | Persist embedding provenance through schema and adapters | DONE - isolated PostgreSQL gate passed | HBR-01 |
| HBR-03 | Enforce fail-closed corpus/query compatibility and reindex lifecycle | DONE - local source and isolated Supabase dev application-path gates passed | HBR-02 |
| HBR-04 | Build a synthetic RU/KK retrieval benchmark and baseline | DONE - local synthetic gate | HBR-03 |
| HBR-05 | Add tenant-scoped PostgreSQL full-text retrieval | DONE - isolated normal-plan FTS/RLS gate passed | HBR-04 |
| HBR-06 | Add parallel retrieval, RRF, deduplication, and diversity caps | DONE - local structural and synthetic benchmark gate | HBR-05 |
| HBR-07 | Add post-rank context expansion and citation provenance | DONE - local source and isolated Supabase dev Writer/context gates passed | HBR-06 |
| HBR-08 | Evaluate an optional reranker against the benchmark | DONE - verdict REJECT until a concrete candidate is measured | HBR-07 |
| HBR-09 | Build a separate local agent knowledge router | DONE - local read-only gate | HBR-04 |
| HBR-10 | Complete dev, release, production, and rollback gates | BLOCKED - dev runtime and local CI source READY; remote CI/release/production gates pending | HBR-08, HBR-09 |

## HBR-01 - Pure embedding-space contract

- **Objective:** make semantic-space identity and vector validity explicit
  before any persistence or provider integration.
- **Owner:** root orchestrator.
- **Writer:** root only.
- **Scope:** one pure Python module and focused unit tests.
- **Dependencies:** none.
- **State:** DONE.
- **Interface:** immutable `EmbeddingSpace`, immutable validated `Embedding`,
  and fail-closed `require_compatible`.
- **Exit gate:** exact provider/model/revision/dimensions compatibility; strict
  identifier and dimension validation; finite exact-length vectors; one-shot
  iterable support; stable sanitized error codes; no DB/settings/provider/I/O
  dependency.
- **Evidence:** `GIT-DERIVED` module and unit tests. Test execution belongs to
  the node completion report and must pass before HBR-02 starts.
- **Approval gate:** none for safe local code and tests.
- **Cleanup:** none; no external or temporary objects.

## HBR-02 - Persist embedding provenance

- **Objective:** persist provider, model, revision, native/storage dimensions,
  content hash, source revision, and index timestamps without guessing legacy
  values.
- **Owner:** root orchestrator.
- **Scope:** Alembic migration, persistence adapter, read/write contracts, and
  migration tests on an isolated dev database.
- **Dependencies:** HBR-01.
- **State:** DONE - source tests and isolated PostgreSQL `0127 -> 0130 -> 0127 -> 0130`
  runtime gate passed with legacy provenance classification and cleanup.
- **Exit gate:** upgrade/downgrade tests pass; legacy rows are explicitly
  classified rather than assigned invented provenance; ordinary tenant RLS and
  FORCE RLS remain effective.
- **Evidence:** `GIT-DERIVED` migration/tests; `RUNTIME-DERIVED` only after an
  isolated database run.
- **Approval gate:** separate action-time gate before any shared or production
  migration.
- **Cleanup:** remove only the isolated test database/schema created by this
  node.

## HBR-03 - Compatibility enforcement and reindex lifecycle

- **Objective:** ensure document and query vectors are compared only inside one
  compatible embedding revision.
- **Owner:** root orchestrator.
- **Scope:** provider adapters, ingestion/query guards, active revision,
  controlled reindex state, and fail-closed mismatch behavior.
- **Dependencies:** HBR-02.
- **State:** DONE - local source/test review and the isolated Supabase dev
  application-path runtime gate are `READY`.
- **Exit gate:** mixed provider/model/revision tests fail closed; no silent
  cross-model zero-padding comparison; partial reindex cannot become active;
  old active revision remains usable until atomic cutover.
- **Evidence:** `GIT-DERIVED` migration `0131`, immutable lifecycle, transactional
  repository, active-revision VectorStore seam, focused regressions, and independent
  reviews; `RUNTIME-DERIVED` evidence `HBR-DEV-APP-20260823T141806Z` proves the
  bounded PostgreSQL 17 lifecycle, concurrency, cutover, rollback, FORCE RLS,
  downgrade/re-upgrade, shared-`public` immutability, and cleanup gates.
- **Approval gate:** external provider probes and shared data reindex require an
  exact gate.
- **Cleanup:** remove only explicitly tagged disposable index revisions.

## HBR-04 - Synthetic RU/KK benchmark

- **Objective:** measure the current retrieval baseline before ranking changes.
- **Owner:** root orchestrator; low-cost agents may author synthetic cases but
  root verifies expected evidence.
- **Scope:** synthetic/public-safe RU/KK documents and questions covering exact
  tokens, paraphrase, OCR-like text, revisions, abstention, and tenant denial.
- **Dependencies:** HBR-03.
- **State:** DONE - local synthetic benchmark gate passed.
- **Exit gate:** deterministic corpus and expected source IDs; recall@5/10,
  MRR, revision correctness, citation completeness, abstention, leakage,
  latency, and cost baselines recorded.
- **Evidence:** `GIT-DERIVED`; no customer data.
- **Approval gate:** none for local synthetic work.
- **Cleanup:** corpus remains a versioned test fixture.

## HBR-05 - PostgreSQL full-text adapter

- **Objective:** make lexical retrieval a first-class tenant-scoped retriever,
  not an emergency fallback.
- **Owner:** root orchestrator.
- **Dependencies:** HBR-04.
- **State:** DONE - isolated PostgreSQL gate passed normal production-shaped
  FTS `EXPLAIN`, GIN valid/ready, FORCE RLS positive/negative checks, and cleanup.
- **Exit gate:** exact identifiers and RU/KK fixtures improve or preserve the
  benchmark; query plans use the intended tenant-scoped index; RLS negatives
  pass.
- **Evidence:** `GIT-DERIVED`, then isolated `RUNTIME-DERIVED` query plans.
- **Approval gate:** shared/production index creation requires a separate gate.
- **Cleanup:** isolated database only.

## HBR-06 - Parallel retrieval and RRF

- **Objective:** run independent semantic and lexical retrieval paths; preserve
  exact-phrase, heading, and document-metadata lexical signals; fuse ranks
  deterministically.
- **Owner:** root orchestrator.
- **Dependencies:** HBR-05.
- **State:** DONE - local structural and synthetic benchmark gate passed.
- **Exit gate:** stable RRF ordering, deduplication, per-document cap, complete
  tenant/provenance trace, tenant/document/revision boundaries, and measured
  benchmark improvement without leakage.
- **Evidence:** `GIT-DERIVED` tests and benchmark report.
- **Approval gate:** none for local/dev synthetic work.
- **Cleanup:** none.

## HBR-07 - Context expansion and citations

- **Objective:** fetch neighboring sections only after final ranking and return
  traceable source/version/page context.
- **Owner:** root orchestrator.
- **Dependencies:** HBR-06.
- **State:** DONE - local source review and isolated application
  `VectorStore.get_context_window`/Writer readback are `READY`.
- **Exit gate:** context never crosses document revision or tenant; prompt
  budget is bounded; learner-visible citations reveal no internal-only data.
- **Evidence:** `GIT-DERIVED` tests and benchmark plus `RUNTIME-DERIVED` evidence
  `HBR-DEV-APP-20260823T141806Z` for active-only semantic/FTS/context retrieval,
  bounded Writer context, safe citations, and tenant/revision negatives.
- **Approval gate:** none for local/dev synthetic work.
- **Cleanup:** none.

## HBR-08 - Optional reranker decision

- **Objective:** add a reranker only when measured quality gain justifies cost,
  latency, and operational risk.
- **Owner:** root orchestrator.
- **Dependencies:** HBR-07.
- **State:** DONE - verdict `REJECT` for adding a real reranker until a concrete
  candidate has measured provider/local evidence; the deterministic evaluator is ready.
- **Exit gate:** baseline comparison records quality, abstention, latency, cost,
  and failure behavior; verdict is explicit `ADOPT` or `REJECT`.
- **Evidence:** `GIT-DERIVED`; `PROVIDER-CONFIRMED` only for an authorized live
  provider evaluation.
- **Approval gate:** provider spend/external calls require an exact gate.
- **Cleanup:** remove disposable provider artifacts if any.

## HBR-09 - Local agent knowledge router

- **Objective:** expose thin read-only retrieval tools over canonical docs,
  Graphify, source/tests/migrations, Git evidence, and inert HERMES candidates.
- **Owner:** root orchestrator.
- **Dependencies:** HBR-04.
- **State:** DONE - local read-only router gate passed.
- **Exit gate:** project scopes are hard; tools return citations and permitted
  evidence labels; no source is copied into a second canonical store; no
  candidate can activate a rule or skill.
- **Evidence:** `GIT-DERIVED` tests and local synthetic evaluation.
- **Approval gate:** none while local and read-only.
- **Cleanup:** local indexes are replaceable and excluded from canonical truth.

## HBR-10 - Release and production gates

- **Objective:** release only the measured compatible pipeline with rollback.
- **Owner:** root orchestrator; owner approves production mutation.
- **Dependencies:** HBR-08 and HBR-09.
- **State:** BLOCKED - earlier isolated dev runtime gate and local structural evaluator
  passed; the PG17 `0131` CI workflow/schema contract is local-source `READY`.
  `0131` application runtime, exact GitHub CI/release, controlled reindex,
  deployment, canary, rollback,
  canonical evidence, and production approval gates remain.
- **Exit gate:** dev tests, isolated DB tests, CI, exact release SHA, migration
  preflight, bounded tenant canary, cross-tenant negatives, latency/cost limits,
  observability, backup, rollback, and post-deploy readback all pass.
- **Evidence:** `GIT-DERIVED`, `PROVIDER-CONFIRMED`, `RUNTIME-DERIVED`, and
  `OWNER-CONFIRMED` production gate.
- **Approval gate:** exact action-time approval for migration, deployment,
  reindex, provider spend, or production data mutation.
- **Cleanup:** remove disposable canary/index revisions and transfer durable
  facts into canonical documentation.

## Current frontier

- `GIT-DERIVED`: local agent-tool tests passed (`10` knowledge-router and `24`
  inert-candidate tests); the earlier complete focused KB-RAG suite passed (`140`
  tests). HBR-03 migration/lifecycle/repository/VectorStore regression now passes
  `121` tests; Python compilation passed; the source migration chain extends to `0131`.
- `GIT-DERIVED`: HBR-04 records a seven-case synthetic RU/KK/OCR/paraphrase/
  revision/abstention/tenant-denial baseline with recall@5/10, MRR, citation,
  leakage, latency, and zero provider-cost evidence.
- `GIT-DERIVED`: HBR-08 evaluator and independent review are ready, but no
  concrete reranker was evaluated. Product verdict is `REJECT` adoption now,
  not permission to call or purchase a provider.
- `GIT-DERIVED`: HBR-09 is a pure stdin/stdout local skill; it creates no index
  or second canonical store and cannot activate HERMES candidates.
- `RUNTIME-DERIVED`: read-only current dev database preflight reports PostgreSQL
  17, pgvector 0.8.0, Alembic `0127`, existing `documents` and
  `document_embeddings`, and no 0128/0129 constraints.
- `OWNER-CONFIRMED`: the owner authorized only the bounded isolated Supabase dev
  mutation executed by this gate; that authority is recorded in the root thread
  and is deliberately not asserted by the runtime evidence artifact.
- `RUNTIME-DERIVED`: evidence `HBR-DEV-20260823T125151Z` in
  `docs/evidence/2026-08-23_kb-rag-isolated-dev-gate.json` records PostgreSQL 17,
  target/source fingerprints, `0127 -> 0130 -> 0127 -> 0130`, legacy provenance,
  constraint validation, active/stale revision and embedding-space SQL contracts,
  FORCE RLS tenant A/B, cross-tenant read/write and no-tenant negatives, normal
  production-shaped GIN `EXPLAIN`, re-upgrade validation, unchanged `public`
  revision/schema metadata, and disposable-schema cleanup.
- `GIT-DERIVED`: isolated gate safety tests passed (`7`), focused FTS/revision
  tests passed (`6`), and the local structural release evaluator passed (`10`).
- `GIT-DERIVED`: independent bounded reviews returned `READY` for both the
  isolated dev gate and the non-actionable local structural release evaluator.
- `GIT-DERIVED`: HBR-06 focused suite passed (`26`); the seven-case synthetic
  comparison improved semantic-only recall@5, recall@10, and MRR by `0.8`, with
  zero leakage and no latency/cost regression. Independent review returned
  `READY`; no production quality, provider, latency, or cost claim is inferred.
- `GIT-DERIVED`: HBR-07 focused suite passed (`36`) and independent review
  returned local-source `READY`; learner citations are projected without
  internal embedding/index metadata, total Writer prompt size is bounded,
  tenant provenance is explicit, and overlapping windows fail closed.
- `GIT-DERIVED`: the combined HBR-05/06/07 local regression passed (`68`).
- `GIT-DERIVED`: HBR-03 implements generation-bound staged/running/ready/active/
  abort/rollback/cleanup state, candidate manifest readback, deferred tenant/document/run
  binding, FORCE RLS declarations, run/pointer CAS, exact non-active cleanup, and active
  revision visibility across semantic, FTS, lexical corpus, and context-window paths.
  Independent migration/repository and VectorStore reviews both returned local-source
  `READY`; no PostgreSQL runtime claim is inferred.
- `GIT-DERIVED`: semantic result decoding now matches the complete SQL column order,
  including tenant identity, provenance, chunk index, and distance; the focused
  regression passed (`20`) and independent review returned `READY`.
- `RUNTIME-DERIVED`: `HBR-DEV-APP-20260823T141806Z` in
  `docs/evidence/2026-08-23_kb-rag-application-dev-gate.json` records the approved
  isolated Supabase dev application gate as `READY`: PostgreSQL 17/pgvector,
  `0127 -> 0131 -> 0127 -> 0131`, application tenant context, FORCE RLS negatives,
  transactional rollback, single-open-run and concurrent CAS, partial-candidate
  invisibility, atomic activation, semantic/FTS/context and Writer/citation readback,
  rollback, exact non-active cleanup, disposable-schema removal, and unchanged
  shared `public`. Independent review returned `READY` for HBR-03 and HBR-07.
- `GIT-DERIVED`: the runtime gate exposed and regression-covered two fail-closed
  defects before release: lifecycle policies now use the canonical `app.tenant_id`
  GUC, and semantic tuple vectors are normalized to pgvector bracket syntax. The
  combined focused migration/repository/VectorStore/runner/schema-contract suite
  passes `69` tests.
- `GIT-DERIVED`: ordinary CI now explicitly compiles and runs both isolated-gate
  safety suites, runs named HBR-03/HBR-07 tests, and evaluates the migrated
  ephemeral PostgreSQL 17 schema read-only at exact Alembic `0131`. The schema
  evaluator binds lifecycle FORCE RLS, embedding revision/run columns, exact
  generation/count/state/binding/FK/event definitions, and the unique partial
  open-run index. Local CI-contract regression passed (`109`); YAML parsed, and
  independent reviews returned `READY` after exact-definition and negative-case
  corrections. GitHub Actions itself has not run, so no remote CI claim is made.
- `NOT VERIFIED`: migration `0131` execution, real transaction rollback, FORCE RLS,
  deferred FK, concurrent CAS/event uniqueness, candidate invisibility/active/stale
  visibility, controlled application reindex/cutover, hybrid benchmark
  closure, context-expansion application DB path, CI, exact intended release SHA,
  immutable artifact, release-bound backup/restore, production approvals,
  canary, observability, deployment/readback, rollback, cleanup, and canonical
  evidence transfer.
- `NOT VERIFIED`: current Graphify freshness after these edits. The attempted
  root command could not run because the repository root has no pnpm importer
  manifest; this is an index-maintenance gate, not runtime evidence.
- Next approval frontier: HBR-10 remote Git/CI and exact-release evidence. The
  completed dev gate does not authorize Git, GitHub Actions, provider calls,
  deployment, shared-schema migration, reindex, or production mutation.
- Mutations performed in this epic: one owner-authorized isolated Supabase dev
  disposable schema, fully removed. Shared dev, production, provider,
  deployment, and reindex mutations: none.

## Next isolated application-path dev gate contract

- **Gate ID:** `HBR-DEV-APP-02`.
- **Authority:** `OWNER-CONFIRMED` and consumed only for the bounded execution
  recorded as `HBR-DEV-APP-20260823T141806Z`; it authorizes no further mutation.
- **Prepared command contract:** the runner remains inert unless both `--execute`
  and `--approval-id HBR-DEV-APP-02` are supplied; these checks happen before
  `.env` is loaded. Preparation and local tests do not constitute execution.
- **Target:** the canonically fingerprinted Supabase dev project only; PostgreSQL
  17 and expected pgvector must be read back before mutation.
- **Isolation:** one random `hbr_kb_app_<suffix>` schema, synthetic UUID tenants,
  synthetic documents, deterministic four-dimensional vectors, no real tenant
  identifiers, document content, contacts, or external embedding provider calls.
- **Preflight:** fail closed unless the public Alembic revision and public schema
  fingerprint equal their recorded pre-gate values, migration sources are schema
  neutral, no residual `hbr_kb_app_%` schema exists, and the disposable schema
  name passes the existing bounded validator.
- **Migration:** bootstrap only the minimal disposable `0127` contour, execute
  `0127 -> 0131`, validate lifecycle tables/constraints/indexes/policies, execute
  `0131 -> 0127 -> 0131`, and never alter the shared `public` revision.
- **HBR-03 application path:** bind the real async session/`VectorStore` to the
  disposable search path; stage one legacy active revision; write a partial
  candidate and prove it is invisible and cannot activate; complete the exact
  manifest; persist READY; atomically activate; prove the candidate is visible
  and the stale revision is excluded across semantic, PostgreSQL FTS,
  `get_all_chunks`, and `get_context_window`; persist rollback and prove the old
  revision is restored; run exact non-active cleanup.
- **Concurrency:** use two bounded sessions to prove one open-run winner, one
  event per generation, stale run CAS rejection, stale pointer CAS rejection,
  and full transaction rollback after an injected post-tag failure.
- **Tenant safety:** DB-backed FORCE RLS positive read/write for tenant A;
  tenant-B read/write negatives; unset-tenant negative; embedding-row deferred
  tenant/document/run FK positive and cross-tenant negative.
- **HBR-07 application path:** retrieve one bounded neighbor window through the
  real `VectorStore`, pass it through context expansion and Writer projection,
  prove no tenant/revision crossing, enforce the total prompt budget, and assert
  learner-visible citations omit provider/model/hash/revision/timestamp/chunk and
  tenant internals.
- **Cleanup:** abort on the first failed assertion, drop only the created
  disposable schema in `finally`, read back its absence, and prove the shared
  public revision/schema fingerprint is unchanged. A cleanup failure makes the
  gate `BLOCKED`, never `READY`.
- **Evidence:** one sanitized JSON artifact containing stable gate/evidence ID,
  migration source digests, target fingerprint digest, boolean/count/plan
  results only, timestamps, and cleanup readback. It must contain no URL,
  credential, schema suffix, tenant/document UUID, text payload, or vector.
- **Exit:** HBR-03 and HBR-07 may become `DONE` only after root review plus an
  independent `READY` review of that runtime artifact and runner; the gate does
  not authorize Git, CI, provider, shared-dev, deployment, or production work.
