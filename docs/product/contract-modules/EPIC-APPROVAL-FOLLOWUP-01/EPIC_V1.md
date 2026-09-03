# EPIC-APPROVAL-FOLLOWUP-01: approval follow-up V1

## Identity and governance

| Field | Value |
|---|---|
| Status | Accepted |
| Document / template version | V1 / V2 |
| Root owner | Codex root agent: architecture, integration, release, readback |
| Product owner | Kamilya product owner |
| Approved by | Kamilya product owner, 2026-09-03 |
| Module owners | Backend agent; frontend agent; root integrates shared files |
| Reviewer | Independent cheap agent or root contract review |
| Supersedes | None |
| Change control | Evidence -> V2 or impact addendum -> root review -> product-owner approval for business/invariant/production change; otherwise cancel with cleanup |

## User-visible objective

An assigned approver and the requesting methodologist see actionable course
approval follow-up in Kamilya. The approver receives deadline email reminders
without a repeated PIN. Due, overdue and terminal states do not create duplicate
or stale actions.

## Success evidence

- Internal assignment creates one durable in-app notification.
- The bell shows a real unread count, never a static marker.
- Read state belongs only to the recipient and does not alter workflow state.
- Reminder email contains an action URL but no PIN or replacement secret.
- Overdue escalation reaches the requesting methodologist, not an address copied
  from the reviewer's invitation.
- Repeated recovery is idempotent; terminal work is suppressed.
- A crashed worker cannot strand an accepted delivery: an expired claim lease
  is recovered, while an exhausted lease is classified terminally.
- Existing learner assignment notifications and approval decisions are unchanged.

## Explicit exclusions

Route templates, multi-stage approval, automatic reviewer selection, push/SMS/
Telegram/websockets, provider-plan changes, reminder credential rotation, a new
event bus or microservice, and redesign of learner assignments, certificates,
training evidence or roles.

## States and critical journeys

```text
delivery: queued -> accepted(leased) -> delivered | failed -> accepted | terminal
inbox: unread -> read
deadline: unset | scheduled -> due -> overdue -> closed
outcome: pending -> approved | changes_requested | cancelled | superseded
```

| ID | Start/action | Terminal evidence |
|---|---|---|
| CJ-01 | Internal reviewer assigned; opens bell item | One inbox row; count decrements; safe request route opens |
| CJ-02 | Pending work reaches reminder threshold twice | One reminder per channel/rule; email has URL and no PIN |
| CJ-03 | Pending work becomes overdue twice | Reviewer sees overdue; requester gets one escalation |
| CJ-04 | Work decided/cancelled before threshold | No new actionable follow-up |
| CJ-05 | Tenant A accesses tenant B notification ID | 404/non-disclosure; no mutation |
| CJ-06 | Existing learner assignment worker runs | Existing outbox contract remains green |

Email delivery never means opened, started, completed or approved. Inbox read
state never changes approval outcome.

## Directed module map

```text
course_approval -> WorkflowDelivery(message_kind V1)
  -> approval-followup-delivery
       -> WorkflowNotificationIntentV1 -> notification-inbox
       -> ApprovalFollowupEmailV1 -> EmailService

TopBar -> NotificationInboxHttpV1 -> notification-inbox
```

Expected graph has no dependency from `notification-inbox` to `course_approval`,
email providers, enrollment or certificate modules.

## Modules and contracts

| Module | Active mini-spec | Data owner |
|---|---|---|
| Approval follow-up delivery | `modules/APPROVAL_FOLLOWUP_DELIVERY_V1.md` | Existing approval delivery/reminder/escalation rows |
| Notification inbox | `modules/NOTIFICATION_INBOX_V1.md` | New tenant/user inbox rows and read state |
| Notification center UI | `modules/NOTIFICATION_CENTER_UI_V1.md` | No durable data |

| Contract | Producer -> consumer | Compatibility |
|---|---|---|
| `WorkflowNotificationIntentV1` | Follow-up delivery -> inbox | Additive kinds only; no secrets |
| `NotificationInboxHttpV1` | Inbox -> UI | Additive fields only |
| `ApprovalFollowupEmailV1` | Follow-up delivery -> EmailService | Reminder/escalation signature cannot accept PIN |

## Existing-module impact matrix

| Existing module | Impact | Allowed change | Must remain unchanged |
|---|---|---|---|
| `course_approval.models` | Interface | Typed delivery message kind | Request/reviewer/work-item states |
| `course_approval.service` | Invariant | Correct reminder/escalation recipients | Request creation and one-time credentials |
| `course_approval.notification_tasks` | Invariant | Safe follow-up materialization | Claim/retry bounds and task names |
| `core.email.EmailService` | Interface | PIN-free follow-up methods | Invitation and learner emails |
| `main.py` / registry | Interface | Register inbox module | Existing routers/models |
| `TopBar` | Interface | Real notification state | Role/auth/support/language behavior |
| RU/KK/EN locales | Interface | Equal notification keys | Existing keys |
| Learner outboxes, roles, providers, billing | None | None | All existing behavior/configuration |

An unlisted module is forbidden scope.

## Data, security and migration

- Add projection revision `0150` after `0149` and additive hardening revision
  `0151`; never rewrite an already applied migration.
- Add constrained `message_kind` to workflow deliveries, default `invitation`.
- Add inbox rows keyed by tenant, recipient and unique source delivery, with safe
  JSON context, allowlisted relative action path, `read_at` and timestamps.
- Apply RLS, FORCE RLS, tenant integrity, recipient-scoped `app.user_id`, runtime
  grants and database checks for the exact safe context/path allowlists.
- Server derives tenant/recipient. No PIN, token, encrypted payload, answer key,
  arbitrary HTML or external URL enters inbox context or logs.

## Verification

| Level | Required evidence |
|---|---|
| Focused | Delivery policy, inbox, TopBar and locale tests |
| Contract | Actual EmailService arguments and notification HTTP DTO tests |
| Database | Remote DEV Supabase `0151`, FORCE RLS, cross-tenant/cross-user, trigger and unsafe-payload tests |
| Neighbor | Existing learner outbox, approval credential, auth and queue tests |
| Integration | CJ-01 through CJ-05 on DEV |
| Release | CI, build, migration, worker registration and graph comparison |
| Production | Exact web/API/schema/worker revisions and bounded synthetic smoke |

Project-native pytest/Vitest contracts are selected. Pact or Spring Cloud
Contract is unnecessary for two in-repository consumers in this modular
monolith, but remains allowed if deployment boundaries later justify it.

## Agent allocation

Maximum two concurrent cheap agents; all agent communication is English.
Backend owns approval/email/inbox/migration tests. Frontend owns client/TopBar/
locales/tests. Root owns contracts, shared registration, integration and release.

## Rollout, rollback and stop conditions

Order: contracts -> focused tests -> additive DEV migration -> DEV API/worker ->
web preview -> critical journeys -> production migration/API/worker -> web ->
readback. The existing approval kill switch remains the emergency behavior gate.

Stop on unlisted dependency, ambiguous recipient, untestable RLS, provider or
billing mutation, secret exposure, unrelated worktree change or negative-space
regression. Root records evidence and either accepts V2/addendum or cancels with
cleanup; no silent exception.

## Ready and done

Ready: roles, approval, change control, seams, owners, expected graph, impact and
tests are explicit. Done: focused/contract/RLS/neighbor tests pass; Graphify
matches the module map; DEV critical journeys pass without Docker/local DB; exact
production revisions and bounded flow are read back; synthetic state is closed.
