# EPIC RECURRENCE-COMPLETION-01 V1

Status: Accepted  
Approved by: Kamilya owner, 2026-09-29  
Change control: root proposes versioned addenda; material product or production
scope changes require owner approval.

## Observable outcome

A methodologist can see every repeated learning occurrence, distinguish the
original and effective deadline, and apply a reasoned learner-specific deadline
override. Completion, attempts, certificates and exports remain bound to the
exact enrollment occurrence. Support impersonation preserves tenant integrity
and platform-operator audit identity.

## Critical journeys

1. A course/program recurrence materializes once, freezes its target and
   original dates, and produces enrollment-scoped evidence.
2. A methodologist extends or shortens an active participant deadline; the
   original deadline remains visible, an append-only event records actor/reason,
   training log and cycle UI show the effective deadline, and only an unsent
   reminder is rescheduled.
3. A competing completed enrollment cannot be used for a program certificate.
4. Tenant B cannot read or mutate tenant A occurrence/events.
5. An impersonated platform operator writes no platform UUID into tenant-owned
   author fields, while the tenant audit event names the real operator.

## Module map

```text
source-actuality router -> tenant domain actor + platform audit actor
learning-cycle occurrence -> participant deadline command -> append-only event
participant deadline projection -> training log / cycle UI / reminder schedule
learning-path certificate -> exact learning-path assignment enrollment
```

## Negative space

Do not change role contracts, login/session behavior, existing occurrence IDs,
completion semantics, attempt limits, certificate history, source publication,
assignment rules, notification channels, provider configuration or billing.
SCORM recurrence stays unsupported.

## Success evidence

Focused public-seam tests, migration/RLS tests, producer-consumer contract tests,
one assembled synthetic course and program cycle, exact DEV/production runtime
identity, worker/task registration and a cleaned synthetic production journey.
