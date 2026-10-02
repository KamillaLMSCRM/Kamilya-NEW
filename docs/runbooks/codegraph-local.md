# CodeGraph: bounded local code navigation

Accepted local pilot: 2026-10-03. Runtime pinned to `@colbymchenry/codegraph@1.6.1`.
This is a development tool, not an LMS application dependency or production service.

## When to use

Use `rg` for known files, text and symbols. Retain the project's Graphify workflow
for cross-module navigation. CodeGraph adds directed caller/callee lookup for
Python/TypeScript/TSX when that helps narrow a change or find relevant tests.
Do not query both indexes routinely or import the upstream instruction to trust
graph output without reading source. Confirm decisive edges in source/tests.

The wrapper returns at most12 results and6000 JSON characters, marks omissions,
requires a unique definition for caller/callee lookup, and prioritizes product files
over scripts/tests. Missing edges do not prove absence of a dependency or that a
test can safely be skipped. All edges remain static candidates.

## Setup in the actual linked worktree

Requires Node22.5–24; pilot used Node24.18.0 on Windows x64. Do not install globally,
run upstream `install`, `init --yes`, `upgrade`, or change agent/MCP configuration.
Upstream CLI init can offer/install shared Git hooks as a fallback when watching
is disabled; our SDK wrapper bypasses that installer entirely.

Run from the repository root with the repository-owned public npm configuration:

```powershell
npm.cmd install --prefix .release-evidence/codegraph-pilot/runtime --cache .release-evidence/codegraph-pilot/npm-cache --userconfig scripts/dev/codegraph.public.npmrc --globalconfig scripts/dev/codegraph.global.npmrc --registry https://registry.npmjs.org --ignore-scripts --no-audit --no-fund @colbymchenry/codegraph@1.6.1
npm.cmd audit signatures --prefix .release-evidence/codegraph-pilot/runtime --cache .release-evidence/codegraph-pilot/npm-cache --userconfig scripts/dev/codegraph.public.npmrc --globalconfig scripts/dev/codegraph.global.npmrc --registry https://registry.npmjs.org
node --test scripts/dev/test_codegraph.cjs
node --liftoff-only scripts/dev/codegraph.cjs index
```

Stop on a failed command. Registry download/signature checking needs network;
ordinary navigation needs no LLM/provider key. No application lockfile, global
package or credentials are changed. Runtime/cache and SQLite index are ignored
local data; never commit them. Upgrades need a scoped compatibility/privacy check.

## Navigation and freshness

```powershell
node --liftoff-only scripts/dev/codegraph.cjs sync
node --liftoff-only scripts/dev/codegraph.cjs search confirm_assignment_plan
node --liftoff-only scripts/dev/codegraph.cjs callers confirm_assignment_plan apps/api/app/modules/methodologist_workbench/assignment_service.py
node --liftoff-only scripts/dev/codegraph.cjs callees requestAssignmentPreview apps/web/src/lib/methodologistWorkbench.ts
node --liftoff-only scripts/dev/codegraph.cjs status
```

Sync once after relevant edits/before review. Queries use a read-only manual
snapshot. No watcher, daemon, hook or scheduler is started. `lastUpdated` is tool
metadata, not proof that current source matches. Root derives from the wrapper's
file location, not CWD; an absolute invocation from the parent workspace was
verified to open only this linked checkout's index.

Telemetry and background updates are disabled before SDK import:
`CODEGRAPH_TELEMETRY=0`, `DO_NOT_TRACK=1`, `CODEGRAPH_NO_UPDATE_CHECK=1`;
`CODEGRAPH_NO_WATCH=1` / `CODEGRAPH_NO_DAEMON=1` reinforce manual operation.
The wrapper rejects missing/weakened exclusions and compares the pinned SDK's
effective config before scanning. `.env*`, certificate/key files, dependencies,
generated output, raw evidence and documents are excluded by `codegraph.json`.
`apps/api/app/core/storage` remains source, not runtime storage. Post-index path
auditing is supplementary, not a secret scanner; hard-coded sensitive values
still require the project's normal secret policy.

## Measured pilot and limitations

- Initial index:1602 files,29696 nodes,79018 edges,520 route nodes; zero file parse
  errors. Index duration3.815s; total SDK init/index/query work12.995s. Different
  Graphify scope/node schemas mean counts are not a precision comparison. Later
  wrapper additions incremented the index.
- Source-checked positives: API `confirm_plan` calls `confirm_assignment_plan`;
  that service calls `enroll_users` and `evaluate_confirmation`; frontend
  `requestPreview` calls `requestAssignmentPreview`. Warm wrapper query bodies
  took8–12ms, excluding process startup.
- Known false edge: `assignment_service.py:442` calls external `AsyncSession.flush`,
  but graph points at the same-named fake in
  `test_learning_path_recurrence_materializer.py:73`. Sampled edge provenance was
  unspecified; do not manufacture an EXTRACTED/verified confidence label.
- The preview client's HTTP POST did not appear as a call to its FastAPI handler.
  Zero callers for a decorated route is not dead-code evidence. PostgreSQL/RLS,
  permissions, transactions, queue delivery and deployments need usual gates.
- Synthetic alpha→beta rename: sync removed the old symbol, added the new one and
  preserved its directed caller. Synthetic `.env.py` and `docs/private.py` canaries
  were absent from file records and symbol search.
- Registry signatures and attestations verified for both installed packages.
  Five wrapper regression tests passed; independent cheap review accepted the
  hardened preflight. Runtime264823961 bytes (~253MiB); resting index~102MiB at the
  measured snapshot; package cache is additional local storage.
- Token/cost savings, end-to-end task speedup, affected-test completeness and MCP
  auto-sync NOT MEASURED. Author benchmarks are not Kamilya/subscription evidence.

Decision: adopt as an optional bounded local navigator. Keep Graphify and source/
test validation; no deployment, global integration or automatic permissions.

Primary references: [repository](https://github.com/colbymchenry/codegraph),
[telemetry](https://github.com/colbymchenry/codegraph/blob/main/TELEMETRY.md),
[retained-context benchmark](https://github.com/colbymchenry/codegraph/blob/main/docs/benchmarks/residual-context-occupancy.md),
[MIT license](https://github.com/colbymchenry/codegraph/blob/main/LICENSE).
