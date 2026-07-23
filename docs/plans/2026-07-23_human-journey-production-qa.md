# Human-journey production QA — 2026-07-23

## Scope

Read-only, evidence-backed production UX QA for Kamilya LMS from the perspective of a first-time Kazakhstan corporate client. No deploy, commit, production-code change, or modification/deletion of existing customer data is authorized.

## Plan

1. Establish the production baseline: read the current project, auth/RBAC, operational and ADR documentation; inspect repository state; use Graphify only for targeted architecture orientation.
2. Create the reusable scenario and disposable-data guardrails; confirm the production entry point and available login/onboarding paths without exposing secrets.
3. Run the unauthenticated first-time visitor/admin journey at desktop and mobile sizes, capturing entry, auth, empty/error, language, accessibility and recovery evidence.
4. Run the safely accessible authenticated role journeys (admin, methodologist, employee/learner and manager) without modifying existing customer data; capture permission boundaries and outcome visibility.
5. Assess the end-to-end business outcome, consolidate observed evidence and distinguish confirmed defects, UX ambiguities, data/environment blockers and out-of-scope capabilities.
6. Produce the reusable scenario and executed-results report, perform secret/working-tree hygiene checks, and hand off the findings to the root agent.
7. Independently review high-severity findings and correct any claim that does not reproduce.

## Execution log

### Step 1 — production baseline and targeted orientation

**What I did:** Read the required project handoff, product/current-context, internal, documentation-index and relevant auth/RBAC/tenant ADRs; inspected `master` at `7bbc069` and the last eight commits. Graphify was built in code-only mode and its targeted auth/role query selected `register-tenant/page.tsx`, `login/page.tsx`, `accept-invite/page.tsx`, `rolePolicy.ts`, `Layout.tsx`, `Sidebar.tsx` and `TopBar.tsx` for later corroboration.

**Checks:** `git status --short` shows only the pre-existing ignored/untracked `graphify-out/`; Graphify semantic extraction initially lacked an LLM key, then code-only indexing completed successfully. No secrets were read or printed.

**Status:** ✅ done

### Step 2 — reusable scenario and safe-production guardrails

**What I did:** Created `docs/qa/2026-07-23_human-journey-scenario.md` with repeatable persona scripts A–E, test-data naming, preconditions, exact expected human outcomes, evidence fields, recovery/cleanup notes and an end-to-end acceptance gate. Confirmed that the browser has an existing authenticated `Методист Демо` session in the explicitly labelled `Демо-организация`, while `/login` and `/register-tenant` remain inspectable unauthenticated.

**Checks:** No form was submitted and no production data was mutated. Registration visibly offers a 14-day trial, one ordinary and one job-instruction AI course, up to 10 learners, with a copy issue observed in the otherwise Russian form (`Minimum 8 characters`). Login visibly exposes Email and Telegram paths; Telegram only exposes `Получить Telegram-код` with no pre-send explanation.

**Status:** ✅ done

### Step 3 — unauthenticated and first-run browser journey

**What I did:** Exercised `/login`, Email/Telegram selector, `/register-tenant`, navigation/reload and RU/KK visible language paths at 1440×900 and 390×844 without form submission. Captured the public login and registration views.

**Checks:** Both entry routes render and are mobile-readable in DOM/accessibility snapshots. Registration correctly describes a 14-day trial, 2 AI generation types, up to 10 learners and a Kazakhstan-style company identity (`ТОО`, BIN/IIN, `+7`). Confirmed UX issues: English `Minimum 8 characters` in the Russian registration form; Telegram view gives only `Получить Telegram-код`, without explaining destination, prerequisite bot interaction, expiry or fallback; global language selection leaves important Russian values/options/mixed product terms on the KK page.

**Status:** ✅ done

### Step 4 — authenticated role journeys and business outcome

**What I did:** Used the visibly labelled Demo organization only. Created the disposable learner `QA-UX-20260723-001`, manually assigned the published course `Охрана труда для офисных сотрудников`, and verified the assigned record in the shared training log. Tested demo learner and demo admin entry paths, role-specific navigation, blocked direct admin access to `/assignments`, invitation creation, learner empty state, training-log search and RU/KK views.

**Checks:** Manual staff creation and manual assignment succeeded with visible result updates; the learner can be found in the log. Invitation history loaded with a visible error and creation of the disposable invite failed (`Не удалось создать приглашение`); therefore the new learner could not enter/complete the assigned course. Existing Demo learner had no assignments. Training-log text search retained both rows rather than filtering, and summary counters (`2 assigned / 1 in progress / 0 completed`) contradicted the visible table (`1 assigned / 1 completed`). Admin direct navigation to `/assignments` correctly redirected to `/admin`, but the admin dashboard still promotes multiple forbidden learning-management links. No browser console errors were recorded for the observed UI failures.

**Status:** ✅ done

### Step 5 — findings synthesis and evidence classification

**What I did:** Classified browser observations in `docs/qa/2026-07-23_human-journey-results.md` into confirmed defects, UX ambiguity, environment/safety limits and out-of-scope work. Prioritized the production invite failure and reporting-truth defects before any pilot.

**Checks:** Each persona has an explicit reached/stopped state. The executive verdict does not claim unexecuted source-to-certificate behavior as passing. Evidence paths and created Demo-only records are recorded for reproducibility.

**Status:** ✅ done

### Step 6 — artifact hygiene and handoff

**What I did:** Saved the scenario, results and five non-secret browser evidence screenshots under `docs/qa/`. Reset the temporary responsive viewport and finalized the browser QA session.

**Checks:** Secret-pattern scan of the new QA artifacts had no matches; whitespace checks passed. `git status --short` shows only these intended untracked QA artifacts plus the pre-existing `graphify-out/`, which remains untouched and untracked. No commit, push, deploy or production code change was made.

**Status:** ✅ done

### Step 7 — root-agent independent review

**What I did:** Re-entered the production demo as admin and methodologist. Reproduced the training-log search failure and interpolation placeholders. Reproduced invitation-history failure and captured HTTP `403` for `GET /api/v1/users/invitations?per_page=100`; saved a sixth screenshot.

**Checks:** Search still returned both rows after a 900 ms wait. Invitation history still showed `Не удалось загрузить приглашения`. Freshly loaded cards correctly showed 1 assigned, 0 in progress and 1 completed, matching the two table rows; therefore the earlier mismatch was downgraded to a possible intermittent stale-state issue pending focused reproduction.

**Status:** ✅ done
