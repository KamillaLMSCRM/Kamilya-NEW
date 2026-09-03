# ADR-0024: Contract-first modular delivery

## Status

Accepted by the product owner on 2026-09-03.

## Context

Kamilya product goals commonly span domain state, API, background work, email,
in-app UI, tenant isolation, migrations and production operations. Implementing
such a goal as one large task slows feedback and lets incidental changes in a
shared module disable an unrelated route, role, queue or workflow. Splitting it
only by files, pages or endpoints creates shallow modules and duplicates policy.

The owner prioritizes delivery speed without losing quality. A completed module
must therefore be independently specifiable and testable, while the assembled
chain must still have critical-journey and production evidence.

## Decision

Kamilya uses contract-first modular delivery for multi-block product goals.
The default runtime shape remains a modular monolith. A module is separated by
a stable business responsibility and a small interface, not automatically by a
process, repository, page, endpoint, worker or deployment.

Each epic has:

1. one versioned EPIC chain specification;
2. a module map and directed dependency graph;
3. one versioned mini-spec for every new or materially changed module;
4. an impact matrix for existing modules;
5. contract tests at seams;
6. critical-journey tests for the assembled goal;
7. release and independent production readback gates appropriate to risk.

Implementation may remain opaque to callers only after the module interface,
data ownership, invariants, side effects, error modes, idempotency, performance
constraints and security rules are explicit. The interface is also the primary
test surface.

## Module depth

A module should hide meaningful policy behind a small interface. A proposed
module is rejected or merged into its owner when deleting it would remove only
a pass-through wrapper and leave no concentrated complexity.

UI pages, HTTP routes and Celery tasks are delivery mechanisms unless they own
distinct business policy. Channel adapters deliver an already-authorized intent
and do not decide recipients, deadlines, escalation or permissions.

## Change isolation

Every implementation packet has an explicit read scope, write scope and
forbidden scope. A discovered need to change a neighboring module is not an
implicit expansion of authority.

Before changing a neighboring module, the root orchestrator adds an impact
addendum describing:

- the existing interface or invariant being changed;
- compatibility and migration behavior;
- affected callers and data;
- regression risks;
- focused and integration checks;
- rollback or disable behavior.

Shared contracts, migrations, common authorization, route registries and worker
routing remain root-owned unless explicitly delegated.

## Verification ladder

Feedback is optimized without weakening release evidence:

1. edit loop: focused unit and module-interface tests;
2. module completion: contract tests and proportional neighbor regression;
3. chain assembly: integration and critical-journey tests;
4. release candidate: full risk-based suite, migrations, RLS/security and build;
5. production: exact revision readback and a bounded business-flow smoke.

A full suite is not used as the default edit loop. Focused tests alone never
authorize release. Each impact matrix includes negative-space assertions for
existing roles, routes, workers, queues, settings and journeys that must not be
disabled or redirected.

## Version retention

Accepted EPIC, module mini-spec, contract and impact-addendum files are immutable
records. A changed contract creates a new versioned file or an additive,
versioned addendum. The new document names the predecessor with `Supersedes`,
and the epic index identifies the active version.

Older accepted versions remain in the repository so the product can compare or
return to an earlier design. This does not preserve temporary execution logs,
generated evidence containing sensitive data, local secrets or obsolete
operational instructions as active documentation.

## Agent model

No more than two subagents work concurrently by default. Cheap agents are used
for narrow module implementation, inventories and focused tests. The root
orchestrator owns module boundaries, shared contracts, integration, final diff,
release and production readback. Subagent reports are inputs, not evidence.

## Canonical templates

- `docs/product/contract-modules/templates/EPIC_CHAIN_SPEC_V1.md`
- `docs/product/contract-modules/templates/MODULE_MINI_SPEC_V1.md`

Template V1 is frozen after acceptance. Future changes create V2 rather than
rewriting V1.

## Consequences

- Agents receive smaller, safer packets with measurable completion criteria.
- Most failures surface in focused contract tests before full integration.
- Cross-module changes become visible before implementation.
- The repository gains more design artifacts, but accepted versions remain
  compact and reusable.
- Cross-module integration remains an explicit root responsibility and cannot be
  declared complete from isolated module tests.

## Rejected alternatives

- One large feature task: fast to start, slow to debug and unsafe for shared
  modules.
- One module per page, endpoint or notification type: shallow interfaces and
  duplicated policy.
- Separate microservice per block: unnecessary deployment and operational cost
  at the current scale.
- Full suite after every edit: slow feedback without replacing contract design.
- Focused tests only: does not prove the assembled business chain.

## Related decisions

- [ADR-0021](0021-course-assignment-notification-outbox.md): durable email outbox.
- [ADR-0023](0023-render-like-kz-release-plane.md): KZ production release plane.
