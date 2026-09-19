# Kamilya Test Run Ledger

This append-only ledger stores sanitized, version-controlled evidence from the
persistent Kamilya Test & Evidence Runner. It is not a replacement for CI,
provider/runtime readback, `ERRORS.md`, critical-journey contracts, or root review.

Rules:

- never edit or delete an accepted run entry; append a correction referencing it;
- never store secrets, `.env` values, PII, tenant payloads, contact data, or raw
  production logs;
- use exact immutable Git SHA and UTC timestamps;
- distinguish product, harness, access, and provider failures;
- historical green results are not evidence for a later SHA or runtime;
- only one active writer owns this file at a time.

## RUN-20260828-HELP-TEAM-MODAL-01

- Timestamp: `2026-08-28T05:30:00Z`
- Executor: root orchestrator (seed entry before Test Runner ownership)
- Exact SHA: `d3d7ec3428a1730a1f68d76d09aea065acea7741`
- Scope: shared modal portal, contextual help viewport containment, create-user
  backdrop preservation
- Local matrix:
  - focused Vitest: `2 files, 18 tests passed`
  - TypeScript: `PASS`
  - Next.js production build: `PASS`, `57/57` static pages
- CI:
  - dev run `33144847798`: `success`
  - master run `33145064607`: `success`
- Provider evidence:
  - Vercel production: `READY`, exact SHA, alias `app.kml.kz`
- Production browser evidence:
  - help dialog parent: `document.body`
  - viewport `1920x911`; dialog `y=47.5`, height `816`, bottom `863.5`
  - create-user backdrop click: dialog remained open
  - `Escape`: dialog closed
- Evidence labels: `GIT-DERIVED`, `PROVIDER-CONFIRMED`, `RUNTIME-DERIVED`
- Result: `PASS_WITH_FOLLOW_UP`
- Follow-up: add a visible explicit close control to the create-user modal; the
  current production form closes by `Escape` but has no visible close button.
- Cleanup: no user created, no mail sent, no production data mutation
- Root review: accepted evidence; UX follow-up remains open

## RUN-20260828-PLUS-FULLFLOW-02

- Timestamp: `2026-08-28T06:30:00Z` (UTC; sanitized runner record)
- Executor: persistent Kamilya Test & Evidence Runner
- Packet SHA: `2ef3afdda938127f17dc7edaff7ef4c23dd1551e`
- Runtime identity: root supplied independent readback for fixed release
  `f71da2a0af9da4c94c82622450cc78daa7ad22b8`; browser health/SHA readback was
  `NOT VERIFIED` because direct public health navigation was blocked by the
  browser client. Root supplied `kz-production`, image `kamilya-api:f71da2a0af9d`,
  zero worker restarts, and Alembic `0134`.
- Scope: exact Plus tenant only; resumed existing indexed document and published
  service-standard course; no regeneration or publication repeat.
- Matrix:
  - Existing group membership: `PASS`; exactly two synthetic members saved;
    visible count `2 участника`; toast `Состав группы сохранён`.
  - Second group: `PASS`; one group created for the other branch with two
    synthetic members; visible count `2 участника`; same success toast.
  - Individual course assignment: `PASS`; one synthetic learner assigned using
    personal link/PIN; visible status `Записан`, access active, notification
    `Не требуется`.
  - Learner journey: `PASS_WITH_FOLLOW_UP`; all 6 lessons reached `6 из 6
    уроков (100%)`; all 6 assessments returned visible `100%` and
    `Тест пройден!`.
  - Group course assignment through learning program: `BLOCKED`; two identical
    visible failures, `Не удалось сохранить` / `404: Learning program not found`.
  - Certificate: `BLOCKED`; learner Certificates page showed no issued
    certificates. Result confirmation remained `Ожидает подтверждения`; the UI
    stated electronic confirmation is unavailable without email and offered
    manual PDF confirmation.
  - Menu audit: `PARTIAL`; safe route traversal began, but the browser session
    timed out before complete coverage. No menu mutation was performed.
- Failure classification: `PRODUCT_DEFECT` for the learning-program save/publish
  path after two materially identical failures; dependent group assignment was
  not retried.
- Evidence labels: `RUNTIME-DERIVED` for visible production UI state;
  `PROVIDER-CONFIRMED` only for root-supplied independent runtime readback;
  `NOT VERIFIED` for browser health/SHA.
- Mutations: two group membership saves, one second group, one individual course
  assignment with personal access, synthetic learner lesson/test completion, and
  resulting progress/test records. No email or notification was sent.
- Cleanup: no duplicate or accidental artifact identified; successful Plus demo
  state preserved. No source fixture remained locally.
- Root review: group-program failure escalated through the required root thread;
  ledger entry is sanitized and append-only.

## RUN-20260828-PLUS-FULLFLOW-02 — fixed-release assignment retest addendum

- Runtime: root independently verified `kz-production`, exact SHA `4f694f02a99eb0215bc9b8f352be886fb10a75f8`, matching API/worker image, zero restarts, and Alembic `0134` (`PROVIDER-CONFIRMED`).
- Program/group assignment: `PASS`; exactly one normal UI assignment attempt succeeded with `Программа назначена`. The published v1 one-course program read back two active synthetic assignments from the Алматы group; no duplicate assignment or published program observed.
- Learner/result readback: `PASS_WITH_GATE`; training journal showed the completed synthetic learner at 100% progress and 100% best score, with status `В процессе` / `Ожидает подтверждения`. The normal confirmation UI requires a signed PDF/JPEG/PNG scan; no artifact was fabricated, uploaded, or signed.
- Menu/help audit: `PASS_PARTIAL`; training journal route loaded, Russian purpose/actions were understandable, and its help dialog opened and closed safely. Broader menu audit remains partial.
- Cleanup: none; demo-ready Plus state preserved. No email, other tenant, real-person data, direct API/DB, code, deployment, or provider action.

## RUN-20260828-PLUS-FULLFLOW-02 — narrow retest addendum (release 8f53120)

- Environment / exact SHA: `kz-production` / `8f53120a32f0fd91013968d45e9464d706645210` (`PROVIDER-CONFIRMED`, root independent runtime readback: public health exact SHA, API and three workers image `kamilya-api:8f53120a32f0`, zero restarts, Alembic `0134`).
- Scope: exact Plus tenant, methodologist UI; no other tenant, direct API/DB, code, deploy, provider, or mail action.
- Program save: `PASS`; reused the first preserved draft, added the existing published service course, saved successfully; visible toast `Траектория сохранена`.
- Program publish: `PASS`; exactly one selected draft became `Опубликована`, v1, 1 курс. Two identical pre-existing drafts were observed from the prior interrupted run; no new duplicate was created.
- Group-targeted program assignment: `FAIL / PRODUCT_DEFECT`; publication succeeded but automatic assignment failed once with visible `Программа опубликована, но назначение не выполнено` / `Internal server error`; current assignments visibly showed none. No unchanged retry performed.
- Group reconciliation: `PASS`; first group remained at 2 synthetic members; second group saved as the other 2 synthetic members, visible counts `2 участника` for both; toast `Состав группы сохранён`; first group readback confirmed its original 2.
- Remaining learner confirmation/certificate and full menu audit: `NOT RUN` in this narrow continuation after the assignment defect; prior learner completion evidence remains unchanged.
- Cleanup: none; successful Plus demo artifacts preserved. No identifiers, links, PINs, emails, or real-person data recorded.

## RUN-20260829-PLUS-READONLY-0bd6ecc — bounded production UI acceptance

- Runtime: root supplied exact SHA `0bd6eccce1fe841595a2842034e1396643ac1f5e`, `kz-production`, matching API/worker image, zero restarts, Alembic `0134`, and READY Vercel deployment (`PROVIDER-CONFIRMED`).
- Groups candidate list: `PASS`; visible Plus candidates excluded the platform admin/methodologist-only account. No group save.
- Platform audit: `BLOCKED`; superadmin handoff opened a credential login unavailable in the signed-in session. No credentials entered.
- Termination modal, assignment email mode, learner final screen, and lesson textarea resize: `NOT VERIFIED`.
- Residue: none; no mutations, uploads, notifications, or cleanup.

## RUN-20260831-METHODOLOGIST-DEV-13E43E4 — full section and key-flow acceptance

- Environment / exact frontend SHA: `development` / `13e43e497ef76b9e6909e32c0aaa9f85c2da7829`.
- Provider and CI evidence: Vercel deployment `READY` with the dev alias attached to the exact SHA; GitHub Actions run `33332934886` completed `success`, including frontend typecheck/lint, backend unit and DB-backed suites, release and tenant-security gates, secret detection, Python quality, PostgreSQL/pgvector RLS, and the document-to-course critical journey.
- Tenant / role: approved synthetic QA tenant / methodologist, plus a bounded admin impersonation for team-modal and audit-log readback. No unrelated tenant was opened or mutated.
- Navigation and help: `PASS`; all 13 primary methodologist routes loaded through the normal sidebar without a visible 5xx. Every contextual-help dialog opened, stayed inside the viewport, matched the final page/menu terminology, and closed explicitly.
- Information architecture: `PASS`; the sidebar is grouped as courses/materials, learning assignment, employees/candidates, and results. Staff and groups are adjacent; candidate testing is accurately included under `СОТРУДНИКИ И КАНДИДАТЫ`.
- Documents: `PASS`; the indexed synthetic source remained ready and selectable.
- Course generation preflight: `PASS`; one selected source produced a coherent thematic-group result and the short-format recommendation `1` module, about `5` lessons, `20` minutes. Duplicate-source protection required an explicit business reason before independent generation.
- Course generation execution: `BLOCKED`; two bounded attempts separated by a substantial pause returned visible `429 Rate limit exceeded`. No new AI job or course was created, and no third identical attempt was made.
- Courses and tests: `PASS_WITH_FOLLOW_UP`; the existing published synthetic course opened and its lesson editor exposed vertical resizing. The test list now exposes lessons as keyboard-accessible pressed-state buttons. Manual review found a repeated answer-length cue in generated single-choice questions; quality remediation remains open.
- Programs, groups, and assignments: `PASS`; the existing one-course program remained published, the synthetic group retained two members, and both group-derived assignments read back as active/enrolled. The email mode excluded no-email learners before a course was selected and explained that they require personal link/PIN access. No new link/PIN was issued in this run.
- Staff: `PASS`; employee edit and termination dialogs exposed the expected fields, preserved training-history copy, required a termination reason, and were closed without mutation.
- Candidate testing: `PASS_READ_ONLY`; page, course selector, campaign controls, and contextual help loaded. No candidate access or notification was created.
- Training log and admin audit: `PASS`; the learning log exposed course/status/date filters and export controls. The admin audit exposed actor, action, object, and period filters and read back employee update/termination, course review/publication, procedure creation, and impersonation events with an attributable account.
- Procedures and retention: `PASS`; a synthetic draft procedure had already been saved and read back; retention remained appropriately read-only for the methodologist.
- Admin team modal: `PASS`; the visible title, close control, optional-password explanation, and Cancel action were present. A backdrop click preserved the dialog; explicit Cancel closed it.
- Learner completion using a newly issued personal link/PIN: `NOT VERIFIED`; issuing a new persistent access credential requires a separate action-time confirmation. Prior production synthetic evidence remains separate and was not reused as dev proof.
- Local focused gates: `18/18` and `19/19` targeted frontend tests passed in the two UX rounds; `pnpm typecheck` passed after each round.
- Mutations / residue: the previously approved synthetic course, program, assignments, procedure, groups, and employees were preserved. No email, external notification, candidate access, learner credential, employee termination, or unrelated tenant mutation occurred. The failed AI submissions created no job.
- Overall: `PASS_WITH_FOLLOW_UP`; dev is ready for UX review, but AI generation remains blocked by the tenant/rate-limit path and a fresh learner credential flow remains gated.

## RUN-20260831-METHODOLOGIST-DEV-13E43E4 — learner-flow addendum

- **Target:** dev only, synthetic tenant `QA Методист 30.08.2026`, synthetic learner `Анна Тестова`; no production tenant, real employee, email or external notification was used.
- **Access:** PASS. One personal link/PIN was created through the normal methodologist UI for the existing program assignment. The link opened the assigned course without an ordinary account. The credential value was not persisted in evidence.
- **Course completion:** PASS. All 9 lessons reached `9 из 9 уроков (100%)`. All 9 lesson quizzes were passed; one quiz required a permitted second attempt after the deliberately naive first-option strategy scored 20%.
- **Quiz flow:** PASS with UX findings. Questions were shown in Russian, answers were selectable, results were saved, and the final quiz displayed explicit next-step guidance. In the measured 35-question first-attempt sample, the first option was the unique longest option in 25 questions; the naive first-option strategy still passed six of seven sampled quizzes at 80–100% before failing the eighth at 20%.
- **Result readback:** PASS. Methodologist training log showed the learner as `Завершён`, progress 100%, best score 100%, completion date present, and a certificate number present.
- **Certificate readback:** PASS. Learner certificate list showed the certificate as valid; the public verification page independently showed the exact synthetic tenant, learner, course, issue date and no expiry.
- **Confirmation consistency:** FAIL. A valid certificate was issued while the methodologist journal simultaneously showed `Ожидает подтверждения`, requested a signed scan, and kept export unavailable until confirmation.
- **Final course navigation:** FAIL. On the last completed lesson the UI still showed `Следующий урок`; one click produced no visible state change.
- **Access revocation:** NOT AVAILABLE. The assignment row exposed only `Перевыпустить доступ`; no `Отозвать`, `Удалить доступ` or equivalent action was present. The synthetic access therefore remains active until its displayed expiry.
- **Session-isolation note:** NOT VERIFIED as a product defect. A final learner transition switched to the existing superadmin identity because methodologist and learner roles shared one browser profile/origin during this test. Re-entering through the same personal link/PIN restored the learner session with all progress intact. A separate-device E2E is required to classify this behavior.
- **Overall:** PARTIALLY READY. Core personal-link learner flow, progress, scoring and certificate issuance work; confirmation semantics, final navigation, revocation and answer-quality bias remain open.

## RUN-20260831-METHODOLOGIST-DEV-13E43E4 — local remediation addendum

- **Scope:** local code and disposable PostgreSQL 18 compatibility database only; no production access or mutation.
- **Course completion:** PASS LOCALLY. The exact assignment bearer can repeat a completed course request idempotently without weakening revoked, cancelled or cross-tenant denial.
- **Terminal action:** PASS LOCALLY. The last completed lesson exposes `Завершить курс`; its click sends the normal completion request instead of reusing next-lesson navigation.
- **Personal access revocation:** PASS LOCALLY. The assignment UI calls the existing tenant-scoped revoke endpoint, requires confirmation, clears one-time credential UI and reads back `Доступ отозван`; the backend audit assertion verifies actor, action and reason.
- **Certificate/evidence semantics:** PASS LOCALLY. RU, KK and EN copy now states that the certificate confirms course completion while documentary confirmation controls the separate evidence package.
- **Automated evidence:** backend focused suites `34/34`, frontend focused suites and typecheck; exact-SHA dev deployment and normal-browser readback are still pending.
- **Residual:** quiz answer-length quality gate remains OPEN and is not part of this remediation package.

## RUN-20260831-PROD-SMOKE-BE35E60 — persistent synthetic production acceptance

- **Environment / runtime:** `kz-production`; public health returned HTTP 200, `production`, and exact application release `be35e60c2b1af1465f770375ba9ff15e8bed4d0b` (`RUNTIME-DERIVED`). The ops-only smoke-provisioner commit `e650b76e16c75e87f81aa747789a9386200b33d7` passed CI run `33397466187` and the no-op-safe KZ release workflow run `33397802150`.
- **Scope:** persistent synthetic smoke tenant, methodologist impersonation, one synthetic document, course, program, group and employee, plus an isolated learner tab. No customer tenant, real employee, invitation email, external notification, direct database edit, certificate fabrication or signed evidence artifact was used.
- **Document ingestion:** `PASS`; TXT upload succeeded through the normal UI, the document persisted, and indexing changed from `Обработка` to `Готов` before generation.
- **Course generation:** `PASS_WITH_UX_DEFECTS`; thematic preflight accepted one coherent source and automatically recommended 1 module, about 5 lessons and 20 minutes. One AI job completed all stages and persisted a Russian draft with 1 module, 5 lessons and 5 tests. The progress UI exposed internal English agent/tool messages, and the completion screen incorrectly said `Структура пуста` despite the persisted structure.
- **Course content:** `PASS`; all five lessons were source-grounded and covered greeting, needs clarification, priority, recording/deadlines, escalation and closure without a material invented rule.
- **Assessment quality:** `FAIL / PRODUCT_DEFECT`; 25 questions were generated, but several answer keys were semantically incomplete or wrong. Examples include a three-element question keyed to a section heading, a prohibition keyed to an affirmative fragment, a priority question keyed to an example sentence rather than the priority, a sensitive-data question omitting the prohibition, and raw Markdown table syntax in an answer. The first 5-question test also made every correct option the longest or a near-verbatim lesson excerpt. A blind longest-option strategy scored 40% on the second test, proving the length cue is not universal but remains severe and exploitable.
- **Methodologist review and publication:** `PASS`; the course was explicitly approved and published through the normal UI. The generated assessment set is not approved for unsupervised customer use despite technical publication success.
- **Staff lifecycle:** `PASS`; one no-email synthetic employee was created with a synthetic department and position, the profile edit dialog saved a surname change, and the structure read back the updated value. No termination was executed.
- **Groups/programs/assignment:** `PASS_WITH_COUNTER_DEFECT`; one group saved exactly one synthetic member. A one-course learning program published and assigned the group; the assignments page independently read back the learner as `Записан`, source `По программе`. The program card nevertheless displayed `0 обучающихся` immediately after the successful assignment.
- **Personal access and learner journey:** `PASS`; one personal link/PIN was created without email and was used only inside an isolated browser tab. The credential values were not persisted. The learner completed 5/5 lessons and all five tests, including one intentional failed attempt followed by a source-keyed retry; final progress and best score both read back as 100%.
- **Completion/certificate:** `PASS_WITH_SEMANTIC_FOLLOW_UP`; the learner received an explicit final `Завершить курс` action and a valid certificate. The training journal read back `Завершён`, 100% progress, 100% score, completion date and certificate, while correctly keeping the separate documentary evidence package pending for a no-email learner. Learner-facing wording still says the result itself awaits confirmation and should be aligned with the clearer journal wording.
- **Contextual help:** `PASS`; sampled dialogs for dashboard, candidate testing, training journal, confirmation and retention stayed fully inside a 1280x720 viewport, used a 512 px panel and `overflow-y: auto`, and closed explicitly.
- **Admin team modal:** `PASS`; the add-admin/methodologist dialog remained open after a backdrop click and closed only through the explicit Cancel action. Nothing was saved or sent.
- **Impersonation navigation:** `FAIL`; several ordinary links from the course/quiz/results surfaces unexpectedly returned the tab to the platform superadmin dashboard. Re-entering the same synthetic tenant restored methodologist access; no tenant boundary was crossed.
- **Residue:** the synthetic tenant, methodologist, indexed source, published course, program, group, employee, assignment, progress and certificate are intentionally preserved as a repeatable production smoke baseline. The local source file remains outside the repository and contains no personal data.
- **Overall:** `PARTIALLY READY`. Release infrastructure, ingestion, persistence, publication, assignment, PIN access, completion, journal and certificate paths pass. Generated assessments remain `NO-GO` without human review and deterministic quality gating.

## RUN-20260831-ASSESSMENT-QUALITY-PROD-03718D8

- **Environment / exact SHA:** `kz-production` / `03718d8d958d475c02c16381ee6dc27e235e4ae3`; CI `33423645134`, protected release `33424142694`, and production smoke `33424391721` completed successfully. Release readback reported one exact migration to Alembic `0141`, the same immutable image across API and three workers, and no rollback.
- **Scope:** one disposable synthetic tenant and synthetic Russian source; no customer tenant, personal data, invitation email, external notification, direct database write, or fabricated confirmation artifact.
- **Generation:** `PASS`; the production pipeline persisted one module, one lesson, one quiz and three independently validated questions, including the bounded focused-evidence recovery path.
- **Assessment contract:** `PASS`; every question exposed four usable plain-text options with exactly one correct answer, all correct answers remained concise and source-supported, and no correct answer was the unique longest option.
- **Review gate:** `PASS`; publication after course review but before quiz review failed closed with `quiz_review_required`. Explicit review of every generated quiz then allowed normal publication.
- **Source compatibility:** `PASS`; learner-safe source references retained public document identity without exposing embedding/query internals, and legacy references remained parseable.
- **Cleanup lifecycle:** `PASS`; the first cleanup exposed the immutable `content_releases` deletion gap. The corrected exact-SHA release kept direct release mutation blocked, used the bounded superadmin purge contract, and removed the disposable tenant through the normal API with DELETE `204` and independent GET `404` readback.
- **Residue:** none. No synthetic tenant, credential, local fixture, email, or external notification remains.
- **Overall:** `READY` for the assessment-quality scope. Deterministic generation checks and mandatory methodologist review are active in production; ongoing real-document sampling remains a product-quality monitoring activity rather than a release blocker.
### 2026-09-06 — AI cancellation repair (LOCAL/DEV PASS)

- TDD red reproduced three missing contracts; implementation adds per-request and
  per-retry cancellation checks, completed-only progress, shared row locking, and
  atomic course/job/link completion.
- Focused API suite: 59 passed, 6 warnings, 7.08s. Operations wrapper: 13 passed.
- Supabase DEV disposable-schema race: six runs, latest cancelled/no-course=4,
  completed/correct-link=2, split-state=0; both outcomes observed, restricted
  runtime role and unchanged
  shared migration head confirmed; temporary schema removed.
- Production residual cleanup was separately owner-authorized. Dependency scan:
  19 course FK paths, only own module cascade nonzero. Exact residual deleted;
  original synthetic course/source and cancelled job history preserved.
- Release/CI/image/provider-backed production reacceptance remain NOT VERIFIED.

## LI-LOCAL-RELEASE-20260906 — Learning Insights local acceptance

- **UTC evidence timestamp:** `2026-09-06T10:26:15Z`.
- **Worktree identity:** `C:\Kamilya New\Kamilya-NEW\.worktrees\learning-insights`, branch `feat/learning-insights-20260906`, HEAD `5c297eb99c64834aac3f5b57628d017a1006f644`; local Windows only.
- **Source manifest:** 19 filtered modified/untracked `apps/**` and `scripts/**` source files; before/after manifest digest unchanged at `4b0ab9e39685bf99eeaa716cd1515310114ede2b79d303494799bb9788d1a76c`. Docs/plans/verification and ledger were excluded as authorized; no application/test source changed.
- **Frontend Vitest:** `pnpm test -- --maxWorkers=2` — **PASS**, 104 files and 535 tests, 86.15s. Non-failing jsdom navigation notice was emitted.
- **Frontend build:** `NEXT_TELEMETRY_DISABLED=1 pnpm exec next build` — **PASS**, 62/62 static pages generated. Two non-fatal React hook dependency warnings were emitted in `LearningInsights.tsx` at lines 125 and 346.
- **Frontend typecheck:** `pnpm typecheck` — **PASS**, exit code 0. Build and typecheck ran sequentially.
- **API focused regression:** canonical `C:\Kamilya New\Kamilya-NEW\.venv\Scripts\python.exe` ran the LI service, evidence, training-log, quiz, and procedure-gate no-DB set — **PASS**, `35 passed, 1 deselected in 2.57s`; the deselected case was the migration-only procedure test.
- **Python quality baseline:** **BLOCKED / HARNESS_FAILURE**. The canonical maintained venv contains no `ruff.exe`, `mypy.exe`, or importable `ruff`/`mypy` modules; `python_quality_baseline.py` failed before analysis with `FileNotFoundError: [WinError 2]` while resolving `ruff`. No install or ambient fallback was used.
- **Release-contract gate:** **FAIL / CONTRACT_DEFECT**. Alembic chain, Celery contract, and migration ownership checks passed; the gate failed the existing error-journal contract with `Errors journal contract error: header date must equal the latest entry date`.
- **Accidental Poetry environment:** the initial forbidden-method correction attempt created `C:\Users\user\AppData\Local\pypoetry\Cache\virtualenvs\api-eEQ5pG_A-py3.12`. No explicit install command was run; the environment lacked `pytest_asyncio`, `ruff`, and `mypy`. It was not deleted pending root review.
- **Scope/cleanup:** no DB, network, provider, browser, production, secrets, customer data, Git index/history, or dependency installation action. No persistent fixtures created; no owned processes remained.
- **Root review:** required; local frontend/API tests pass, but canonical Python quality tooling is unavailable and the release-contract gate has an existing journal-date failure.

## LI-LOCAL-RELEASE-20260906-R1 — quality-gate correction

- **UTC evidence timestamp:** `2026-09-06T10:29:08Z`.
- **Prior-run reference:** correction of `LI-LOCAL-RELEASE-20260906`; prior harness failure is preserved above. Root corrected only the candidate `ERRORS.md` header date and approved the maintained quality environment.
- **Quality environment:** `C:\Kamilya New\Kamilya-NEW\apps\api\.venv`; Python `3.13.15`, Ruff `0.8.6`, mypy `1.20.2`. Its `Scripts` directory was prepended to `PATH` process-locally; no install or Poetry execution was used.
- **Python quality baseline:** `C:\Kamilya New\Kamilya-NEW\.worktrees\learning-insights\scripts\ci\python_quality_baseline.py` — **PASS**, `ruff=1091`, `mypy=2356`.
- **Release-contract gate:** same maintained interpreter and explicit candidate script path — **PASS**. Alembic chain: 153 revisions, head `0155`; Celery contract, migration ownership, and 74-entry secret-safe error-journal structure all passed.
- **Whitespace check:** `git diff --check` — **PASS**, no output.
- **Source manifest:** 19 filtered modified/untracked `apps/**` and `scripts/**` files; digest remained `4b0ab9e39685bf99eeaa716cd1515310114ede2b79d303494799bb9788d1a76c`. Only the authorized ledger and root-owned `ERRORS.md` correction were outside that source manifest.
- **Accidental environment:** `C:\Users\user\AppData\Local\pypoetry\Cache\virtualenvs\api-eEQ5pG_A-py3.12` remains present and was not deleted; root owns cleanup after scope review.
- **Root review:** required; all authorized local LI checks are now green, while DEV/browser/production acceptance remains a separate gate.

## LI-LOCAL-RELEASE-20260906-R1 — cleanup residual addendum

- **UTC evidence timestamp:** `2026-09-06T10:30:02Z`.
- **Related entry:** `LI-LOCAL-RELEASE-20260906-R1`.
- **Residual:** the accidental Poetry virtualenv `C:\Users\user\AppData\Local\pypoetry\Cache\virtualenvs\api-eEQ5pG_A-py3.12` remains present. Root independently verified its creation time and contents as virtualenv bootstrap plus pip `26.0.1`; canonical maintained environments are untouched.
- **Cleanup attempt:** root attempted guarded native PowerShell cleanup; tool policy rejected the command before execution. No deletion occurred, and no alternate deletion mechanism was attempted.
- **Status:** cleanup remains root-owned and pending explicit safe execution; no application or test source is affected.

## V0543-LIVE-ACCEPTANCE-20260914 — one PDF and one full Excel

- **Production identity:** version `0.5.43`, source `a09ebed1d9e856346e41d37ca8c324c91dd5119a`; CI `34810930623`, native build `34810954933`, protected deployment `34812611163` PASS. Runtime readback for API, three workers, native frontend and watchdog PASS; no schema migration.
- **Method:** owner-authorized Chrome UI, synthetic tenant `83552ce6-8058-4561-abe3-cfbda14e030a`, methodologist impersonation. Existing hash-verified full source copies, automatic structure and explicit goal/audience. No new upload/index timing. Observer only read jobs/results; no API generation start. Exactly one run per source.
- **PDF:** job `ce19c590-7d7d-4d98-991b-b36a1e9d684f`, course `892992b0-05c3-445f-9454-0a4aa1158193`, `06:23:35.776681Z` to `06:39:18.135524Z`, 942.36 s. Saved 24/32 planned lessons, 20 quizzes, 52 actual questions. Four lessons without quizzes. All questions/options reviewed independently; daily-versus-annual-limit ambiguity and semantic repetition remain. Source APR rounding rule absent from retained lessons. Technical PASS, complete-content NO_GO.
- **Excel:** job `e6ef81cf-2575-417d-b021-3f93f7c3ce0e`, course `c42c0c48-800a-42f6-8ff2-3f6aa07c70fa`, `06:48:17.724049Z` to `06:52:56.369098Z`, 278.65 s. Saved 6/6 lessons, five quizzes, 14 questions. Independent question/choice correctness PASS within this set. Root confirmed wrong collection and door-count attribution in hardware lesson against original workbook. Technical PASS, full-course content NO_GO.
- **Timing limits:** completion is terminal `updated_at`, because API `completed_at` is null; transition observation approximately two seconds. PDF observer JWT expired, complementary read-only observer captured terminal state; browser job continued through re-login. Separate storage-write duration unavailable.
- **Visual:** production wide lesson editor and formatted preview inspected; source side remains Markdown, not WYSIWYG. PDF lesson and Excel quiz screens inspected, no approval/publication/save/learner-completion performed. Impersonation context loss, long warning headings and duplicate rendered lesson titles recorded.
- **Review discipline:** root rejected overstrict reviewer findings that treated reasonable paraphrase as contradiction or source-citation prefix as release blocker; corrected old-plan/current-omission mapping. Retained confirmed content defects only. Spreadsheet source read-only; no workbook changes.
- **Disposition:** two drafts intentionally retained for owner review; no customer courses changed. No automatic further production code changes. Bounded local-first remediation plan awaits owner approval. Private detailed report and timing logs under ignored `.release-evidence/v0.5.43/`; canonical status is `docs/PRODUCTION_READINESS.md`.

## V0544-LOCAL-CANDIDATE-20260914

- **Scope:** local no-DB acceptance of row-bound lesson facts, conflicting source
  values, numerical-question scope, course-wide objective coverage and no-quota
  assessment generation. The complete control workbook was used only in ignored
  private replay evidence; repository tests use synthetic data.
- **Result:** API unit `1672 passed`; `AI-COURSE-01` local `6 passed`; release
  workflow `45 passed`; quality baseline PASS (`ruff=1065`, `mypy=2333`);
  release-contract gate PASS at Alembic `0159`.
- **Replay:** four lessons generated in `26.671s + 9.651s + 37.670s`;
  deterministic lesson admission 4/4 PASS; final audit retained 10/11 questions
  in `6.033s`, deleting one semantic duplicate without padding.
- **Status:** local candidate GO. CI, DEV and production evidence pending.

## SEMANTIC-BLOCK-ASSESSMENT-LOCAL-20260918

- Timestamp: `2026-09-18T08:15:36Z`.
- Baseline SHA: `46fccaec609fec852d4f384ea3ae8ed58fb6d3f2` plus uncommitted
  current-task changes on `feature/typesafe-course-eval-20260918`.
  This is not immutable-release or production evidence.
- Executors: root; bounded gpt-5.6-terra workers for blocks, outcomes, UI and
  synthetic harness; gpt-5.6-luna for DEV evaluator and independent review.
- Verification: full API unit 1879 PASS / 5 warnings / 75.89s. Final reviewer
  refinement additionally checked by 53 affected tests. Python baseline PASS
  ruff=1061, mypy=2238. Web focused25 before localization; final page21 and
  typecheck PASS after RU/EN/KK labels. No new dependencies or DB schema.
- Real-provider local replays: single paragraph1 lesson/1 question8.443s;
  independent sections3/2 in22.072s; corrected synthetic-table surrogate3/7
  in32.156s; full owner-provided Excel3/5 in60.908s then3/3 in56.293s.
  Customer-derived content is only in ignored private output files, not ledger.
- Final isolated assessment replay on saved Excel lessons: accepted6/9,
  23.790s, no provider failures. No ingestion/lesson/DB/browser replay in that
  measurement. Known absurd alternatives were independently rejected in a
  separate assessment-only rereview. No lesson/question minimum quota.
- Corrected harness failure: synthetic-table metadata had been omitted;
  deterministic regression now proves all9 cells and3 entity owners.
- TypeSafe: DEV-only, synthetic only, report_only REVIEW for simple recall,
  source repetition and distractor distinction; not universal PASS. A subtle
  optional-vs-forbidden wording risk was found manually despite TypeSafe PASS.
- Graphify AST refresh refused smaller graph; no force overwrite. Source/tests,
  not stale graph, establish findings. Canonical local Python environment drift
  restored to lock-pinned packages; no manifest or production environment edit.
- Decision: targeted defect remediated locally; overall release GO NOT GIVEN.
  Full current PDF replay, DB integration, web production build, CI and runtime
  acceptance remain unverified. No Git push/deploy or existing course mutation.
- Detailed Russian report: `docs/testing/2026-09-18-semantic-block-assessment.md`.

## SEMANTIC-BLOCK-CONSTRAINTS-LOCAL-20260918

- Recorded: `2026-09-18T09:02:35Z`; same baseline
  `46fccaec609fec852d4f384ea3ae8ed58fb6d3f2`, uncommitted candidate, no release.
- Root exact modal replay: old general and added LLM constraint checks both
  accepted a bad optional-to-forbidden key. Narrow deterministic guard rejects
  it, retaining a valid privacy question. Boundary unit tests6; constraint tests16.
- Root checks: focused61 PASS; full API unit1902 PASS,5 warnings,77.19s;
  Python baseline PASS Ruff1061/mypy2238; targeted Ruff and diff whitespace PASS.
- Frozen assessment SHA256:
  `45fb69a91f505d259973f6d1fa7800f58f50fa3492425e5effd36e1bfed2dc3b`.
  Two assessment-only real-provider runs:5/9 in45.655s and4/9 in47.895s;
  primary-lesson counts2/0/3 and1/1/2. Repair-validation/fallback failures2 and1.
- Local PDF prep:21 pages, rendering23.108s,OCR5.740s,corpus0.262s;
  250chunks/238facts/25 planned lessons, NOT generated lessons. Visual page3
  confirms reordered definition fragments. Production converter unavailable
  locally; no generation from this invalid substitute, no production inference.
- TypeSafe: no additional calls; earlier false PASS remains documented.
- Workers requested Terra/medium (16 constraint tests,one specification correction)
  and Luna/medium (read-only independent review). Root integrated and verified.
  Runtime effort/token counters and isolated review elapsed time not exposed;
  unknown, not zero. Root rejected the reviewer's source-hash/page conflation:
  original PDF SHA and normalized-document hash are different identifiers.
- Decision NO_GO: exact bug narrowed, repeatability/coverage not accepted.
  No full generation, DB, browser, CI, push or deployment. Private source traces
  retained only in ignored local outputs; no secrets/customer text in this ledger.

## SEMANTIC-REPAIR-COVERAGE-LOCAL-20260918

- Baseline46fccaec609fec852d4f384ea3ae8ed58fb6d3f2; local uncommitted candidate,
  no release/push/DB/customer-course change. Terra implementation, Luna readonly
  content review, root integration/acceptance. Worker token counters unavailable.
- Implemented singleton server-bound repair, same-block citation refinement,
  trusted rejection reasons, fail-closed primary-topic coverage, saved-draft UI,
  ordinal-explanation guard before option shuffle. RED->GREEN contract tests.
- Frozen assessmentSHA60f541fedd9be19b3b35f26ef6f4b2e633261123f60a5d5fb72c96f37a69e49d.
  Excel assessment-only42.843s6/9 topics3/3;39.876s5/6 topics2/3 due invalidJSON
  and fallbackConnectTimeout. Root detects absurd remaining distractor. NO_GO.
- Owner-authorized deployed VM126 converter used, currentrelease46fcca...,green;
  Docling2.106.0,21pages,95.934s,no fallback. Captured artifactSHA
  b4f7ff47546a25a5d765bbd2ded8353c68792e57f3413cfb1fc0d009d576e7ab.
  Two actual conversions: first extraction failed in DEV harness. Temporary
  container and host files cleaned after verifiedlocaltransfer; original retained.
- PDF prep0.220s116chunks321facts29plannedlessons. Image marker/TOC become
  lessons; PDFassessment stopped31/321blocks,lastcheckpoint111.200s. No final
  artifact, no secondPDFassessment/fullcourses; partial trace is not a PASS.
- Synthetic fullseam25.618s3lessons3questions. TypeSafeDEV6livecalls6988inputtokens,
  5.632s,costestimateUSD0.00029350,REVIEW(distractors_distinct); no customer input
  senttoTypeSafe. Repetitionofshortsource alone is not release blocker.
- FullAPIunit1924PASS,5warnings77.05s; separatecapture6PASS; web22PASS/typecheck;
  PythonbaselinePASS(ruff1061/mypy2238). Focusedcounts overlap, not summed.
- No CI/DBworker/browserreleaseevidence. DecisionNO_GO; next bounded work is
  sourceblocknormalization and exact bad-option/providerJSON replay, not fullprod
  regeneration. Details:docs/testing/2026-09-18-semantic-block-assessment.md.

### 2026-09-18 — semantic assessment V1.4 local continuation

- Scope:local only; samebaseline46fccaec609fec852d4f384ea3ae8ed58fb6d3f2.
- Terra/medium source+JSON writers; Luna/medium independent artifact reviewer;
  root integration/manualacceptance. Sourcewriter firstpass notaccepted; root
  corrected overlap navigation, repeated heading and strict TOCcorroboration.
  Reviewer falsepositive onpaletteclaim withdrawn afterroot exactfactreadback.
  Perworker duration/rootreworktime/token counters not separatelyavailable.
- APIunit1946PASS/76.89s/5warnings; capture6PASS/0.40s; PythonbaselinePASS
  Ruff1061/mypy2238. No newfrontenddelta or livebrowserverification.
- Excel assessment67.880s:7/9,3/3topics;56.883s:6/9,3/3topics,oneconstraintschema
  failure+unreachablefallbacks. Both manuallyNOTACCEPTED. Laterenumclarification
  verifiedonlyon4casecalibration/allmatched andnewsynthetic,notnewExcelpair.
- PDFcachedproductionDocling sourceprep0.152s:116chunks267facts26plannedlessons;
  firstfactisbodyrule,notTOC; nofullPDFcourse orassessmentrepeatclaimed.
- Syntheticsmallfullseam24.274s:3lessons2questions,coverage2/3REVIEW.
  TypeSafeDEVonlyPASS:4live1cache5614inputtokens3.911swallUSD0.00019345estimate.
  Rootrejects duplicatewrongactiondespiteTypeSafePASS. No customerTypeSafepayload.
- DecisionNO_GO; noDB/push/release/providerconfiguration. Allagentsclosed.
  Artifacts:outputs/semantic-normalization-20260918; detailedfindings in
  docs/testing/2026-09-18-semantic-block-assessment.md.

### 2026-09-18 — isolated objective-alignment A/B pilot

- Root-owned local-only experiment; runtime AI SHA256 map50files unchanged.
  Freeze manifest723d0a9cb478ad81308ba99a32fa69d6f7429466b979c20c13d795e51bf0840a.
- 4synthetic cases,2repeats,A/B=16attempts; sameenv DeepSeek-v4-flash,temp0.2,
  max8192tokens,30calls/arm,180s/arm. Shared source-plan packs; onlyA computes
  embedding retrieval metric, so totaltime is not a pure speed comparison.
- A8/8artifacts26questions99calls225.594s103462input32779completion tokens;
  B1/8artifacts4questions22calls53.554s17025input8664completion tokens.
  Completion is not quality. Both fail repeatability/coverage or semantics.
- TypeSafe synthetic only9reports4PASS5REVIEW51evaluations50live1cache;
  60154input6054output45.420ssummedwall,adapterestimatedUSD0.00248754.
  FalsepositivePASS onB duplicateaction/optionalexclusion; no runtime dependency.
- Root corrected two DEV validator false positives after RED controls:
  short exactquotes/options and identical general errorcategory≠sameaction.
  19focusedPASS0.64s,RuffPASS;8savedBtraces replayedoffline0APIcalls.
  Frozen engine preserved, originalfailedmetricsunchanged; no fullrerun claimed.
- Holdoutwriter Feynman:Luna/medium,firstpass accepted with later oracle caveat;
  tests Godel:Terra/medium,14testsfirstpass; reviewer Singer:Luna/medium,
  firstpassnotaccepted,1root-directedcorrectionconfirmedtwo semanticdefects.
  Requested models known; independent backend model/token/elapsed counters not
  exposed. Root implementation/integration/QA; rootwall/rework not separatelytimed.
  All agents closed. No CI/DB/browser/release, no fullcustomerfile replay.
- Artifacts:outputs/objective-alignment-20260918. DecisionNO_GO; detailed
  perattempt timings,root findings andlimitations in existing semantic report.

### 2026-09-18 — objective alignment continuation and per-stage thinking

- Local-only: engine/review/runner/source adapter, no runtime/DB/tenant/frontend,
  no Git push/release. AI50file SHA map independently unchanged from firstpilot.
- 3DEVseries x2cases +8freshholdoutattempts =14generationattempts/130calls;
  two captured-artifact reviewjobs add6calls, no course regeneration.
  Recorded usage total185472input/286661completion; not an account billing total.
- Same-prompt disabled vs low:61.232s vs253.004s summed2cases; semantics improve,
  cost/latency rise. Later selective series changes prompts too, not clean A/B.
- Freshholdout manifestae69eb25e33e3c3c1dbd91ab5f90541f5b744590b70b88fa96cb72d8a836bf85:
  8attempts/49calls/651.021s,5completed artifacts,3HTTP failures. Two short cases
  accepted byroot; mixedtable sourcecoverage fails; policy normative wording not
  accepted. Reviewer self-PASS is not rootacceptance. No newTypeSafe run.
- Sourcebuilder excludes narrative sharing table heading; DEV-only adapter
  preserves prose and original sectionroles.3offlinecontrolsPASS, liveNOTVERIFIED.
  Holdout oracleoptional->forbidden error marked; frozenfixtureunchanged.
- Read-only balance HTTP200 availablefalse USD-0.03; furtherDeepSeek calls stopped.
  Original error HTTPcodesunknown. No top-up/plan/credentialmutation authorized.
- Source-only realprep,0modelcalls: Plus48facts3plannedlessons0.515s;
  Lombard267facts26plannedlessons0.129s usinghash-boundproductionDocling capture.
  Neither is a completednewrealcourse. NOTGO forproduction.
- Luna/medium leafworkers: hiddenfixtures/contracts and read-only quality/harness
  review. Root rejected unsupported blocker claims (hashing is not holdout
  disclosure; authorized localrawartifacts are not externalexfiltration) and
  implemented actionable direct-main preflight. Full-testfixtures needed one
  correction for missing testfiles; rootownsfinal acceptance.
- Artifacts: outputs/objective-alignment-{round2-dev,round2-thinking,
  round3-selective,final}-20260918; capturedrechecks and real-source-check folders.
  See existingsemanticreport for exact paths, caveats and everyattempttime.
- Final focused44PASS/0.74s,RuffPASS,diff--checkPASS. Pendingtransfer frozen,
  zeroAPIcalls,manifest2139332ef49ee64b744b911c11e8a6835f0d2e1f6d72233349e554ebff774214.
  Bothleafagentsclosed; no generationleft running. Externalbalance restoration
  and unresolvedqualitygates are required before claiming completion.

### 2026-09-18 — ASUS GLM route and cache observability (DEV only)

- Owner requested local GLM while DeepSeek balance remains unrefilled; later
  explicitly requested longer GLM timeouts. No paid inference, deployment,
  credentials, billing, global env or production mutations in this continuation.
- Live discovery: GLM-5.3-Flash-EXL3 at10.66.66.28:8888, qwen3.8-flash-next
  at.30:8888, nvidia/Qwen3.6-35B-A3B-NVFP4 at.15:8000. Embeddings at.15/.7:8001
  both returned4096dim; .25:8001 and old.28:8000 ConnectError fromworkstation.
- GLM probe JSON200/3.45s. Firstdev-policy run NOT_COMPLETED214.738s:
  plan75.038s,teacher19.247s,assessmentReadTimeout120.453s;3calls,
  1352prompt/2817completion from2returnedresponses only.
- Failed stage only retry, saved plan/teacher,1call: ReadTimeout240.693s;
  no usage returned. Do not interpret oldzero accumulator as zero server work.
  Queue metrics afterward running0/waiting0. Fresh authorized600s one-call
  targetedretry recordedseparately, not overwritten historical evidence.
- Local route no paid key lookup or fallback. New experiment defaults GLM.
  Limits request600s,syntheticarm1800s,lesson1800s,fullcourse7200s;
  no full customer-document generation was run in this continuation.
- Recorder now retains optional cachehit/miss/reasoning usage, requesthash/time,
  returnedmodel; absentmetrics unknown, notzero. Historical136DeepSeekcalls:
  185472prompt/286661completion; cache-hit fraction not recoverable from totals.
- Regression46PASS/0.85s; latertimeoutfocused10PASS/0.34s andrunner6PASS/0.29s;
  RuffPASS,diffcheckPASS. RuntimeAI50filehashmap unchanged fromfirstpilot.
  Source-faithful semantic acceptance and production GO remain separate gates.
- Targeted600s attempt finished170.670s,1GLMcall,1228input/4959completion,
  onequestion/threeon-topicoptions. Root sourcecheck: distinct wrongactions;
  explanation ordinalreferences remain a shuffle defect. No blind audit or
  full-course acceptance claimed. No background generation remains.

### 2026-09-18 — ASUS GLM objective-alignment repeatability closeout

- DEV-only, no DeepSeek calls, no production/runtime/env/DB/tenant mutation.
- Added source-tethered plan/teaching/question recovery, complete-fact citation
  expansion, risky-stem neutralization and duplicate-wrong-action collapse.
- Focused objective-alignment regression61PASS/0.86s; RuffPASS; diffcheckPASS.
- Seven key frozen two-repeat policy series:4COMPLETED,1COMPLETED_WITH_GAPS,
  9NOT_COMPLETED across14attempts. One apparent2/2 series was root-rejected
  because a lesson omitted a required middle clause from its cited fact.
- Latest live frozen candidate before final offline missing-block correction:
  repeat1 NOT_COMPLETED95.919s/11calls; repeat2 COMPLETED96.552s/12calls,
  3lessons/3questions/0unresolved. This is1/2 and fails repeatability.
- Final offline missing-teaching recovery is test-proven only; no claim of live
  completion. Dev-table, holdout, Plus Excel and Lombard PDF were not run after
  policy failure. DecisionNO_GO; no generation remains running.

### 2026-09-18 — axis-owned assessment and TypeSafe replay acceptance

- Local-only isolated worktree; no release, production, DB, tenant, credential,
  billing or provider configuration mutation. New model calls for replay:0.
- Server now owns axis/fact/key/evidence/id; model supplies wording+distractors.
  Malicious model key fields are ignored. Optional rules use deterministic
  binary questions. Weak extra distractors may be deleted without quota padding.
- Captured GLM replay harness fixed to route by axis/question identity; dedicated
  regression protects against queue shift when new logic skips a former repair.
- Final replay `axis-owned-glm-independent-sections-20260918-v4-replay3`:
  3lessons/3questions, coverage3/3, dropped0, removed1, publishabletrue,0.011s.
- Complete cited multi-sentence facts are restored source-exactly; duplicate
  teaching blocks for the same fact are removed. No unsupported advice added.
- TypeSafe/Jev synthetic DEV report improved REJECT->REVIEW. Final questions:
  2PASS/1REVIEW; lessons:1PASS/2REVIEW. Remaining reviews are source repetition
  and low educational value on a one-rule binary question, not key/support
  defects.6calls:2live/4cache,cost estimate$0.00008051,report_only.
- Focused regression186PASS/7.08s,RuffPASS,diff-checkPASS. Real Plus/Lombard
  full-document acceptance and production deployment remain separate NOTVERIFIED gates.

### 2026-09-18 — Plus Excel axis-owned run and checkpoint resume

- Local isolated worktree only; no production/release/DB/tenant mutation and no
  TypeSafe submission of customer material. Voyage embeddings + explicit ASUS
  GLM generation route; DeepSeek calls0.
- Preserved v3-v6 evidence instead of overwriting failures. v3=3lessons/7questions/
  publishable/401.506s; v4=3/4/publishable/291.568s; v5=3/6/not-publishable/
  311.781s; v6=3/0/not-publishable/294.510s.
- Negative evidence isolated two defects: strict all-axes parsing lost a whole
  block after partial output, and the relevance reviewer incorrectly rejected
  distractors before the specialized source-constraint audit.
- v7 resumed from v6 trace and used live GLM only for missing/invalid stages:
  10 captured calls +8 live fallback calls,170.236s,17847 prompt/5284 completion
  tokens,3lessons/8acceptedquestions,requested/authored axes9/9,coverage3/3,
  publishabletrue,fallbacks0.
- Manual acceptance: keys and topic relevance pass. Editorial debt remains:
  near-duplicate lesson phrasing and two over-broad correct answers. Lombard PDF
  final-logic run NOTVERIFIED; production GO not claimed.
- Final focused regression192PASS/2.67s; RuffPASS; diff-checkPASS.

### 2026-09-18 — Plus Excel atomic keys and layered checkpoint acceptance

- Local isolated worktree only; no production/release/DB/tenant mutation,
  DeepSeek calls0, client material not sent to TypeSafe.
- Multi-sentence source facts remain complete in lessons/evidence, while each
  assessment key is now one exact atomic source claim. Model still owns only
  wording+distractors, never truth/key.
- Deterministic lesson cleanup now removes later semantic repeats across exact,
  inflected and catalog-list wording; source fact links remain intact.
- DEV replay accepts ordered immutable trace layers. v8=3lessons/3questions/
  not-publishable/103.805s(two HTTP failures); v9=3/6/not-publishable/108.054s
  (one malformed JSON); v10=3/9/publishable/81.261s; v11=3/9/publishable/
  43.897s,15captured+2live,4364prompt/1486completion tokens.
- v11 acceptance: axes9/9,accepted9,repaired1,dropped0,removed1,coverage3/3,
  3questions/lesson. Root manually reviewed every question: concise exact keys,
  same-task plausible distractors, no unrelated filler. One question safely has
  3 total options after weak-option removal; no quota padding.
- Existing tenant generation checkpoint tables are the intended production
  seam for later fact/block/axis/audit persistence; no schema change in this run.
- Final focused regression198PASS/2.66s; RuffPASS; diff-checkPASS. Plus Excel
  local candidate accepted. Lombard final run and production remain NOTVERIFIED.

### 2026-09-18 — adaptive narrative assessment and real-source acceptance

- Local isolated worktree only; no production/release/DB/tenant/provider config
  mutation, no TypeSafe customer-data submission, DeepSeek calls0.
- Real production-Docling Lombard subset baseline:35facts/4lessons/31assessment
  scopes/8questions/not-publishable/616.516s; DEV 64-call recorder exhausted.
- Added autonomous source preflight for truncated fragments, non-text OCR debris,
  dangling clauses and ambiguous formula glyphs; unsafe facts cannot own lessons
  or assessment truth.
- Narrative density is source-adaptive: up to3 atomic facts per lesson, one
  author batch, no per-fact quota. Explicit `density_omitted` outcomes keep the
  audit complete while topic coverage remains mandatory.
- Added one contract-only retry, isolated review fallback for malformed batch
  JSON, semantic paragraph dedup and server-owned concise source spans.
- Final bounded Lombard v19:17facts/3lessons/6questions, per-lesson3/1/2,
  coverage3/3,audit-complete,failures0,publishabletrue,230.028s. One weak
  question was deleted without regeneration/padding.
- Current-code full Plus v12:3lessons/9questions,axes9/9,accepted9,dropped0,
  coverage3/3,failures0,publishabletrue,225.998s.
- Voyage `voyage-4-lite` first and healthy in both runs; ASUS GLM generation;
  no DeepSeek. Final expanded regression137PASS; RuffPASS; diff-checkPASS.
- Full26-lesson Lombard generation, production release and browser acceptance
  remain NOTVERIFIED and were not performed in this run.

### 2026-09-19 — current-source Excel and live-Docling local closeout

- Local isolated worktree only. Production, tenant data, database, deployment
  and runtime provider configuration were not changed. Customer material was
  not submitted to TypeSafe.
- The current full Plus workbook was independently hashed as
  `00783869f407800c94917053d84430091424de2cf36108d4e972540cf8bc52be`;
  it differs from the earlier v12 fixture and therefore received a fresh run.
- The first current-source run correctly failed closed: 3 lessons, 9 candidate
  questions, 6 accepted, one lesson unassessed, `publishable=false`. The
  constraint reviewer had collapsed categorical product alternatives such as
  classic, loft and Provence into one broad `not minimalism` misconception.
- The correction is deliberately narrow: only an explicit allowlist of
  categorical attributes may ignore that broad model collapse after each wrong
  option has independently passed contradiction, realism and option-level
  review. Scope, duties, permissions, prohibitions and open-ended advice retain
  the strict distinct-error veto. A red regression reproduced the defect; the
  existing scope-veto regression prevented the initial over-broad correction.
- Final current-source Excel result
  `axis-owned-real-plus-20260919-current-source-fixed-final-v2`: 3 lessons,
  8 accepted questions from 9 candidates, 3/3 required topics, no unassessed
  lesson, failures0, validation errors0, provider fallback0, deterministic
  fallback0, Voyage embedding degradation false, `publishable=true`,
  `quality_status=validated_draft`. One weak bed-selection question was deleted
  instead of padding the course. Replay/live-tail path used 18 exact captured
  responses and 2 DeepSeek calls; wall time6.928s, new usage3599 prompt and656
  completion tokens.
- Independent read-only review of all eight questions: GO, P0=0, P1=0, P2=2.
  The P2 items are two related but non-duplicate pairs (`main accent` versus
  `style`); incorrect keys, irrelevant questions, materially implausible
  distractors, ambiguity, OCR artifacts, exact duplicates, unsupported keys and
  cross-lesson leakage were all0. The 3/3/2 question distribution is accepted;
  no ninth question is required.
- Current synthetic table through the live model seam: 3 lessons, 8 questions,
  3/3 topics, no unassessed lesson, failures0,38.589s. TypeSafe/Jev report-only
  evaluation used only that deidentified synthetic artifact: decision REVIEW,
  11 live calls,11277 input tokens, estimated costUSD0.00047363. Signals concern
  expected source repetition and low educational depth in a deliberately tiny
  three-fact-per-product source; source support and exactly-one-correct remained
  high. This is a development signal, not a client-flow gate.
- Full Lombard evidence remains accepted from v39 after a fresh production-
  application Docling conversion: 21 pages,72525 Markdown chars,98.189s,
  conversion fallback false; generation15 lessons/30 questions/13 of13 topics,
  `publishable=true`, no embedding degradation. Independent review found P0=0,
  P1=0 and only six P2 reduced-option/discrimination notes.
- Final verification after the categorical-attribute correction: full API unit
  suite2028PASS/77.59s with5 existing deprecation warnings; focused constraint
  and practical-quality suite33PASS; previously completed web suite619PASS,
  TypeScript typecheckPASS and ESLintPASS. Production remains unchanged.
- Release-tree verification for version0.7.3 after the type-only quality-gate
  correction: full API unit suite2028PASS/77.25s with the same5 deprecation
  warnings; Python quality baselinePASS (`ruff=1061`, `mypy=2238`); affected
  assessment/application selection86PASS; local AI-COURSE-01 selection7PASS;
  release/version/controller contracts45PASS. Frontend619PASS, typecheckPASS,
  ESLintPASS and production buildPASS. No production mutation had occurred at
  this checkpoint.
