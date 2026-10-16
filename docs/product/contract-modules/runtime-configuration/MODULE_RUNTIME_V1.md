# Runtime configuration module V1

Status: Accepted,2026-10-16; templateV2; supersedes:none; approved by root under Askar's implementation instruction. Product owner Askar; root/module owner root; independent reviewer assigned after source completion. Epic EPIC_V1.md. Change control: evidence -> impact addendum -> root acceptance; owner approval for external/security/billing expansion.

## Responsibility / interface

Concentrate typed operational policy and transactional revision history behind `resolve_runtime_settings()` and `RuntimeSettingsService.get/update/history/revert`. Inputs: closed key names and JSON scalar values, expected positive revision, bounded reason, authenticated superadmin. Output: immutable validated snapshot for consumers; admin response includes effective values, defaults, bounds, provenance, revision and metadata; no credentials/URLs/tenant content. Unknown/type/range/cross-field-invalid values rejected before mutation. Reads once per operation, no global cache, no inference during get/save. Defaults inherit current env only for previously env-owned values.

## Non-responsibilities / contribution

No provider activation/order/credentials/endpoints, billing, source boundaries, scheduling/claims, auth or retention policy. Operators tune permitted operation/provider knobs and restore prior snapshots; no redeploy/restart for existing catalog entries. Adding a new key/adapter still needs reviewed code once.

## Data and state

runtime_settings singleton id1: override object/revision/updater/time; module sole writer, non-secret runtime readers. runtime_settings_history: complete before/after override snapshots, new revision, actor/time/reason; superadmin readers, insert only, no delete/update grant. Global not tenant-owned. FORCE RLS on both, no PUBLIC/anon/authenticated/service_role grants. SQL runtime role lms_app non-BYPASS; platform context required for mutation/history. No tenant business data. Keep audit indefinitely; updater references SET NULL on account deletion.

Valid update N -> N+1 under FOR UPDATE and optimistic revision. Exact no-op returns N without history. Invalid/conflict/cancellation rolls back all; commit outcome is reconciled by GET/revision (UI does not automatically replay writes). Revert reads a selected historical snapshot and writes it as a new audited N+1 with expected current revision. Repeated stale command conflicts, never double-applies. Missing singleton/unreadable/invalid DB snapshot -> bounded503, sanitized class-only logs; pre-migration undefined table -> defaults only. No silent reactivation of disabled provider: existing routing fail-closed remains independent.

## Constraints and security

Strict numeric types (bool not int), finite values, conservative per-key ceilings. Assignment total includes DeepSeek + ChatGPT + fallback plus overhead; web95s ceiling retained, server total<=90s. Document timeout remains below fixed120s request lease. Models are identifiers, not URLs; ChatGPT connector currently supports only its declared Luna model and may not pretend another is usable. BYOK values never overridden. Raw SQL invalid values fail runtime validation, never execute arbitrary code. Root owns schema/integration; workers receive identical next-operation semantics.

## Dependencies / observations

SQLAlchemy AsyncSession, existing get_db/require_role and runtime session factory; SQL and deterministic fake store are real test adapters. No new packages/services. Snapshot value/revision used consistently in each consumer operation; safe log error class only. History and revision are operator evidence, not provider spend. No arbitrary configuration payload logs.

## Verification and scope

Unit: all registry types/bounds/defaults/cross-field constraints. Interface: store compare-and-swap/noop/history/revert. HTTP: superadmin-only +422/409/503, read-only normal runtime. Contract: exact production consumer seams take changed values, no effect on endpoints/order/BYOK/retries. SQL: actual isolated DEV migration, non-BYPASS read, tenant write/history denied, superadmin atomic audit, downgrade/owned cleanup/public neutrality. Integration: live DEV settings read/change/use/reload/revert; existing dialogue and routing regressions. Full risk-based CI and frontend checks before release.

Permitted writes exactly epic impact matrix, root only shared integration/schema; leaf agents read-only until bounded ownership packet. Stop on unknown key/consumer/security impact or failed gates. Expand migration before new code, old defaults preserved. Rollback new settings by new revision, binary rollback keeps tables; no destructive downgrade on shared public schema. DEV only. Done requires exact source/schema/readback and real consumer proof, not just local tests.
