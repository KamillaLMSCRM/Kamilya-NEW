# Contract-First Modular Engineering Addendum for Agents V1

**Status:** Accepted portable instruction
**Version:** V1
**Scope:** Any software project that uses code-graph-assisted engineering
**Purpose:** Increase delivery speed while preventing accidental cross-module
regressions, hidden redesigns and unrelated feature disablement.

This file is intentionally project-neutral. A project may reference it from its
own `AGENTS.md` or copy this version without changing its meaning. Project-local
instructions, security policies, data boundaries, owner approvals and platform
rules always take precedence.

V1 is immutable after acceptance. Create a new `V2` file with `Supersedes` and
`Reason` fields instead of silently rewriting this contract.

## 1. Operating model

For every multi-block product objective, work in this order:

```text
User-visible objective
  -> critical journeys and exclusions
  -> graph-scoped impact map
  -> deep module map
  -> versioned module mini-specs
  -> explicit implementation packets
  -> focused module verification
  -> seam contract verification
  -> assembled-chain verification
  -> full risk-based release verification
  -> exact production readback
```

Do not start by distributing pages, files, endpoints or tickets among agents.
First decide which module owns each business responsibility and state transition.

## 2. Relationship to graph engineering

The code graph is the navigation and impact-analysis layer. It is not runtime
truth, product authority or proof that behavior works.

Use the project's configured graph tool before broad source exploration:

1. Query the user objective and known domain terms.
2. Identify candidate owners of state, interfaces, callers and tests.
3. Find paths between the proposed module and authentication, authorization,
   persistence, background work, external providers and user interfaces.
4. Record directly connected modules in the impact matrix.
5. Verify graph findings against current source, schema, tests and project docs.
6. After code changes, update the graph using the project's code-only update
   procedure.
7. Compare the post-change graph with the accepted module map and investigate
   unexpected new edges.

If the graph is stale, missing or unavailable, report that condition explicitly.
Do not invent graph-derived conclusions. Follow the project's documented
fallback or stop rule.

Use these evidence distinctions:

```text
GRAPH-DERIVED: a candidate relationship found in the graph.
SOURCE-DERIVED: confirmed by current source or schema.
TEST-DERIVED: confirmed by an executed test.
RUNTIME-DERIVED: confirmed by current runtime evidence.
OWNER-CONFIRMED: explicitly decided by the authorized owner.
INFERRED: plausible but not yet verified.
NOT VERIFIED: verification was not performed or was unavailable.
BLOCKED: work cannot safely continue inside the current authority and scope.
```

## 3. Define the objective before modules

Create one versioned epic-chain specification containing:

- one observable user or business outcome;
- intended roles and authority;
- starting, intermediate and terminal states;
- success evidence;
- explicit exclusions;
- critical journeys;
- rollback or disable behavior;
- production acceptance boundaries.

A technology change is not a product objective. Replace statements such as
"add a worker" or "create an endpoint" with observable outcomes such as
"an authorized reviewer receives one reminder after the configured deadline."

## 4. Choose deep modules

A module is anything with one external interface and an implementation. It may
be a function, package, domain slice or tier-spanning capability.

A good module:

- owns one stable business responsibility;
- has one small interface callers can understand;
- hides meaningful policy and complexity;
- owns clearly identified state or produces a clear result;
- is naturally testable through the same interface callers use;
- can change internally without forcing unrelated callers to change.

Reject or merge a proposed module when it is only:

- a pass-through wrapper;
- one page or button with no distinct policy;
- one HTTP endpoint mirroring another layer;
- one background task that only calls a function;
- one channel-specific copy of shared recipient or scheduling rules;
- an abstraction created for a hypothetical second adapter.

Apply the deletion test: if deleting the proposed module merely removes a name
and leaves no concentrated complexity, the module is too shallow.

## 5. Required module mini-spec

Every new or materially changed module must have an accepted, versioned
mini-spec before implementation. It must define:

```text
Module identity and version
Responsibility
Non-responsibilities
User-visible contribution
External interface
Inputs and outputs
Data ownership
Invariants
State transitions
Idempotency and concurrency
Error modes
Dependencies and adapters
Forbidden dependencies
Security and privacy rules
Observability
Verification plan
Read scope
Write scope
Stop conditions
Rollout and rollback
Definition of Ready
Definition of Done
```

Implementation may be treated as a black box only after these facts are fixed.
"Black box" never means unknown side effects, unspecified failures or unclear
data ownership.

## 6. Interface rules

An interface includes more than a type signature. It includes:

- accepted inputs and validation;
- returned results and emitted events;
- ordering constraints;
- invariants;
- error classification;
- idempotency;
- expected performance;
- required configuration;
- authorization and tenancy rules;
- retry and timeout semantics.

Keep the interface smaller than the implementation. Prefer one operation that
encapsulates policy over many thin methods that expose internal steps.

Callers and tests must cross the same seam. If routine tests need to bypass the
interface and manipulate internals, reconsider the module shape.

## 7. Data ownership

Each mutable record, state machine and durable event must have exactly one
owning module.

Record for every data item:

```text
Owner
Authorized writers
Authorized readers
Tenant or account key
Retention rule
Deletion or revocation behavior
Migration owner
Audit requirements
```

Another module may consume an owner's interface or event. It must not write the
owner's tables directly unless the accepted contract explicitly assigns that
operation.

## 8. Directed dependencies

Draw a directed module map before implementation:

```text
Module A -> versioned command/event -> Module B -> result/event -> Module C
```

Business-policy modules may emit authorized intents. Delivery adapters execute
those intents. Adapters must not independently decide permissions, recipients,
deadlines, pricing, state transitions or escalation policy.

Explain any dependency cycle before accepting the design. Prefer restructuring
around an owner and emitted event rather than allowing modules to mutate each
other in both directions.

## 9. Existing-module impact matrix

The epic must classify every existing module that may be affected:

| Impact class | Meaning | Required action |
|---|---|---|
| None | No source, interface, invariant or data change | Negative-space check when risk justifies it |
| Consumer | New code only consumes a stable interface | New module mini-spec |
| Interface | Existing interface changes compatibly | Impact addendum and contract tests |
| Invariant | Existing business behavior changes | New version of the affected mini-spec |
| Ownership | Data or responsibility moves | Architecture decision and migration plan |

An unlisted module is forbidden scope.

If implementation reveals an unplanned cross-module dependency:

1. Stop editing the affected module.
2. Record the graph and source evidence.
3. Add or request an impact addendum.
4. Define compatibility and regression checks.
5. Update the permitted write scope.
6. Resume only after the root owner accepts the revised contract.

Do not hide the expansion inside a "small refactor."

## 10. Negative-space protection

Every impact matrix must state what is not allowed to change. Consider:

```text
Existing roles and capabilities
Authentication and session behavior
Tenant or account isolation
Canonical routes and redirects
Existing API contracts
Worker and queue registration
Schedulers and recovery timers
External provider configuration
Existing records and state machines
Billing and usage limits
Public pages and forms
Existing user journeys
Logging, audit and retention
```

Add proportional regression tests for high-risk unchanged behavior. A new
feature passing its own happy path does not prove that neighboring behavior
remained available.

## 11. Verification ladder for speed and quality

Use the smallest sufficient feedback loop at each stage.

### Stage A: edit loop

Run focused unit and module-interface tests for the changed behavior. Prefer
pure deterministic policy tests where possible.

Do not run the full repository suite after every small edit unless the project
has no reliable focused test boundary.

### Stage B: module completion

Run:

- all tests for the module interface;
- producer-consumer contract tests;
- persistence and authorization checks owned by the module;
- regression tests named by the impact matrix;
- static, type and formatting checks proportional to changed files.

### Stage C: chain assembly

Run integration tests across module seams and every critical journey defined by
the epic. Confirm terminal evidence, not only HTTP success.

### Stage D: release candidate

Run one full risk-based suite for the exact candidate, including applicable:

- build and type checks;
- migrations;
- tenant/account isolation;
- authorization and security gates;
- background task and queue registration;
- external-provider contract tests;
- rollback compatibility;
- secret scanning.

### Stage E: production acceptance

Independently confirm:

- exact deployed revision;
- expected schema revision;
- required processes and workers;
- bounded user-visible business flow;
- absence of unexpected errors;
- restoration or cleanup of synthetic test state.

A successful command, green deploy, HTTP 200 or agent report alone is not proof
of the complete product outcome.

## 12. Agent work packets

Each delegated agent receives a bounded packet containing:

```text
Objective
Accepted mini-spec version
Relevant graph subgraph
Interfaces it may consume
Read scope
Write scope
Forbidden scope
Expected tests
Stop conditions
Required handoff evidence
Language and reporting requirements
```

Prefer at most two concurrent agents unless the project owner explicitly allows
more. Use cheap agents for narrow inventories, isolated implementations,
fixtures and focused tests. Do not delegate the critical integration blocker,
final architecture ownership or release decision.

Avoid concurrent writers for:

- shared interfaces;
- migrations;
- authorization policy;
- route registries;
- common schemas;
- dependency manifests;
- release configuration;
- documentation indexes.

The root agent owns the combined diff, contract consistency, integration tests,
release packet and production readback. A subagent's report is not evidence until
the root verifies the relevant source or execution result.

## 13. Documentation versioning

Accepted design artifacts are immutable:

```text
EPIC_V1.md
MODULE_<ID>_V1.md
CONTRACT_<ID>_V1.md
IMPACT_ADDENDUM_<ID>_V1.md
```

When a decision changes, create a new file:

```text
Status: Accepted
Version: V2
Supersedes: <path to V1>
Reason: <verified reason for the change>
```

Keep the predecessor available and mark the active version in the epic's module
index. Do not preserve temporary logs, secrets, sensitive runtime payloads or
obsolete operational instructions as active design contracts.

## 14. Stop conditions

Stop implementation and return to the root owner when any of these occurs:

- an unlisted module must change;
- an accepted interface or invariant is insufficient;
- data ownership is ambiguous;
- graph and current source materially disagree;
- migration safety or rollback is undefined;
- required tenant/account isolation cannot be tested;
- a destructive, production, credential, privacy, billing or authority boundary
  exceeds the current approval;
- the same access, provider or infrastructure failure repeats according to the
  project's escalation rule;
- unexpected unrelated changes appear in the worktree;
- a critical test would need to be weakened or skipped to proceed.

Do not bypass the stop by guessing credentials, widening scope, disabling a
guard, replacing an environment or lowering a test expectation.

## 15. Completion report

Report completion in this order:

```text
CURRENT STATUS
OBJECTIVE ACHIEVED
MODULES CHANGED
INTERFACES CHANGED
EXISTING-MODULE IMPACT
NEGATIVE-SPACE RESULTS
FOCUSED TESTS
CONTRACT TESTS
CRITICAL JOURNEYS
FULL RELEASE GATES
DEPLOYED REVISION
PRODUCTION READBACK
RESIDUAL RISKS
ROLLBACK
```

Separate verified facts from inference. State skipped or unavailable checks as
`NOT VERIFIED`; do not silently convert them into success.

## 16. Compact execution checklist

Before implementation:

- [ ] Objective and exclusions are explicit.
- [ ] Graph query and source verification are complete.
- [ ] Deep module map is accepted.
- [ ] Data owners are explicit.
- [ ] Mini-spec versions are accepted.
- [ ] Impact matrix includes negative-space behavior.
- [ ] Agent read/write scopes are disjoint.

During implementation:

- [ ] Work remains inside the accepted interface and write scope.
- [ ] Focused tests provide rapid feedback.
- [ ] Unplanned impact stops editing before scope expansion.
- [ ] No neighboring module is silently redesigned or disabled.
- [ ] Graph is updated after source changes.

Before release:

- [ ] Module and contract tests pass.
- [ ] Impact-matrix regressions pass.
- [ ] Critical journeys pass.
- [ ] Full risk-based candidate gates pass.
- [ ] Rollback and stop conditions remain valid.
- [ ] Production authorization is current and exact where required.

After release:

- [ ] Exact revision is independently confirmed.
- [ ] User-visible production flow is confirmed.
- [ ] Synthetic state is restored or safely retained by design.
- [ ] Active document versions are indexed.
- [ ] Residual risks are explicit.
