# Runtime settings (DEV-qualified control plane)

Scope: Kamilya LMS. Initial schema0182 and compatible API/worker/frontend must
be released once. This document is not production release approval.

## Normal operator workflow

1. Sign in as platform superadmin, open **Providers → Runtime settings**
   (`/admin/providers`, Russian **Параметры выполнения**).
2. Filter by operation or key, inspect current value, default and allowed range.
3. Edit related values together. For assignment the provider attempts plus5s
   must fit the total90s ceiling; e.g. DeepSeek30 + ChatGPT40 + last reserve8 +5.
4. Enter a meaningful3–240-character reason and save. The whole bundle and
   history commit atomically. No inference/readiness check/provider activation
   is performed on save.
5. New operations on API/worker read the new revision immediately. An operation
   that already started retains its immutable snapshot. There is no process cache
   or restart requirement, but an already-created client does not mutate itself.
6. On409 another operator saved first. The UI reloads current values and keeps
   your draft; compare them and deliberately save again. It never auto-replays.
7. Reset removes an override and uses the declared deployment default. **History**
   displays prior changes. Choose a revision and a reason to revert; the revert
   itself creates a new revision. Initial revision1 means no overrides.

See [the inventory](../product/contract-modules/runtime-configuration/INVENTORY_V2.md)
for all31 keys and excluded categories. Existing model route activation/order is
still edited separately; a model-name override does not enable a disabled route.
DeepSeek/Qwen/GLM names must exist at the configured provider, which is not checked
by save. A wrong name can cause provider error/failover; restore the old revision.
The current official CLI connector accepts only its supported Luna identifier.
Do not use embedding names here: a different embedding space requires reindexing.

## DB and API safety

- Global non-secret overrides are in `runtime_settings`; operational revisions
  are in `runtime_settings_history`. No key/URL/password belongs in either.
- Normal supported write path: superadmin revisioned PUT
  `/api/v1/admin/runtime-settings`; history GET and `/revert` POST are role-gated.
- Database constraints also reject unknown keys, wrong types/ranges and invalid
  cross-field budgets. Direct unaudited UPDATE is rejected at commit. Use the
  operator API rather than bypassing audit with a DB owner/superuser.
- Runtime role remains non-BYPASS; FORCE RLS protects writes/history. The runtime
  may read non-secret settings, not mutate them as a tenant. Audit is append-only
  for runtime even in a validated platform-superadmin session.
- Read failure/invalid stored state fails closed with sanitized503. Pre-migration
  undefined-table alone uses declared defaults for expand compatibility.
- Revert values using a new revision. Public0182 downgrade is intentionally
  blocked to preserve audit; binary rollback leaves additive tables intact.

## Qualification / release

Use canonical Supabase DEV, never workstation Docker PostgreSQL:

```powershell
& 'C:\Kamilya New\Kamilya-NEW\.venv\Scripts\python.exe' scripts/ops/runtime_settings_dev_gate.py --env-file 'C:\Kamilya New\Kamilya-NEW\.env' --execute --evidence .release-evidence/runtime0182-isolated.json
```

This creates and drops only its own validated random schema, checks real
non-BYPASS/RLS/update/audit/revert/reload/SQL guards, and verifies public schema
neutrality. It does not migrate public DEV or prove full public row equivalence.
Run the explicit canonical public-schema gate only after isolated/CI acceptance,
then deploy exact approved SHA to existing DEV targets and perform live readback.
No new resource, plan, spend-limit or production changes are authorized here.
