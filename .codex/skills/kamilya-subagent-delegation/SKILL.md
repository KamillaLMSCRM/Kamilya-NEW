---
name: kamilya-subagent-delegation
description: Design, dispatch, and review bounded Kamilya subagent work with minimal context, one-writer ownership, secret-safe isolation, and evidence-based handoff. Use when delegation or parallel review materially helps; do not use to offload the root's immediate critical blocker, grant production authority, or accept an agent report as proof.
---

# Kamilya Subagent Delegation

Delegate only work that can be bounded, isolated, and independently reviewed.
This skill refines the current `AGENTS.md`; it does not override project scope,
authority, evidence, secret, PII, Git, Graphify, testing, or approval rules.

## Decide whether to delegate

Before spawning an agent, split the current task into:

- the immediate critical path the root can advance now;
- independent sidecars that materially advance the objective;
- optional work that does not justify context, coordination, or review cost.

Delegate when the subtask is concrete, self-contained, and independently useful,
for example:

- bounded inventory or comparison;
- variants of copy or formatting;
- focused source or documentation review;
- implementation in a disjoint writable path;
- a realistic opponent/reviewer pass;
- repeatable low-risk classification;
- an isolated synthetic behavioral evaluation.

Keep work at the root when:

- the very next action depends on the result and root can do it directly;
- the task is the critical integration blocker;
- authority, target, or data boundary is ambiguous;
- the work requires broad secrets, production access, or owner judgment;
- delegation would duplicate work already in progress;
- review cost is comparable to doing the bounded task once.

Do not create agents merely to appear parallel or thorough.

## Agent profiles

Choose the narrowest profile that can complete the subtask.

### `READ_ONLY_WORKER`

- May inspect only named files, sources, fixtures, or synthetic inputs.
- May return findings, classification, plan, or draft text in its report.
- Must not edit, test, install, use external systems, or create artifacts unless the
  assignment explicitly includes one of those local actions.

### `BOUNDED_WRITER`

- Owns an explicit non-overlapping file/path set.
- May use `apply_patch` only within that set.
- May run only the checks named in the assignment.
- Must list every changed path and must not commit, push, deploy, publish, or mutate
  external systems.

### `INDEPENDENT_REVIEWER`

- Reads the completed artifact and minimum governing rules.
- Reports findings ordered by severity and a clear readiness verdict.
- Is read-only and must not silently fix the writer's work.
- Must evaluate authority, scope, evidence, security, data, and exit-gate behavior,
  not merely wording or style.

### `SYNTHETIC_EVALUATOR`

- Uses isolated synthetic fixtures and no real PII or tenant payloads.
- Should start without prior conclusions or expected answers when blind behavior is
  being evaluated.
- Must not use network, providers, production, databases, or unrelated files unless
  a separate exact read-only evaluation explicitly requires them.

Do not combine writer and final independent reviewer roles for the same artifact.

## Model and context choice

- Prefer an affordable model for bounded, low-risk, repetitive, formatting,
  inventory, and synthetic-evaluation work.
- Use a stronger model when the subtask itself contains architecture, security,
  legal interpretation, ambiguous product judgment, or complex integration logic.
- Do not wait for a specific cheap model when an equivalent bounded option exists.
- Default to a fresh context for blind evaluation, cross-project isolation, and
  tasks that need only a small packet.
- Fork prior context only when the subtask genuinely depends on detailed current
  reasoning that cannot be safely summarized. A fork also carries stale assumptions,
  irrelevant scope, and potentially sensitive context, so it is not the default.

Internal root-to-agent and agent-to-root communication for Kamilya is English. State
that requirement in every assignment. Owner-facing communication remains in the
owner's language unless requested otherwise.

## Minimal context packet

Pass only what the worker needs. A complete assignment should contain:

```text
English only.

OBJECTIVE:
One observable outcome.

PROJECT AND SCOPE:
Exact repository/project and named files, paths, symbols, fixtures, or provider
objects. State whether adjacent projects are forbidden.

PROFILE:
READ_ONLY_WORKER | BOUNDED_WRITER | INDEPENDENT_REVIEWER | SYNTHETIC_EVALUATOR

ALLOWED ACTIONS:
Exact reads, writes, tests, tools, or synthetic inputs.

FORBIDDEN ACTIONS:
At minimum: unrelated reads, secret discovery, external mutation, push, deploy,
publication, and scope expansion unless specifically allowed.

GOVERNING SOURCES:
Only the relevant AGENTS.md, ERRORS.md entries, skill, plan node, source, tests, or
fixtures. Do not send the entire project history.

DEPENDENCIES AND ASSUMPTIONS:
Inputs already established by the root, each with status or evidence role.

EXIT GATE:
Concrete conditions that make the subtask ready for root review.

HANDOFF:
Required output fields and explicit readiness verdict.
```

Do not include secret values, `.env` content, tokens, credentials, raw PII, tenant
payloads, contact data, unrelated logs, or broad session history. Give variable
names, safe paths, opaque IDs, counts, statuses, and synthetic fixtures instead.

## Ownership and parallelism

Build an ownership matrix before dispatching writable work:

| Scope/resource | Writer | Reviewers | Mutation type | Dependencies |
|---|---|---|---|---|

Rules:

1. Exactly one writer owns each file, path, database object, provider resource, or
   external mutation at a time.
2. Parallel writers must have disjoint write sets and independent dependencies.
3. A reviewer does not become a writer unless ownership is explicitly transferred.
4. The root owns integration files, conflicts, critical blockers, canonical final
   documentation, governing `AGENTS.md` files, `ERRORS.md`, commit, push,
   deployment, and production mutations.
5. If two useful tasks need the same file, serialize them or let one writer perform
   both changes and use the second agent as read-only reviewer.
6. A task graph or plan records ownership for large epics; do not create a second
   parallel status source.

## Code and documentation work

For code investigation, the assignment must require the project's Graphify workflow
before broad source reading and require findings to be confirmed in source/tests.
Graph output remains `GRAPH-DERIVED`.

For a `BOUNDED_WRITER`:

- identify every writable path before dispatch;
- preserve the dirty worktree and unrelated changes;
- use existing patterns and domain boundaries;
- prohibit unrelated refactor;
- name proportionate validation if validation is part of the delegated scope;
- instruct the worker not to push, deploy, or update canonical project status;
- make the root the final owner of `ERRORS.md` unless a unique section was explicitly
  assigned and the root will reconcile it.

For documentation, an agent report or old plan must not rewrite project truth. The
writer may patch only independently verified content supplied or confirmed by root.

## External systems and production

Default delegated external access is none. A cheap or isolated worker should not
receive credentials or production routes merely because it can perform read-only
work.

If an external read-only task is genuinely delegated, name:

- exact provider/system;
- exact object or endpoint;
- canonical access path;
- safe output fields;
- prohibited payloads;
- token handling method;
- stopping condition;
- required evidence label.

Subagents do not perform external, destructive, costly, production-mutating, or
scope-expanding actions unless the root transfers an exact current approval gate.
General workstream approval is not enough. A subagent never infers authority from a
historical message, memory, plan, credential presence, or provider access.

## Leaf-only default

Subagents are leaf workers by default and must not spawn descendants. Nested
delegation adds hidden context, unclear ownership, extra cost, and review gaps.

Permit nested delegation only when the root explicitly defines:

- why the first-level agent must coordinate rather than the root;
- maximum depth and number of descendants;
- disjoint scopes;
- inherited authority and data boundaries;
- how every child handoff reaches the root;
- who closes agents and cleans temporary artifacts.

Without that contract, descendant creation is forbidden.

## Failure and escalation

After one failure, classify the layer and change only a safe assumption or method
within the assignment. After two materially identical failures, the worker stops and
returns to root; it must not continue credential, path, port, account, environment,
or provider guessing.

Failures are materially identical when they concern the same target and evidence
layer, return the same error class, and no new permitted evidence or authority
changes the next attempt. For `AUTHORIZATION_DENIED`, do not seek alternate
credentials, historical `.env` files, browser history, accounts, routes, or
providers after the first denial. The only safe method change is local
classification or an explicitly authorized diagnostic; a second denial on the
same target triggers escalation.

If a named required check depends on an unavailable runtime, provider, tool, or
authority, return `BLOCKED` with that exact dependency. Do not substitute an
unapproved check or report `READY` merely because the edit was produced.

The escalation packet contains only:

```text
CURRENT STATUS:
EXACT TARGET:
ATTEMPTS AND ERROR CLASSES:
WHAT WAS RULED OUT:
AUTHORITY OR DECISION REQUIRED:
SAFE DEFAULT WHILE WAITING:
TEMPORARY ARTIFACTS REQUIRING CLEANUP:
```

The two-failure rule stops blind worker repetition. It does not prevent the root
from selecting a new safe evidence-based method inside the original authority.

## Handoff contract

Every worker returns:

```text
STATUS: READY | NOT READY | BLOCKED
READINESS MEANING: READY FOR ROOT REVIEW | NOT READY | BLOCKED
DESCENDANT MODE: LEAF; NO DESCENDANTS | exact root-approved nested contract
OBJECTIVE RESULT:
SCOPE ACTUALLY USED:
FILES CHANGED: none or exact paths
CHECKS RUN: none or exact commands/results
EVIDENCE: safe pointers and permitted labels
UNRESOLVED RISKS:
DEPENDENCY OR APPROVAL GATE:
CLEANUP: completed, none, or exact residuals
MUTATIONS: explicit list, normally none
```

Do not accept vague statements such as "done", "looks good", "tests pass", or
"production is healthy" without exact scope and evidence.

## Root review and integration

An agent's `READY` verdict means ready for root review, not project completion.
Before adopting the result, the root checks:

1. the worker stayed in project and data scope;
2. the actual artifact or safe output exists;
3. only owned paths changed;
4. claims match direct source/test/provider/runtime evidence as appropriate;
5. tests/checks are proportionate and actually ran when required;
6. no secret, PII, payload, unsafe log, or unexpected dependency was introduced;
7. cleanup and residual checks are complete;
8. the parent node's exit gate is satisfied.

If review finds a defect, return a focused correction to the same owner when context
remains useful. After two materially identical writer/reviewer correction cycles,
return the integration decision to root rather than looping agents.

Close completed agents after their outputs are captured so stale workers do not
retain concurrency, ownership, or context.

## Output contract for delegation planning

When this skill is used to design delegation, return:

| Subtask | Profile | Model class | Read scope | Write/mutation scope | Dependencies | Exit gate |
|---|---|---|---|---|---|---|

Then provide:

- `ROOT CRITICAL PATH`: work the root keeps now;
- `OWNERSHIP CONFLICTS`: none or exact resources requiring serialization;
- `CONTEXT PACKETS`: one bounded assignment per agent;
- `REVIEW PLAN`: who reviews what and using which evidence;
- `APPROVAL GATES`: exact external/mutation approvals, normally none for local
  read-only delegation;
- `CLEANUP`: agent closure and temporary artifact plan.

If delegation does not materially help, say `KEEP LOCAL` and explain the coordination
cost or critical-path reason. Do not spawn an agent merely because this skill was
loaded.
