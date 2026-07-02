# Current status and next steps

> No secrets in this file. Updated on 2026-07-02 after the first production tenant-flow smoke.

## Current production state

- Repo: `KamillaLMSCRM/Kamilya-NEW`, branch `master`.
- Backend API: `https://kamilya-lms-api.onrender.com`.
- Render service: `srv-d8rp8ej7uimc73fglid0`.
- Live backend deploy: commit `2990f2f fix: ignore empty ai quizzes in completion`.
- Frontend app: `https://app.kml.kz`.
- Supabase Alembic head: `0045`.
- Runtime DB role: `lms_app` through `DATABASE_URL`.
- DDL and direct maintenance: `MIGRATION_DATABASE_URL`.
- Transactional email: Resend.
- Sender: `Kamilya LMS <no-reply@notify.kml.kz>`.
- Resend domain `notify.kml.kz`: DKIM, SPF/return-path and DMARC verified.

## Verified first tenant flow

The first tenant launch path was verified on production on 2026-07-02:

1. Upload tenant documents.
2. Confirm document embeddings show `success`.
3. Generate an AI course from tenant documents.
4. Review and publish the generated course.
5. Assign the course as a methodologist through `/assignments`.
6. Log in as a learner.
7. Complete lessons and required quizzes.
8. Complete the course through the backend completion endpoint.
9. Issue and display a certificate.

Production evidence:

- Generated course: `7e434b25-1057-42b0-ac64-ed56daa6b041`.
- AI job: `64891564-5bb5-4648-ba40-c3ec04d40621`.
- Course shape: 2 modules, 6 lessons, 6 quiz records.
- Learner completion: 6 of 6 lessons.
- Certificate: `KML-2026-5DE383`.
- Learner UI smoke:
  - `/student` shows the generated course, 100% progress and 1 certificate
  - `/my-courses` shows the completed course
  - `/certificates` shows `KML-2026-5DE383`

## Fixes made during the production smoke

Two production blockers were found and fixed:

- `f660d12 fix: bound ai review stage latency`
  - AI generation no longer stalls indefinitely at review progress 72%.
  - LLM-as-judge review now has a 45s timeout and falls back to heuristic review.
  - The review stage writes per-lesson progress messages.
- `2990f2f fix: ignore empty ai quizzes in completion`
  - AI generation no longer creates empty quiz records for lessons without questions.
  - Course completion counts only quizzes that contain at least one question.
  - `QuizAttempt.score_percent` now maps to the actual `score_percent` column.

## Product decisions now fixed

- Tenant self-registration starts from `/register-tenant`.
- Trial is created immediately after registration:
  - 14 days
  - 1 normal AI course generation
  - 1 job-instruction course generation
  - 10 learners
  - 3 system users
- Email login uses OTP codes through Resend.
- Telegram login remains available as a second mode.
- No self-hosted mail server in v1.
- Dedicated tenant Telegram bot is not required for trial.
- Dedicated tenant bot belongs to paid/business setup.
- `/admin/enrollments` is a legacy URL and redirects to `/assignments`.
- Direct learner-course assignments belong to methodologist/teacher, not tenant admin.

## Remaining P0 before the first real tenant

### 1. Clean up stale AI jobs

There are historical AI jobs from earlier smoke runs, including queued or running jobs created before the latest fixes. They do not block the verified flow, but they confuse operational dashboards.

Deliverables:

- Add a superadmin action or maintenance script to mark stale jobs as `failed` or `cancelled`.
- Define a timeout rule for jobs stuck in `pending` or `running`.
- Add a dashboard filter for active vs terminal jobs.

Done when:

- Superadmin can see only meaningful active work by default.
- Stale jobs cannot look like live tenant activity.

### 2. Trial enforcement

Trial limits are stored, but every cost-bearing flow must enforce them.

Deliverables:

- Enforce normal AI course generation limit.
- Enforce job-instruction course generation limit.
- Enforce active learner limit in invite/import/create-student flows.
- Enforce system user limit in tenant team management.
- Return structured upgrade-required errors.
- Show upgrade CTA in the frontend when a limit is hit.

Done when:

- Trial tenant cannot exceed configured limits through UI or API.
- Paid tenant is not blocked by trial limits.
- Backend tests cover each limit.

### 3. Superadmin commercial control

Superadmin can manage core tenant state, but the commercial workflow still needs a focused surface.

Deliverables:

- Show `tenant_leads` as a pipeline.
- Show trial usage, billing contact and activation state in one tenant detail view.
- Add actions:
  - extend trial
  - reset trial usage
  - mark sales qualified
  - activate paid plan manually
  - suspend/reactivate tenant
- Add audit events for each action.

Done when:

- A new registration appears in superadmin without DB access.
- Superadmin can move a tenant from trial to paid manually.
- Each action is tenant-scoped and audited.

## P1 after first tenant launch

### Trial onboarding wizard

Goal: after `/register-tenant`, HR/admin should land in a guided pilot setup instead of an empty admin area.

Deliverables:

- Add `/trial/onboarding`.
- Guide first path selection:
  - normal course generation
  - job-instruction course generation
- Add pilot learner creation/import step.
- Add invite step.
- Add progress dashboard link.

### Email templates and delivery events

Goal: support can answer whether an OTP or invite email was attempted.

Deliverables:

- Add templates for:
  - login OTP
  - trial started
  - learner invitation
  - trial limit reached
  - trial expiring soon
  - paid activation
- Store delivery intent/event rows for important emails.
- Add resend/retry action where appropriate.

### Billing v1

Goal: support manual sales/invoice flow before online payments.

Deliverables:

- Add plan catalog.
- Add `/billing` or `/admin/billing`.
- Show current plan, trial usage and upgrade request.
- Add superadmin handling of upgrade requests.

## Production smoke checklist

Run after every deploy touching auth, registration, billing, AI generation, assignments or completion:

```powershell
curl.exe -I --max-time 20 https://kamilya-lms-api.onrender.com/
curl.exe -sS --max-time 20 https://kamilya-lms-api.onrender.com/api/v1/health
```

Then verify:

- `/register-tenant` creates tenant, first admin and usage row.
- `/login` email OTP request returns neutral success.
- Known tenant user receives OTP through Resend.
- OTP verify returns access/refresh tokens and sets refresh cookie.
- AI course generation moves past review and assessment.
- Generated course can be reviewed and published.
- `/assignments` can assign a learner as `teacher`.
- Learner can complete lessons and required quizzes.
- `/courses/{course_id}/complete` returns a certificate id.
- `/certificates` shows the issued certificate.

## Open product questions

1. Should one company domain be limited to one active trial by default?
2. Should trial certificates be normal, watermarked or disabled until paid?
3. Which paid plan limits are final for `starter`, `business` and `enterprise`?
4. Should learner invitations send email automatically, or remain copy-link first until templates/events are implemented?
