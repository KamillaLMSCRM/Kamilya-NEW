# Full human learning journey — production QA result

**Date:** 2026-07-23
**Target:** `https://app.kml.kz` and production API
**Requested journey:** admin → methodologist → course → learner → quiz → assistant → certificate

## Executive result: PASS

The complete production journey passed after iterative defect discovery and
retests: isolated Kazakhstan tenant/admin → methodologist → source-grounded AI
course → approval/publication → manual learner → kiosk access → lessons,
low/high quiz attempts, learner assistant → server-backed completion →
certificate `KML-2026-25AF54` and accepted Russian Unicode PDF.

Early direct-browser discovery was unavailable in this QA agent runtime
(`iab`/`extension` unavailable). That limitation was superseded by relayed
interaction in the root agent's working in-app browser; it is historical
execution context, not a current test blocker.

## Relayed continuation

After the direct-browser limitation, the root agent confirmed it has a working
in-app browser. This QA agent is continuing as a **relayed test director**:
the root agent performs and evidences each approved UI action, then this report
records the observation and directs the next checkpoint. Claims below will be
marked as relayed rather than direct interaction by this agent.

### Relayed checkpoint 1 — tenant registration

**Observed:** The browser operator opened `/register-tenant` and captured the
empty and populated states. The user-facing form promises immediate access and
uses password registration rather than an OTP. Submission with organization
`QA-E2E-20260723 KZ Learning Journey` and
`qa-e2e-20260723-admin@example.invalid` remained on the form and displayed only
`Request failed with status code 422`; browser console was empty. Screenshot:
`01` (empty), `02` (populated), and
`03-register-tenant-422.png` (failure) are held by the browser operator in the
evidence directory.

**Usability defect — P1:** An otherwise ordinary validation failure is surfaced
as a raw HTTP status instead of field-level, human-readable guidance. The UI
invites a user to act but gives no way to identify or correct the invalid input.
The frontend handles only string/object error details, whereas FastAPI's normal
422 validation detail is a list. Repository inspection confirms the backend
uses `EmailStr`; the `.invalid` address is expected to be rejected. This is a
product UX defect, not a server outage.

**Safe next attempt:** Do not retry merely by removing optional BIN/phone; those
are not required and would not make an `.invalid` email acceptable. Use a fresh
address in a mailbox controlled by the browser operator (a clearly owned QA
alias is sufficient), retain the same `QA-E2E-20260723` organization prefix,
and leave optional contacts blank. If no controllable address exists, stop
before submitting again.

### Relayed checkpoint 2 — registration with a valid controlled address

**Observed:** The second submit used the safe reserved
`qa-e2e-20260723-admin@example.com` address and reached the backend, but the UI
again presented a generic HTTP 500. Render production logs identified the
cause: `EmailService.send_trial_started` received a Resend HTTP 422 before the
tenant-registration transaction committed, causing the whole registration to
roll back. No tenant or QA user persisted.

**Activation defect — P0:** A non-essential notification provider failure
prevents a prospective Kazakhstan customer from opening a trial workspace.
The registration UI also obscures the operational failure behind a raw 500.
The immediate priority is to preserve the registration transaction independently
of best-effort notification delivery; the root agent is implementing and
deploying that production correction. This QA director will not direct another
registration attempt until the deployment is healthy.

### Relayed checkpoint 3 — successful non-Demo activation after correction

**Observed:** After deployment revision `a721fe6` became Render live and Vercel
READY, one retry with the same reserved QA email succeeded despite the Resend
rejection. The UI showed `Trial создан` and routed to `/admin`. The dashboard
identified administrator `Айдана QA` and tenant
`QA-E2E-20260723 KZ Learning Journey`; it showed trial, 13 days remaining, AI
`0/1`, JD `0/1`, learners `0/10`, system users `1/3`, and onboarding `0/7`.

**Assessment:** The critical persistence behavior is now correct. The capacity
summary makes the next action reasonably clear and gives the human a useful
sense of the safe test budget. The underlying notification rejection still
needs operational follow-up, but it no longer blocks activation.

**Evidence tooling note:** DOM evidence was captured. Two attempts to capture a
screenshot of the very tall dashboard timed out; this is evidence-tooling
behavior, not a product defect.

### Relayed checkpoint 4 — admin provisions methodologist

**Observed:** The administrator's Team UI is clear about ownership and correctly
excludes learners. The new-member modal defaults to **Methodologist** and
explains the existing-account role-addition case. However, real coordinate-based
interaction reproduced a hard blocker: email, name, and password fields render
with `readonly=true`; their intended focus-based unlock does not change the
DOM, so a human cannot type into them.

**Provisioning defect — P0:** An administrator cannot add a required system
user through the only relevant UI. This is not an automation-only issue because
the failure occurred through ordinary user-like focus/click interaction. The
root agent is replacing the fragile `readOnly`/`onFocus` anti-autofill lock
while retaining safer autocomplete/data-ignore attributes, then will deploy and
retest. No methodologist was created from this failed modal attempt.

### Relayed checkpoint 5 — methodologist creation and first-login handoff

**Observed:** After Vercel revision `940a496` became READY, the Team form no
longer had `readonly`; real UI filling succeeded. It created `Мадина QA`
(`qa-e2e-20260723-methodologist@example.com`) with the default `Методист` role
and `Активен` status; table total became 2. The modal supplied no invitation,
copy-password, or login-handoff instruction.

**Authentication defect — P0:** The normal `/login` UI exposes only email OTP
and Telegram, while the Team flow requires administrators to set a password for
the new system user. The backend still has `/v1/auth/login` for email/password,
but no corresponding tenant-user UI. With a reserved QA mailbox that cannot
receive OTP, the just-created user cannot discover or complete sign-in. This is
both a functional activation blocker and an onboarding/discoverability defect;
it should be corrected before claiming the new-user methodologist journey.

**Temporary test boundary:** Role switching for the already signed-in admin,
after explicitly adding `methodologist` to that same existing account, could
exercise the content-owner surface; it must not be misreported as a separate
new-methodologist login. The new user remains an important regression retest
after a password-login/handoff correction.

### Relayed checkpoint 6 — separate methodologist password login

**Observed:** With revision `05ef427` live on Render and Vercel READY, `/login`
now visibly defaults to three modes: password, email code, and Telegram, and
includes an administrator-password handoff hint. The browser operator logged
out the admin and entered the methodologist credentials through the UI. Login
succeeded to `/dashboard`, showing the correct methodologist identity, isolated
tenant, zero courses/employees, and a clear New Course CTA to `/ai/generate`.
No browser logs were observed.

**Assessment:** The separate-user, password-based methodologist path is now
directly verified as a human-facing production flow. The empty state makes the
next content-authoring action clear.

### Relayed checkpoint 7 — source upload and indexing

**Observed:** The methodologist uploaded the approved disposable TXT through the
visible dropzone. Production displayed the document but indexing immediately
failed with tooltip: `All embedding providers failed: ['qwen-self-hosted',
'voyage']`; the document status was Error and both selection and Generate stayed
disabled.

**Generation defect — P0:** The primary first-course workflow is blocked because
no embedding provider is operational. The UI correctly keeps unsafe generation
unavailable and provides recovery-oriented status/copy; however, retry cannot
succeed until the provider chain is repaired. This is an infrastructure/product
availability defect, not a discoverability issue. The root agent is diagnosing,
fixing, and deploying before the authoring flow continues.

### Provider-routing change awaiting QA

Commit `58b5fe5` changes course-generation/chat LLM routing to DeepSeek
v4-flash primary with Qwen fallback; a direct DeepSeek smoke request succeeded.
This is relevant to generation and assistant-chat quality, but it does **not**
repair the observed indexing failure because embeddings remain Qwen then Voyage.
The current deployment `dep-d9grrnepbkes73c785t0` was building at the time of
this note. Do not claim the source-upload blocker fixed until the same QA TXT
indexes successfully in production.

**Additional later checkpoint:** DeepSeek's official API is text-only. Upload a
disposable synthetic scanned PDF after the core text scenario and verify Docling
OCR yields usable indexed text; do not attribute image parsing to DeepSeek.

### Relayed checkpoint 8 — source indexing recovery

**Observed:** On live commit `6042aad`, the methodologist uploaded an
identical-content retry TXT via the normal dropzone. It became Ready in about
four seconds, its checkbox became enabled, and no Qwen dependency/error was
shown. The prior failed document remains visibly disabled and was not deleted.

**Assessment:** The core authoring prerequisite is now working in production.
Keeping the failed record is correct for evidence/audit safety; the disabled
state avoids accidentally using it. The side-by-side failed/ready records may
be mildly confusing to a first-time author, so the next selection checkpoint
must confirm labels identify the ready retry unambiguously.

### Relayed checkpoint 9 — source selection and generation readiness

**Observed:** The methodologist selected only the Ready source. Compatibility
reported one thematic group and permitted a unified course; audience was set to
new warehouse employees in Kazakhstan, language Russian, and three modules.
Generate became enabled.

**UX defects — P2:** The UI says `1 документов` rather than the correct
singular `1 документ`. Its automatic source summary is weak generic English
(`Document about various topics`) despite the concise Russian safety source.
Both issues reduce confidence in source selection before consuming a limited
trial generation, although neither blocks the current run.

### Relayed checkpoint 10 — generation quota recovery

**Observed:** A subsequent Generate click did not create a job: the frontend
logged HTTP 403 and stayed on the configured state. The likely cause is that
the first generation attempt, which failed during the provider/infrastructure
incident, consumed the tenant's only normal AI trial slot. The UI exposed no
readable 403 explanation or recovery action.

**Quota-recovery defect — P0:** A platform-side failed generation can permanently
consume a small trial allowance and strand a customer at a ready-to-generate
screen. This blocks the first-value moment and offers no human-readable reason
or support/retry route. The root agent is diagnosing quota accounting/recovery;
no further Generate clicks should be made before the correction is live.

### Quota-recovery correction awaiting production retest

Commit `6b17948` has been pushed and deployed to the worker. It refunds trial AI
count and LLM budget for future failed jobs, including enqueue/unavailable
branches. Only the disposable QA tenant was restored after verification of one
failed job: AI usage changed from 1 to 0 and `failed_jobs=1`. Render API was
still building when reported; no new generation click is authorized until that
deployment is live.

### Relayed checkpoint 11 — controlled generation retry starts

**Observed:** The controlled retry created a visible job and reached 10% at
Projecting structure. The human UI does not expose the job ID (no hidden
storage was inspected). Its progress message leaks technical trace text:
`Architect: -> list_documents returned 124 chars`, rather than a user-facing
status.

**UX defect — P1:** Progress feedback discloses implementation details and is
not meaningful to a methodologist. Job ID invisibility is not necessarily a
defect, but it removes a useful support reference; the key issue is the
technical trace leakage. No extra clicks were made while monitoring terminal
state.

### Relayed checkpoint 12 — generation terminal failure

**Observed:** The controlled retry reached 50% (lesson 3/6) then failed with
visible error: `All embedding providers failed: ['voyage', 'qwen-self-hosted']`.
No further UI retry was made. The automatic quota refund is being verified.

**Generation defect — P0:** The full AI course pipeline still cannot complete
because its worker embedding configuration/path fails, even though Voyage works
for Render API ingestion. This isolates the remaining issue to worker
configuration/credentials or its request path rather than the authoring UI.
The user-visible provider list is more informative than the earlier silent
403, but it remains overly technical and gives no actionable user recovery.

### Worker root cause and correction awaiting production retest

Worker logs showed Voyage returning HTTP 200 for the first three embedding
requests, then HTTP 429 project limit. The old client exhausted only 1+2+4
second retries and failed. A read-only verification confirmed the QA tenant's
automatic AI counter refund (`current=0`). Commit `506c38b` changes the worker
to six retries with exponential backoff up to 60 seconds and honors
`Retry-After`; worker deployment is live and API deployment was building when
reported. One post-fix controlled retry is pending after API live.

### Relayed checkpoint 13 — generated draft reaches review

**Observed:** The visible generation terminal state succeeded. Draft title:
`Безопасное начало смены на складе`; status: `На проверке`; three modules, six
lessons, six tests, and the retry source document shown. The methodologist
assistant is visible both at whole-course scope and through per-module
`Спросить AI` controls. No publication action was taken.

**Assessment:** The end-to-end authoring pipeline has now produced a reviewable
draft from the disposable Kazakhstan-relevant source. Assistant behavior and
review/publish gates remain to be tested before any publication.

### Relayed checkpoint 14 — whole-course authoring assistant

**Observed:** The grounded question returned three relevant warehouse-safety
rules (relayed DOM/UI observation; no stored screenshot). The
out-of-source Kazakhstan penalty question failed the non-fabrication criterion:
the assistant invented a 5–30 MRP range while conceding it could not guarantee
the article.

**Assistant safety defect — P1:** The assistant gives unsupported legal/penalty
guidance instead of clearly declining or requesting an approved source. This
can materially mislead a Kazakhstan customer and blocks publication in this QA
journey until grounding behavior is corrected and retested. No publication or
assistant-applied content change was made.

### Relayed checkpoint 15 — assistant grounding and module-scope retest

**Observed:** Production retest at commit `42c7c72` passed. The same unsupported
fines question answered exactly `В материалах курса этого нет.` without a
numeric/legal fabrication. Per-module Ask AI switched scope to the selected
module, produced a focused improvement, and displayed `Применить к уроку`.
No edit was applied (relayed DOM/UI observation; no stored screenshot).

**Assessment:** The assistant now sets an appropriate boundary for unsupported
content and makes scoped suggested changes explicit. It is safe to proceed to
human review and publication without applying an unreviewed assistant edit.

### Relayed checkpoint 16 — review approval and publication

**Observed:** The methodologist reviewed all three modules: six source-linked
lessons and six lesson quizzes (11, 11, 11, 11, 13, and 12 questions). A factual
QA audit comment was used for approval; status became Approved, with the comment
and timestamp visible, and the publish button appeared. One publication made
the catalog show a single Published course with AI badge and source-aligned
description (relayed DOM/UI observation; no stored screenshot).

**Assessment:** Review gating, audit visibility, and single publication behaved
as expected. The course is ready for assignment to one disposable learner.

### Relayed checkpoint 17 — learner provisioning and assignment

**Observed:** The Methodologist Staff UI created exactly one learner:
`QA-E2E-20260723-001`, `Ерлан QA`, department `QA Warehouse`, position
`Warehouse trainee`. Structure showed one employee, department, and position
(relayed DOM/UI observation; no stored screenshot). Assignment selected the sole published course and this
learner once. The row showed `Ерлан QA / Записан / Вручную`; toast stated
`Назначено обучающихся: 1` (relayed DOM/UI observation; no stored screenshot).

**Discoverability defect — P1:** Neither manual Staff creation nor Assignment
supplied a learner access/login handoff. Manual learner records use the
admin-owned kiosk route, but a first-time methodologist receives no visible
instruction or link to it. The data/assignment function works; the human path
to start learning is not discoverable from the completion point.

### Relayed checkpoint 18 — kiosk creation failure

**Observed:** QA admin opened `/admin/kiosks`. The kiosk form offered no position
options (only unrestricted). Creating `QA-E2E-20260723 Warehouse kiosk` at
`QA Warehouse, Қазақстан` returned generic `Ошибка создания`; no kiosk was
created.

**Kiosk defect — P1 (journey blocking):** The intended manual-learner access
channel cannot be established. The UI hides the server cause, so the admin
cannot tell whether to correct a field, retry, or contact support.

**Likely code cause (requires log confirmation):**
`create_kiosk_link()` commits and then calls `refresh(link)`. Tenant RLS context
is set transaction-locally by `get_current_user`; commit ends that transaction.
The post-commit refresh, and router's subsequent `db.get`, can therefore run
without `app.tenant_id` and fail/return no row. This pattern is visible in
`apps/api/app/modules/users/kiosk_service.py` and `kiosk_router.py`. The lack of
position choices is a second data-model gap: manual Staff creation stores
department/position text on the learner, while the kiosk UI loads options from
`GET /v1/positions`, which has no corresponding canonical Position row here.
Existing kiosk tests cover public JWT identification, not authenticated kiosk
creation or manual-staff-to-position scoping.

### Kiosk correction and controlled access retest pending

Commit `9f31144` is live. Root cause was confirmed: internal creation commit
cleared transaction-local RLS before response; the admin position fetch used a
methodologist-only endpoint. The correction adds an admin scope-positions
endpoint and removes the internal create commit; tests passed. Exactly one
active QA kiosk exists. It remains unrestricted because it persisted before the
old post-commit response failure, but the corrected modal now offers
`Warehouse trainee (QA Warehouse)`. Do not create a second kiosk merely to test
scope; continue with the existing disposable kiosk and record the scope caveat.

### Relayed checkpoint 19 — public kiosk link cannot resolve

**Observed:** After admin logout, the exact active QA kiosk URL showed `Киоск
недоступен — Ссылка не найдена`, although the active row exists in the admin
surface.

**Kiosk access defect — P1 (journey blocking):** The public employee endpoint
cannot resolve a valid kiosk token. This is consistent with missing tenant RLS
context on token-scoped public lookup. The root agent is adding a safe
token-scoped bootstrap and will retest the exact existing URL; no new kiosk or
token should be created.

### Relayed checkpoint 20 — public kiosk and learner player access

**Observed:** At commit `34fa53d`, the exact existing kiosk URL resolved
unauthenticated. Personnel number `QA-E2E-20260723-001` identified `Ерлан QA`
as `Warehouse trainee` and showed exactly one assigned course. Opening it
authenticated as learner and landed in the course player: 0/6 lessons,
module/lesson outline, first-lesson content, clear `Отметить урок пройденным`,
and lesson AI assistant promising not to choose quiz answers. No unrelated data
was visible.

**Assessment:** The kiosk access model now works as intended for the disposable
learner: identification is isolated, assignment visibility is correct, and the
first completion action is obvious.

### Relayed checkpoint 21 — learner assistant, persistence, and low-score quiz

**Observed:** Learner assistant gave a grounded answer: damaged PPE should be
reported immediately to the shift supervisor and not used. Lesson 1 completion
persisted through full kiosk re-identification (1/6, resumed at lesson 2).
Direct reload redirects to login because kiosk session is memory-only. Kiosk
catalog nevertheless shows `Не начат` at 17% (P2 status inconsistency). Lesson
2 completion reached 2/6. A deliberate unsupported-answer attempt on its
11-question quiz scored 0%, clearly failed, showed explanations/correct answers,
and exposed `Попробовать снова`. Matching-question content renders mojibake
`в†’` instead of an arrow (P2 encoding defect).

### Relayed checkpoint 22 — quiz retry high score and stale toast

**Observed:** The learner completed the first quiz twice: deliberate 0% failure,
then 100% pass (11/11). Retry history correctly retained 0% and showed 1/3
attempts. After the 100% result, the toast title said passed but its description
stale-read 0%.

**UX defect — P2:** Success feedback contradicts the actual high score, which
can undermine learner confidence. Commit `add2f67` addresses this stale pass
description, kiosk in-progress catalog status, and matching-arrow mojibake;
deployment was pending when reported.

### Relayed checkpoint 23 — continued learner completion and exact toast cause

**Observed:** Four of six lessons are complete. Learner AI gave a grounded
post-result explanation without selecting an option. A second completed quiz
scored 100% (11/11); matching arrow now renders correctly as `→`. The true
toast defect remains: API score is nested at `data.attempt.score_percent`, while
the toast reads `data.score_percent`, so it still shows 0%. Certificate is not
yet issued.

**Assessment:** Assistant boundaries and second high-score semantics pass.
Mojibake correction is verified. The stale-score toast has a precise frontend
field-path cause and is being corrected; completion/certificate verification
continues only after all requirements are met.

### Relayed checkpoint 24 — false course completion at 6/6 lessons

**Observed:** At 6/6 lessons, the player declared Course completed solely from
100% lesson progress and hid all quizzes, while Certificates correctly showed
none. This left the learner unable to satisfy the real assessment requirement.

**Completion defect — P0:** The UI equated lesson progress with server-side
enrollment completion. Root cause: dashboard API exposed publication status but
not enrollment completion; player used `progress_percent=100` as completion.
Commit `cf40b81` adds `enrollment_status`, makes counts/status use it, retains
course access until server-side completion, and converts raw student
course/certificate anchors to Next Link. TypeScript and backend compile passed;
integration suite was blocked by a local PostgreSQL test-password mismatch.
Render/Vercel deployment is pending.

### Relayed final production completion

**Verified outcome:** The learner completed the previously missing lesson-5 quiz
(`a1eb15d0-ead4-40a8-9d00-6498acd8e9ea`) at 100% (13/13). All six quizzes are
now passed; server-side course completion succeeded. Dashboard shows one
completed course and one certificate. Certificate `KML-2026-25AF54` was issued.

**Completion fixes verified in production:** Structured completion errors now
use the API `details` envelope instead of surfacing a raw HTTP 400 in the UI;
`/quizzes/enrolled` import failure and UUID/string lesson-map mismatch were
corrected. Relevant deployed commits before the PDF work: `b10d544`,
`3cba6f6`.

**Certificate PDF acceptance — PASS:** Production commit `79e86c3` is live on
Render and active on the VPS worker. Existing certificate `KML-2026-25AF54` was
regenerated through the real authenticated production download endpoint using
the v2 template. The one-page A4 PDF contains native Cyrillic
`СЕРТИФИКАТ`, `Ерлан QA`, `Безопасное начало смены на складе`, date
`23 июля 2026 г.`, the correct certificate number, and verification URL.
Rendered PNG inspection found no clipping or overlap. Bundled Ubuntu fonts
remove OS-font dependency.

**Download UX note:** The UI programmatic blob-download action completed with
no visible error, but did not emit a browser download event. Endpoint-level
production verification returned a valid PDF, so functional download acceptance
passes; browser event observability remains a tooling limitation.

**Evidence references:** the evidence directory currently contains
`04-methodologist-document-ready.png`,
`12-certificate-KML-2026-25AF54-prod-v2.pdf`,
`13-certificate-KML-2026-25AF54-prod-v2.png`, and the two disposable TXT source
files. Other browser findings in this report are relayed DOM/UI observations,
not stored screenshots.

Using curl only, the public availability baseline passed:

| Check | Result |
| --- | --- |
| `https://app.kml.kz` | HTTP 200 |
| `https://kamilya-lms-api.onrender.com/api/v1/health` | HTTP/status ok |

## Evidence

Stored artifacts and relayed production UI observations are distinguished above.
Evidence directory: `docs/qa/evidence/2026-07-23-full-learning-journey/`.

## Graphify note

Graphify was used before repository orientation. It identified the relevant
course, quiz, certificate, enrollment and learner-assistant modules; these
would be the implementation paths to inspect if a later interactive run finds
a defect. The current handoff documents that admin owns tenant/system users,
methodologist owns courses/assignments, and students complete assigned learning
and receive certificates.
