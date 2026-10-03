# Tool-efficiency acceptance: known-file lookup/consumer discovery pilot

##32 closeout /33 PDF continuation measurements,2026-10-03

- Runner32B wall243090ms;852web/144files fresh plus linked prior API/Node.
  Requested fresh release-contract was NOT_RUN in B; root caught the omission,
  independently ran exact materialized3f0f contract PASS211journal entries before
  push. Do not attribute it to Runner. Exact CI later independently passed.
- Runner32C production readback wall194418ms,0business mutations;2wrapper syntax
  failures before import/network corrected once. Role/history/PDF/header PASS is
  not visible browser PDF PASS. Release Runner local handoff wall21677ms/controller
  about2.9s, technical executor remains root. No duplicate network execution.
- Native32 protection required3fresh artifact downloads; each2–3minutes, not
  replaced by local cache. This deliberate overhead is not tool speedup.
- CodeBurn0.9.23 root-only snapshot ended2026-10-03T07:18:39.48Z:21turns/1651calls,
  input5436489/output679303/cacheRead223609600/cacheWrite0,duration44318929ms,
  API-equivalent estimate27.64664836USD. Cumulative history, not bill/plan/quota
  or exact repair/child usage; reported savingsUSD0 is not a causal savings verdict.
-33 component initial cheap writer was corrected for real PDF.js types, promise
  cleanup and a true pending-render sequentiality test; root changed interface
  URL→Blob bytes to avoid extra blob-fetch/CSP coupling. Strict lint caught an
  effect-cleanup ref warning; effect-local task set fixed without suppression.
  Final5module tests PASS. Root consumer/header/sidebar11PASS; header/navigation
  RED3failed/4passed before removing32exceptions. Mock-only runs are not pixels.
- Root local dependency preparation had failed no-TTY purge prompts, one frozen
  lock mismatch, guessed source/glob/CWD/evidence paths and a case-insensitive test
  filter that also selected an in-flight leaf test. These are recorded overhead,
  not product regressions or first-pass acceptance. Canonical Corepack10.26.1,
  verified junction target/exact virtual-store-dir and explicit mechanical lock
  update resolved install without source/secret/global configuration writes.
- Fresh audit rejected16advisories and firstPDF5.6.205; safe5.5.207/Next15.5.24/
  Axios1.20/Sharp0.35.4 whole prod graph0known. Axios typing change required one
  pagination mock signature correction; not a pre-existing unrelated defect.
- Stable CodeGraph33 sync SDK2107ms/wrapper8491ms,1623files/29892nodes/79722edges,
  exclusionsPASS. PdfPreview search17candidates/12returned/truncated/10ms body;
  callers2heuristic page candidates/untruncated/21ms, both source-confirmed.
  Prior isPdfPreview query5edges13/19ms narrowed two real consumers plus3testcalls.
  No Graphify rerun for this answered relation; renderer/build/browser remain
  source/runtime gates. Exact per-task/child tokens, causal savings NOT_AVAILABLE.

Date: 2026-10-03  
Checkout: `C:\Kamilya New\.worktrees\daily-learning-20260930`  
Historical measurement base HEAD: `0a52b99f6d7edfe7b8f1f96d1d17f2bf6cecc47b`,
plus the then-uncommitted bounded client/tool changes. Retained pilot JSON is
not a run of current31 source and is not retroactively rerun/relabelled.
Published30/initial31 review base HEAD: `d8ab25d6940eee4d388f3e32c820eb5ee57b169b`.
Deployed31 source: `572f0d9569dfbdce8dc662d5fc6bcf4a52f234a3`; the retained
navigation pilot was not rerun against it.
Later sync, Runner and live-retest rows below carry separate contexts/timings.

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

- Test Runner C complete local gate825web/141Python/9Node plus quality/build
  accepted; C runner wall357195ms includes retrieval, commands and ledger/handoff,
  not just57.61s Vitest. Prior B wall226288ms stopped at stale source-literal
  assertion; A matrix unrun. Neither overhead nor stops are erased.
- Release Runner wrong packet-path attempt22156ms and executor-network block
  corrected attempt16823ms; later local reconciliation23255ms, not independent
  remote execution. Root used the same protected bridge in an authorized executor.
  A missing local published tag caused one avoidable156MB download before source
  gate failure; exact canonical tag fetch fixed it. Fresh download per phase is
  deliberate CI provenance, not cache proof. Network permissions were not expanded.
- Root also assumed a native artifact member_count field, attempted import of a
  CLI module whose global parser correctly rejected missing operation, and assumed
  inventory JSON instead of documented text. Corrections used existing dataclass/
  canonical inventory parser. These are harness costs, not product/provider faults.
- Technical30 rollout passed, then live browser valid-Next exposed premature native
  form validation absent from click-only mocks. Tiny31 cancel-default/button-identity
  correction and a fresh regression/release gate are required; no end-to-end
  savings or complete product PASS is claimed from the navigation pilot.
- Final stable31 source batch CodeGraph sync: SDK1964ms/full wrapper10795ms,
  1615files/29829nodes/79590edges; exclusions PASS. Exact local wizard repair is
  KEEP_LOCAL, with source and mock default-action/node-identity/final-submit
  checks; two focused tests PASS. This sync is freshness evidence, not runtime
  validation or a causal productivity benefit.
- Later natural-expiry30 live test exposed missed operations rawfetch consumer;
 31A intentionally stopped140993ms before matrix completion. This invalidates a
  claim that the earlier shared-consumer investigation was complete. Exact-file
  apiFetch graph query found7edges/26ms without truncation, all source-confirmed;
  further repair and stable-batch sync are required. Do not erase interrupted
  suite time or label it a passed regression.
- Root caught missing v1-prefix in leaf operations transport before freeze;
  restored exact URLs, added component URL/body/no-auto-mutation bindings and
  GET401 replay alongside3previewPOST cases. Focused19tests/typecheck PASS;
  final stable sync SDK1497ms/wrapper8001ms,1616files/29837nodes/79603edges,
  exclusions PASS. Review P2 measurement-revision ambiguity corrected explicitly;
  these corrections are overhead, not evidence of causal tool savings.

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

##32 continuation measurements,2026-10-03

- Static PDF inventory narrowed two actual iframe consumers; source and browser
  CDP, not graph inference, established the cause:200PDF + parent frame-src block.
  Inventory leaf's approximate25s is self-reported, not independently timed.
- Stable-batch CodeGraph1.6.1 sync: SDK2432ms, wrapper10926ms,
  tool wall about11s;1621files/29866nodes/79665edges, exclusions PASS.
  New isPdfPreview callers query20ms body/0.87s entire shell action (also included
  version/diff gates),5edges/untruncated: two real consumer functions and three
  test-file calls, source-confirmed. No claim that these are five product consumers.
  Config exact-route edit KEEP_LOCAL; iframe/header/runtime cause SOURCE_FALLBACK.
- Corrections are counted: one mistaken training-log patch hunk was caught by
  the red-capable component test and fixed; one leaf help correction removed an
  invented Why-assigned control. Several guessed Windows glob/source paths and
  help/audit locator mismatches failed; oversized audit AX output added overhead.
  A lost browser binding after context transition required one existing-tab rebind.
- PDF/security red:2failed/2passed; invalid-response component red:2failed/2passed
  plus missing-helper suite, then14PASS/3files (3.99s Vitest/4.96s shell).
  Leaf stale-session regression red then4PASS, bounded source integration check
  found no concrete issue; no independent browser/deployment PASS inferred.
- Graphify was not rerun for an answered two-consumer problem. ECC compact
  ownership/runner packets remain routing, not automatically measured speedup.
  CodeBurn day/session metadata remains cumulative; this repair's exact per-agent
  token/cost/quality-adjusted savings NOT_AVAILABLE. No global hooks or telemetry.
-32A wall372761ms, completed851web/144files plus build/lint/type/Node/version/
  release-contract/2244APIunits/141selectors. Intentionally stopped before quality/
  Poetry/diff after Root caught document-vs-SPA CSP integration risk. Root also
  corrected one guessed benchmark filename before its gate; no file delta.
  Additional Sidebar search19candidates/truncated18ms, callers1Layoutcandidate9ms
  source-confirmed. New native-document navigation regression red1/2 then17PASS
  and typecheck; this extra correction/retest is overhead, not claimed savings.

##31 closeout additions,2026-10-03

- Full B commands independently read from Runner outputs: Vitest68549ms,
  lint10369ms, typecheck4387ms, build49369ms, Node414ms, syntax327ms;
  total133415ms. These unchanged source/test/config gates were not repeated for
  hash-linked doc-only C/D deltas. This quantifies previously measured commands
  not repeated, not causal CodeGraph/ECC speedup or subscription/USD savings.
- Runner31A wall140993ms (interrupted/uncompleted), B254101ms (release-notes
  marker stop), C139960ms (linked localPASS), D154783ms (journal contract repair
  and2244unitPASS), E162215ms (bounded production API readbackPASS).
  Release Runner local plans21576/19217ms; post31 local technical reconciliation
  39074ms. Network execution remains Root-owned, not independent Runner proof.
- Root missed canonical Cause label in journal; original7da CI failed all three
  dependent gates.572 fixes documentation only; originalfailedCI preserved.
  Root corrected inherited D packet wording before execution. E had one local
  wrapper parenthesis error before any import/network/login; corrected once.
  These are real coordination/harness overhead, not savings.
- Root QA recipe review used existing CodeGraph1.6.1 snapshot: create_employee
  search0candidates/504ms (not absence proof); exact create_admin callees16edges,
  12returned/truncated,44ms query body. bind_tenant_context/_sync_user_role were
  source-confirmed; AsyncSession.flush/refresh edges again resolved to unrelated
  same-name methods. Source fallback established no-delivery/password-init and
  rule-task contracts. No claim of exhaustive consumer discovery or saved reads.
- Native maintenance accidentally used httpx in agent-tools Python, which lacks
  it; no installation. Corrected by keeping SSH in agent-tools and public HTTP in
  canonical API Python. Web health is text, not JSON; parsing assumption corrected.
  Repeated guessed source paths and the searchbox/textbox locator mismatch remain
  overhead. No product failure or secret exposure inferred from these stops.
- Latest bounded CodeBurn0.9.23 metadata snapshot ended2026-10-03T05:55:56.051Z:
  Root session01a0f16d-e27e-7a43-8d7c-d0e5b07a12bd,17turns/1397calls,
  input4482462/output592914/cache-read186188544/cache-write0,
  session duration39355500ms. Root-only filter applied before output; no raw
  session bodies read. Same-day/session cumulative values include historical
  work, not exact current-turn/epic usage, child attribution, bill or savings.
  Current-turn and per-child token savings remain NOT_AVAILABLE.
