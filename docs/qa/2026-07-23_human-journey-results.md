# Human-journey production QA results

**Executed:** 2026-07-23, Asia/Qyzylorda
**Environment:** production `https://app.kml.kz`; current local baseline `master` `7bbc069a122c7b9d3ef98a8b7cde2a7284945210`.
**Method:** black-box Chrome production interaction first, DOM/accessibility snapshots and application console review. Desktop 1440×900; critical public pages also at 390×844.
**Data safety:** Only the visually labelled `Демо-организация` was changed. Created `QA-UX-20260723-001` / `QA-UX 20260723` with a non-deliverable `example.invalid` address and one manual enrollment. No customer data, personal mailbox or external file was used. Existing rows were not changed/deleted.
**Graphify:** Used. Code-only graph indexing (semantic extraction unavailable without a configured key) selected `register-tenant/page.tsx`, `login/page.tsx`, `accept-invite/page.tsx`, `rolePolicy.ts`, `Layout.tsx`, `Sidebar.tsx` and `TopBar.tsx` for later corroboration; findings below remain browser-observed.

## Executive verdict

**No: a Kazakhstan corporate client cannot yet complete the promised flow today without expert help.** The entry and core methodologist actions are understandable enough to create a learner and manually assign an existing published course. However, the required access hand-off fails in production: invitation history reports a load failure, an independent review captured HTTP `403` from `GET /api/v1/users/invitations?per_page=100`, and a new invite shows only `Не удалось создать приглашение`. This blocks the new employee from opening the assigned course, taking the quiz and receiving a certificate. The management log also has a non-functioning text filter and exposes untranslated interpolation placeholders, weakening trust in the claimed result. A summary-card mismatch observed immediately after the assignment did not reproduce after fresh navigation and is therefore tracked as a possible stale-state defect, not a deterministic reporting failure.

### Minimum changes before a real pilot

1. Fix and production-verify learner invitation creation/listing with a copyable invite URL; then run an authenticated invite → learner → course → required quiz → certificate smoke test.
2. Fix training-log filtering and reconcile summary counters with the actual returned rows/export.
3. Remove or relabel forbidden admin dashboard learning-management CTAs so they do not lead to redirects; preserve the RBAC boundary in the ADR.
4. Finish high-visibility RU/KK copy: remove `Minimum 8 characters`, translate KK filter options/placeholders and clarify Telegram prerequisites/recovery.
5. Repeat this scenario with an isolated disposable trial tenant, including AI source/indexing/review/publish and mobile learner completion.

## Evidence

| Path | What it supports |
|---|---|
| `docs/qa/evidence/2026-07-23-human-journey/A04-login-desktop.png` | Public RU login: Email/Telegram choice, registration and demo paths. |
| `docs/qa/evidence/2026-07-23-human-journey/A03-register-desktop.png` | Trial framing, company fields and Russian-form copy inconsistency. |
| `docs/qa/evidence/2026-07-23-human-journey/D02-demo-learner-empty-state.png` | Demo learner lands on a truthful empty assignment state. |
| `docs/qa/evidence/2026-07-23-human-journey/E01-training-log-desktop.png` | Shared operational result view after disposable assignment. |
| `docs/qa/evidence/2026-07-23-human-journey/D01-invitation-history-403.png` | Methodologist invitation-history state after the failed load; the independent network capture returned HTTP `403`. |
| Browser DOM snapshots recorded during this run | Exact success/error copy, role redirects, source/assignment states and counters documented below. |

## Persona outcomes

| Persona | Reached | Outcome | Status |
|---|---|---|---|
| A. First decision maker/admin | Public login, Telegram selector, trial registration fields, mobile views | Value/trial scope and Kazakhstan-company inputs are clear. Could not complete a trial without creating a new production tenant, intentionally not done. | Partial — safe environment limit |
| B. Tenant admin | Demo admin dashboard, navigation, direct blocked route, training log | Clear tenant context and direct `/assignments` protection; dashboard sends conflicting signals with forbidden learning links. Team invitation not exercised to avoid changing existing system users. | Partial |
| C. Methodologist | Demo staff structure → disposable learner → published-course assignment → training log | Manual staff creation and course assignment succeeded; document/AI/publish not run because demo quota/source data were shared and invitation is already blocking downstream result. | Partial |
| D. Employee | Demo learner entry and empty state | Learner home/navigation renders, but no assigned course exists for that identity. Disposable learner invite creation failed, so course/quiz/retry/certificate were blocked. | Blocked by confirmed defect |
| E. Manager/methodologist | Admin training log, QA row, filters, KK | QA assignment is visible and status cards are consistent after fresh navigation, but search does not filter and pagination text exposes placeholders. CSV was not downloaded because the displayed filter did not isolate QA data. | Partial / unreliable |

## Detailed executed results

| ID | Actual observed result | Classification | Severity / reproducibility / business impact |
|---|---|---|---|
| A01–A02 | Root state restored an authenticated demo methodologist instead of a public landing page. `/login` is discoverable and provides clear Email, Telegram, register-company and demo choices. | Environment/session context; UX observation | N/A. A true clean-browser marketing-to-app handoff remains untested. |
| A03 | `/register-tenant` clearly states 14-day trial, 1 ordinary + 1 job-instruction generation, up to 10 learners, company/contact/email/password/phone/Telegram/BIN-IIN/goal. It uses Kazakhstan-relevant examples `ТОО` and `+7`. Password help remains English: `Minimum 8 characters`. | Confirmed UX ambiguity/defect | Minor; deterministic; makes the Russian form look unfinished. |
| A04 | Email path says `Рабочий email` and `Получить код`. Telegram tab switches to only `Получить Telegram-код`; it does not tell a first-time person whether the bot must be started, where the code will arrive, how long it is valid, or what to do if it fails. | Confirmed UX ambiguity | Major for Telegram-led onboarding; deterministic; likely support burden/drop-off. |
| A06 | Russian/KK selector is visible. KK translates navigation/headings/statuses, but training-log option values remain Russian (`Все статусы`, `Назначен`, etc.), top-bar tenant context stays Russian (`Кабинет: Демо-организация`), and product terms mix (`AI генерация`, `Native`). | Confirmed localization defect | Major for a Kazakhstan bilingual client; deterministic; cannot describe KK as a complete working UI. |
| B01 | Demo admin entry lands at `/admin`, shows Demo organization context and a preparation checklist. Reload/session persistence was not independently retested after role change to avoid session mutation across shared demo tabs. | Pass with scope limit | N/A. |
| B02–B03 | Sidebar correctly limits admin navigation. Direct `/assignments` redirects to `/admin`. But the admin dashboard checklist and quick links still visibly offer `Импортировать штат`, `Загрузить документы`, `Сгенерировать первый курс`, `Назначить курс сотрудникам`, and staff links—methodologist-owned activities—before redirecting when followed. The demo role selector also describes the administrator as managing courses. | Confirmed UX/RBAC policy conformance defect | Major; deterministic; admin is told to perform work they cannot perform, contradicting ADR-0012 and wasting pilot time. |
| C01–C03 | Methodologist staff screen clearly says Excel/CSV or manual add. Disposable `QA-UX-20260723-001` was saved; counters moved 0→1 learner and 5→6 positions; structure exposed it under IT/QA Tester. No console warnings/errors. | Pass | Demonstrates a viable manual-structure start, although auto-created position is not explained before saving. |
| C04–C07 | Document/AI/publish flows were intentionally not executed: only shared demo source/quota existed and downstream invite was already failing. UI navigation labels identify the areas but cannot substitute for end-to-end evidence. | Environment/safety blocker | Not a product pass; full source provenance/review/publish requires an isolated QA tenant. |
| C08 | Published `Охрана труда для офисных сотрудников` was selected; disposable learner checkbox became available; `Записи на курс (1)` succeeded. Table changed to `Записи на курс: 2`, QA row `Записан`, `Вручную`; toast `Назначено обучающихся: 1`. | Pass | The manual assignment portion of the promise is achieved. |
| D01 | `/admin/invitations` initially showed `Приглашений пока нет` **and** toast `Не удалось загрузить приглашения`. After entering the disposable email and pressing `Создать ссылку`, UI showed `Не удалось создать приглашение`; history remained empty. Independent review reproduced the history failure and captured HTTP `403` from `GET /api/v1/users/invitations?per_page=100`; no browser console error was logged. | Confirmed defect | **Blocker**; reproducible in demo production; stops the supported no-email copyable-invite learner path. |
| D02 | Demo learner login lands at `/my-courses`, has understandable learner-only nav, and states `Вы пока не записаны ни на один курс`. This is a truthful empty state, but the assigned disposable learner cannot access it because D01 failed. | Pass / downstream blocked | The employee experience is visible but the actual QA assignment cannot be consumed. |
| D03–D05 | No safe route to login as the assigned QA learner after invitation failure. Course player, saved resume, quiz failure/retry, certificate issue/PDF and learner refresh persistence were not run. | Confirmed downstream blocker | Blocker; promised business outcome cannot be evidenced. |
| E01 | Training log showed the QA enrollment as `Назначен 0%`, plus an existing completed record with certificate number. This makes assignment outcome visible without a spreadsheet. | Pass | Good information architecture baseline. |
| E02 | Entering `QA-UX-20260723-001` in `Имя, email или табельный номер` left both rows visible; independent review reproduced this after a 900 ms debounce wait. The counter also renders `Всего записей: {2}` and pagination `Показаны {1}–{2}` instead of values. The earlier post-assignment card state (`2 assigned / 1 in progress / 0 completed`) did not reproduce after fresh navigation; current cards correctly show 1 assigned, 0 in progress and 1 completed. | Confirmed search/i18n defects; possible intermittent stale-state defect | **Major**, deterministic for search/placeholders; managers cannot isolate a person safely. Summary-card mismatch needs a dedicated cache-invalidation reproduction before severity is assigned. |
| E03 | CSV is available, but was not downloaded because the failing filter left pre-existing person data visible. | Safe-test limitation caused by confirmed E02 defect | No export usability claim made. |
| Cross-cutting mobile/accessibility | Login and registration maintain labelled inputs and a visible skip-to-content link at 390×844; DOM did not expose horizontal overflow. Keyboard-visible focus, contrast at 200% and modal escape were not fully instrumented. | Partial evidence | Needs dedicated accessibility pass. |
| Performance/feedback | Main screens showed brief `Загрузка...`, then stable content. Staff save exposed `Сохраняю...` and resolved successfully; assignment toast was explicit. Invitation operations fail with generic error only and no recovery/support action. | UX observation + confirmed defect | Major for recovery: user cannot self-diagnose or continue. |

## Prioritized recommendations

1. **P0 — Invitation endpoint/UI:** reproduce from a disposable tenant, preserve server response/log correlation, correct the failing request, and surface a created copyable URL plus expiry/retry guidance. Verify history load and creation with a browser refresh.
2. **P0 — Training log truthfulness:** trace search/filter state and placeholder interpolation; add browser/API tests asserting a query returns only matching rows and displays concrete counts. Add a focused assignment cache-invalidation test before classifying the one-time summary mismatch.
3. **P1 — Role-safe onboarding:** admin checklist must link only to admin-owned work or explain that the next action is to switch/ask a methodologist; do not present inaccessible workflow CTAs.
4. **P1 — Learner E2E gate:** automated and manual production smoke: disposable invite → accept → assigned native course → lesson progress survives refresh → failing quiz retry → pass → certificate → visible log/export row.
5. **P1 — Kazakhstan language quality:** full RU proofread and complete KK strings, including native select options, placeholders, tenant chrome and product terminology.
6. **P2 — Complete QA matrix:** capture real mobile screenshots, 200% zoom, keyboard modal/validation behavior, OTP arrival/retry, source indexing/AI provenance/review/publish, rule-driven assignment, SCORM, CSV content/encoding and cleanup.

## Cleanup and residual data

- Created Demo-only disposable learner `QA-UX-20260723-001` and its manual enrollment. They remain intentionally so the root agent can reproduce the log/invitation defects and validate a fix. They are the only records created in this QA pass.
- No invite was created (server/UI reported failure); no files or AI jobs were created; no existing data was deleted or altered.
- Evidence images contain no non-disposable data beyond the visibly available Demo tenant UI. No secrets appear in these reports or evidence paths.
