# Runtime configuration DEV epic

## Scope and truth

- Root/module owner: root; product owner: Askar. Owner requested implementation 2026-10-16; production explicitly forbidden.
- Checkout: `feature/document-completeness58-20261016` at `580c200c5dbfef3b60489e66ed2ae891a188a4ec`; initially clean. LMS only, not landing/CRM.
- Existing Free Render API/worker, Hobby Vercel, canonical Supabase DEV only. No ASUS, voice, provider billing or infrastructure changes.
- Current date-followup candidate CI38892508630 PASS; DEV deployments `dep-db90hr7f3r2c73fm68ng`/`dep-db90hs7f3r2c73fm6cdg` pending. API auto-deploy temporarily disabled; restore after acceptance.
- Canonical sources: PROJECT.md product; PROJECT-CONTEXT.md access; PRODUCTION_READINESS.md deployed state; PRODUCT_BACKLOG.md open work. Source is not runtime proof.
- Navigation: CodeGraph query rejected four excluded files; existing combined receipt stale after source edits. SOURCE_FALLBACK, bounded source-verified inventory, no forced rebuild or index reuse.

## Ownership and dependency graph

Root is sole writer of contracts/schema/shared runtime/integration/provider operations. Two cheap read-only agents inventoried AI and non-AI sources; both inventories independently source-checked at root. Independent review follows implementation.

`INVENTORY -> CONTRACT -> STORE -> CONSUMERS -> TESTS -> DEV-ACCEPT`

`DATE-ACCEPT` is independent; its one-shot environment keys must be disarmed and API auto-deploy restored.

| Node | State | Exit gate | Owner / scope |
|---|---|---|---|
| INVENTORY | DONE | Existing DB routes/tenant policy distinguished from hot candidates/security/startup constants | root + read-only inventories |
| CONTRACT | IN_PROGRESS | Versioned epic/module/impact matrix | root docs/product/contract-modules/runtime-configuration |
| STORE | NOT_STARTED | Typed registry, snapshot read, atomic revision/audit/rollback; FORCE RLS | root new runtime_configuration module and0182 |
| CONSUMERS | NOT_STARTED | Real consumers use operation snapshots; preserve routing/BYOK and security | root named impact matrix |
| TESTS | NOT_STARTED | Focused/contracts/SQL isolation and cleanup/full candidate gates | root, delegated bounded checks |
| DEV-ACCEPT | NOT_STARTED | Exact revision, live update/readback/rollback and real dialogue | root existing DEV only |
| DATE-ACCEPT | IN_PROGRESS | Exact580 runtime; normal + forced real ChatGPT, original follow-up, negative cases and browser | root existing operator packet |

## Decisions and cleanup

- No arbitrary environment replacement. Endpoints/secrets/auth/RLS/embedding identities/billing/security/cleanup/retention/engine version remain release/security-owned.
- Model route order remains owned by generation_model_routing; names are currently env-backed, not DB-backed. New names affect only approved existing managed provider adapters, never endpoints/keys or reserve enablement.
- No production migration/deploy without fresh owner agreement. DEV migration only after isolated schema gate; no Docker PostgreSQL.
- Configuration updates have no model invocation side effect. Revert values in an audited new revision, never delete history. Remove temporary one-shot probe keys separately after date acceptance.
