---
name: kamilya-release-evidence-gate
description: Evaluate a sanitized Kamilya release evidence envelope and return deterministic GO or NO_GO without performing any mutation. Use before dev database gates, CI/release, canary, deployment, or production sign-off; do not treat the output as evidence itself or access files, Git, networks, databases, providers, secrets, PII, or production.
---

# Kamilya Release Evidence Gate

This skill is a pure release-decision module. It validates evidence identity,
dependencies, environment binding, exact release SHA, and owner approval scopes.
It never gathers evidence or performs an operation.

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
4. Exact owner approvals and backup/restore readiness.
5. Approved production migration/reindex, bounded canary, cross-tenant
   negatives, latency/cost limits, and observability.
6. Deployment identity, production readback, rollback drill/readiness, and
   disposable cleanup, followed by transfer of durable evidence into canonical
   documentation.

Missing, failed, blocked, mismatched, duplicated, malformed, or out-of-order
evidence yields `NO_GO` or input rejection. No phase can be skipped.

## Input and use

The envelope contains only hashes, stable IDs, finite states, permitted evidence
labels, timestamps, and opaque references. See `examples/no-go.json`.

```powershell
Get-Content -Raw .codex\skills\kamilya-release-evidence-gate\examples\no-go.json |
  python .codex\skills\kamilya-release-evidence-gate\scripts\evaluate_release_gate.py
```

Any external call or mutation remains subject to the exact action-time approval
outside this module.
