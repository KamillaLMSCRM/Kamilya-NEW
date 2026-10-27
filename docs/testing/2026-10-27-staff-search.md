# Staff search and employee-list acceptance — 2026-10-27

Status: **local candidate ready; not deployed**. This is a separate hotfix, not
acceptance or release of the unfinished generation engine.

## Scope and identity

- Checkout: `C:\Kamilya New\Kamilya-NEW\.worktrees\staff-search-20261027`.
- Branch: `fix/staff-search-20261027`; base `93ccbfabc8fcc0429140db35876c232e1f4ea0fc`.
- Base application files match production65 `00e41ca7001564574fb89d2de97f9636d7e5020f`.
- Preserved ordinary staff edit/transfer preview/explicit-confirm contracts,
  tenant/RLS, access, position, placement and pagination filters. No migrations.
- No employee, position, course, enrollment, result, history, role or model-setting
  writes. Existing ordinary authentication/tenant-view audit only.

## Confirmed production defect

At 06:17 UTC, ordinary authentication and the canonical methodologist tenant view
confirmed the exact requested client tenant. With identical company-wide filters:

| Fragment | Active access | Any access |
|---|---:|---:|
| `танаб` | 0 | 0 |
| `Танаб` | 1 | 1 |
| `ТАНАБ` | 0 | 0 |

A read-only, paginated inventory confirmed one matching active employee. No client
row payload, identifier, email or token was saved in the report. An independent
production synthetic-QA browser reproduction likewise returned zero for `тест`
and four for `Тест` with unchanged filters.

The existing SQL-NAME-001 recurrence applies: production C collation does not
case-fold Cyrillic as required by `ILIKE`. The roster already searches before
count/offset/limit; the defect was not a first-page-only frontend filter.

## Changes

1. Use existing expression-local `und-x-icu` on both SQL `lower` operands for
   name and personnel-number comparisons. Keep bound/escaped literal patterns.
   No global database locale, schema, grants, indexes or provider changes.
2. Start search after a 300 ms typing pause; Enter/Find submits immediately.
   Keep the selected unit/access/position visible and reset to page one for a
   changed search. A single explicit action widens to all employees while keeping
   the fragment. An empty result explains the exact query and scope.
3. Persist query and position in URL state; reload and Back/Forward restore them.
   Unknown/deleted/foreign position links normalize before any roster request.
4. Removable filters and one reset action; return keyboard focus to search after
   clearing. Hide old count/rows while pending. Hide empty pagination. Keep name,
   personnel number, position, unit breadcrumb and actions readable on small and
   large screens; remove internal placement-provenance wording from ordinary rows.
   The guarded transfer preview still shows consequences before confirmation.
5. Add Russian, Kazakh and English copy for the new search controls.

## Verification and proof boundaries

| Gate | Result |
|---|---|
| Backend behavioral/SQL regression baseline | RED 2 failed / 1 passed |
| Initial frontend interactions | RED 4 failed / 1 passed |
| Stale position / duplicate reset regressions | RED 2 failed / 4 passed |
| Final focused search + existing workspace/page integration | 38 passed, 4.73 s |
| API search, scaling and guarded change regressions | 52 passed, 2.17 s |
| Actual Supabase DEV, C-collated synthetic VALUES | 11 checks PASS, transaction READ ONLY |
| Actual changed `employee_roster`, permanent DEV QA + RLS | PASS: three case variants have identical IDs/totals; foreign tenant empty; no writes |
| Full web suite, bounded two workers | 173 files / 1345 tests PASS, 194.77 s |
| Python quality baseline | PASS, existing Ruff1005 / Mypy2170 debt unchanged |
| Web lint/typecheck and final production build | PASS; 67 static pages |
| Independent frontend review | No remaining P1/P2 in local path |

The first unconstrained full web run had 1344 passes and one failure waiting for
the unrelated signed-scan Accept button in `learningInsightsJournal`. No runtime
or test was changed for that failure and no timeout was increased. The exact
file plus search passed 13/13; the complete bounded run then passed 1345/1345.
Its precise intermittent cause remains unproven; do not claim a fix to the
training-log feature or infer CPU causality from this rerun.

Browser acceptance mounted the **real changed component and API client** in an
isolated local synthetic fixture, with 1000 employees and no backend network or
mutations. It covered starting on page40, `танаб`/`ТАНАБ`, no hidden first-page
filter, query retention, narrow-unit empty result, widen-to-company, reload,
Back/Forward, clear/focus, RU/KK/EN search copy, and 390/768/1440 px without
horizontal overflow. Desktop header/row column coordinates matched exactly.
Fixture matching is not evidence of server Unicode behavior; the separate real
PostgreSQL and candidate-function gates provide that evidence.

The changed function was executed locally against the real DEV QA database. This
is **not** a deployed DEV HTTP-route or production release claim. Public DEV and
production runtimes have not been replaced. A separately approved protected
release still needs exact CI/deployment identities and live readback.

## Reproduction artifacts and final source

Sanitized local receipts, READ ONLY probe sources and screenshots are under
`.release-evidence/staff-search-20261027/` in this checkout. Authentication tokens
and raw client staff payloads are not persisted. Temporary browser/server closed.

Final SHA256:

- `workspace_read.py`: `89548177bcd4466a15e99d7bede31d829086343869c3c18356a3c2bfb1ac2adc`.
- `StaffWorkspace.tsx`: `2c846b8533ccb642be9322f359296aa4bcc1b2d0c85789171aef6609de14b599`.
- `staffWorkspaceSearch.test.tsx`: `b2aecb5e94c30b9041663ce71bb7dec335059e5ba350fe23d813de81817fd5cc`.

Before deployment, keep this hotfix separate from LOCAL129/V215 generation work,
confirm exact release authority and current DEV identity, then use the canonical
protected procedures. Post-release: verify all three case variants return the
same single client employee via read-only search, and repeat the synthetic
browser search/filter/reload scenario. No employee-data migration is required.


## Production66 closeout — 2026-10-27, PASS

Frozen tag/runtime `v0.11.66` / `7c35c798d9ff4e44183a1e499f1b1c1a7cc2fe16`.
CI master40469278685 / DEV40467889903, native40468000163 and protected backend
40469647733 all SUCCESS. Exact API and three workers green/image
`6af62edb34c85324d05d4412d91f36da832303e530df1c928ae09f95dd6f3223`, running/restarts0;
public/private health66. Native CT137 exact66/marker/nginx/routes PASS, archive
SHA256 `0a69c4b5514e027115eaa6626377bc763fae475360fa2c5a59fcee0b7b27088d`.
DEV API dep-dbg5aicipgvc73eijl8g, worker dep-dbg5bip42hec73dl5vmg and frontend
dpl_AgCVYsu2hevoftKttsB8a7uq2MUr exact66 live/READY on unchanged Free/Free/Hobby.

Real DEV ordinary methodologist: case parity, unit-empty/widen, query/position
reload and clear16→search1 PASS. Production Lombard ordinary methodologist view:
lower/title/upper fragment each returns1 for active/all; actual browser uppercase,
lowercase, other-branch empty, widen and reload PASS. Employee273 hash
`beae5545ccd5f42f66aec11bb3dada764f8aa09c97d3dc0a93e55658c977e126`
and workspace hash
`32216dbb7b7df280f3435f09c59ac2e8d081d2fc7dccfb57dbc65d3953f7778e`
unchanged.273 is the student roster, not all280tenant users. No staff/customer
data writes, assignments, history changes or new model calls. No fresh broad CRUD
or assignment acceptance claimed for this search-only package.

Post-maintenance local3296 API/PDF and1345web/173files PASS; build67, quality
1005/2170 unchanged, runtime SCA passed in exact CI/build. Existing initial CI/native
failures and intermittent unrelated journal timeout remain documented.

Fresh signed0183 restore PASS:130public tables126FORCE/RPO44s/RTO19s, disposable
DB/plaintext/temp absent. Independent CT125 revision0183/FORCE7/runtime non-BYPASS,
model routing unchanged. Backend65 retained healthy API/stopped workers as rollback;
native65 retained as immediate rollback,62 and protected359/299 retained. Actual
rollback switch NOT_RUN. Native artifact required1321046199bytes; capacity passed,
no CT137 cleanup or Proxmox used. Postrelease native free668108KiB is bounded
headroom, not readiness for another release without a fresh capacity check.

Standing owner capacity authority used only for seven unused local API copies:
obsolete64 c78a29bed…fcca2;0f741d440…6f555;5335396f…e2440;96a1bc2c…292e2;
a395295d…26d0f;a6c99741…8507e;fcb47c54…879b. Each exact GHCR index/amd64/body digest
and13blobs verified; all16container references checked before/after, current66,
rollback65 and extra62 protected; registry/containers/volumes/DB/config unchanged.
No force/prune. VM126 free1350→5939MB, df96→82%; cleanup stopped below existing
85% warning threshold. First finalizer failed on disk warning and restored its old
config; R2 after cleanup passed, only EXPECTED_RELEASE/EXPECTED_API_IMAGE changed,
byte-identical root backup retained, watchdog success/exit0 and both timers active.
Earlier capacity-reader12-container assumption and invalid output format were
read-only failures; corrected inventory16, no deletion ran on those failures.

Autonomous existing credential login works via direct process-local ordinary form
fill. Owner must not be asked again to log in because diagnostic getters mask
values. Old textarea helper exposed a synthetic DEV password in a tool snapshot;
its value is not repeated or persisted here. This was not a customer credential.
Do not use that helper or claim zero prior output exposure.

Evidence: `.release-evidence/staff-search-20261027/`; safe UI screenshot
`dev-live-search-result.png` uses synthetic DEV data. Provider-after inspection
overwrote its hardcoded before filename; truthfully retained as providers-after.json.
The original first provider observation is only in tool history; controller and
after receipts establish unchanged approved tiers. No fabricated durable baseline.
