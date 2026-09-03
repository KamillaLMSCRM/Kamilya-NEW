# EPIC chain specification V1

> Copy this file to `<epic-id>/EPIC_V1.md`. Do not edit this accepted template.

## Identity

| Field | Value |
|---|---|
| Epic ID | `<EPIC-ID>` |
| Status | Draft / Accepted / Superseded |
| Owner | `<owner>` |
| Version | V1 |
| Supersedes | None |
| Decision date | `<YYYY-MM-DD>` |

## User-visible objective

Describe one observable business outcome. Do not describe implementation.

## Success evidence

List the facts that prove the objective is achieved for the intended role and
tenant.

## Explicit exclusions

List behavior intentionally deferred so agents cannot silently expand scope.

## Roles and authority

| Role | Allowed actions | Forbidden actions |
|---|---|---|
| `<role>` | `<actions>` | `<actions>` |

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
| Contract | Seam | `<test>` | PASS |
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
that stop implementation or deployment.

## Definition of Ready

- Objective, exclusions and roles are explicit.
- Module seams, interfaces and data owners are explicit.
- Impact matrix and negative-space checks are accepted.
- Mini-specs and contract versions are frozen.
- Write scopes and verification commands are assigned.

## Definition of Done

- Module, contract and neighbor regression checks pass.
- Critical journeys pass in the approved environment.
- Migrations and security gates pass where applicable.
- Exact release revision is independently read back.
- Production business-flow smoke passes without unapproved customer mutation.
- Active document versions and user-facing documentation are updated.
