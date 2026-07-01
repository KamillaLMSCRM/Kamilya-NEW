# Current Status And Next Steps - 2026-07-01

> No secrets in this file. This is the working plan after the tenant registration, Resend, Render and root health probe deployment.

## Current Production State

- Repo: `KamillaLMSCRM/Kamilya-NEW`, branch `master`.
- Latest pushed commit: `5dfaee6 fix: add root health probe endpoint`.
- Render API service: `srv-d8rp8ej7uimc73fglid0`.
- Live Render deploy: `dep-d92dgvpo3t8c73bd5pug`, commit `5dfaee6`.
- API health:
  - `GET/HEAD https://kamilya-lms-api.onrender.com/` -> 200;
  - `GET https://kamilya-lms-api.onrender.com/health` -> 200;
  - `GET https://kamilya-lms-api.onrender.com/api/v1/health` -> 200.
- Supabase Alembic head: `0043`.
- Runtime DB role: `lms_app` via `DATABASE_URL`; DDL uses `MIGRATION_DATABASE_URL`.
- Transactional email: Resend.
- Sender: `Kamilya LMS <no-reply@notify.kml.kz>`.
- Resend domain `notify.kml.kz`: DKIM, SPF/return-path and DMARC verified.

## Product Decisions Now Fixed

- Tenant self-registration starts from `/register-tenant`.
- Trial is created immediately after registration:
  - 14 days;
  - 1 normal AI course generation;
  - 1 job-instruction course generation;
  - 10 learners;
  - 3 system users.
- Email login uses OTP codes. Telegram login remains available as a second mode.
- No self-hosted mail server in v1.
- Dedicated tenant Telegram bot is not required for trial; it belongs to paid/business setup.
- `/admin/enrollments` is legacy; direct assignments belong to methodologist/teacher through `/assignments`.

## Next Step Plan

### 1. Superadmin Commercial Control

Goal: superadmin must see and manage the full tenant lifecycle, not only raw tenant rows.

Deliverables:

- Add superadmin view for `tenant_leads`.
- Add tenant detail screen with trial status, billing fields, usage counters and admin contact.
- Add actions:
  - extend trial;
  - reset trial usage;
  - mark sales qualified;
  - activate paid plan manually;
  - suspend/reactivate tenant.
- Add audit events for every commercial/admin action.

Done when:

- A new registration appears in superadmin without DB access.
- Superadmin can move a tenant from trial to paid manually.
- All actions are tenant-scoped and audited.

### 2. Trial Enforcement

Goal: trial limits must be real product limits, not only stored counters.

Deliverables:

- Enforce AI generation limits in normal course generation.
- Enforce job-instruction course generation limit.
- Enforce active learner limit in invite/import/create-student flows.
- Enforce system user limit in tenant team management.
- Return structured upgrade-required errors, not generic 403/500.
- Show upgrade CTA in the frontend when a limit is hit.

Done when:

- Trial tenant cannot exceed configured limits through UI or API.
- Paid tenant is not blocked by trial limits.
- Backend tests cover each limit.

### 3. Trial Onboarding Wizard

Goal: after `/register-tenant`, HR/admin should land in a guided pilot setup instead of an empty admin area.

Deliverables:

- Add `/trial/onboarding`.
- Steps:
  - confirm company profile;
  - choose first path: normal course or job-instruction course;
  - create/import pilot learners;
  - send/copy invites;
  - open progress dashboard.
- Add empty states for tenants with no courses, no staff and no invites.

Done when:

- A new tenant can reach the first generated course and first invite without asking support.

### 4. Email Templates And Delivery Events

Goal: email should be operationally traceable.

Deliverables:

- Add templates for:
  - login OTP;
  - trial started;
  - learner invitation;
  - trial limit reached;
  - trial expiring soon;
  - upgrade/paid activation.
- Store delivery intent/event rows for important emails.
- Add resend/retry action where appropriate.
- Keep unknown-email login response neutral to avoid account enumeration.

Done when:

- Support can answer "was this invite/login email attempted?" without checking Render logs.

### 5. Billing V1

Goal: support manual sales/invoice flow before online payments.

Deliverables:

- Add plan catalog in code/config or DB.
- Add tenant subscription fields if current tenant fields are insufficient.
- Add `/billing` or `/admin/billing` for tenant admin:
  - current plan;
  - trial usage;
  - request invoice/demo;
  - upgrade request.
- Add superadmin handling of upgrade requests.

Done when:

- A trial tenant can request purchase from UI.
- Superadmin can mark tenant paid and the app behavior changes accordingly.

### 6. Production Smoke Checklist

Run after every deploy touching auth, registration, billing, or tenant limits:

```powershell
curl.exe -I --max-time 20 https://kamilya-lms-api.onrender.com/
curl.exe -sS --max-time 20 https://kamilya-lms-api.onrender.com/api/v1/health
```

Then verify:

- `/register-tenant` creates a tenant, first admin and usage row.
- `/login` email OTP request returns neutral success.
- Known tenant user receives OTP through Resend.
- OTP verify returns access/refresh tokens and sets refresh cookie.
- Superadmin can see the new tenant/lead.
- Trial limits block exactly at the configured thresholds.

## Open Product Questions

1. Should trial tenant activation require email OTP before creating the tenant, or is "create immediately, verify for login" acceptable for v1?
2. Should one company domain be limited to one active trial by default?
3. Should trial certificates be normal, watermarked, or disabled until paid?
4. Which paid plan limits are final for `starter`, `business`, `enterprise`?
5. Should learner invitations now send email automatically, or remain copy-link first until templates/events are implemented?
