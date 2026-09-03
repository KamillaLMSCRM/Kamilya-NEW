# Module mini-spec V2

> Copy this template to `<epic-id>/modules/<module-id>_V1.md` for a new module.
> Template V2 supersedes template V1; module document versions start independently.

## Identity

| Field | Value |
|---|---|
| Module ID | `<MODULE-ID>` |
| Name | `<name>` |
| Status | Draft / Accepted / Superseded |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | `<root/product authority>` |
| Change control | `<proposal -> review -> approval -> supersede/cancel>` |
| Owning epic | `<EPIC-ID>` |

## Field classification

Every section marked **Core** is mandatory. Every section marked **Extended**
is mandatory when its stated condition applies; otherwise write `Not applicable`
with a reason. Blank mandatory sections keep the module in Draft.

## Responsibility [Core]

State the business policy concentrated inside this module.

## Non-responsibilities [Core]

State what remains owned by other modules. Include delivery mechanisms that must
not make business decisions.

## User-visible contribution [Core]

Describe the part of the epic outcome supplied by this module.

## External interface [Core]

Define the smallest interface callers and tests must understand. Include input,
output, ordering, performance and configuration obligations.

```text
<operation>(<input>) -> <result>
```

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | `<command/event>` | V1 | `<rules>` | `<none/list>` |
| Output | `<result/event>` | V1 | `<rules>` | `<none/list>` |

## Data ownership [Core]

| Data | Owner | Writer | Readers | Retention |
|---|---|---|---|---|
| `<table/state>` | `<module>` | `<module>` | `<modules>` | `<rule>` |

State tenant key, RLS/FORCE RLS and ownership validation for every tenant-scoped
record.

## Invariants [Core]

List facts that must remain true after success, failure, retry and cancellation.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| `<state>` | `<input>` | `<state>` | `<condition>` | `<effect>` |

## Idempotency and concurrency [Extended when applicable]

Define deduplication key, locking/claim behavior, retry window and the result of
processing the same command twice.

## Error modes [Core]

| Error | Permanent/transient | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| `<error>` | `<class>` | `<behavior>` | `<rule>` | `<evidence>` |

## Dependencies and adapters [Extended when applicable]

| Dependency | Interface used | Why needed | Test adapter |
|---|---|---|---|
| `<module/provider>` | `<interface>` | `<reason>` | `<fake>` |

Do not introduce a seam for a hypothetical second adapter. Record direct
dependencies that are intentionally internal.

## Forbidden dependencies and side effects [Extended when applicable]

List modules, tables, providers, credentials, routes and state transitions this
module must not access or mutate.

## Existing-module impact addendum [Extended when applicable]

Use this section only when the implementation changes an existing module.

| Affected module | Existing contract | Change | Compatibility | Regression test |
|---|---|---|---|---|
| `<module>` | `<contract>` | `<change>` | `<rule>` | `<test>` |

If implementation discovers an unlisted impact, stop and version this mini-spec
before changing the affected module.

## Security and privacy [Core]

Specify role checks, tenant context, object ownership, secret handling, PII,
logging, audit and rate limits.

## Observability [Extended when applicable]

Specify safe metrics, terminal states and diagnostic identifiers. Do not include
application payloads, secrets or raw PII.

## Verification [Core]

| Level | Scenario | Test/evidence | Required result |
|---|---|---|---|
| Unit | Policy | `<test>` | PASS |
| Interface | Public seam | `<test>` | PASS |
| Contract | Producer/consumer | `<executable project-native test; Pact/Spring Cloud Contract when appropriate>` | PASS |
| Database | Ownership/RLS | `<test>` | PASS |
| Neighbor | Negative space | `<test>` | PASS |
| Integration | Epic chain | `<test>` | PASS |

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | `<paths>` |
| Write scope | `<paths>` |
| Forbidden scope | `<paths/actions>` |
| Required checks | `<commands>` |
| Stop conditions | `<conditions>` |
| Handoff evidence | `<format>` |

## Rollout and rollback [Extended when applicable]

Describe migration ordering, compatibility window, feature enablement, exact
readback and how to disable behavior without data loss.

## Definition of Ready [Core]

- Responsibility and non-responsibilities are explicit.
- External interface and data ownership are accepted.
- Invariants, errors and idempotency are testable.
- Existing-module impact is complete.
- Write scope and stop conditions are assigned.
- Root owner, module owner, product owner, reviewer and approval authority are named.
- Expected module map is recorded for post-change Graphify comparison.

## Definition of Done [Core]

- Implementation satisfies the accepted interface.
- Focused, contract and affected-neighbor tests pass.
- No forbidden dependency or unplanned file change exists.
- Epic critical journey passes after integration.
- Documentation points to the active version without deleting the predecessor.
- Updated graph is compared with the accepted module map; unexpected edges are resolved through change control.
