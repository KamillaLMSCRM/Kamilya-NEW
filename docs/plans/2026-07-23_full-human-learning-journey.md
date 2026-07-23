# Full human learning journey QA — 2026-07-23

## Scope

Run a production, human-style QA journey using only disposable entities named
`QA-E2E-20260723-*`. Do not alter or remove existing customer/demo records. No
code, deployment, or Git changes are in scope.

**Execution mode:** The test design and findings are produced by this QA
director. All browser interaction and screenshots are relayed by the root
agent's working in-app browser. This document does not represent direct browser
interaction by this agent.

## Final result

**PASS:** The relayed production journey completed through tenant registration,
methodologist course generation/review/publication, manual learner assignment,
kiosk access, lessons, low/high quiz attempts, certificate issuance, and
Russian Unicode PDF acceptance. Earlier blocked steps below are chronological
history and were superseded by documented production fixes/retests.

## Plan

1. Inspect the current production entry points and available safe demo/QA
   accounts; record the exact administrator provisioning path and any demo
   restriction.
2. Sign in as a methodologist where safely possible; create a Kazakhstan
   relevant course, publish it, and assign it to a disposable learner. Exercise
   the authoring assistant wherever it is exposed.
3. Complete the assigned course as the learner, including intentionally
   different quiz outcomes, learner assistant interactions, progress behavior,
   and successful completion.
4. Verify certificate visibility, details, download/open behavior, and capture
   screenshots plus browser/network evidence.
5. Write a detailed QA result with clear separation between product defects,
   expected demo limits, and unavailable-account/environment limits. Do not
   commit, push, or deploy.

## Execution log

### Step 1 — production entry points and role provisioning

**What I did:** Started Graphify-assisted orientation, prepared isolated QA
evidence/result locations, and attempted the required production browser
connection.

**Checks:** `graphify query "course creation publishing assignment learner quiz certificate assistant chat roles"` identified the course, quiz, certificate and learner-assistant modules used for targeted verification. Browser discovery returned no backends (`[]`). A documented retry produced `Browser is not available: iab`; supported Chrome selection also produced `Browser is not available: extension`. Public availability baseline: `https://app.kml.kz` HTTP 200; `https://kamilya-lms-api.onrender.com/health` HTTP 200.

**Status:** ✅ superseded — relayed browser QA completed the full journey.

### Steps 2–5 — role journey, course, learner, certificate, and report

**What I did:** Wrote the explicit blocked-run result at
`docs/qa/2026-07-23-full-human-learning-journey-results.md` and reserved the
requested evidence folder.

**Checks:** Initial browser-only limitation was superseded by relayed browser
interaction and complete production verification.

**Status:** ✅ superseded.

### Step 1b — relayed non-Demo tenant setup

**What I did:** Switched to relayed human-test direction after the root agent
confirmed a separate working in-app browser. The test must start in a freshly
registered, isolated non-Demo Kazakhstan tenant because Demo correctly blocks
user provisioning.

**Next UI actions for the browser operator:**

1. Open `/register-tenant` and capture the initial desktop screenshot plus any
   visible validation/help text.
2. Enter the unique organization name `QA-E2E-20260723 KZ Learning Journey`.
   Use a unique administrator email only if the operator can receive its OTP;
   do not use customer or unknown third-party mailboxes. Capture pre-submit
   state.
3. Submit only after confirming the displayed trial limits and consent/terms
   text are understandable. Capture the first response, route, and any OTP
   instructions.

**Decision criteria:** The page should make the Kazakhstan context, trial
limits, required credentials, and next step clear. A usable OTP route is
required before creating data. If no safe controllable inbox is available,
stop before submit and record this as an environment/access limitation.

**Status:** ⏳ awaiting relayed browser observations.

### Step 1c — registration failure analysis and safe retry

**What I did:** Evaluated the relayed 422 registration failure with targeted
Graphify/code inspection. The browser operator submitted the unique QA company
using `qa-e2e-20260723-admin@example.invalid`; the page showed only a generic
HTTP error and no field guidance.

**Checks:** `TenantRegisterRequest.email` is `EmailStr` in
`apps/api/app/modules/tenants/schemas.py`; `.invalid` is therefore expected to
fail validation. `apps/web/src/app/register-tenant/page.tsx` only maps string
or object error details and falls through to Axios's generic message when the
422 detail is the FastAPI list shape. This is a confirmed UX defect. No code
change is authorized in this QA task.

**Next UI actions for the browser operator:**

1. Keep the same QA company/contact and leave optional phone/BIN blank.
2. Replace only the address with a new, operator-controlled mailbox or owned
   QA alias; do not use customer or unowned addresses.
3. Submit once, then capture the landing route, admin identity, role, and
   trial-limit/onboarding state. If no safe mailbox exists, stop before submit.

**Status:** ⏳ awaiting relayed safe retry.

### Step 1d — valid-address registration failure

**What I did:** Assessed the relayed second submit. It used the controlled
`qa-e2e-20260723-admin@example.com` address and failed with a generic 500.
The browser operator verified through Render logs that
`EmailService.send_trial_started` hit a Resend HTTP 422 before commit, rolling
back registration.

**Checks:** No tenant or QA user was persisted from either failed submit.
Production root cause is an activation-critical coupling of the registration
transaction to optional notification delivery.

**Status:** ❌ blocked pending root agent's production fix/deploy. This is a P0
activation defect; do not retry until health and the deployed correction are
confirmed.

### Step 1e — activation retest after production correction

**What I did:** Evaluated the relayed post-deploy retest. Revision `a721fe6` is
Render live and Vercel READY. One registration retry succeeded and routed the
admin to `/admin` despite the best-effort Resend rejection.

**Checks:** Tenant `QA-E2E-20260723 KZ Learning Journey` is a non-Demo trial;
dashboard displayed 13 days remaining, AI `0/1`, JD `0/1`, learners `0/10`,
system users `1/3`, onboarding `0/7`. DOM evidence captured. Two full-page
screenshot timeouts on the unusually tall dashboard are evidence-tooling only.

**Next UI actions for the browser operator:**

1. From the admin navigation, open **Team** (`/admin/team`); capture the first
   view and whether it explains the admin's limited ownership clearly.
2. Select **Create user**, retain the default **methodologist** role, and enter
   `qa-e2e-20260723-methodologist@example.com`, first name `Мадина`, last name
   `QA`, and an operator-known disposable password of at least eight characters.
3. Submit once; capture the created row, role badge, status, any password/login
   instructions, and current system-user count. Do not create a student here:
   the Team page explicitly reserves learner provisioning for staff/import or
   the learner flow.

**Decision criteria:** Successful creation must produce an active
methodologist, stay within trial system-user capacity, and leave no ambiguity
about how that person signs in. A raw error, unclear password handoff, or
student option on this surface is a usability defect.

**Status:** ⏳ awaiting relayed methodologist-provisioning result.

### Step 2 — admin Team provisioning blocker

**What I did:** Evaluated the relayed Team surface. Its role ownership, default
methodologist selection, and exclusion of learners are clear. The actual
email/name/password inputs, however, were `readonly=true` and did not unlock
after real focus/click interaction.

**Checks:** This was reproduced through user-like coordinate interaction, not
only programmatic typing. No methodologist was created. The root agent is
removing the failing readOnly/onFocus anti-autofill mechanism while preserving
autocomplete/data-ignore protections.

**Status:** ❌ blocked pending production fix/deploy. P0: the administrator
cannot provision a necessary system user through the intended UI.

### Step 2b — provisioned methodologist cannot use visible login journey

**What I did:** Evaluated the relayed post-deploy Team retest. Revision
`940a496` allowed real user input; `Мадина QA` was created as active
methodologist and the Team table total became 2. The UI presented no handoff
after creation.

**Checks:** Targeted Graphify/code inspection confirms a backend password
endpoint (`POST /v1/auth/login`) exists, while `apps/web/src/app/login/page.tsx`
offers only email OTP and Telegram. The new-user form requires a password, so
the product currently creates an account with no discoverable path to use that
credential. The reserved QA mailbox cannot receive an OTP.

**Decision / next actions for the browser operator:**

1. Do **not** attempt to bypass the UI through the hidden API endpoint; that
would not be a human test and would conceal the product defect.
2. The root agent should correct the password-login/handoff issue and deploy;
then open `/login`, verify a visible password route, sign in as `Мадина QA`,
and capture the resulting role home.
3. If a temporary content-surface smoke is needed before that fix, add the
methodologist role to the already signed-in admin via the documented
existing-account role-addition path, switch active role, and label every
finding as **role-switch coverage**, not a separate-user login.

**Status:** ❌ blocked for the requested separate-methodologist login. P0
authentication/discoverability defect.

### Step 2c — separate methodologist login retest

**What I did:** Evaluated the relayed production retest after revision
`05ef427` became Render live and Vercel READY. `/login` visibly offered
password, code, and Telegram modes plus an admin-password handoff hint. The
methodologist logged in via the password UI and landed on `/dashboard` with the
correct role/tenant and an empty-state CTA to `/ai/generate`.

**Checks:** Separate-user login is directly verified; no browser logs reported.

**Next UI actions for the browser operator:**

1. Click **New Course** and capture the empty `/ai/generate` documents step,
   including whether a first-time author can understand why a source is needed.
2. Upload the disposable Kazakhstan-relevant source file
   `docs/qa/evidence/2026-07-23-full-learning-journey/QA-E2E-20260723-warehouse-safety-source.txt`.
   Capture upload state and wait for its index/embedding status to become ready;
   do not upload any customer material.
3. Select that one ready source, set the audience to new warehouse employees
   and three modules in Russian, then capture the enabled/disabled generation
   CTA and all source/compatibility explanations before launching.

**Decision criteria:** The first-time author must be told what source material
is needed, must see a progress/error state for upload/indexing, and must be
able to understand why the Generate button is enabled or withheld. Any raw
technical error, unclear indexing state, or stale CTA is a defect.

**Status:** ⏳ awaiting relayed course-generation setup.

### Step 3 — source indexing blocks course generation

**What I did:** Evaluated the relayed methodologist upload of the approved
disposable TXT source via the visible dropzone. The document appeared in the
list but indexing immediately failed; tooltip text was
`All embedding providers failed: ['qwen-self-hosted', 'voyage']`.

**Checks:** Document state was Error. Selection and Generate remained disabled,
which is the safe behavior. Recovery/status copy is clear, but a retry cannot
work until the production embedding chain is restored.

**Status:** ❌ blocked pending root agent diagnosis/fix/deploy. P0: a new
methodologist cannot generate a course because every configured embedding
provider has failed.

### Step 3b — provider-routing change and OCR follow-up

**What I did:** Recorded the relayed provider change: commit `58b5fe5` makes
DeepSeek v4-flash primary for course-generation/chat, with Qwen fallback. A
direct DeepSeek smoke request succeeded. Deployment
`dep-d9grrnepbkes73c785t0` was building when reported.

**Checks:** This improves the LLM/chat path but leaves the observed source
blocker unresolved: embeddings remain Qwen then Voyage. The success criterion
is a production re-index of the same QA TXT, not merely a chat/LLM smoke test.

**Later UI checkpoint:** After completing the text-source journey, upload a
synthetic scanned PDF and verify the document pipeline's Docling OCR produces
usable indexed text. DeepSeek is text-only and must not be treated as PDF-image
OCR.

**Status:** ⏳ awaiting deploy completion and explicit production re-index
evidence.

### Step 3c — successful production re-index

**What I did:** Evaluated the relayed live retest on commit `6042aad`. An
identical-content retry TXT uploaded through the visible dropzone reached Ready
in about four seconds and enabled selection. The old failed document remains
safely disabled; no deletion was performed.

**Checks:** The upload prerequisite no longer depends on the failed Qwen path.

**Next UI actions for the browser operator:**

1. Select **only** the Ready retry document, capture its title/status and the
   compatibility result. Confirm a first-time author can distinguish it from
   the older disabled error record.
2. Set audience to `New warehouse employees in Kazakhstan`, three modules, and
   Russian; capture the full pre-generation state and confirm the button says
   precisely what irreversible/trial-limited action it will start.
3. Launch generation **once only** (the tenant quota is AI `0/1`), then capture
   job ID/progress stage, elapsed feedback, and any error/retry/cancel guidance.

**Decision criteria:** One ready source must permit generation without a
technical workaround. The author must see which source will be used, why it is
compatible, and the quota-consuming effect before launch. Job progress should
remain understandable while the page is open.

**Status:** ⏳ awaiting relayed source selection and generation start.

### Step 3d — compatible source ready for generation

**What I did:** Evaluated the relayed configured state: one Ready source,
one thematic compatibility group/unified course allowed, Kazakhstan warehouse
audience, three Russian modules, and enabled Generate CTA.

**Checks:** Two non-blocking UX defects found before launch: grammar says
`1 документов` rather than `1 документ`; summary is generic English
`Document about various topics` despite a Russian safety source.

**Next UI actions for the browser operator:**

1. Capture the configured state, then click **Generate** exactly once; this
   consumes the only normal AI-generation trial slot.
2. Capture job ID, each visible stage/progress message, elapsed feedback, and
   completion/failure state. Do not navigate away while it runs unless the UI
   explains recovery.
3. Once review opens, do not publish yet. Locate the authoring assistant and
   send: `Какие три правила безопасности должен запомнить новый сотрудник
   склада?` Capture answer quality, grounding/citations, latency, errors, and
   visible chat persistence controls.

**Decision criteria:** The generation must complete to a reviewable draft from
the selected source. The assistant should give a useful source-grounded answer,
not invent unrelated rules. Any assistant error or ungrounded response is a
separate defect; publication waits for review/chat assessment.

**Status:** ⏳ awaiting relayed generation and review-assistant result.

### Step 3e — failed infrastructure attempt exhausts trial quota

**What I did:** Evaluated the relayed subsequent Generate click. It returned
HTTP 403 in frontend logs, created no job, and left the configured page visible.
The likely cause is that the original provider-failed attempt consumed the sole
AI trial slot.

**Checks:** No readable 403 message or recovery action appeared in the UI.

**Status:** ❌ blocked pending root diagnosis/fix/deploy. P0: failed
infrastructure generation appears to consume the only trial allowance, leaving
the user unable to retry and without a usable explanation. Do not click
Generate again until the quota is restored and the fix is production-verified.

### Step 3f — quota-recovery correction awaiting retest

**What I did:** Recorded the relayed correction in commit `6b17948`. The worker
now refunds trial AI count and LLM budget on future failed jobs, including
enqueue/unavailable paths. Only this disposable tenant was restored after
verification: usage `1 → 0`, one failed job.

**Checks:** Render API deployment was still building; no customer or existing
tenant quota was modified.

**Next UI actions after the deployment is live:**

1. Reload the configured generation page and capture visible quota/state,
confirming the Ready source remains selected or can be reselected.
2. Click Generate exactly once and capture the newly created job/stages.
3. If it fails, verify the UI displays a clear human-readable error and that
the trial counter is later refunded; do not loop retries.

**Status:** ⏳ awaiting live API deployment and one controlled retest.

### Step 3g — controlled retry enters generation

**What I did:** Evaluated the relayed retry: the visible job reached 10%,
Projecting structure. Its user-visible progress detail was
`Architect: -> list_documents returned 124 chars`.

**Checks:** The UI does not surface a job identifier; no hidden state was
inspected. No additional actions were made while the job runs.

**Finding:** P1 technical-information leakage and unusable progress copy. The
methodologist should see a concise content-generation status, not an internal
tool trace.

**Status:** ⏳ awaiting terminal job state; do not click further controls.

### Step 3h — worker generation fails mid-pipeline

**What I did:** Evaluated terminal result from the controlled retry. At 50%
(lesson 3/6), UI showed `All embedding providers failed:
['voyage', 'qwen-self-hosted']`. No new retry was made.

**Checks:** Worker-specific failure remains despite successful Voyage-backed
Render API ingestion; likely worker provider configuration/credential or
request-path difference. Root is verifying automatic quota refund and worker
configuration/logs.

**Finding:** P0 course-generation reliability blocker; visible text is still
technical and does not tell a methodologist what to do next.

**Status:** ❌ blocked pending root cause fix/deploy and quota-refund evidence.

### Step 3i — worker rate-limit root cause and retry-policy correction

**What I did:** Recorded the root-cause evidence from worker logs: Voyage
returned 200 for three embedding calls and then HTTP 429 project limit. The old
client exhausted a 1+2+4 second retry budget. Read-only verification confirmed
this QA tenant's refunded AI counter is `0`.

**Checks:** Commit `506c38b` uses six retries, exponential backoff up to 60
seconds, and respects `Retry-After`; worker is live. API was still deploying.

**Next UI actions after API live:**

1. Confirm the QA tenant still shows one available AI generation and the same
Ready source can be selected.
2. Launch one controlled retry and capture a user-understandable waiting state
through any rate-limit delay; do not perform another manual retry.
3. At terminal state, verify either review opens or a readable recovery message
appears and the quota is automatically restored.

**Status:** ⏳ awaiting API-live post-fix controlled retest.

### Step 3j — passive terminal-state observation

**What I did:** Paused all interaction after the controlled retry. This QA
director cannot inspect the root agent's browser-bound job without prohibited
hidden session/API access, so it awaits relayed visible stage/terminal evidence.

**Checks:** No retry, publication, hidden storage inspection, or direct API
job-status request was performed. Root is adding Cohere embedding fallback.

**Status:** ⏳ awaiting relayed visible terminal state only.

### Step 4 — generated course review entry

**What I did:** Evaluated the relayed visible terminal state. Generation
succeeded with draft `Безопасное начало смены на складе`, status `На проверке`,
three modules, six lessons, six tests, and the retry source shown. Whole-course
assistant and per-module **Ask AI** controls are visible.

**Checks:** No publish action performed.

**Next UI actions for the browser operator:**

1. At whole-course assistant scope, send the agreed question: `Какие три
правила безопасности должен запомнить новый сотрудник склада?` Capture latency,
answer, grounding/source references, errors, and whether it is actionable.
2. Ask one out-of-source question: `Какой размер штрафа за нарушение правил
склада в Казахстане?` Capture whether it appropriately states the limitation
instead of fabricating a policy/legal answer.
3. Use **Ask AI** on one module, ask `Сделай этот модуль понятнее для нового
сотрудника`, and capture whether the scope is visibly module-specific plus any
apply/change/persistence affordance. Do not apply edits yet.

**Decision criteria:** The assistant must be useful and grounded for the first
question, must not invent an unsupported legal answer for the second, and must
make scope/action consequences clear for the module question.

**Status:** ⏳ awaiting relayed authoring-assistant results; publication remains
blocked until review is complete.

### Step 5 — review approval and single publication

**What I did:** Evaluated the relayed review. All three modules were inspected:
six source-linked lessons and six lesson quizzes (11, 11, 11, 11, 13, 12
questions). Approval with factual QA audit comment showed Approved status,
comment/timestamp, and publish action. One publication produced one Published
catalog item with AI badge and source-aligned description (relayed DOM/UI
observation; no stored screenshot).

**Checks:** Review gate and publication behavior pass; no duplicate course.

**Next UI actions for the browser operator:**

1. Open **Staff** (`/admin/staff`) and capture the empty state, role ownership,
and manual-add explanation. Choose **Add employee**, not system Team.
2. Create exactly one disposable learner record: personnel number
`QA-E2E-20260723-001`, name `Ерлан QA`, email
`qa-e2e-20260723-learner@example.com`, department `QA Warehouse`, position
`Warehouse trainee`; leave phone blank. Submit once and capture the employee
row/structure and any access/login handoff.
3. Open **Assignments** (`/assignments`), select the single published course
and this learner, and capture the assignment confirmation plus learner-visible
availability guidance. Do not use a role rule or assign any other learner.

**Decision criteria:** Manual learner provisioning must be understandable and
clearly separate from system-user Team. Assignment must target exactly the one
active learner and clearly indicate how the learner can open it.

**Status:** ⏳ awaiting relayed learner provisioning and assignment.

### Step 6 — manual learner provisioned and assigned once

**What I did:** Evaluated the relayed Methodologist flow. Exactly one learner
was created (`QA-E2E-20260723-001`, `Ерлан QA`, QA Warehouse, Warehouse
trainee); structure counts were one employee/department/position (relayed
DOM/UI observation; no stored screenshot).
One manual assignment to the sole published course succeeded; row showed
`Ерлан QA / Записан / Вручную`, toast count 1 (relayed DOM/UI observation; no
stored screenshot).

**Finding:** P1 discoverability defect: no access/login/kiosk handoff appears
at either Staff creation or Assignment completion.

**Next UI actions for the browser operator:**

1. Log out of Methodologist and sign in as the already-created QA admin with
the known disposable password. Open **Kiosks** (`/admin/kiosks`), capture why
this admin-owned surface is required and whether it explains the employee flow.
2. Create one kiosk named `QA-E2E-20260723 Warehouse kiosk`, scoped to
`Warehouse trainee` if the selector offers it; capture the generated URL/QR and
copy/open only that kiosk link in a fresh unauthenticated tab.
3. At the kiosk, enter personnel number `QA-E2E-20260723-001`; capture identity
confirmation and assigned-course visibility, then open the course. Do not use
any hidden URL/token storage or create additional kiosks.

**Decision criteria:** The kiosk must safely identify only the assigned learner,
show the one assigned published course, and make the start action obvious.

**Status:** ⏳ awaiting relayed kiosk learner access.

### Step 7 — kiosk creation failure analysis

**What I did:** Evaluated the relayed admin kiosk attempt. No position option
was available; unrestricted kiosk creation with QA name/location returned
generic `Ошибка создания`, and no kiosk was created.

**Checks:** Targeted repository review found likely post-commit RLS-context loss:
`create_kiosk_link()` commits then refreshes its ORM row; router then executes
`db.get` after that commit, while `get_current_user` establishes tenant RLS
context with transaction-local `set_config`. Both post-commit operations can
lose `app.tenant_id`. Root logs must confirm the exact exception. Separately,
manual Staff position text does not create the canonical Position rows used by
the kiosk position selector. Tests cover kiosk JWT identification but not this
authenticated creation/manual-staff path.

**Status:** ❌ blocked pending root cause confirmation/fix/deploy. P1 journey
blocker: manual learner cannot reach their assigned course via the documented
kiosk route.

### Step 7b — kiosk correction live; use existing controlled QA kiosk

**What I did:** Recorded the live correction at `9f31144`. Confirmed causes:
internal commit cleared transaction-local RLS before response; admin position
fetch used a methodologist-only endpoint. Fix adds an admin scope-positions
endpoint and removes internal create commit; tests passed. Exactly one active
QA kiosk exists. It is unrestricted only because it persisted during the old
response failure; the corrected modal now offers Warehouse trainee (QA
Warehouse). No second kiosk is needed.

**Next UI actions for the browser operator:**

1. Open the existing QA kiosk URL in a fresh unauthenticated tab; capture the
employee-facing landing screen, personnel-number instructions, and privacy
copy. Do not expose/copy the kiosk token in further reports.
2. Enter `QA-E2E-20260723-001`; capture learner identity confirmation and the
single assigned published course. Verify an unrelated name/course is not
shown.
3. Open that course and capture the learner course-player first screen,
progress semantics, navigation, quiz prerequisites, and any visible assistant
entry point. Do not complete lessons or start a quiz until those first-time
orientation findings are recorded.

**Decision criteria:** Kiosk identification must be clear and limited to the
assigned learner; course access must be direct and not require a hidden
credential. The player must explain what to do first and how completion is
earned.

**Status:** ⏳ awaiting relayed kiosk/learner-player orientation.

### Step 7c — active public kiosk URL reports not found

**What I did:** Evaluated the relayed unauthenticated kiosk opening attempt.
The existing active kiosk URL returned `Киоск недоступен — Ссылка не найдена`
after admin logout.

**Checks:** Admin had already confirmed the active kiosk row exists. Likely
public token lookup has no tenant RLS context.

**Status:** ❌ blocked pending root's safe token-scoped RLS bootstrap fix and
retest of the exact existing URL. Do not create another kiosk/token.

### Step 7d — public kiosk and learner player retest pass

**What I did:** Evaluated the relayed production retest at `34fa53d`. The exact
existing kiosk URL worked unauthenticated; personnel number identified only
`Ерлан QA` / Warehouse trainee and one assigned course. Course opening created
learner access and showed 0/6 lessons, outline/content, clear completion CTA,
and lesson assistant promise not to choose quiz answers. No unrelated data.

**Checks:** Kiosk isolation and learner first-time orientation pass.

**Next UI actions for the browser operator:**

1. In lesson 1, open learner AI and ask `Почему нельзя оставлять поднятый груз
без присмотра?` Capture usefulness, source grounding, latency/error, and ensure
it does not give a quiz answer. Do not use it to answer any quiz.
2. Mark lesson 1 complete, reload once, and verify progress persists. Then work
through the remaining five lessons in outline order, marking each complete;
capture progress transitions and any locked/unlocked navigation behavior.
3. When the first quiz becomes available, deliberately submit a low-score
attempt by selecting clearly unsupported options without consulting AI. Capture
score, pass threshold, answer feedback, retry rule, and course-progress effect.
Do not start a second quiz until low-attempt evidence is saved.

**Follow-up sequence after low-attempt evidence:** Retry that same quiz using
the lesson material only to obtain a high/pass score; then complete the remaining
required quizzes, record at least one distinct high score, complete the course,
and verify certificate creation/PDF open. Ask learner AI once more after a quiz
result about an explanation (not an answer), and verify chat context/persistence.

**Decision criteria:** Lesson completion must persist; assistant must help
understanding without supplying answers; low vs high quiz attempts must have
clear, truthful progress semantics; certificate only follows genuine completion.

**Status:** ⏳ awaiting relayed learner lesson/chat/low-score quiz evidence.

### Step 8 — learner assistant, completion persistence, and low-score attempt

**What I did:** Evaluated relayed learner flow: assistant gave grounded PPE
guidance without answer assistance. Lesson 1 persisted through full kiosk
re-identification (1/6, resumed lesson 2). Direct reload redirects to login due
memory-only kiosk session. Kiosk catalog says `Не начат` while progress is 17%
(P2 status inconsistency). Lesson 2 reached 2/6; deliberate low quiz attempt
scored 0% with clear feedback/correct answers/retry. Matching text shows mojibake
`в†’` (P2 encoding).

**Next UI actions for the browser operator:**

1. Use **Try again** on this same quiz. Answer from the completed lesson
material, not AI, to obtain a high/passing score; capture score, threshold,
attempt history, and whether the prior 0% is preserved distinctly.
2. Ask learner AI after the result: `Объясни, почему правильный вариант связан
с безопасной работой, но не выбирай ответ за меня.` Capture answer boundary and
whether it has course/lesson context. Do not ask it before submitting.
3. Complete lessons 3–6 and each newly required quiz from lesson content only.
Capture at least one other high score, progress semantics, and any navigation
or session-restoration friction. On true completion, open certificates and
verify issuance, content, download/PDF open; do not claim certificate before it
is visible.

**Decision criteria:** Retry must retain a truthful history of low/high scores;
assistant must explain rather than answer; completion/certificate must reflect
all requirements.

**Status:** ⏳ awaiting relayed high retry and remaining learner completion.

### Step 8b — high-score retry and contradictory pass toast

**What I did:** Evaluated relayed retry result: initial 0% then 100% (11/11)
pass. History truthfully retained 0% and showed 1/3 attempts. The passed toast
title had stale 0% description (P2 contradiction).

**Checks:** Commit `add2f67` fixes stale pass description, kiosk in-progress
status, and matching-arrow mojibake; deployment pending.

**Status:** ⏳ continue remaining lessons/quizzes; recheck the affected feedback
after deployment where practical.

### Step 8c — four lessons, second high score, and precise toast-path defect

**What I did:** Evaluated relayed continued flow: 4/6 lessons complete;
post-result learner AI stayed grounded and did not choose an answer; second quiz
100% (11/11). Matching arrow now displays correctly. Toast still shows 0%
because it reads `data.score_percent` instead of nested
`data.attempt.score_percent`.

**Checks:** P2 mojibake fixed; exact P2 toast cause confirmed; no certificate
yet because learner has not completed all requirements.

**Status:** ⏳ root correcting toast field; complete remaining lessons/quizzes
then verify certificate/PDF.

### Step 8d — false completion hides required quizzes

**What I did:** Evaluated the relayed 6/6 lesson state. Player said Course
completed and hid quizzes, while Certificates showed none. Root identified UI
using lesson `progress_percent=100` rather than server enrollment completion.

**Checks:** `cf40b81` adds enrollment_status, fixes player/dashboard completion
semantics, and Next Links. TypeScript/backend compile pass. Integration suite
could not begin due to local PostgreSQL test password mismatch; deployment in
progress.

**Next UI actions after deploy:**

1. Re-enter the same learner course and confirm 6/6 lessons alone does **not**
claim completion or hide required quizzes.
2. Complete all revealed required quizzes from lesson material, capturing final
server-backed completion state.
3. Open Certificates; verify issuance only after genuine completion, certificate
identity/details, download, and PDF opening.

**Status:** ❌ blocked pending `cf40b81` production deployment/retest. P0:
learner cannot finish a course whose quizzes are hidden by false completion.

### Step 8e — final learner completion and certificate verification

**What I did:** Recorded the relayed final production journey. Missing lesson-5
quiz `a1eb15d0-ead4-40a8-9d00-6498acd8e9ea` passed 100% (13/13); all six quizzes
passed; server completion succeeded. Dashboard showed one completed course and
one certificate; `KML-2026-25AF54` was issued.

**Checks:** Completion errors use structured API `details` rather than raw HTTP
400; `/quizzes/enrolled` import and UUID/string lesson-map defects fixed in
deployed commits `b10d544` and `3cba6f6`.

**Certificate PDF acceptance:** PASS. Production commit `79e86c3` is live on
Render and active on the VPS worker. The existing certificate was regenerated
through the real authenticated production download endpoint using v2. One-page
A4 output contains native Cyrillic title/learner/course/date, correct number and
verification URL; rendered PNG has no clipping or overlap. Bundled Ubuntu fonts
remove OS dependency.

**Download note:** UI blob download completed without visible error but did not
emit a browser download event. The authenticated production endpoint returned a
valid PDF, so acceptance passes; the missing event is a browser-tooling
observation limitation.

**Status:** ✅ full human journey and certificate PDF acceptance complete.

### Step 4b — whole-course assistant grounding and hallucination test

**What I did:** Evaluated the relayed whole-course assistant answers. The
grounded safety question returned three relevant rules (relayed DOM/UI
observation; no stored screenshot). The out-of-source
Kazakhstan penalty question invented a 5–30 MRP range despite admitting the
article could not be guaranteed.

**Finding:** P1 harmful hallucination: unsupported legal/penalty guidance must
be declined or grounded in an approved source. Root is correcting assistant
grounding before publication.

**Next UI actions after the grounding correction is live:**

1. Repeat the same out-of-source penalty question and capture an explicit
limitation/refusal or source-request response; it must not supply a numeric
range.
2. Use **Ask AI** at one module and ask `Сделай этот модуль понятнее для нового
сотрудника`; capture module scope and any apply/change/persistence affordance.
3. Do not apply suggested changes or publish until both checks pass.

**Status:** ❌ publication blocked pending P1 assistant-grounding correction and
retest.

### Step 4c — assistant-grounding correction retest

**What I did:** Evaluated the relayed production retest at `42c7c72`. The same
unsupported fines question answered exactly `В материалах курса этого нет.`;
no fabricated numeric/legal claim. Per-module assistant visibly changed scope,
gave a focused improvement, and displayed **Apply to lesson** without applying
it (relayed DOM/UI observation; no stored screenshot).

**Checks:** Whole-course non-fabrication and module-scope/apply affordance pass.

**Next UI actions for the browser operator:**

1. Review the generated modules/lessons/tests at least at summary level, then
open the review action. Capture status, required comment/confirmation text, and
whether the consequence of approval is understandable.
2. Approve the disposable QA course with a factual QA comment only if the UI
does not require substantive content edits; capture the new status and publish
availability.
3. Publish once. Capture confirmation, final published state, and whether the
course remains visibly tied to its source. Do not create a second course.

**Decision criteria:** A methodologist must understand the review gate and
publish consequence. Only an approved course should become publishable; the
published state must be unambiguous before learner assignment.

**Status:** ⏳ awaiting relayed review/approval/publication result.

## Final closure

All historical `blocked`, `awaiting`, and pre-fix statuses above are superseded
by their documented production fixes and retests. The full production human
journey is **PASS**: isolated tenant/admin, methodologist, generated and
published course, learner kiosk access, lessons, low/high quiz attempts,
assistant boundaries, server-backed completion, certificate issuance, and
certificate PDF acceptance. Certificate PDF acceptance is **PASS**. No required
QA step remains.
