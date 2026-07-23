# Human-journey production QA scenario

**Product:** Kamilya LMS · Kazakhstan corporate B2B SaaS
**Purpose:** Determine whether a first-time corporate client can achieve the promised document-to-evidence learning outcome without expert intervention.
**Primary language:** Russian; also assess visible Kazakh-language availability and terminology.
**Execution rule:** Use production through a real browser. Observe before inspecting implementation. Do not reveal secrets or PII, and do not change or delete customer data.

## Preconditions and safety

| Item | Requirement |
|---|---|
| Environment | `https://app.kml.kz`, production API on Render; capture revision/time in results. |
| Browser profiles | Start one clean, unauthenticated session; use a separate session/tab only for explicitly supplied non-production/demo QA credentials. |
| Test data | Only data named `QA-UX-YYYYMMDD-*`, created in a disposable QA tenant. Never upload real employee, client, instruction, certificate or personal data. |
| External hand-offs | OTP/invite delivery may be attempted once. If mailbox/Telegram access is unavailable, record the precise UI hand-off, copy and recovery route; do not fabricate completion. |
| Mutations | Do not create a trial tenant, invite, course, import, assignment, AI job, quiz attempt or export in an existing customer tenant. Before every write, confirm the tenant and record the disposal/cleanup plan. |
| Evidence | Screenshot every decision point, error state, permission boundary, completion state and responsive view using non-PII file names. Capture console/network errors attributable to the application separately from extensions. |

## Personas and success definition

| Persona | Desired business result | Minimum proof |
|---|---|---|
| A. Decision maker / first admin | Understands value, starts a trial or gets to login, knows what information is needed and the next action. | Clear entry, registration/login path, tenant context or documented hand-off. |
| B. Tenant admin | Understands admin boundary, finds team/settings, can add a system user and use an assigned second role where safely available. | Correct nav, role explanation/switch, success or safe blocked mutation evidence. |
| C. Methodologist | Creates structure and source-to-published-training path, then assigns it. | Staff/position/source/draft/review/publish/assignment state with provenance. |
| D. Employee | Opens assigned training, completes lessons and a required quiz, recovers from one failed attempt, receives certificate. | Assignment → player → quiz → completion → certificate PDF/list. |
| E. Manager/methodologist | Can find a person/status, filter and export a usable result. | Training log status and export or explicit limitation. |

## Reusable test cases

Status field values: `Pass`, `Fail`, `Blocked`, `Not run`. Severity applies only to a confirmed defect: Blocker, Critical, Major, Minor.

### A — acquisition, first-run and authentication

| ID | Exact action | Expected human outcome and acceptance criteria | Evidence / result fields | Recovery / cleanup |
|---|---|---|---|---|
| A01 | Open `/` in a clean 1440×900 browser. Do not use prior knowledge. | Within the first viewport, visitor understands that this is corporate learning software, who it is for, and has an obvious next action. Login and trial paths are distinguishable. | Screenshot, first-impression notes, time to identify CTA, console/network errors. | Return to entry route. |
| A02 | Follow every visible unauthenticated CTA and browser back navigation. | No dead end; route purpose, previous step and next action are understandable. | URL, screenshot, labels, back-navigation result. | None. |
| A03 | Open `/register-tenant`; inspect every field, validation and legal/consent copy without submitting. | A Kazakhstan company understands required company/contact information, trial scope, password/OTP expectation and what happens next. Russian copy is concise; no Russia-specific assumptions. | Screenshot, required field list, validation on empty/invalid synthetic input only if no submission occurs. | Clear local input before leaving. |
| A04 | Open `/login`; inspect email OTP and Telegram paths. Enter only a non-deliverable/invalid synthetic address if the UI allows a safe non-submit validation. | Channel choice, code destination, retry/expiry and recovery are explained; no channel falsely appears available. | Screenshot, copy, UI validation, API error/neutral response if sent. | Do not wait indefinitely for inbox/bot. |
| A05 | Refresh login/register pages; use browser Back/Forward. | No lost explanatory state or confusing redirect; focus remains usable. | URLs, screenshots, observed focus. | None. |
| A06 | Switch visible language to KK if offered, then revisit A01–A04 summaries. | Switch is discoverable, preserves intent, and core labels do not mix untranslated/incorrect terminology. | Screenshots; RU/KK findings. | Restore RU for following tests. |

### B — tenant admin, active roles and settings

| ID | Exact action | Expected human outcome and acceptance criteria | Evidence / result fields | Recovery / cleanup |
|---|---|---|---|---|
| B01 | With an explicitly authorized disposable QA admin session, enter the default post-login screen and refresh once. | User remains signed in, sees tenant name/context, understands dashboard purpose and next task. | Screenshot, URL, reload result, errors. | Log out at end. |
| B02 | Explore sidebar/top bar without using direct URLs: team, settings, integrations, kiosk, shared training log. | Navigation labels match the admin responsibility; learners/courses/assignments are not presented as admin actions. Empty states tell the admin what can be done next. | Per-screen screenshots and comprehension notes. | Do not change settings. |
| B03 | Attempt to reach a methodologist route through UI and direct URL. | UI and redirect/permission response make the boundary clear and offer a useful next action, not a generic failure. | URL, screenshot, response/error copy. | Return to admin home. |
| B04 | If a dedicated QA tenant is available, open team invitation/create-user flow and stop before irreversible submit; otherwise record blocker. | Role, invite delivery mechanism, expiry and system-user slot impact are explained before submission. | Screenshot, fields, warnings, blocker reason. | Cancel; no customer data change. |
| B05 | If the QA account has both admin and methodologist roles, switch active role, inspect changed navigation and refresh. | Role switch is visible, lands on correct home, removes irrelevant actions and persists on refresh. | Before/after screenshots, role label, reload result. | Switch back and log out. |

### C — methodologist: source to released assignment

| ID | Exact action | Expected human outcome and acceptance criteria | Evidence / result fields | Recovery / cleanup |
|---|---|---|---|---|
| C01 | Enter QA methodologist home; navigate naturally to staff/positions/documents/courses/assignments. | User can infer an ordered starting point without documentation; distinct concepts are named consistently. | Screenshot/navigation path; ambiguity notes. | None. |
| C02 | Inspect empty staff/structure state; start manual employee and import flows without commit. | The system explains the difference between system users and learners, accepted file format, preview/mapping/commit sequence and how to cancel/recover. | Screenshots, fields, validation. | Cancel and clear local data. |
| C03 | In QA tenant only, create `QA-UX-YYYYMMDD-Employee` and minimal department/position or safely stage it without final save. | Completion feedback identifies the person and what to do next; no duplicate-risk ambiguity. | Screenshots, success/toast, record state; timing. | Delete only the created QA record if product provides safe deletion; otherwise document cleanup owner. |
| C04 | Open document upload/job-instruction/AI generation entry points; do not upload real sources. | Acceptable formats, source purpose, indexing progression, privacy/provenance and failure/retry responsibilities are clear before upload. | Screenshots, visible limits/error help. | Cancel. |
| C05 | In isolated QA tenant only, upload a tiny synthetic non-sensitive document, wait for indexing, and capture loading/success/error/retry. | Progress is understandable; user knows whether the document is ready for generation and what to do after failure. | Timestamped screenshots, network/console evidence. | Delete QA document if safe. |
| C06 | Start native or AI draft creation from QA source; stop if it would consume a non-disposable/shared quota. | UI explains audience, language, source selection, AI limitations and expected processing state. | Screenshots; source-selection/provenance evidence; blocked reason if applicable. | Cancel/cleanup QA job only. |
| C07 | With a QA draft, inspect editor, provenance, validation status, review/approval and publish controls. | Clear distinction between draft/published, AI suggestion/human responsibility, and learner visibility. Publish must be prevented until required review. | Screenshots, button states, error copy. | Do not publish unless QA tenant and planned full E2E cleanup permit it. |
| C08 | Attempt direct/group/position/department assignment for a published QA course only. | Recipient scope, duplicate behavior, source of assignment and immediate outcome are visible. | Screenshots; enrollment status/confirmation. | Remove only QA manual assignment; rule changes only in QA tenant. |

### D — learner completion and certificate

| ID | Exact action | Expected human outcome and acceptance criteria | Evidence / result fields | Recovery / cleanup |
|---|---|---|---|---|
| D01 | Use a QA invite or student session; accept invite if available, then refresh. | Invite identifies organization/role safely, explains account/access transition, arrives at learner home and persists session. | Screenshot, URL, refresh result, expiry/error copy. | Log out. |
| D02 | From `/student` and natural nav, find the QA assignment. | Course title/status/deadline/next action are visible; no draft or unassigned content leaks. | Screenshot, findability time, status. | None. |
| D03 | Open course; complete required lessons. Navigate back/forward and refresh mid-course. | Progress is saved, current step is obvious, controls and completion prerequisites are clear. | Screenshots, progress before/after refresh, errors. | Do not alter non-QA training. |
| D04 | Take required QA quiz; intentionally answer one safe attempt incorrectly, then retry and pass. | Score, feedback, retry rules and remaining requirement are intelligible; retry does not lose course state. | Screenshots of fail/retry/pass; timing. | Record attempts as QA data. |
| D05 | Reach completion and certificates. Open/download certificate only for QA learner. | Completion acknowledgement, certificate availability/legitimacy and retrieval are clear; PDF/list state agrees with course status. | Screenshots; download filename only, no PII. | Remove QA data only if safe. |

### E — evidence for manager/methodologist

| ID | Exact action | Expected human outcome and acceptance criteria | Evidence / result fields | Recovery / cleanup |
|---|---|---|---|---|
| E01 | As methodologist and, where allowed, admin, open `/admin/training-log`. | User understands what statuses mean and can locate the QA learner/course without a spreadsheet. | Screenshot, labels, role access result. | None. |
| E02 | Apply filters/search and inspect course/person detail. | Filters have clear scope and empty/no-result states; completed/in-progress/assigned are distinguishable and actionable. | Screenshots, filter behavior. | Clear filters. |
| E03 | Export CSV only from QA-only result set when safe. | Export description, encoding/columns and download feedback make it usable in local business workflows. | Screenshot, filename/headers (no PII). | Delete local generated export after recording headers. |

### Cross-cutting checks applied to every visited critical screen

1. **Responsive:** A01–A04, B01–B03, C01/C04, D01–D04 and E01 at 390×844; record clipped controls, horizontal overflow, tap target and sticky navigation issues.
2. **Keyboard/accessibility basics:** Tab from page start, visible focus, logical order, Enter/Space on actionable controls, form labels, error association, modal escape, 200% zoom and contrast/readability observation.
3. **Performance perception:** record initial blank time, loaders, duplicate-submit protection, completed-state updates and any request above five seconds.
4. **Trust/copy:** source provenance, AI limitation, review responsibility, certificate credibility, status explanation, Russian terminology, Kazakhstan relevance, and Kazakh UI availability.
5. **Failure recovery:** for each error/empty/denied state, record whether a non-expert can tell what happened, retain work, retry safely or contact support.

## End-to-end acceptance gate

The promised result passes only if a new QA tenant can, without expert intervention: (1) understand and begin access; (2) establish staff context; (3) convert an approved source into a published course; (4) assign it; (5) let a learner complete it and obtain a certificate; and (6) let a methodologist/manager find the result in the log. Any missing required credentials, mail delivery, isolated QA tenant, or safe disposable test data is reported as an environment/data blocker—not silently treated as a product pass.

## Result record template

For every ID: `status`, `actual`, `evidence path`, `persona voice`, `severity if defect`, `reproducibility`, `business impact`, `recovery outcome`, `environment/data limitation`, `recommended owner/action`, and `cleanup state`.
