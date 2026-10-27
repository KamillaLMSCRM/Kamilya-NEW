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
