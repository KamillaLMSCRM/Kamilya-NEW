# AI-PROVIDER-INDEPENDENCE — EPIC V1

Status: Accepted for implementation. Template: V2. Supersedes: None.
Approved by: product owner (current user), 2026-09-10, five-item implementation request; root accepts technical contract. New production migration/deployment remains an exact release gate, not implicit schema approval.
Root owner/reviewer: root orchestrator; product owner: current user; module owners: assigned DIRECT and BYOK workers; root owns UI, integration, operations and final review. Independent reviewer required for root changes before release.
Change control: worker proposes unlisted impact -> root reviews/addendum -> product owner approves changed business/authority boundaries -> new immutable version or cancellation. Root alone integrates and accepts evidence.

## Objective, states and success

An authorized methodologist generates a grounded editable course and quiz from selected readable tenant documents even when semantic indexing is unavailable. Tenant admin can securely configure separate own generation and embedding models; other tenants and global generation order remain unaffected.
States: original stored -> readable source validated -> course queued/running -> grounded draft+quiz; optional index independently succeeds/fails. Generation failure/cancellation remains truthful and atomic. Provider settings: absent(global default) -> configured(enabled/disabled) -> replaced/revoked. Explicit tenant override must not silently fall back to platform or another tenant's key.
Success: real source-to-course+quiz browser flow, no embedding calls in direct mode, exact source revision/tenant checks, tenant isolation, unreadable-file rejection, failed-provider recovery and no secrets in responses/logs.
Exclusions: paid provider tiers, arbitrary network destinations, changes to global generation priority, weakening RAG provenance, customer documents in testing, changing every tenant's limits, disabling safety rate/concurrency/file budgets.

## Module map and index

Tenant admin -> BYOK credential/config policy -> tenant-aware AI client factories -> DIRECT course pipeline -> existing transactional course/quiz persistence.
Document indexing -> tenant-aware embedding factory -> existing verified vector storage. Direct source conversion consumes original blob independently and never invents vectors.
Active mini-specs: DIRECT V1 and BYOK V1 below; this file contains their complete compact contracts. UI is an adapter of these modules, not a new business-policy owner.

## DIRECT V1 mini-spec

- Responsibility/contribution: source-grounded generation independent of availability/status of vector indexing.
- Non-responsibilities: credentials, pricing, tenant admin, unrelated RAG chat, publication policy.
- External interface: existing compatibility/admission and run_generation_pipeline APIs stay compatible; direct selected-source context has explicit mode, tenant/doc/original-SHA provenance, bounded text/chunks and truthful readiness/errors. No fake compatibility score when embeddings absent; multiple documents require an explicit combination goal if semantic compatibility is unknown.
- Inputs: selected active tenant-owned document IDs, canonical original SHA, verified stored blob, existing generation settings. Outputs: bounded source tools/context, safe compatibility/readiness response, existing draft course+quiz result.
- Data ownership: document/storage module retains original blobs and document state; pipeline retains existing AI job and course persistence owners. No global mutable cache; no cross-tenant summary lookup. Prefer original conversion at direct generation time; no new DB schema in this module.
- Invariants: source hash matches original; no silently dropped selected source; no document/tenant/revision mixing; no vectors fabricated; no success claimed for unreadable or missing blobs; generation needs generation provider, not embedding provider. Existing cancellation row lock and quiz methodological review preserved.
- Idempotency/concurrency: existing queue/job admission and cancel/save transaction retained; bounded conversion per job; no blind external retries or duplicated course writes.
- Errors: unreadable/missing/mismatched source is terminal and safe; conversion/provider outage is classified, bounded and recoverable; unavailable embeddings cannot reject an otherwise valid direct source.
- Dependencies/adapters: DocumentConverter, storage, existing source tools/pipeline; tenant-aware client factories from BYOK with optional tenant_id. Tests use synthetic converters/providers and actual seams.
- Forbidden: credential/LLM factory implementation, new migrations, deployment, customer data, global auth/roles, unrelated chat retrieval, billing.
- Security/privacy: authorize active-role and tenant at ingress and worker; verify original blob integrity; keep parser/ZIP/file budgets; treat document text as untrusted content; no raw exceptions or text in logs.
- Observability/performance: expose direct-source vs search-index status safely; bounded document/character/token budgets, not unbounded full-file prompts; timeout/cancellation preserved.
- Read scope: AI, documents, storage, critical journey tests. Write scope: AI source_analysis.py, pipeline.py, tools.py/tools subpackage as needed, new direct_source.py; documents service/operations and AI ingestion only if required by the contract; related focused tests. Root owns AI router, web adapters and shared schemas unless an explicit handoff grants them.
- Verification: red-capable admission/pipeline tests with embedding factory forced to fail; multi-source completeness; cross-tenant, stale SHA, corrupt/oversize/OCR cases; cancellation; AI-COURSE-01 regression and real synthetic end-to-end.
- Rollout/rollback: backward-compatible API first, then UI; old records retain index states; rollback code does not remove source/course data. No schema change here.
- Ready: root-approved contract and write ownership. Done: focused+contract+neighbor tests, reviewed diff, integrated critical journey; production separately verified.
- Stop: any unlisted file/data/state invariant or need for a new schema/unsafe parser bypass.

## BYOK V1 mini-spec

- Responsibility/contribution: secure tenant-owned provider settings and independent generation/embedding resolution.
- Non-responsibilities: document parsing, UI business roles, global generation order, external billing management.
- External API: GET /admin/ai-providers -> {providers:[sanitized settings]}; PUT /admin/ai-providers/{purpose} -> sanitized setting; DELETE same -> 204. purpose is generation or embedding. Configuration fields: provider, model, api_key(write-only optional on update), enabled, free_only(default true for OpenRouter), output_dimensions(optional embedding). No plaintext/ciphertext/partial key returned; expose has_key only. Tenant context server-owned, never request-owned.
- Provider allowlist: generation deepseek/openrouter; embedding voyage/cohere/openrouter. Endpoint URLs are server-owned official HTTPS constants, not arbitrary tenant URLs. Model ID validated/bounded. Native Cohere adapter retained. OpenRouter free-only requires explicit :free model or openrouter/free for generation and zero max_price for all applicable usage categories; never silently fall back to paid/global routes. Non-free production use requires explicit tenant configuration, never our synthetic test default.
- Runtime interface: existing ResilientLLMClient.from_settings_async and ResilientEmbeddingsClient.from_settings_async gain optional tenant_id; absent override preserves existing global behavior except Qwen removed entirely from configured embedding chain. Enabled tenant override selects only its own configuration; disabled/absent returns platform defaults. Error resolving tenant config fails closed, not global fallback. Direct helpers should use the same resolver where used by course/test generation.
- Data: new tenant_ai_providers with unique tenant_id+purpose, encrypted key using existing Fernet owner, safe configuration, created/updated timestamps; tenant FK cascade; migration0157 following0156, FORCE RLS and least-privilege runtime grants. Global provider_keys unchanged.
- Authorized writers/readers: active tenant admin, scoped superadmin if established route convention; methodologist/student denied secret-settings routes. AI worker reads only current tenant through tenant context. No user-owned tenant ID.
- State/idempotency: PUT upserts one row per purpose with concurrent unique protection; secret omitted retains key, blank rejects, DELETE revokes; no post-commit ORM refresh without renewed tenant context. No shared cache across tenants.
- Errors: safe validation/auth/missing configuration/provider errors; no secret echo in Pydantic errors, repr, logs or responses. Limit model/key lengths; no CRLF or URL credentials.
- Dependencies/adapters: existing auth/get_db/encryption, SQLAlchemy, httpx AI clients; new tenant runtime resolver imported lazily to avoid circular imports. No extra dependencies required.
- Forbidden: arbitrary base URL/SSRF path, disabling TLS, redirects with credentials, provider plan changes, platform generation routing mutation, direct source implementation, root route registry edits without handoff.
- Observability/performance: safe provider/purpose/status only, short DB reads; no external request on settings GET. Bounded provider timeout/retries.
- Read scope: auth/db/encryption, tenant schema/RLS patterns, AI clients, routing and provider key modules, relevant tests. Write scope: new modules/admin/tenant_ai_providers/**, llm_client.py, config.py only for embedding fallback cleanup, migration0157_tenant_ai_providers.py, module import registration if required by migration models, focused tests. Root integrates app router, pipeline/ingestion call sites and frontend.
- Verification: actual resolver/consumer seam with two tenants; no key leakage; role negatives; schema+real Supabase FORCE RLS CRUD; overwrite/revoke/default; free-only request body; absent embedding providers never call Qwen. Reindex provenance/dimensions guards retained.
- Rollout: isolated DEV migration and RLS gates first, API before UI; production migration only with applicable exact approval. Rollback older app leaves additive table intact; disable/delete synthetic override to restore default. No existing vector reindex/destructive migration.
- Ready: root-approved contract, source0156 head checked. Done: reviewed API/runtime seam, unit/DB contracts, browser tests, exact release evidence separately.
- Stop: any required external secret/provider action, unlisted neighboring change, unsafe migration or inability to demonstrate RLS.

## Impact matrix, verification and release gate

| Existing module | Impact | Preserved negative space | Checks |
|---|---|---|---|
| Source compatibility/pipeline | Invariant: direct source allowed without index | Tenant/revision, budgets, cancellation, review | Direct outage tests + AI-COURSE-01 |
| AI clients | Interface: optional tenant_id; remove embedding Qwen | Global DeepSeek-first generation, provenance/dimensions | Factory/failover tests |
| Document operations | Interface only if needed for truthful source readiness | Original blobs, upload validation, index failure truth | Upload/reindex and hash tests |
| Tenant settings | New isolated BYOK capability | Other tenant/global keys and role separation | DB/RLS CRUD/negative tests |
| Admin/AI web adapters | Compatible settings and readiness views | Student access denied, secret not retained/rendered | Vitest, lint/typecheck, browser |
| Synthetic tenant limits | Owner-approved fixture-only values | Production customer limits, safety caps, paid budgets | Exact fixture marker/identity readback |

Full completion requires focused/module/producer-consumer tests, migrated Supabase isolated-schema RLS, mandatory critical journey, complete risk-based release suite once, secret scan, code-only Graphify update and module-map comparison, exact authorized release/readback and human-style synthetic browser acceptance. HTTP200/auth-only is not inference proof. Root owns CHANGELOG, ERRORS and durable docs after verification.
