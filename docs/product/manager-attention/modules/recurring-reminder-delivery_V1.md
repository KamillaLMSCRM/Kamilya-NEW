# Recurring reminder delivery V1

Module: KML-MANAGER-ATTENTION-REMINDER-001. Epic: KML-MANAGER-ATTENTION.
Status: Accepted for R2a local implementation, not an enabled production feature.
Document V1, template V2, supersedes none. Root/module owner: Astra.
Product owner: repository owner; local planning authorized by «делай».
Independent source review: Luna/medium. Production activation: not approved.
Change control: root review completed 2026-09-05 under owner «продолжай» → freeze V1 → bounded implementation; subsequent
interface/invariant changes require a new version/addendum.

## Responsibility and exclusions

Deliver a due-date reminder for an explicitly opted-in recurring occurrence,
with visible outcome and recoverable ownership. Initial assignment emails,
course completion, invitations, evidence and statutory interpretations remain
with their existing owners. No LLM is involved.

R2a is one pre-deadline learner email; R2b will add overdue steps and explicit
manager escalation. This split does not declare the full planned R2 complete.
Manual/non-recurring assignments, historical backfill and automatic tenant-wide
activation are excluded. No new commercial email provider or billing resource.

## External interface and inputs/outputs

Proposed internal, tenant-scoped commands (not public unauthenticated APIs):

```text
enqueue(tenant_id, exact_course_or_path_occurrence) -> existing_or_new_id | no_op
claim(tenant_id, reminder_id) -> bounded_claim | none
finalize(tenant_id, reminder_id, claim_token, outcome_category) -> status
due(limit <= 100) -> opaque tenant/reminder pairs (recovery role only)
statuses(tenant_id, occurrence_ids <= 100) -> safe delivery metadata
```

Enable through existing methodologist-owned recurring rule command; default
disabled. Proposed lead time: 1 day before due, configurable integer 0–30 days.
Policy version, scheduled time and target are frozen when the occurrence is
materialized. Rule edits affect future occurrences only. Rule disabled later
suppresses still-unsent items; it does not erase prior history.

Input IDs require explicit tenant/object/learner consistency. Outputs include
status, attempt count, timestamps and category, never email bodies, invitation
tokens, provider credentials, document content or arbitrary error strings.

## Data ownership and migration packet

New `learning_reminder_outbox`, owned by reminder module; writes only through
bounded functions. Store id, tenant_id, one of course_occurrence_id /
path_cycle_instance_id, policy_version, step, channel, scheduled_at, status,
claim_token, claimed_at, next_attempt_at, attempt_count, first_attempt_at,
delivered_at, provider_message_id and allowlisted error_category.

Unique identity: tenant + typed occurrence + policy version + step + channel.
Exactly one occurrence FK is non-null. Recipient is resolved tenant-safely at
delivery, not stored as an email copy. Program reminder is per program cycle,
not one per constituent course. Enrollment links must identify the exact cycle.

Expand migration, root-owned, after rechecking the actual Alembic head:

1. Add disabled-by-default rule policy fields and validated bounds.
2. Add table/checks/FKs/partial unique indexes and due index; no backfill sending.
3. Enable/FORCE RLS; no PUBLIC access or unrestricted `lms_app` DML.
4. Add tenant-checked SECURITY DEFINER functions with fixed search_path and
   schema-qualified objects; claim uses SKIP LOCKED and an unforgeable token.
5. Grant only the necessary functions to `lms_app`; global bounded discovery
   only to existing `lms_recovery`. Enqueue rejects cross-tenant target links.
6. Extend canonical tenant purge safely; active claims block removal. No new
   automatic retention deletion. Reuse approved project retention policy; an
   altered retention period requires owner approval before activation.
7. Downgrade refuses to discard nonempty history. Runtime rollback disables
   scheduling/delivery and retains rows, rather than deleting them.

No migration file/revision is reserved by this draft. DEV DDL uses an approved
isolated schema and verified cleanup, not shared-schema experimentation.

## State machine, invariants and concurrency

| State/event | Next | Guard |
|---|---|---|
| opted-in occurrence materialized | queued | transactionally unique identity |
| due queued item | sending | exclusive bounded claim; eligible target |
| accepted provider result | sent | matching claim token |
| transient failure | queued | bounded backoff and attempt budget |
| no provider configuration | queued/deferred category | no attempt budget consumed |
| missing recipient/activation | failed | terminal visible category |
| completed/skipped/cancelled/inactive target | skipped | no send |
| stale claim inside safe retry window | queued | same message identity |
| ambiguous acceptance outside safe retry window | failed/manual_review | no blind resend |

Recheck tenant, learner access/status and occurrence completion/cancellation
immediately before sending. Do not claim absolute prevention of a cancellation
race after an external request has begun. Such timing must remain auditable.
Claim commits require re-establishing transaction-local tenant context.

Use a reminder-specific stable provider key, never an initial-assignment key.
Provider deduplication is time-bounded, not a promise of eternal exactly-once
delivery. Retry horizon must be checked against the actual provider contract
before activation. Expired reminders must be skipped, not delivered as stale
pre-deadline messages. Manual retry reuses identity and respects that horizon.

## Dependencies, impact and forbidden side effects

| Existing module | Planned change | Preserved invariant / check |
|---|---|---|
| learning_cycles models/schemas/router/service | opt-in + occurrence enqueue | existing scheduling and initial emails unchanged |
| reminder module, new | policy/store/tasks/status view | DB owns retry/dedup; synthetic adapter tests |
| core email | reminder renderer via existing send path | no new credential/config source; escaped titles |
| celery + broker-independent recovery | bounded reminder discovery | recovery works after broker loss |
| canonical purge/security tests | additive table coverage | tenant deletion/retention and runtime grants |

R1 reporting remains read-only. Inbox kind expansion, escalation recipients,
bulk resend, provider changes and scheduler deployment are not implicit scope.

## Verification and implementation packet

Root: schema, functions, materialization seam, recovery, integration/release.
Terra/medium: one disjoint renderer or policy/test module after contract freeze.
Luna/medium: independent review. English five-field handoffs; no worker external
access, credentials, Git/deploy or unlisted module edits.

Required gates: deterministic boundaries; opt-out/no backfill; double tick and
concurrent claim dedup; immutable snapshots; cancellation/completion suppression;
path not multiplied by courses; late recovery; provider-disabled/no-email states;
same provider key; ambiguous timeout beyond retry horizon; actual `lms_app`
cross-tenant read/enqueue/claim/finalize denial; purge/downgrade safeguards;
initial-assignment regressions; exact worker/timer and provider readback.

Safe observability: opaque IDs, categories, counts and timestamps only.
Local synthetic provider tests send nothing. Real pilot email needs explicit
recipient/tenant authorization. No production customer notifications as tests.

Ready requires frozen policy, retention mapping, write sets and isolated DEV
migration procedure. Done requires the full occurrence → ledger → recovery →
delivery/status chain, not merely a passing policy unit test or HTTP 200.
