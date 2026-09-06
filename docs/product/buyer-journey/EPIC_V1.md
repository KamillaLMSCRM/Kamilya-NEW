# BUYER-JOURNEY — useful example before setup

Status: Accepted. Document V1, template V2. Supersedes: none.
Approved by: product owner, current instruction to implement the reviewed plan,
2026-09-06. Root owner: Astra (contracts, integration, release decisions).
Module owners: root for EXAMPLE and DECK; bounded Terra worker for START;
existing landing owner for PUBLIC. Reviewer: independent Luna plus root review
of delegated changes. Product owner retains material scope/production decisions.
Change control: worker proposes -> root reviews compatible impact addendum ->
product owner approves new business/authority scope; root may stop/cancel safely.

## Objective and boundaries

A visitor without documents can read a concrete lesson, answer a question, see
clearly synthetic learning outcomes and understand the next action and two starts.
No seed writes, real identities, provider calls, mail, AI generation, migration,
new permissions, billing, human-service promises, compliance guarantees or removal
of historical presentations/instructions. Preview is an interactive illustration,
not a live training record or proof of a user's professional competence.

## States, interfaces and module map

PUBLIC/DECK/START -> EXAMPLE `/login/example?lang=ru|kk|en` V1.
EXAMPLE: lesson -> selected answer -> checked feedback -> illustrative records ->
next-step explanation; reset is local and repeatable. No durable state.
START -> existing `/ai/generate`, `/courses`, `/training-log` V1.
PUBLIC -> existing registration and lead modal; consent/conversion contracts unchanged.
DECK -> same preview and existing public HTML/PDF URLs.

## Accepted mini-specs (core and applicable extended fields)

| Field | EXAMPLE V1 | START V1 | PUBLIC/DECK V1 |
|---|---|---|---|
| Responsibility/contribution | Explain lesson/check/outcome/action with synthetic content | Explain available start and prioritize actual training work | Consistent buyer story and division of responsibility |
| Non-responsibilities | Actual enrollment, authentication, tenant operations | Alter onboarding completion or backend contracts | Marketing operations, ads/billing, legal certification |
| Interface/input/output | Public route with allowlisted language -> interactive local example | Existing status/jobs -> unchanged real progress plus entry links | RU/KK locales/components and public deck -> preview URL and truthful copy |
| Data owner/writers/readers/retention | Root-authored fixtures; browser state; public; reset/unmount clears | Existing API remains owner; worker edits presentation only | Static public copy; root/landing owner; public; Git |
| Invariants | Always labeled illustrative; no API/auth/store dependency; no PII or persisted result | Role gates, draft requirements, real empty states and active jobs preserved | Two start options; expert approval required; no unsupported claims; forms and measurement preserved |
| State/error modes | No selection: check disabled; wrong: explain/retry; right: explain; invalid locale: RU | Existing loading/error states; do not hide nonempty failed/unknown jobs | Stateless; links tested; missing copy/build failures block release |
| Security/privacy | No tenant key, DB or credentials because no tenant data exists | No new writes, capability or token handling | No form submission or customer content in examples |
| Dependencies/adapters | React/Next public rendering only | Existing onboarding, jobs and course interfaces | Next-intl, existing registration/modal; public preview URL |
| Forbidden side effects | API/DB/auth/AI/mail/analytics additions | Backend edits, fixture injection, resetting real data | New paid integrations, CSP/consent changes |
| Idempotency/concurrency | Local answer/retry repeatable, no shared state | Read-only presentation, API unchanged | Static assets, one writer/path |
| Observability | Visible illustrative label and local feedback, no payload logging | Existing status/error signals retained | Existing analytics only; no invented conversion event |
| Performance/config | Tiny static fixture, no new dependency/config | Existing fetches retained | Existing deployment/runtime only |
| Verification | RTL render/answer/reset/languages; source no-network; browser anonymous and responsive | Focused onboarding/dashboard/demo/template tests, typecheck, regression | Locale leakage/CTA contracts, test/lint/typecheck/build; desktop/mobile RU/KK; deck/PDF visual QA |
| Read scope | Web route wrapper, styles, UI/tests | Named web files and immediate callers/tests; instructions/graph | Landing source/tests/docs; reviewed report; deck assets |
| Write scope | `apps/web/src/app/login/example/`, `apps/web/src/features/product-example/`, `apps/web/tests/productExample.test.tsx` | dashboard, login/demo, OnboardingChecklist, template page, blueprintAdaptation, RU/KK/EN locales and focused new tests only | Landing Hero/ProductCatalog/FAQ, RU/KK messages, focused tests (landing owner); public presentation assets and PresentationShowcase (root) |
| Stop conditions | Any live data/auth dependency | Unlisted write, backend dependency or dirty overlap conflict | Unlisted provider/form/measurement change |
| Ready | This contract and known public-prefix source verified | Existing status/role seams verified; preserve preexisting locale changes | Separate repo ownership and current hero/graph verified |
| Done | Tests, anonymous user flow and exact deployed readback | Tests, real/synthetic separation, role and active-job regression, deployed readback | Matching copy/routes/artifacts, checks, visual review and exact deployed readback |

## Impact matrix and negative space

| Existing module | Class | Change | Protected behavior / check |
|---|---|---|---|
| RouteWrapper/auth | Consumer | Existing public `/login` prefix | No role/session source edits; public preview render without auth |
| Onboarding/dashboard | Interface presentation only | Links + hide empty job board | Real completion and role ownership unchanged; nonempty jobs remain visible |
| Template adaptation | Interface presentation only | Localized friendly wording | Required answers/create guard and legal limits retained |
| Course generation/training log | Consumer | Existing navigation only | No mutations/schema/workers; existing focused tests |
| Lead/trial/consent | Consumer | CTA hierarchy/copy | Existing form transport and conversion contract tests |
| Providers/DB/security/retention | None | None | Diff check excludes these paths |

## Critical journeys and release

CJ1 anonymous RU/KK: public link -> lesson -> incorrect/correct feedback ->
synthetic completed/failed/overdue rows -> truthful next-step explanation.
CJ2 methodologist: start from basis without required upload; normal tenant remains
empty; active/failed jobs remain reachable; expert approval and required fields stay.
CJ3 site/deck: two starts and same responsibility boundary; coherent HTML/PDF.

Verify focused -> executable consumer link/interface tests -> impacted regressions
-> full frontend and landing checks once -> browser desktop/mobile -> exact candidate
release/readback under canonical runbooks and exact authority. No DB gate needed
for purely static changes, but no assertion of backend deployment equivalence.
Rollout: app preview first, then public consumers. Rollback scoped commit changes;
no data rollback. Production gate remains pending until candidate and authority
are resolved. Unexpected graph dependencies or failed gates stop release.
