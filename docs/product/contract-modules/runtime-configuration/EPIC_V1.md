# RUNTIME-CONFIG — V1

Status: Accepted for implementation and DEV verification, not production release.
Template: V2. Date:2026-10-16. Supersedes:none.
Product owner/Approved by: Askar, direct request for DB hot parameters. Root and module owner: root. Reviewer: independent cheap agent after implementation. Changes require source evidence, impact addendum and root acceptance; production/billing/security expansions return to owner.

## Objective and evidence

Superadmin can inspect, atomically change and revert allowlisted non-secret operational parameters without a code release. Subsequent operations on API and worker observe a consistent current DB snapshot; in-flight operations keep their original values. Evidence: SQL role isolation, revision conflict, atomic audit, live DEV change -> consumer result -> reload -> audited revert. No model call on save.

## Module map and ownership

`superadmin UI -> runtime_configuration HTTP -> validated atomic store + audit`

`AI/workbench/outbox consumers -> immutable runtime snapshot -> existing operations`

`existing model routing -> enabled order -> existing provider adapters <- runtime model names/timeouts`

One deep module owns validation, cross-field constraints, revisions, snapshots and history. HTTP/UI are adapters; no second model routing or secret store. Active mini-spec: MODULE_RUNTIME_V1.md. State: defaults -> revisionN -> atomic validated revisionN+1; conflict/invalid writes leave both state and history unchanged; revert is a new revision.

## Impact matrix / permitted writes

| Module | Impact | Change | Preserved / regression |
|---|---|---|---|
| New admin/runtime_configuration | New owner | registry/store/HTTP/history/snapshot | superadmin-only writes; runtime reads non-secret |
| SQL models/registry/main | Interface | additive0182 and router registration | existing routes/model registration, non-BYPASS/FORCE RLS |
| AI llm_client | Consumer | approved managed model names/transport from snapshot | enabled order, endpoints, keys, BYOK, sync legacy factory, zero added inference/retries |
| AI pipeline/reviewer | Consumer | generation temperature/review timeout | evidence/validation, source boundaries, cost admission |
| Workbench intent/document_intent/document_dialogue | Consumer | operation-scoped timing/token values | roles/tenants, cancellation, schemas, history, budget, preview/confirm, lease |
| Notification/reminder/CRM outboxes | Consumer | recovery batch defaults only | hard caps, claims/idempotency/delivery, enablement |
| Web providers/settings UI | Interface | visible superadmin settings editor/history/revert | existing route activation/readiness/key UI |
| Frontend operation timeouts | Consumer | safe bounded server contract if changed | fixed protective ceiling, no secrets in public settings |
| Tests/operator gate/docs | Interface | deterministic config adapter + SQL/runtime contract evidence | no weakened assertions or invented runtime proof |

All other modules are forbidden write scope pending additive accepted impact record. Inventory documents candidates not implemented; no claim that every numeric constant is a hot parameter.

## Data / rollout / negative space

New global singleton runtime_settings (non-secret overrides, revision, updater/time), append-only runtime_settings_history. Both FORCE RLS; lms_app can read singleton for workers, writes only platform-superadmin context; history superadmin-only. No tenant content copied. History indefinitely retained as operational change record; user FK SET NULL, no deletion endpoint. Migration expands0181; defaults preserve existing env effective values. Old binaries ignore additive tables; code rollback leaves tables/history. No cache: one short DB read per operation, no cross-process invalidation race. Invalid/unreadable persisted settings fail closed; absent table only before migration uses declared defaults (expand compatibility). No mutable settings process singleton.

Excluded: secret/URL/auth/CORS/RLS/session/role changes, embedding space/dimensions, durable engine/schema identifiers, retention/destructive limits, paid plans/spend, concurrency/capacity increases, arbitrary routes, voice, ASUS and production.

## Gates

Focused policy/store/HTTP and producer-consumer tests, existing model routing/BYOK/failover/dialogue/outbox regressions, canonical isolated Supabase schema upgrade/RLS/rollback/cleanup with public neutrality; quality baseline/frontend type/build/full CI before DEV. Then current schema exact readback and real DEV flow, update without restart and revert. Stop on graph/source conflict, unknown impact, partial audit, failed isolation, unexpected dirty work or authority expansion. Root records decision before resume. Production is NOT AUTHORIZED.
