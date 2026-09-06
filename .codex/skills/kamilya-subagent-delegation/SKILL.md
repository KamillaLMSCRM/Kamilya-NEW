---
name: kamilya-subagent-delegation
description: Plan, dispatch, and accept bounded Kamilya subagent work with minimal context, one-writer ownership, secret-safe isolation, and evidence-based handoff. Use when delegation or parallel review materially helps; not to offload an immediate root blocker, grant external authority, or treat an agent report as proof.
---

# Kamilya Subagent Delegation

Delegate only a concrete, isolated sidecar whose outcome the root can review.
This skill refines current project instructions; it never overrides scope, authority,
secrets/PII, Git, Graphify, testing, or approval rules.

## Choose and scope the work

Keep the immediate critical path, ambiguous authority/data boundaries, integration,
and owner judgement at root. Delegate a self-contained inventory, focused review,
disjoint-path implementation, repeatable classification, or synthetic evaluation
only when its benefit exceeds packet and acceptance cost. Do not delegate merely to
look parallel.

Use the narrowest profile:

- `READ_ONLY_WORKER`: named sources/fixtures only; no edits, external systems, or
  artifacts unless specifically allowed.
- `BOUNDED_WRITER`: owns explicit non-overlapping paths; uses `apply_patch` only
  there and runs only named checks; never commits, pushes, deploys, publishes, or
  mutates external systems.
- `INDEPENDENT_REVIEWER`: read-only; reports severity-ranked findings and readiness,
  without silently fixing the work.
- `SYNTHETIC_EVALUATOR`: isolated synthetic inputs only; no real PII/tenant data,
  network, provider, production, database, or unrelated files.

One person must not write and perform the final independent review of the same
artifact. Agents are leaf workers by default. Root may use at most two concurrent
leaf workers, and only with disjoint scopes and independent dependencies. For
external access or nested delegation, read [rare delegation procedures](references/rare-delegation-procedures.md)
before dispatching; neither is implied by this skill.

## Route model, context, and ownership

For this owner’s subscription workflow, Astra is the root product-development
orchestrator for decomposition, contracts, difficult diagnosis, integration, and
acceptance. Do not translate API prices into subscription cost or change models in
the LMS application. Check the live spawn tool, explicitly set model and effort,
and do not silently inherit Astra/high effort:

- `gpt-5.6-luna` / `medium`: narrow inventory, deterministic edit, bounded check,
  or explicit-criteria review.
- `gpt-5.6-terra` / `medium`: normal implementation within one defined module.
- `gpt-5.6-sol` / `high`: difficult bounded implementation/review justified by risk
  or observed failure; cross-module decisions remain root-owned.

If unavailable, report it and choose a supported equivalent only under owner
instructions. First distinguish weak specification, missing environment, defect,
and model limitation; repair the packet/procedure before escalation. Default to
fresh context for small or blind work; fork only when detailed current reasoning
cannot safely be summarized.

Use an ownership matrix for writable work. Exactly one writer owns each file, path,
database object, provider resource, or external mutation at a time. Root owns
integration files/conflicts, critical blockers, canonical final documentation,
governing `AGENTS.md`/`ERRORS.md`, commit, push, deployment, and production mutation.
Serialize shared-file work; a reviewer becomes a writer only after explicit transfer.

## Send a minimal packet

All Kamilya root/agent communication and every assignment are English. Send only:

```text
English only.
OBJECTIVE: one observable outcome.
PROJECT AND SCOPE: exact project; named files, paths, symbols, fixtures, or objects.
PROFILE: one defined worker profile.
ALLOWED ACTIONS / FORBIDDEN ACTIONS: exact reads, writes, checks, tools; prohibit
unrelated reads, secret discovery, external mutation, push, deploy, publication, and scope expansion unless explicitly allowed.
GOVERNING SOURCES: minimum relevant instructions, contracts, source, tests, fixtures.
DEPENDENCIES AND ASSUMPTIONS: root-established inputs and their evidence status.
EXIT GATE: root-review conditions, expected artifact, acceptance checks, invariants,
and stopping condition.
HANDOFF: result, changed, verified, blockers, next; READY means root review only.
```

Include baseline/revision when material; reference a versioned contract rather than
copying it. A 150–300-word packet is normally enough. Do not send history, secrets,
`.env` contents, credentials, raw PII, tenant payloads, contact data, unrelated logs,
or broad session context. Use safe paths, variable names, opaque IDs, counts, and
synthetic fixtures. Read named skills fully; retain mandatory project reads.

For source investigation, require the project’s Graphify workflow before broad
reading and confirm graph-derived findings in source/tests. Writers preserve dirty
work, use existing patterns, avoid unrelated refactors, and name proportionate
validation. Documentation writers may change only independently verified content.

## Stop safely and hand off

Default external access is none. An agent never infers authority from history,
memory, credentials, or provider access. After one failure, classify the layer and
change only a safe, assigned assumption/method. After two materially identical
failures, stop; do not guess credentials, paths, ports, accounts, environments, or
providers. For an authorization denial, do not seek alternate credentials or routes;
a second denial on the target escalates. If a required check is unavailable, return
`BLOCKED` with the exact dependency—never substitute an unapproved check or call an
edit `READY`.

Every worker returns only:

```text
result: READY FOR ROOT REVIEW | NOT READY | BLOCKED; observable outcome
changed: exact paths and mutations, or none
verified: exact checks/evidence pointers, or NOT VERIFIED
blockers: unresolved risks, missing check/authority, cleanup residue, or none
next: one required integration/correction/decision, or none
```

Keep routine handoffs near 150 words; no raw logs or stale progress. `READY` is not
completion. Root directly accepts only after confirming scope, artifact/output,
owned-path delta, evidence claims, proportionate checks, secret/PII/dependency safety,
cleanup, and the parent exit gate. Return a focused defect to the same owner when
useful; after two materially identical correction cycles, root decides integration.
Close completed agents after capture. Do not repeat unchanged passing checks without
a new risk, though mandatory gates still apply.

## Acceptance review and validation

The independent reviewer and root review four separate dimensions: **requirements**
(requested behavior, omissions, unrequested additions); **correctness** (affected
inputs, states, callers, and consumers); **standards** (mandatory project rule versus
preference); and **complexity** (unnecessary dependency, duplication, or speculative
flexibility). Complexity never substitutes for the first three. Findings state the
location, manifestation condition, impact, evidence, and severity.

Understand the changed flow and relevant callers before choosing reuse, a standard
library, or platform capability. Preserve needed interfaces, validation, transaction
boundaries, error handling, accessibility, provider isolation, and testability; one
implementation alone does not prove an abstraction unnecessary.

Test expected behavior independently from the implementation—by contract, manually
checked example, or oracle—using the existing test stack. Choose behavioral or
internal/DB evidence according to what proves the risk (for example transactions,
deduplication, or avoided provider calls). Run mandatory checks plus risk-proportionate
ones. Repeat/broaden checks only for a changed delta/baseline/environment, failure, or
new unresolved risk. Never claim a run, red/green state, browser pass, integration,
deployment, or runtime observation that did not occur.

## Learn without creating a parallel operation

For each accepted task, preserve in the existing task ledger: task ID/type, requested
and independently observed model/effort when available, elapsed time, first-pass
acceptance, correction rounds, root review/rework time, and exposed token counters
(unknown is not zero). Include root work. Daily analysis reads only new events and
comparable aggregates, retains failed outcomes, identifies up to three evidenced
patterns, and proposes one bounded measurable improvement. It creates no scheduler,
dashboard, automatic rule change, invented cost, or quota multiplier.

This is product-engineering routing, not commercial operations. Marketing work stays
with its owner. Root receives only actionable product evidence: affected journey,
evidence, desired behavior, acceptance, and urgency. A commercial report neither
creates a development task nor authorizes mutation.

For multi-worker planning, keep an internal ownership table plus root critical path,
conflicts, packets, review plan, approval gates, and cleanup. If delegation does not
materially help, record `KEEP LOCAL` and why.
