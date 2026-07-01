# Tenant Registration And Trial Flow

> Status: product spec with v1 implementation notes.
> Date: 2026-07-01.
> Decision: no self-hosted mail server for v1; use transactional email provider plus Telegram bot as optional acceleration channel.

## Current Implementation Status

Implemented on 2026-07-01:

- Frontend route: `/register-tenant`.
- Public backend endpoint: `POST /api/v1/tenants/register`.
- First registered user becomes tenant `admin`.
- Trial tenant is created immediately with:
  - `plan = trial`;
  - `status = trial`;
  - 14 trial days;
  - 1 normal AI course generation;
  - 1 job-instruction course generation;
  - 10 learners;
  - 3 system users.
- New tables/fields:
  - `tenants.trial_started_at`;
  - `tenants.billing_contact_email`;
  - `tenants.billing_company_name`;
  - `tenants.billing_identifier`;
  - `tenant_leads`;
  - `tenant_usage`.
- Migration `0041_tenant_registration_trial.py` adds registration/trial storage.
- Migration `0042_rls_empty_tenant_context_safe.py` makes tenant RLS policies safe when `app.tenant_id` is empty.
- Transactional email is currently a log-backed `EmailService`; no self-hosted mail server is required.
- Email OTP login is implemented:
  - `POST /api/v1/auth/email/request-code`;
  - `POST /api/v1/auth/email/verify-code`;
  - `/login` has Email and Telegram modes.
- Resend support is implemented behind `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM`.
- Production Resend is active as of 2026-07-01:
  - sender: `Kamilya LMS <no-reply@notify.kml.kz>`;
  - sending domain: `notify.kml.kz`;
  - DKIM, SPF/return-path and DMARC for `notify.kml.kz` verified in DNS;
  - Render env is set for `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM`.
- Production Render API is live on commit `5dfaee6`; `/`, `/health`, `/api/v1/health` return 200.
- The old `/register` Telegram-ID flow remains as a legacy fallback.

Not implemented yet:

- Separate email verification before activation. Current v1 uses email OTP for login.
- `/trial/onboarding`.
- `/billing` and upgrade request UI.
- Superadmin leads/activation screens.
- Trial usage enforcement inside AI generation and invite flows.
- Shared/dedicated Telegram bot connection flow for tenant onboarding.

## Goal

Turn landing traffic from `kml.kz` into a working tenant without manual setup for every lead.

The flow must let an HR / L&D employee:

1. Read the landing page.
2. Start a free trial or request purchase.
3. Create a tenant.
4. Generate one normal course and one job-instruction course for free.
5. Invite a small pilot group.
6. Convert to paid plan when value is proven.

## Principles

- Registration must work from a work laptop with only email.
- Telegram bot is useful, but cannot be the only registration channel.
- Trial setup must not require manually creating a dedicated Telegram bot.
- Dedicated tenant bot is a paid/advanced integration, not a trial blocker.
- Email delivery should use a transactional email provider, not a self-hosted mail server.
- Billing can start as manual invoice/admin activation; online card payment can come later.
- Trial limits should protect AI cost while still showing the core value.

## Recommended UX

Landing CTA:

- `Попробовать бесплатно`
- `Получить демо`
- `Купить / запросить счет`

Primary route:

```text
kml.kz CTA -> app.kml.kz/register-tenant
```

Secondary route:

```text
Telegram shared bot deep link -> app.kml.kz/register-tenant?telegram_token=...
```

## Registration Form

Required fields:

- company name;
- work email;
- contact name;
- phone or Telegram username;
- expected employee count range;
- preferred language: `ru`, `kk`, `en`;
- intent: `try`, `demo`, `buy`.

Optional fields:

- BIN / company identifier;
- industry;
- city/country;
- message/comment.

Target validation:

- email should be verified before trial activation in a later iteration;
- company name cannot be empty;
- one active trial per email domain by default, unless superadmin overrides;
- disposable email domains should be blocked or flagged.

## Tenant Lifecycle

Suggested statuses:

```text
lead_submitted
email_pending
trial_active
trial_expired
sales_qualified
paid_active
suspended
churned
```

Happy path:

1. `lead_submitted`: form submitted.
2. `email_pending`: tenant shell exists, but HR cannot use trial until email verification.
3. `trial_active`: email verified, first admin user created.
4. `sales_qualified`: HR requested invoice/demo or hit trial limit.
5. `paid_active`: superadmin or billing automation activates paid plan.

## Trial Offer

Recommended free trial:

- 1 normal AI course generation;
- 1 job-instruction course generation;
- up to 10 learners;
- up to 3 system users: admin, methodologist, teacher;
- 14 days trial duration;
- certificate generation enabled for pilot learners;
- Supabase Storage enabled;
- tenant bot not included, shared bot only.

Why this offer works:

- one normal course demonstrates general AI value;
- one job-instruction course demonstrates Kamilya's differentiated onboarding use case;
- 10 learners are enough for pilot proof without becoming a free production tenant;
- certificates make the end-to-end value visible.

## Trial Limits

Required counters:

| Counter | Trial limit |
|---|---:|
| `ai_course_generations_used` | 1 |
| `jd_course_generations_used` | 1 |
| `active_students_count` | 10 |
| `system_users_count` | 3 |
| `trial_days` | 14 |

Recommended behavior:

- when a generation limit is reached, show upgrade CTA, not a raw error;
- when learner limit is reached, block adding new learners and show upgrade CTA;
- when trial expires, keep read-only access for admin/methodologist and block new generation/invites;
- student access can remain for 7 grace days to avoid pilot frustration.

## Billing Model V1

Do not implement full payment processing first.

V1 billing should support:

- plan catalog;
- tenant subscription status;
- trial limits and usage;
- manual activation by superadmin;
- invoice/request form;
- internal notes for sales follow-up.

Suggested plans:

| Plan | Target | Includes |
|---|---|---|
| `trial` | self-service pilot | 1 normal AI course, 1 JD course, 10 learners |
| `starter` | small company/pilot | limited learners, shared Telegram bot, email support |
| `business` | real tenant rollout | more learners, dedicated tenant bot, integrations |
| `enterprise` | custom | SSO/custom SMTP/data residency/white-glove setup |

Payment provider integration can be added after plan validation.

## Email Strategy

Decision: use transactional provider, not self-hosted mail server.

Required emails:

- login OTP;
- verify work email later if strict activation is required;
- trial started;
- invite tenant admin/methodologist;
- learner invitation;
- trial limit reached;
- trial expires soon;
- trial expired;
- invoice/request received;
- paid plan activated.

Provider abstraction:

```text
EmailService
- log
- resend
- postmark
- sendgrid
- smtp
```

Default for production:

- Resend first; `notify.kml.kz` DNS is verified as of 2026-07-01;
- keep SMTP adapter for enterprise/custom tenant settings later.

No self-hosted mail server in v1 because deliverability, DNS reputation, bounce handling and blacklists would become an operational product risk.

## Telegram Bot Strategy

There are two bot modes.

### Shared Bot For Trial

Trial tenants use one Kamilya-owned shared bot:

```text
Kamilya LMS Bot
```

Purpose:

- fast HR identity confirmation;
- login codes;
- trial notifications;
- deep links into app;
- optional learner notifications.

Shared bot deep link examples:

```text
/start trial_<token>
/start invite_<token>
/start login_<token>
```

The token binds the Telegram account to the tenant/user after server validation.

### Dedicated Tenant Bot For Paid Plans

Paid `business` / `enterprise` tenants may use their own bot.

Setup flow:

1. Tenant creates bot in BotFather.
2. Tenant enters bot token in Kamilya integrations.
3. Backend validates token via Telegram API.
4. Backend sets webhook.
5. UI shows status: connected / invalid token / webhook error.
6. Tenant can send test message.

This preserves the idea "each tenant can have its own bot" without making trial onboarding manual.

## Registration Flow Details

### Flow A: Try Free

```text
Landing -> Try free
Register tenant form
Create tenant lead
Send verification email
HR verifies email
Create tenant admin user
Start trial
Open onboarding wizard
Prompt: generate normal course or upload job instruction
Track usage counters
Invite pilot learners
Learners complete course/test/certificate
Upgrade CTA
```

Important screens:

- `/register-tenant`;
- `/verify-email`;
- `/trial/onboarding`;
- `/billing`;
- `/admin/super/tenants/[id]` for superadmin oversight.

### Flow B: Request Demo

```text
Landing -> Request demo
Lead form
Create lead without active tenant
Send confirmation email
Notify sales/admin
Superadmin qualifies lead
Optional: create trial tenant manually
```

Use when:

- company is large;
- HR wants a walkthrough;
- tenant needs dedicated bot/integrations before trial.

### Flow C: Buy / Request Invoice

```text
Landing -> Buy
Company/billing form
Create sales_qualified tenant or lead
Notify superadmin/sales
Manual invoice
Superadmin activates plan
Tenant admin receives activation email
```

Use when:

- customer is ready to buy;
- Kazakhstan invoice flow is needed;
- payment provider integration is not ready.

## Data Model Proposal

Minimal tables/fields:

```text
tenants
- subscription_plan
- subscription_status
- trial_started_at
- trial_ends_at
- billing_contact_email
- billing_company_name
- billing_identifier

tenant_usage
- tenant_id
- ai_course_generations_used
- jd_course_generations_used
- active_students_count_snapshot
- system_users_count_snapshot
- updated_at

tenant_leads
- id
- tenant_id nullable
- company_name
- contact_name
- email
- phone
- telegram_username
- employee_count_range
- intent
- status
- source
- created_at

email_verification_tokens
- id
- tenant_id
- user_id nullable
- email
- token_hash
- expires_at
- consumed_at

tenant_bot_integrations
- tenant_id
- mode: shared | dedicated
- bot_username
- token_encrypted nullable
- webhook_status
- last_checked_at
```

If existing tables already cover some fields, prefer extending them instead of creating duplicates.

## Backend API Proposal

Public:

```text
POST /v1/tenants/register
POST /v1/auth/email/request-code
POST /v1/auth/email/verify-code
POST /v1/tenants/verify-email
POST /v1/tenants/request-demo
POST /v1/tenants/request-invoice
```

Tenant admin:

```text
GET /v1/billing/me
POST /v1/billing/request-upgrade
GET /v1/trial/usage
```

Superadmin:

```text
GET /v1/admin/super/leads
POST /v1/admin/super/tenants/{id}/activate-plan
POST /v1/admin/super/tenants/{id}/extend-trial
POST /v1/admin/super/tenants/{id}/reset-trial-usage
```

Integrations:

```text
POST /v1/integrations/telegram/shared/connect
POST /v1/integrations/telegram/dedicated/validate
POST /v1/integrations/telegram/dedicated/connect
DELETE /v1/integrations/telegram/dedicated
```

## Frontend Proposal

New or updated routes:

```text
/register-tenant
/verify-email
/trial/onboarding
/billing
/admin/super/leads
/admin/super/tenants/[id]
```

Trial onboarding wizard:

1. Company profile.
2. Choose first path:
   - generate normal course;
   - upload job instruction and generate onboarding course.
3. Invite pilot learners.
4. Show progress and upgrade CTA.

## Superadmin Requirements

Superadmin must see:

- new leads;
- trial tenants;
- trial usage counters;
- trial expiration;
- conversion status;
- requested invoice/demo;
- tenant bot status;
- email verification state.

Actions:

- activate paid plan;
- extend trial;
- reset usage once;
- suspend tenant;
- add internal note;
- impersonate tenant admin later if the impersonation feature is approved.

## Open Questions

1. Trial duration: 7, 14, or 30 days?
2. Learner limit: 10 or 20?
3. Should certificates be downloadable during trial or watermarked?
4. Should trial allow public kiosk login?
5. Do we require work email domain, or allow Gmail for early pilots?
6. Which transactional provider first: Resend, Postmark, or SendGrid?
7. Should paid plan activation be manual only, or should Kaspi/card payment be in v1.1?

## Recommended Decision

Implement first:

1. Email-first tenant registration.
2. Shared Telegram bot optional connection.
3. Trial with 1 normal course + 1 JD course + 10 learners + 14 days.
4. Minimal billing/subscription fields.
5. Manual superadmin activation for paid plans.
6. Provider-abstracted transactional email, default Resend/Postmark.
7. Dedicated tenant bot only for paid plans.

This gives self-service acquisition without forcing the team to manually create a bot for every trial lead.
