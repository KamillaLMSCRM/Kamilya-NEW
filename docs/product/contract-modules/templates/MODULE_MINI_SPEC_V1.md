# Module mini-spec V1

> Copy this file to `<epic-id>/modules/<module-id>_V1.md`. Do not edit this
> accepted template.

## Identity

| Field | Value |
|---|---|
| Module ID | `<MODULE-ID>` |
| Name | `<name>` |
| Status | Draft / Accepted / Superseded |
| Version | V1 |
| Supersedes | None |
| Owning epic | `<EPIC-ID>` |

## Responsibility

State the business policy concentrated inside this module.

## Non-responsibilities

State what remains owned by other modules. Include delivery mechanisms that must
not make business decisions.

## User-visible contribution

Describe the part of the epic outcome supplied by this module.

## External interface

Define the smallest interface callers and tests must understand. Include input,
output, ordering, performance and configuration obligations.

```text
<operation>(<input>) -> <result>
```

## Inputs and outputs

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | `<command/event>` | V1 | `<rules>` | `<none/list>` |
| Output | `<result/event>` | V1 | `<rules>` | `<none/list>` |

## Data ownership

| Data | Owner | Writer | Readers | Retention |
|---|---|---|---|---|
| `<table/state>` | `<module>` | `<module>` | `<modules>` | `<rule>` |

State tenant key, RLS/FORCE RLS and ownership validation for every tenant-scoped
record.

## Invariants

List facts that must remain true after success, failure, retry and cancellation.

## State machine

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| `<state>` | `<input>` | `<state>` | `<condition>` | `<effect>` |

## Idempotency and concurrency

Define deduplication key, locking/claim behavior, retry window and the result of
processing the same command twice.

## Error modes

| Error | Permanent/transient | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| `<error>` | `<class>` | `<behavior>` | `<rule>` | `<evidence>` |

## Dependencies and adapters

| Dependency | Interface used | Why needed | Test adapter |
|---|---|---|---|
| `<module/provider>` | `<interface>` | `<reason>` | `<fake>` |

Do not introduce a seam for a hypothetical second adapter. Record direct
dependencies that are intentionally internal.

## Forbidden dependencies and side effects

List modules, tables, providers, credentials, routes and state transitions this
module must not access or mutate.

## Existing-module impact addendum

Use this section only when the implementation changes an existing module.

| Affected module | Existing contract | Change | Compatibility | Regression test |
|---|---|---|---|---|
| `<module>` | `<contract>` | `<change>` | `<rule>` | `<test>` |

If implementation discovers an unlisted impact, stop and version this mini-spec
before changing the affected module.

## Security and privacy

Specify role checks, tenant context, object ownership, secret handling, PII,
logging, audit and rate limits.

## Observability

Specify safe metrics, terminal states and diagnostic identifiers. Do not include
application payloads, secrets or raw PII.

## Verification

| Level | Scenario | Test/evidence | Required result |
|---|---|---|---|
| Unit | Policy | `<test>` | PASS |
| Interface | Public seam | `<test>` | PASS |
| Contract | Producer/consumer | `<test>` | PASS |
| Database | Ownership/RLS | `<test>` | PASS |
| Neighbor | Negative space | `<test>` | PASS |
| Integration | Epic chain | `<test>` | PASS |

## Implementation packet

| Field | Value |
|---|---|
| Read scope | `<paths>` |
| Write scope | `<paths>` |
| Forbidden scope | `<paths/actions>` |
| Required checks | `<commands>` |
| Stop conditions | `<conditions>` |
| Handoff evidence | `<format>` |

## Rollout and rollback

Describe migration ordering, compatibility window, feature enablement, exact
readback and how to disable behavior without data loss.

## Definition of Ready

- Responsibility and non-responsibilities are explicit.
- External interface and data ownership are accepted.
- Invariants, errors and idempotency are testable.
- Existing-module impact is complete.
- Write scope and stop conditions are assigned.

## Definition of Done

- Implementation satisfies the accepted interface.
- Focused, contract and affected-neighbor tests pass.
- No forbidden dependency or unplanned file change exists.
- Epic critical journey passes after integration.
- Documentation points to the active version without deleting the predecessor.
