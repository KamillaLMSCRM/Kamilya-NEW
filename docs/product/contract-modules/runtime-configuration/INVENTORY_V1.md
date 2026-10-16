# Runtime parameter inventory and disposition V1

Source580c200c plus reviewed runtime-configuration delta,2026-10-16. LMS API/app and web/src are in scope, landing/CRM repository not included. Two independent bounded inventories were source-checked by root. `scripts/dev/inventory_runtime_tunables.py` additionally scans every source file in those trees; its count is a reproducible heuristic candidate inventory, not proof of semantic completeness. It never exports string values or reads secrets/env/dependencies. Graph snapshot was stale and CodeGraph refused four excluded files: SOURCE_FALLBACK, not invented graph evidence.

## Implemented hot parameters (29)

| Owner/use | Keys / consumer |
|---|---|
| Assignment dialogue (5) | assignment.total_seconds/deepseek_seconds/chatgpt_seconds/fallback_seconds/max_tokens; intent_application.py |
| Document preparation (3) | document_intent.total_seconds/max_tokens; document_dialogue.provider_seconds; document_intent.py/document_dialogue.py |
| Source-grounded document answers (3) | document_answer.total_seconds/provider_seconds/max_tokens; document_answers.py |
| Course generation/review (2) | generation.temperature; reviewer.timeout_seconds; pipeline.py/reviewer.py |
| Test editor (2) | editor.temperature/max_tokens; editor_assistant/router.py |
| Lesson retrieval (3) | writer.retrieval_count/result_count/similarity_threshold; writer.py; explicit arguments preserved |
| Existing managed providers (8) | provider.deepseek/qwen/glm/chatgpt .model/.timeout_seconds; asynchronous llm_client factory; admin routing shows effective names |
| Recovery batches (3) | outbox.assignment/reminders/crm .batch_size; each owning task; same hard ceiling and delivery switches |

Closed catalog is executable source of current bounds/defaults; frozen0182 SQL constraints mirror initial29 entries and have an executable parity test. Existing env values remain fallback only when not overridden. Defaults do not change routing, enable new providers or generate extra requests. Model names for DeepSeek/Qwen/GLM are operator identifiers at existing authorized endpoint, not checked by calling provider on save. Luna remains constrained by connector support. Embedding identity is NOT hot-switched.

## Existing DB-backed settings: preserve their owners

| Area | Existing owner / reason not duplicated |
|---|---|
| Enabled global model route | generation_model_routing, validated IDs/order/revision/readiness |
| Provider credentials | provider_keys and encrypted tenant_ai_providers; separate secret/tenant RBAC |
| Tenant concurrency | tenants.settings.ai_max_active_jobs, default2/max8 and serialized admission; no increase here |
| Tenant budgets, plans and product settings | tenant_settings / tenants settings, existing tenant policy; no plan/spend override |
| Course/test policy | per-course/quiz/assignment records, explicit review/publish/confirm ownership; not global constants |

## Deliberately not arbitrary hot settings

| Source category | Disposition / risk |
|---|---|
| core/config DB/Redis/storage topology, engine pools; Celery broker/concurrency/beat/time limits | Startup/infrastructure changes require restart or controlled release, not a DB value silently changing a process |
| JWT/session/cookies/CORS/origins/roles/permissions/rate-limit protection | Security contracts; never generic superadmin key/value overrides |
| Provider endpoints, keys, connector auth mode, SMTP/webhooks/addresses | Trust/privacy/credential/delivery boundary; dedicated controlled configuration |
| Embedding model/revision/dimensions/space and index provenance | Reindex/migration compatibility, cannot change via global model-name field |
| Generation engine/source-analysis identifiers, API enums/routes/schemas/statuses | Durable protocol/domain compatibility, code and migrations |
| Upload size/AV/archive/parser/XLSX/Docling/source-token caps | Resource/DoS safety limits; preserve ceilings and isolated qualification; not ordinary operator hot knobs |
| Cleanup ages/counts, access URLs, invitation/OTP/PIN TTLs, leases/idempotency/retention | Destruction/access/concurrency correctness, preserve explicit lifecycle contracts |
| Prices/plans/budgets/usage estimates, active jobs/concurrency, provider quota | Billing/capacity authority; no new paid resources/limits or automatic spend-policy changes |
| UI polling/debounce/copied-state/object-URL timers, list pagination and static display text | Local implementation/UX constants, no evidenced operational requirement to centralize; selected candidates recorded, not remotely controlled by this package |
| Legacy synchronous LLM/test factory | Env-only compatibility surface; deployed asynchronous consumer uses DB. No hidden synchronous DB I/O |
| Retrieval source boundaries / selected document IDs / evidence validation rules | Immutable grounding/tenant controls, not tunables |

Adding a new setting requires a reviewed catalog/consumer/SQL expansion once. Changing an existing permitted value after rollout requires no release. Use the superadmin form or its revisioned API: direct unaudited UPDATE is rejected by a deferred DB audit guard, invalid raw values by SQL constraints. Rollback is a new revision, not deleting audit rows. Values already resolved for an operation remain immutable.
