---
name: kamilya-orchestrator
description: Coordinate large multi-agent or cross-repository Kamilya epics with explicit ownership, dependencies, evidence provenance, and approval gates. Use when work spans multiple repositories, three or more agents, multiple external systems or approvals, or several sessions; do not use for routine single-scope edits.
---

# Kamilya Orchestrator

Create one compact coordination module for a large Kamilya epic. Its interface
is the task graph: stable node IDs, ownership, dependencies, exit gates,
evidence provenance, and exact approval gates. Keep agent transcripts, raw logs,
tool mechanics, and duplicated product documentation behind that interface.

## Choose the mode

- Use **bootstrap** once when adopting an existing, poorly mapped workstream, or
  after a material repository, environment, or ownership discontinuity.
- Use **epic-update** for later turns. Read the current epic plan and update only
  nodes whose state, evidence, dependency, owner, or approval changed.
- For a routine task in one scope, use the normal temporary plan rules from
  `AGENTS.md`; do not create a task graph.

Read [the task-graph template](references/task-graph-template.md) only when this
skill is actually activated for a qualifying epic.

## Canonical sources stay canonical

Do not create `docs/ai/` or parallel context, readiness, error, decision, or
handoff files. Use the existing sources:

- `PROJECT.md` for product boundaries;
- `docs/PROJECT-CONTEXT.md` for the current system and environment map;
- `docs/PRODUCTION_READINESS.md` for production evidence and release gates;
- `docs/PRODUCT_BACKLOG.md` for open product work;
- `ERRORS.md` for confirmed recurring failures and prevention;
- `docs/adr/` for durable decisions;
- `docs/CODEX_HANDOFF.md` for workstation and continuation handoff;
- `docs/plans/YYYY-MM-DD_<slug>.md` for the temporary epic task graph.

History belongs in Git. After completion, move only durable facts to the
canonical source and remove the temporary epic plan.

## Bootstrap mode

Perform a read-only inventory before assigning new implementation work:

1. Read the applicable `AGENTS.md` files and the canonical sources above.
2. Record every repository, exact checkout commit, dirty-worktree status,
   environment, external provider, and current release target in scope.
3. Inspect only discoverable current tasks. An absent task is `NOT DISCOVERED`,
   not proof that no separate user-owned task exists.
4. Preserve a valid existing owner. Send a focused follow-up to that task rather
   than silently replacing it.
5. Check each repository's Graphify graph separately. Record its built commit,
   freshness, exclusions, and extraction gaps.
6. Produce the ownership matrix and initial dependency graph using the template.

Bootstrap does not authorize implementation, deployment, account mutation,
spend, migration, credential discovery, or secret handling.

## Epic-update mode

1. Read the canonical sources and current epic plan, not closed transcripts or
   historical plans.
2. Inspect only agents and nodes related to the current dependency frontier.
3. Give each writable path or external operation one owner and one writer at a
   time. Reviewers are read-only unless ownership is explicitly transferred.
4. Parallelize only independent nodes with non-overlapping write and mutation
   scopes.
5. Update only changed node fields and decision-relevant evidence. Do not
   narrate unchanged status.
6. Verify an agent's artifacts and exit gate before marking its node `DONE`.

After two materially identical failed worker/reviewer cycles, return the node to
the root orchestrator with the failure classes and evidence. This stops blind
repetition by workers; it does not stop the root from choosing a new safe,
evidence-based diagnostic method within the original authority.

## Evidence contract

Label every material claim with one or more of:

- `GIT-DERIVED` — current checkout, diff, commit, or CI artifact;
- `RUNTIME-DERIVED` — direct application, database, worker, network, or UI
  observation;
- `OWNER-CONFIRMED` — explicit current instruction or factual confirmation;
- `PROVIDER-CONFIRMED` — persisted readback from an external provider;
- `GRAPH-DERIVED` — Graphify navigation or inferred relationship;
- `INFERRED` — reasoned conclusion not directly observed;
- `NOT VERIFIED` — evidence is missing or stale;
- `BLOCKED` — a named condition prevents the exit gate.

Use the evidence type appropriate to the claim. Current source establishes code
behaviour; deployed runtime establishes production behaviour; provider readback
establishes provider state. Never strengthen one into another. Agent reports,
memory, screenshots, plans, and Graphify output are navigation or evidence
inputs, not self-sufficient proof of current runtime state.

Store compact evidence pointers: path and line, commit, test command and result,
runtime request/readback ID, or provider execution ID. Never store secrets, raw
credentials, personal data, entire logs, or transient access tokens.

## Agent communication language

- Use English for every root-to-agent and agent-to-root message: assignment
  prompts, clarifications, progress updates, review findings, blockers,
  handoffs, and final reports.
- State this English-only requirement explicitly in every delegated task.
- If a subagent responds in another language, require it to resend the same
  content in English before accepting the handoff.
- User-facing communication follows the user's language unless the user
  requests otherwise.

## Graphify contract

- Query the existing graph before broad source exploration.
- Keep `Kamilya-NEW` and `kamilya-landing` Graphify outputs separate. Connect
  their work only in the task graph.
- Compare the graph's built commit with the current checkout and report dirty
  inputs or parser gaps.
- Treat Graphify as an architecture index, never as task state or runtime truth.
- Mark unverified graph-only conclusions `GRAPH-DERIVED`.
- After code changes, run the project-standard Graphify update and record its
  warnings without upgrading them into functional failures.

## Approval contract

An approval gate names the exact external mutation: target, objects, values,
limits, preservation requirements, and rollback/stop condition. General approval
for a parent workstream does not authorize child objects or a different external
system.

Before a gated mutation, re-read the exact approval and current target state.
After it, persist a deterministic readback. On ambiguity or scope drift, stop the
mutation, preserve the safe current state, and return the node to the owner.

## Completion

A node is `DONE` only when its exit gate and evidence contract are satisfied.
An epic is complete only when required nodes are done, accepted blocked nodes
name their external condition, cleanup/residual checks pass, and durable facts
are transferred to canonical documentation. Delete the temporary task graph
after that transfer; Git retains history.
