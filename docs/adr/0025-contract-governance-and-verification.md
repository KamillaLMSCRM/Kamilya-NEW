# ADR-0025: Governance roles and executable contract verification

## Status

Accepted by the product owner on 2026-09-03.

## Supersedes

This decision amends, but does not delete or rewrite, ADR-0024. ADR-0024 remains
the historical decision for contract-first modular delivery; this ADR defines
the active V2 governance and verification requirements.

## Context

The V1 standard defined module ownership, versioned mini-specs, impact matrices,
contract tests and root-agent integration. It did not make four governance roles
explicit, did not identify the authorized approver and change-control procedure
inside every epic, and did not distinguish the mandatory mini-spec core from
conditional fields. It also needed a stronger requirement that contract tests
be executable at producer-consumer seams and that the post-change graph be
compared with the accepted module map.

## Decision

Every multi-block epic names a root owner, module owner for each changed module,
product owner and reviewer. One person may hold several roles, but each
responsibility and authority remains explicit.

Every epic records `Approved by`, the approval date and a change-control
procedure. Accepted contracts remain immutable; approved changes create a new
version or impact addendum.

Module mini-spec V2 separates mandatory core fields from conditionally mandatory
extended fields. `Not applicable` requires a reason.

Contract verification is an executable producer-consumer test against the same
interface used by the application. A project-native framework is preferred;
Pact, Spring Cloud Contract or an equivalent tool may be used when appropriate,
but no particular framework is required across all stacks.

After a stop condition, the root owner records the evidence and either approves
a versioned contract change or cancels the task with cleanup and rollback
obligations. Work may not resume through an undocumented exception.

After implementation, Graphify is updated and the resulting dependency graph is
compared with the expected module map. Unexpected edges require investigation
or an approved contract change before release.

## Active artifacts

- `docs/product/contract-modules/AGENT_INSTRUCTION_V2.md`
- `docs/product/contract-modules/templates/EPIC_CHAIN_SPEC_V2.md`
- `docs/product/contract-modules/templates/MODULE_MINI_SPEC_V2.md`

## Consequences

- Accountability is explicit without forcing separate people for every role.
- Small modules keep a short mandatory core while risk-driven sections remain
  compulsory when applicable.
- Contract-test evidence becomes tool-independent but executable.
- Stop conditions produce a decision instead of an indefinite partial task.
- Graph drift becomes a release-visible contract failure.
