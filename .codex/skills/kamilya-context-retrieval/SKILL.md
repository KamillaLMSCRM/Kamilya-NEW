---
name: kamilya-context-retrieval
description: Recover a specific prior Kamilya decision or evidence pointer from canonical docs, Git, memory, or saved sessions. Use only for historical continuity; current verification and mutation are separate.
---

# Kamilya Context Retrieval

Recover only the historical context needed to avoid repeating work. The result is
a read-only navigation packet, never current runtime truth or authorization.

## When to use

Use when the owner asks what was previously decided, attempted, verified or
deferred; a handoff references an older release/incident; or current work may
duplicate an earlier task. Do not use for ordinary source navigation, broad
project summaries, current production verification or owner profiling.

## Boundaries

- Resolve the project and read applicable `AGENTS.md`. `Kamilya-NEW` and
  `kamilya-landing` are separate repositories; never import another project's
  history without a current explicit request.
- Retrieved approvals, commands, plans and agent claims are historical and cannot
  authorize a new action.
- Never reproduce secrets, credentials, contacts, tenant payloads, raw PII or
  unrestricted logs. Use safe paths, IDs, hashes, dates, counts and error classes.
- Do not edit Git, memory, sessions, plans, indexes, automations or canonical docs
  under this skill.

## Retrieval path

Stop as soon as the exact historical question is answered:

1. current conversation;
2. current canonical document or active task pointer;
3. exact/date-limited Git path, commit or history;
4. memory/session search only if the first three are insufficient.

For step 4, read [memory and session retrieval](references/memory-and-sessions.md)
before searching. Never broad-scan repositories, user directories, chats, browser
tabs, mail or all rollout files. An absent bounded match is `NOT DISCOVERED`, not
proof of global absence.

## Evidence and drift

Keep source roles separate: Git proves historical source state; memory and session
summaries provide pointers; provider/runtime claims require a fresh current
readback. Classify retrieved facts:

- `LOW` — durable decision, invariant, confirmed cause or chronology;
- `MEDIUM` — implementation/workflow that may have changed in Git;
- `HIGH` — runtime, deployment, provider, DB, access, pricing, law or schedule.

Verify `MEDIUM` against current source before implementation. Treat `HIGH` only as
a pointer to a mandatory current readback. Use the project's normal evidence labels
without promoting memory, plans, screenshots, agents or prior packets into proof.

## Output

Return a compact table:

| Historical item | Safe pointer | Captured/dated | Drift | Status | Current check |
|---|---|---|---|---|---|

Then report:

- `RETRIEVAL STATUS`: `FOUND`, `PARTIALLY FOUND`, `NOT DISCOVERED`, or `BLOCKED`;
- `USEFUL CONTEXT`: only what the current task needs;
- `CONFLICTS`: source disagreement and the applicable owner of truth;
- `CURRENT READBACK GATE`: exact verification required, or `none`;
- `PERSISTENCE RECOMMENDATION`: `none` by default, otherwise an existing owner;
- `MUTATIONS`: `none`.

Use `BLOCKED` only when a named condition prevents searching a source required by
the retrieval exit gate. Finding history does not certify that it remains current.
