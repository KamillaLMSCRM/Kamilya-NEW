---
name: kamilya-release-evidence-gate
description: Evaluate a sanitized Kamilya release evidence envelope and return deterministic GO or NO_GO without performing any mutation. Use before dev database gates, CI/release, canary, deployment, or production sign-off; do not treat the output as evidence itself or access files, Git, networks, databases, providers, secrets, PII, or production.
---

# Kamilya Release Evidence Gate

This skill is a pure release-decision module. It validates evidence identity,
dependencies, environment binding, exact release SHA, and owner approval scopes.
It never gathers evidence or performs an operation.

Do not confuse it with `scripts/ci/release-contract-gate.py`: that CI script checks
repository contracts such as Alembic/Celery ownership and the error-journal schema.
It does not evaluate this envelope or prove CI, artifact, provider, runtime,
rollback, cleanup, or production state.

## Authority boundary

- Input is one sanitized JSON envelope on stdin; output is transient stdout.
- `GO` means every required evidence record and approval is structurally present,
  correctly bound, and marked passed. It is always emitted with
  `actionable=false`; it does not make supplied evidence true or authorize an
  operation.
- Root must independently verify each opaque evidence reference at its canonical
  source before accepting the verdict or producing a separate project-level
  actionable decision. This requirement cannot be satisfied by this pure
  evaluator and is exposed as `root_reference_verification_required=true`.
- Plans, memory, Graphify, agent reports, screenshots, and this gate's own output
  are not accepted as runtime/provider evidence.
- The module has no filesystem, Git, subprocess, network, database, provider,
  scheduler, persistence, deployment, rollback, cleanup, or mutation adapter.
- No second canonical evidence store is created.

## Required phases

1. Local tests and independently verified intended source/release identity.
2. Isolated Supabase dev migration upgrade, downgrade/re-upgrade, FORCE RLS,
   active-revision, FTS `EXPLAIN`, and disposable cleanup.
3. CI and immutable artifact identity for the same exact SHA.
4. Exact owner approvals, backup/restore evidence, and independently verified
   rollback target and operation readiness.
5. Approved production migration/reindex, bounded canary, cross-tenant
   negatives, latency/cost limits, and observability.
6. Deployment identity, production readback, rollback drill/readiness, and
   disposable cleanup, followed by transfer of durable evidence into canonical
   documentation.

Missing, failed, blocked, mismatched, duplicated, malformed, or out-of-order
applicable evidence yields `NO_GO` or input rejection. No phase applicable to the
selected profile can be skipped; the profile alone defines which nodes are
explicitly inapplicable.

## Input and use

The envelope contains only hashes, stable IDs, finite states, permitted evidence
labels, timestamps, and opaque references. It must select one exact fail-closed
profile: `full_reindex`, `bounded_schema_predeploy`,
`bounded_schema_final`, `no_migration_predeploy`, or
`no_migration_final`. Unknown profiles are rejected; a bounded profile makes
only explicitly unrelated nodes inapplicable and never converts missing
applicable evidence into a pass. Use `bounded_schema_predeploy` before an
additive schema rollout and `bounded_schema_final` for its postdeploy
readback/cleanup sign-off. Use `no_migration_predeploy` when the payload has no
database migration: it requires local tests and exact remote release identity,
CI and immutable artifact identity, backup/rollback readiness, and only the
`production_deploy` and `production_cleanup` approvals. Use
`no_migration_final` for the corresponding postdeploy sign-off: it additionally
requires production deployment/readback/rollback/cleanup and canonical evidence,
with no migration stage or migration, reindex, or spend approval. See
`examples/no-go.json`.

```powershell
Get-Content -Raw .codex\skills\kamilya-release-evidence-gate\examples\no-go.json |
  python .codex\skills\kamilya-release-evidence-gate\scripts\evaluate_release_gate.py
```

Any external call or mutation remains subject to the exact action-time approval
outside this module.
