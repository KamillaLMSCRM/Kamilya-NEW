# Telegram learning notifications

Product owner and approver: Kamilya owner, approved the shared-bot design.
Root, module and source review owner: Codex. Release approval remains separate.

| Module | Owns | Interface |
| --- | --- | --- |
| Workspace routing and subscription | Enabled tenant routes and a verified private chat per tenant learner | Profile status/link/confirm/disconnect, authenticated Telegram webhook |
| Event projection | Telegram work derived from committed assignments and existing scheduled reminders | Tenant-bound delivery rows, no writes to email state |
| Delivery and review | Bounded claim, current eligibility, transport, sanitized receipts | Existing notification worker recovery and methodologist status views |

One deployment bot serves configured tenant workspaces. KARLSKRONA can have a distinct branded bot in its white-label deployment. A tenant's configured origin must be under its deployment's controlled domains. Telegram chat reuse across tenants does not share settings, notifications, access, or history.

Critical journeys:

- A learner generates an expiring link, presses Start and confirms the code received in that chat back in the LMS. A linked chat does not become a login credential. The learner can disconnect the current workspace from the profile or select it under the bot's `/settings` command.
- New course, program and knowledge check assignments are sent to the opted-in learner. An enabled recurring reminder produces its due-soon notice and, if explicitly configured, one overdue notice. Before claiming delivery, check the current user, publication and assignment status and the effective deadline.
- An event has a single durable Telegram claim. A provider acceptance records the message receipt. A dispatch with unknown outcome is visible and is never blindly retried. Email keeps its existing independent queue, policy, eligibility and results.
- Methodologists read delivery state only in their own workspace. Where there are separate client workspaces, the existing role model governs which workspace can be read. A new cross-workspace admin role is outside the notification module.
- Locally replay linking, channel independence, deadline/eligibility, and ambiguous-send cases. In DEV verify two routed workspaces or two synthetic learner accounts, real sends to explicitly opted-in testers and existing email behavior. Apply the additive migration to a test schema before any runtime rollout.

## Runtime setup and rollback

Apply migration 0193 in DEV before enabling any route. DEV 0190 already owns the
localization table. The production candidate keeps its separate 0191 → 0192
lineage. The API and notification worker use
the same bot username, token and webhook secret for their environment. Store
`TELEGRAM_REMINDER_BOT_TOKEN` and `TELEGRAM_REMINDER_WEBHOOK_SECRET` as secrets,
and set `TELEGRAM_REMINDER_BOT_USERNAME` to the username without `@`.
Bind the Telegram webhook to `/api/v1/learning-notifications/telegram/webhook`
using that secret and the update types `message` and `callback_query`.
Verify the registered bot identity and webhook URL before opening any workspace.
Use a different bot identity for DEV and a live deployment that runs concurrently.

Enable only the designated workspace IDs in `telegram_reminder_workspaces`.
Each row supplies a display label, its verified HTTPS frontend origin, and the
optional overdue notice. Newly created events are projected after enablement.
Set `enabled=false` to stop that workspace; a provider request already in flight
may complete. Roll back the app with the additive schema retained to preserve
subscriptions and delivery history. Clear a webhook only on the inspected bot.

## Local candidate verification

- Supabase DEV isolated schema, real non-bypass `lms_app`: migration
  upgrade/downgrade/upgrade, FORCE RLS, cross-tenant claim denial, one-time Start,
  same chat independently linked to two workspaces, one claim, uncertain
  delivery retained without retry, completion suppression, email-state
  independence and owned schema cleanup passed. The shared DEV schema revision
  remained unchanged.
- 52 focused API regressions and 83 focused frontend regressions passed.
  TypeScript, scoped ESLint/Ruff and whitespace checks passed.
- Live worker, webhook, two-channel delivery and customer-facing acceptance
  require the coordinated DEV release of migration 0193, API, UI and worker.
