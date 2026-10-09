# CodeGraph: bounded local code navigation

Accepted local pilot and mandatory-use routing updated: 2026-10-03.
Runtime pinned to `@colbymchenry/codegraph@1.6.1`.
This is a development tool, not an LMS application dependency or production service.

## When to use

Use `rg` for exact-file/text/symbol lookup and small local edits. CodeGraph is
required before broad source reading for non-trivial Python/TypeScript/TSX
investigation, shared-service/interface/hook/component changes, and affected
consumer/test discovery. First resolve the exact definition with `search`, then
bounded `callers`/`callees` with its project-relative file. Record what the query
actually narrowed or confirmed. Do not run graph queries as a ceremonial gate.

Graphify remains the next route for unresolved architectural/multi-hop/cross-
language relationships; follow its project skill. Do not ask both graphs the
same answered question routinely. HTTP→handler, queues, SQL/RLS and dynamic
dispatch still require source/contract/runtime evidence, not an imagined edge.
Confirm decisive graph candidates in source/tests before changing their consumers.

Disposition per task: `USED` with query/evidence; `KEEP_LOCAL` for known local
file/prose/config/status with a reason; or `SOURCE_FALLBACK` with the exact stale,
missing, ambiguous/false-edge or failure limitation. An unavailable graph is not
permission to skip tests and is not a reason to block a safe source-based repair.
Stop repeating materially identical tool failures; preserve the old index and
fall back rather than forcing a rebuild, weakening exclusions or upgrading tools.

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

### New-checkout readiness gate

Runtime and indexes are ignored, per-checkout data: an installation/index in the
primary or another linked worktree does not prepare a new checkout. Run from the
actual linked checkout, before its first graph-dependent task:

```powershell
node scripts/dev/prepare_navigation.cjs
```

The default is read-only and exits nonzero with `NOT_READY` for a missing runtime,
index or receipt, a different root/tool identity, changed source content, or an
altered index. A timestamp or successful CLI launch does not replace this gate.
For missing CodeGraph runtime, first complete the pinned install and signature
audit above. Use the existing Graphify interpreter from the project skill; do not
install/upgrade globally. Then explicitly prepare both local AST snapshots:

```powershell
node --test scripts/dev/test_codegraph.cjs scripts/dev/test_prepare_navigation.cjs
node scripts/dev/prepare_navigation.cjs --prepare
node scripts/dev/prepare_navigation.cjs
```

The helper runs the primary-write guard before mutation, performs CodeGraph
`index`/`sync`, and Graphify incremental `extract . --code-only --max-workers 2`
with the same required exclusions. It never installs packages, starts hooks or
watchers, merges repositories, uses provider credentials, or forces a rebuild.
It rejects junctions/symlinks in artifact paths and foreign Graphify root markers.
Graphify acceptance requires nonempty graph data, existing in-checkout source
paths, the exclusion audit and zero input/output LLM tokens. JSON/config files
with no AST nodes may be omitted by Graphify; the graph is not complete coverage.

An ignored `.release-evidence/navigation/receipt.json` binds tool identity, root,
source SHA256 and index SHA256 to that preparation. The source fingerprint uses
Git-tracked/nonignored source-language files (including tracked deletions), not
mtime or HEAD alone. Its scope is deliberately conservative across both tools;
it can request a refresh for a file not represented by every extractor. Source
edits during preparation abort receipt creation. Serialize preparation; do not
run it concurrently with graph writers or source edits.
Empty SQLite WAL and transient SHM files created by a read-only CodeGraph query
do not invalidate readiness; nonempty WAL content remains part of the snapshot.

If the interpreter path differs, pass `--graphify-python ABSOLUTE_PATH`. On the
2026-10-09 workstation Graphify reports package0.9.23 versus skill metadata0.9.58;
its actual installed AST extract/query/diagnose capabilities were verified.
This warning does not authorize an upgrade or skill downgrade. The current
graph is undirected: query neighbors do not establish call direction.

This is an explicit checkout-preparation step, not a shared Git hook. After a
material source delta, run `--prepare` once before review if both snapshots are
needed. A CodeGraph-only `sync` still works for narrowly scoped navigation, but
does not certify the combined receipt; retain source freshness checks/fallback.

```powershell
node --liftoff-only scripts/dev/codegraph.cjs sync
node --liftoff-only scripts/dev/codegraph.cjs search confirm_assignment_plan
node --liftoff-only scripts/dev/codegraph.cjs callers confirm_assignment_plan apps/api/app/modules/methodologist_workbench/assignment_service.py
node --liftoff-only scripts/dev/codegraph.cjs callees requestAssignmentPreview apps/web/src/lib/methodologistWorkbench.ts
node --liftoff-only scripts/dev/codegraph.cjs status
```

Check freshness of the relevant files before relying on a snapshot. Sync once
after relevant source edits/before review, not after every line or prose edit.
Query and verify affected consumers again after a material interface delta.
Graphify AST update is needed only for changed relationships used in that graph.
Queries use a read-only manual
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

For each meaningful navigation task record tool/version/source SHA, task and
oracle, order/cache condition, total process/startup/query and sync/index elapsed,
output chars/items/truncation, source reads, confirmed/false/missing useful links,
final answer correctness, correction rounds and fallback. Count preparation and
failed calls rather than reporting only the fastest warm query body.
Root and delegated token counters are separate and recorded only when exposed;
tool-call count is not model-call count and unavailable usage is not zero.
Matched tasks and preserved quality are required for a speed/savings claim.
CodeBurn estimated API-equivalent USD is not subscription spend or quota saving.
Use the current epic/experiment ledger, not a new global scheduler or telemetry.

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

Decision: mandatory bounded navigator for the source-investigation triggers above;
justified local/source fallback otherwise. Keep source/test/runtime validation and
Graphify for unresolved relationships; no deployment, global integration or
automatic permissions. These rules reach primary only through reviewed master
integration, never a direct edit to the primary checkout.

Primary references: [repository](https://github.com/colbymchenry/codegraph),
[telemetry](https://github.com/colbymchenry/codegraph/blob/main/TELEMETRY.md),
[retained-context benchmark](https://github.com/colbymchenry/codegraph/blob/main/docs/benchmarks/residual-context-occupancy.md),
[MIT license](https://github.com/colbymchenry/codegraph/blob/main/LICENSE).
