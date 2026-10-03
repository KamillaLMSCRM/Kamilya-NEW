# Tool-efficiency acceptance: known-file lookup/consumer discovery pilot

Date: 2026-10-03  
Checkout: `C:\Kamilya New\.worktrees\daily-learning-20260930`  
HEAD: `0a52b99f6d7edfe7b8f1f96d1d17f2bf6cecc47b`

## Scope and procedure

Read-only, database-free known-file lookup/consumer discovery pilot. No Graphify sync/update/build, installation,
provider, credential, browser, global-config, or session-body access. No intentional provider/network calls were made;
egress was **NOT MEASURED** and offline execution was **NOT ENFORCED** because no supported Graphify offline flag was
verified in this bounded run.
Preparation was separate from timed runs. Four fixed source-derived tasks were
run through `rg`, the repository CodeGraph wrapper, and the existing Graphify
snapshot. Two repetitions were counterbalanced: `rg -> CodeGraph -> Graphify`,
then the reverse. Full process startup plus query wall time was measured by
`scripts/dev/tool_efficiency_navigation_benchmark.cjs`.

The source oracle required the expected consumer/entry symbol and source path:

| Task | Oracle |
|---|---|
| Contextual help consumer | `ContextualHelpButton.tsx` consumes `getContextualHelp` |
| Assignment preview consumer | `AssignmentWorkbench.tsx` consumes `requestAssignmentPreview` |
| Sidebar registry consumer | `Sidebar.tsx` consumes `getNavigationRoutes` |
| Methodologist preview API entry | `assignment_router.py` contains `preview_assignment` |

Graph candidates were counted only as navigation hints. The retained timed rows
used a presence-only oracle and are not retroactively reclassified or rerun.
Future script runs use a conservative co-located structural oracle requiring each
expected symbol and source path on one output line or in one parsed JSON object;
this remains navigation evidence, not runtime or call-graph proof. False relations,
source reads avoided, and correction cycles were not inferable from this bounded
run and remain `NOT MEASURED`.

## Measured result

| Arm | n | Median full-process ms | Output bytes | Output items | Oracle pass | Truncated/omitted |
|---|---:|---:|---:|---:|---:|---:|
| `rg` | 8 | 35.11 | 236–876 | 2–4 | 8/8 | 0/8 |
| CodeGraph wrapper 1.6.1 | 8 | 339.49 | 448–3610 | 1–12 | 8/8 | 4/8 |
| Graphify ambient 0.9.58 | 8 | 2909.65 | 2864–2905 | 18–25 | 8/8 | 8/8 |

The CodeGraph and Graphify truncation flags are bounded-output indicators, not
incorrectness. Graphify’s existing graph was usable. `rg` received exact
consumer filenames, while graph tools were asked to discover those consumers;
this is an intentional asymmetry and the result is not generalized throughput.
The project’s historical
Graphify procedure/pinned references say `0.9.23`, while the ambient executable
reported `0.9.58`; it was not upgraded or substituted. This version mismatch is
retained as a comparability limitation. No causal savings claim is made from
this four-task sample.

Executable metadata was captured separately after the timed run with:

```powershell
node scripts/dev/tool_efficiency_navigation_benchmark.cjs --metadata
```

That metadata-only capture records the absolute paths for `node`, `rg`,
`graphify`, and `scripts/dev/codegraph.cjs`; it does not alter the timed rows
and no benchmark rerun is claimed here. The oracle is presence-only (expected
path plus symbol), and Graphify rows marked truncated remain bounded navigation
hints rather than complete or semantically correct relations. `rg` had exact
consumer filenames while graph tools discovered consumers, so this is a
known-file lookup/consumer discovery pilot, not generalized throughput. The
retained graph was not refreshed after UI changes. Same-day CodeBurn totals are
historical-plus-current metadata and are not exact current-turn attribution.

Metadata capture timestamp: `2026-10-03T02:45:22.295Z`.

| Executable | Version | Absolute path |
|---|---|---|
| Node | `v24.18.0` | `C:\Program Files\nodejs\node.exe` |
| ripgrep | `15.2.0` | `C:\Users\user\AppData\Local\Microsoft\WinGet\Packages\BurntSushi.ripgrep.MSVC_Microsoft.Winget.Source_8wekyb3d8bbwe\ripgrep-15.2.0-x86_64-pc-windows-msvc\rg.exe` |
| Graphify | `0.9.58` | `c:\Users\user\.local\bin\graphify.exe` |
| CodeGraph | wrapper `1.6.1` | `C:\Kamilya New\.worktrees\daily-learning-20260930\scripts\dev\codegraph.cjs` |

## Current-day CodeBurn metadata snapshot

Command used with the canonical timezone and work-unit grouping (metadata only;
no raw session bodies):

```powershell
codeburn --timezone Asia/Qyzylorda sessions --from 2026-10-03 --to 2026-10-03 --provider codex --format json --no-pager --by-work-unit
```

Observed three sessions and three work units. The requested root thread matched
one exact session and one exact work unit with zero child-session IDs:

| Scope | Records | Calls | Turns | Input tokens | Output tokens | Cache-read tokens |
|---|---:|---:|---:|---:|---:|---:|
| Root `01a0f16d-e27e-7a43-8d7c-d0e5b07a12bd` | 1 session / 1 work unit | 370 | 14 | 1,696,085 | 208,307 | 39,847,168 |
| Other day records | 2 sessions / 2 work units | NOT ATTRIBUTED | NOT ATTRIBUTED | NOT ATTRIBUTED | NOT ATTRIBUTED | NOT ATTRIBUTED |

CodeBurn cost fields were present, but they are tool estimates. They are not a
provider invoice and are not equivalent to subscription/flat-rate expense or an
API price unless the applicable raw provider rates are independently established.
No raw sessions, private payloads, passwords, emails, or foreign-project data
were printed or persisted. Exact current work-unit child attribution was not
available (the matched root unit had zero children); per-turn benchmark
attribution is `NOT AVAILABLE`. The day-level record count is historical+current
and noncausal for this pilot.

## Limitations

Later root metadata-only refresh at2026-10-03T03:27:15.6150864Z matched the same
one root session/work unit:975calls,15turns,3328076input/389737output/
129634944cache-read/0cache-write tokens, still0child IDs. CodeBurn schema exposes
session counters/timestamps, not turn-level usage. Raw payloads, titles, project
paths and unrelated records were filtered out before output. These are growing
same-day historical+current totals; neither the difference from the earlier
snapshot nor the day totals establish exact epic/child cost or causal savings.

Earlier stable source-batch CodeGraph sync: SDK2558ms, wrapper8063ms,
1610files/29790nodes/79496edges; excluded-path audit PASS. Five wrapper regression
tests passed. Fresh caller candidates: getContextualHelp1edge/8ms,
AIChatPanel3edges/20ms (two test harnesses, heuristic), navigation predicate11edges/
19ms. Root confirms production consumers in source; these are navigation results,
not runtime proof. No per-line refresh or background watcher was used.

Platform-transport batch sync: SDK1537ms, wrapper5507ms,
1613files/29821nodes/79572edges, excluded-path audit PASS; wrapper5/5 and
benchmark helper4/4 tests PASS. Fresh model-routing helper callers2/9ms and
3/22ms were confirmed in provider source and tests. Root additionally corrected
the proposed oracle so an entire JSON parent cannot combine unrelated siblings;
the exclusion test now seeds synthetic secret sentinels. Earlier timed rows
remain unchanged, presence-only and noncausal. No new timing run is claimed.

Review-tail validation helper sync: SDK1260ms/wrapper8417ms,
1615files/29828nodes/79588edges, exclusions PASS. apiErrorMessage caller query
6edges/23ms omitted the provider wrapper consumer despite its source call.
SOURCE_FALLBACK exact two consumer files confirms provider and model routing;
the graph is not an exhaustive consumer oracle. This extra correction/sync cost
is counted, not hidden as a single first-pass final refresh.

- Root review required real corrections: an over-broad navigation-family edit
  was corrected to preserve existing nested admin matching; AI-panel focus
  cleanup was corrected for changing parent callbacks; misleading help steps
  were replaced with actual UI flows. A final provider-label leaf initially
  edited/tested the primary checkout rather than the designated writer. Root
  detected this before freeze and required exact own-hunk restoration and
  writer-specific retesting. These costs are part of the workflow, not savings.
- Browser setup and CSV-download waits each caused a harness reset. Locator
  mismatches, guessed nonexistent paths/routes and truncated source output
  required corrective reads. No CSV completion or full-role PASS is inferred.

- Startup dominates these short queries; warm query-body latency was not isolated.
- `rg` was given exact source filenames, whereas graph arms discovered consumer
  paths; this asymmetry bounds the claim to known-file lookup/consumer discovery.
- `rg` output item counts are matching lines, CodeGraph counts JSON items, and
  Graphify counts `NODE` records; these are not semantically identical units.
- Existing graph freshness was not rebuilt in this worker. Root’s independent
  CodeGraph refresh remains the freshness authority for that arm.
- Hardened future subprocesses receive only a minimal runtime environment
  (path/runtime/temp variables plus explicit CodeGraph no-update/no-daemon flags);
  provider secrets and arbitrary process environment variables are not forwarded.
  The deterministic script tests cover unrelated symbol/path false positives,
  same-line positive evidence, and secret exclusion. These checks do not alter
  the retained timed measurements above.
- The result measures bounded navigation only, not engineering throughput,
  correctness of implementation, test completeness, runtime behavior, RLS,
  deployment safety, or billing savings.
