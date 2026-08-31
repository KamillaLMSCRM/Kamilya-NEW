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
