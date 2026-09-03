# EPIC chain specification V2

> Copy this template to `<epic-id>/EPIC_V1.md` for a new epic. Template V2
> supersedes template V1; document versioning for each epic starts independently.

## Identity

| Field | Value |
|---|---|
| Epic ID | `<EPIC-ID>` |
| Status | Draft / Accepted / Superseded |
| Root owner | `<name/agent and authority>` |
| Product owner | `<authorized product owner>` |
| Approved by | `<name/role>` |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Reason | Initial epic contract |
| Decision date | `<YYYY-MM-DD>` |
| Change control procedure | `<proposal -> review -> approval -> supersede/cancel>` |

## User-visible objective

Describe one observable business outcome. Do not describe implementation.

## Success evidence

List the facts that prove the objective is achieved for the intended role and
tenant.

## Explicit exclusions

List behavior intentionally deferred so agents cannot silently expand scope.

## Roles and authority

| Role | Named owner | Accountable for | Allowed decisions | Forbidden actions |
|---|---|---|---|---|
| Root owner | `<name/agent>` | Module map, combined change, stop decisions, release evidence | `<authority>` | Silent scope expansion |
| Module owner | `<name/agent per module>` | Mini-spec, module implementation and evidence | Internal choices preserving contract | Neighbor/shared-contract changes |
| Product owner | `<name/role>` | Objective, exclusions, business rules, acceptance | Material business and production decisions | Implicit or ambient authorization |
| Reviewer | `<name/agent>` | Independent contract and regression review | Review disposition if assigned | Rewrite scope during review |

## End-to-end states

```text
<state> -> <state> -> <terminal state>
```

Document allowed transitions, terminal states and recovery transitions.

## Critical journeys

| ID | Starting state | Action | Expected terminal evidence |
|---|---|---|---|
| CJ-01 | `<state>` | `<action>` | `<evidence>` |

## Module map

```text
<module> -> <contract/event> -> <module>
```

Dependencies must be directed. Explain any apparent cycle before accepting the
specification.

## Module index

| Module ID | Responsibility | Active mini-spec | Data owner | Writer |
|---|---|---|---|---|
| `<id>` | `<responsibility>` | `<path>` | `<tables/state>` | `<owner>` |

## Interface contracts

| Contract ID | Producer | Consumer | Version | Compatibility rule |
|---|---|---|---|---|
| `<id>` | `<module>` | `<module>` | V1 | `<rule>` |

## Existing-module impact matrix

| Existing module | Impact class | Planned change | Must remain unchanged | Regression check |
|---|---|---|---|---|
| `<module>` | None / Consumer / Interface / Invariant / Ownership | `<change>` | `<negative space>` | `<test>` |

An unlisted module is forbidden scope. Add an impact addendum before changing
it.

## Data and migration plan

Describe new data, ownership, retention, tenant isolation, migration ordering,
expand compatibility and rollback behavior.

## Security and privacy invariants

List authorization, tenant, secret, PII, credential and audit requirements.

## Verification plan

| Level | Scope | Command or evidence | Required result |
|---|---|---|---|
| Focused | Module | `<test>` | PASS |
| Contract | Seam | `<executable producer-consumer test; project-native, Pact/Spring Cloud Contract when appropriate>` | PASS |
| Neighbor regression | Impact matrix | `<test>` | PASS |
| Integration | Chain | `<test>` | PASS |
| Release | Candidate | `<gate>` | PASS |
| Production | Exact revision and flow | `<readback>` | PASS |

## Agent allocation

| Agent | Read scope | Write scope | Forbidden scope | Completion packet |
|---|---|---|---|---|
| `<agent>` | `<paths>` | `<paths>` | `<paths/actions>` | `<tests/evidence>` |

Do not assign more than two concurrent subagents by default. Shared contracts,
migrations and integration are root-owned unless explicitly delegated.

## Rollout and stop conditions

State release order, feature flags, rollback, cleanup and the exact conditions
that stop implementation or deployment. For each stop, root owner records evidence
and either approves a versioned contract change or cancels the task with cleanup.

## Definition of Ready

- Objective, exclusions and roles are explicit.
- Module seams, interfaces and data owners are explicit.
- Root owner, module owner, product owner, reviewer, Approved by and change control are explicit.
- Impact matrix and negative-space checks are accepted.
- Mini-specs and contract versions are frozen.
- Write scopes and verification commands are assigned.
- Expected module map is recorded for post-change Graphify comparison.

## Definition of Done

- Module, contract and neighbor regression checks pass.
- Critical journeys pass in the approved environment.
- Migrations and security gates pass where applicable.
- Exact release revision is independently read back.
- Production business-flow smoke passes without unapproved customer mutation.
- Active document versions and user-facing documentation are updated.
