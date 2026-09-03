# Contract-first modular delivery

**Active standard:** V2
**Decisions:** [ADR-0024](../../adr/0024-contract-first-modular-delivery.md), [ADR-0025](../../adr/0025-contract-governance-and-verification.md)

This directory is the operating standard for decomposing one product objective
into independently implementable modules and assembling them into one verified
business chain.

## Required artifacts

For a multi-block product goal create a dedicated epic directory containing the
epic's own versioned artifacts. New epic documents start at V1, while their
structure must follow the active V2 templates:

```text
<epic-id>/
  EPIC_V1.md
  MODULE_INDEX.md
  modules/
    <module-id>_V1.md
  contracts/
    <contract-id>_V1.md
  acceptance/
    CRITICAL_JOURNEYS_V1.md
```

Use fewer files when the interfaces fit clearly inside the epic contract. Do
not create documents that merely repeat code or each other. If an accepted epic
contract changes, create `EPIC_V2.md` or a versioned addendum and keep V1.

## Sequence

1. State the user-visible outcome and exclusions.
2. Define the end-to-end states and critical journeys.
3. Draw a directed module map.
4. Assign data ownership and one external interface per module.
5. Record existing-module impact and negative-space protections.
6. Name root owner, module owners, product owner, reviewer, Approved by and change control.
7. Freeze the mini-spec version before implementation starts.
8. Implement modules through disjoint write sets where possible.
9. Run focused tests during the edit loop.
10. Run seam contracts when each module is complete.
11. Assemble and test the whole chain.
12. Run the full risk-based release suite once for the candidate.
13. Deploy and independently read back the exact production revision and flow.

## Change classes

| Class | Meaning | Required document |
|---|---|---|
| Consumer only | New code consumes an existing stable interface | New module mini-spec |
| Interface extension | Existing interface receives compatible behavior | New mini-spec plus impact addendum |
| Invariant change | Existing business rule or state transition changes | New version of the affected module mini-spec |
| Ownership change | Data or responsibility moves between modules | ADR or ADR amendment plus migration plan |

## Speed controls

- Keep the edit loop focused on the changed module.
- Prefer pure policy tests before database or browser tests.
- Use contract fixtures instead of starting the full application for every test.
- Reuse approved synthetic tenant fixtures instead of rebuilding customer-like
  data.
- Run neighboring regressions only when the impact matrix says they are touched.
- Run one full suite for the release candidate, not after every local edit.
- Stop an agent at the first unplanned cross-module change and revise the
  contract before continuing.
- Keep at most two subagents active concurrently by default.

## Quality controls

- Every state-changing command is idempotent or explicitly non-repeatable.
- Every tenant-scoped mutation has server-owned tenant context, ownership checks,
  RLS, FORCE RLS and cross-tenant tests.
- Every asynchronous action has durable ownership, retry semantics and terminal
  states.
- Every critical business chain has at least one end-to-end acceptance scenario.
- Every impact matrix names what must remain unchanged.
- HTTP success, deployment success and an agent report are not sufficient
  production evidence without exact-revision and business-flow readback.

## Versioning

Accepted files are frozen. Create `V2` or a versioned addendum and set:

```text
Status: Accepted
Supersedes: <relative path to V1>
Reason: <why the contract changed>
```

Do not delete or rewrite the accepted predecessor. `MODULE_INDEX.md` identifies
which version is active. Drafts may be replaced before acceptance when they have
never governed implementation.

## Templates

- [Portable agent instruction V2, active](AGENT_INSTRUCTION_V2.md)
- [EPIC chain specification V2, active](templates/EPIC_CHAIN_SPEC_V2.md)
- [Module mini-spec V2, active](templates/MODULE_MINI_SPEC_V2.md)
- [Portable agent instruction V1, preserved](AGENT_INSTRUCTION_V1.md)
- [EPIC chain specification V1, preserved](templates/EPIC_CHAIN_SPEC_V1.md)
- [Module mini-spec V1, preserved](templates/MODULE_MINI_SPEC_V1.md)
