# Fix training log filtering, counts, and export consistency

## Scope

Repair the confirmed training-log search and interpolation defects without changing
tenant isolation, role ownership, invitation/auth flows, or unrelated localization.

## Plan

1. Inspect the API, frontend query state, translations, CSV export, and existing
   focused tests; identify the actual search/filter and formatting root causes.
   - Status: completed
2. Implement the smallest backend/frontend changes so table, summary, pagination,
   and CSV share the same tenant-scoped filters.
   - Status: completed
3. Add focused regression tests for matching search, rendered count text, export
   filtering, and report-query invalidation after enrollment mutations.
   - Status: completed
4. Run proportionate backend and frontend verification, record exact results and
   residual risks.
   - Status: completed

## Execution log

### Step 1

- Status: in progress
- Notes: Graphify identified the training-log router/service/schema, frontend page,
  API client, translations, enrollment model, and integration tests as the relevant
  implementation surface. Existing `graphify-out/` is pre-existing and will remain
  untouched.

### Step 1 result

- Status: completed
- Root cause: the page debounced `searchInput` but never copied it to
  `filters.search`, so the table and CSV request never contained `search` even
  though the repository already applies tenant-scoped name/email/personnel-number
  predicates. The summary endpoint accepted no filters and was fetched once per
  mount, so its cards could not match a filtered table/CSV. Locale values used
  `{{name}}`, while `useT` intentionally interpolates `{name}`, leaving a pair of
  literal braces around each rendered value.
- Evidence: `training_log/repository.py` applies the required `ILIKE` conditions
  after `User.tenant_id == tenant_id`; `training-log/page.tsx` built its query
  exclusively from `filters`; and `useT.ts` uses `/\\{(\\w+)\\}/g`.

### Step 2

- Status: completed
- Changed `apps/web/src/app/admin/training-log/query.ts` and the page so one
  trimmed, debounced filter query drives table, summary cards, and CSV. Search
  now reaches the existing backend predicate.
- Changed the summary endpoint/service to accept the same filter contract as the
  table, and added `Cache-Control: no-store` to JSON responses so the next fetch
  after an assignment or completion cannot reuse a browser cache entry.
- Updated only `trainingLog.summary` interpolation templates in RU/KK/EN from
  `{{name}}` to the renderer's `{name}` syntax.
- Tenant safety: no repository predicate was weakened; every list/count query
  continues to begin with `User.tenant_id == tenant_id`.

### Step 3

- Status: completed
- Backend regression coverage adds name/email/personnel-number search assertions,
  verifies the filtered CSV contains the same single employee, and verifies a
  filtered summary/table update from assigned to completed after enrollment state
  mutation with `no-store` cache headers.
- Frontend coverage verifies the shared query includes a trimmed search term and
  renders concrete RU/KK/EN total/pagination strings without placeholders.

### Step 4

- Status: completed and production-verified
- Passed after starting the local pgvector/PostgreSQL service and migrating an
  isolated `kamilya_lms_test` database: combined invitation and training-log suite
  (24 tests), backend `compileall`, frontend `npm.cmd test -- --run` (10 files,
  91 tests), `npm.cmd run typecheck`, Windows-compatible `npx.cmd next build`,
  locale JSON parsing, and repository-wide `git diff --check`.
- Integration review replaced the counter-based debounce with explicit
  `debouncedSearch` state so all table, summary, reset, and CSV queries use the
  settled value without a hook race. It also corrected the previously observed
  onboarding placeholder strings, which use the same single-brace interpolator.
- Graphify was used to trace the router/service/repository/page/tests before
  editing and was refreshed with `graphify . --update --code-only`. A normal
  update first stopped because document semantic extraction has no configured LLM
  key; code-only indexing completed successfully.
- Production verification on revision `5675f2b`: searching for
  `QA-UX-20260723-001` reduced the table from two rows to the single matching
  employee, changed the filtered summary/total to one, rendered `Показаны 1–1`,
  and exposed no placeholder braces or browser errors.
