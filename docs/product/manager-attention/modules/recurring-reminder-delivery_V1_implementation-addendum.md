# R2a implementation addendum V1 — 2026-09-05

Accepted by root under owner continuation; parent `recurring-reminder-delivery_V1.md`.
Root owns SQL/migration, rule command/materialization, config/Celery/recovery seam,
DEV runner/integration and final docs. Terra owns new `learning_reminders/store.py`,
`tasks.py` and `tests/unit/test_learning_reminder_delivery.py`. Luna owns one
EmailService method and `tests/unit/test_learning_reminder_email.py`. No overlaps.

Fixed lead 1–30 days (default 1); zero days is excluded because a pre-deadline
notification scheduled exactly at the deadline is already stale. Rule fields:
`reminder_enabled=false`, `reminder_days_before_due=1`. Global configuration
`LEARNING_REMINDERS_ENABLED=false` gates enqueue and delivery, not just scheduler.
R2a includes methodologist rule PATCH and safe GET delivery states; a new UI is
not part of this backend increment. R2b escalation remains separate.

SQL functions, qualified `public`, tenant checked, root-owned:

- `enqueue_learning_reminder(uuid,uuid,uuid)` → uuid|null (tenant, course occurrence,
  path cycle; exactly one target). Same transaction as first materialization only.
- `claim_learning_reminder(uuid,uuid)` → rows `{id,tenant_id,claim_token}`. Due
  queued or stale sending (>10 minutes), SKIP LOCKED, max 100 recovery items.
- `learning_reminder_payload(uuid,uuid,uuid)` → eligible claimed row with
  `{email,learner_name,company_name,title,target_type,target_id,due_at,has_login_access}`.
  No eligible row → skipped. This function rechecks target immediately before send.
- `begin_learning_reminder_send(uuid,uuid,uuid,text)` → bool; checks eligibility
  again, reserves one of 3 attempts, fixes first_attempt_at and payload hash.
  A changed hash fails terminally; this prevents same provider key/different body.
- `finalize_learning_reminder(uuid,uuid,uuid,text,text,text)` → bool
  (tenant,id,token,kind,message_id,error_category). Kinds success/transient/terminal/
  defer/skipped. Fixed category allowlist; provider free text never stored.
- `due_learning_reminders(integer)` → `{id,tenant_id}`, only lms_recovery.
- `learning_reminder_statuses(uuid,uuid)` → safe rows for one owned recurring rule.

Stable key `learning-reminder/{id}`. Retry horizon: conservative 23 hours from
first actual send reservation; expired/ambiguous work becomes failed/manual review.
Retry delay 60/120/240 seconds, configuration defer 5 minutes, max 3 provider
attempts. No budget consumed by configuration failure. Before begin_send, the
worker hashes the exact renderer arguments (sorted JSON, SHA256). Delivery errors
use existing transient taxonomy; all unexpected categories map to internal_error.
Only Resend is allowed for this increment because the existing SMTP transport
does not honor the provider idempotency key. No transport/credential changes.

Email interface: `EmailService.send_learning_reminder(*,to_email,company_name,
learner_name,training_title,training_kind,due_at,access_url,idempotency_key)`.
`due_at` is an aware datetime; `training_kind` is course/learning_path. Russian
message with explicit UTC deadline, escaped HTML, no raw IDs or internal metadata.
Links: existing `/courses/{id}` and `/learning-paths`; inactive login access is
terminal `activation_required`, no new invitation or token retrieval.

Worker contract: `deliver(tenant_id,reminder_id)` and `recover_due_reminders(limit=20)`
plus Celery wrappers `learning_reminders.deliver` / `learning_reminders.recover`.
Recovery uses existing ASSIGNMENT_RECOVERY_DATABASE_URL; runtime sessions use the
canonical app factory. Restore tenant context after each store commit. Global
disabled returns without DB/provider activity. Existing broker-independent
assignment recovery entrypoint invokes bounded reminder recovery as a separate
batch only when enabled; no new systemd timer is activated.

Retention: no automatic deletion added. New ledger blocks occurrence removal;
existing owner-authorized tenant purge removes the ledger before dependent
occurrences. Preserve existing protected-tenant, superadmin and active-work guards.
Downgrade rejects nonempty ledger. No grant changes to existing roles/tables.

DEV acceptance: additive migration in a unique isolated schema, current runtime
roles unchanged; stub only existing dependencies required for SQL contracts if a
full clone is unavailable, explicitly label this limitation. Never rewrite shared
public objects or run tenant purge on real DEV data. Require cleanup of only the
exact generated schema after confirmed isolation. Production rollout/readback and
real-recipient delivery require a separate exact approval.
