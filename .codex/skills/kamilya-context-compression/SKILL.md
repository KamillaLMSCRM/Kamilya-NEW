---
name: kamilya-context-compression
description: Compress long Kamilya task or session context into a loss-audited continuation packet while preserving approvals, exact evidence identifiers, negative findings, blockers, and cleanup. Use before handoff or context rollover; do not treat the packet as evidence, delete raw history, persist secrets or PII, or authorize mutation.
---

# Kamilya Context Compression

Reduce active context without weakening the evidence or authorization contract.
The output is a navigation and continuation artifact, never independent proof of
source, provider, database, or runtime state.

## Boundaries

- Work only inside the explicitly named Kamilya project and task scope. Do not
  import facts, approvals, credentials, or artifacts from another project.
- This skill is read-only. It does not authorize file edits, deployment,
  provider changes, destructive actions, spend, production mutation, or
  retention/deletion of raw history.
- Redact secrets and personal data before summarizing. Keep only presence,
  classification, safe aggregate, or a canonical pointer when necessary.
- Do not claim that compression deletes platform session history. Raw-session
  retention and deletion remain separate owner or platform operations.

## Preserve exactly

Keep the following verbatim when present, except that secret and personal-data
values must always be redacted:

- the current owner's explicit approvals, denials, limits, stop conditions, and
  superseding instructions;
- named projects, repositories, environments, external systems, mutation
  targets, and scope exclusions;
- commit SHAs, provider run or deployment IDs, stable node IDs, migration
  revisions, release identities, evidence-artifact paths, database identities,
  and other decision-critical identifiers;
- unresolved command/error classes and the safe command text needed to resume;
- files changed, writer ownership, and the exact owned section or hunk when
  known;
- unfinished blockers, approval gates, dependency frontier, cleanup duties,
  residual artifacts, and rollback or stop conditions;
- recent unresolved tool output needed for the next decision;
- negative findings such as `not found in searched scope`, `test not run`,
  `provider inaccessible`, and `result not independently verified`.

Never preserve raw credentials, environment values, access tokens, contact
payloads, tenant records, unrelated mail, or unrestricted logs. Record their
existence only when it is decision-relevant.

## What may be summarized

Compress repetitive exploration, duplicate observations, completed
intermediate reasoning, superseded alternatives, and routine successful
commands. Retain a canonical path, command/result pointer, or exact identifier
when later work depends on it. Reduce long agent reports to their artifacts,
evidence labels, unresolved caveats, and root verification status.

When instructions conflict, the latest explicit owner instruction governs the
current action. Preserve an earlier instruction only when it remains relevant to
audit history, rollback, or understanding the supersession.

## Evidence and drift

Use only the project's permitted evidence labels:

- `GIT-DERIVED`
- `RUNTIME-DERIVED`
- `OWNER-CONFIRMED`
- `PROVIDER-CONFIRMED`
- `GRAPH-DERIVED`
- `INFERRED`
- `NOT VERIFIED`
- `BLOCKED`

Do not promote plans, memory, handoffs, screenshots, Graphify, agent reports,
or an earlier compression packet into current runtime/provider truth. Preserve
their original provenance and uncertainty. Re-read high-drift facts from the
canonical source before acting on them when access and authority permit.

## Build the continuation packet

Start with compact metadata:

- `captured_at`
- `project_scope`
- `source_window` or task/thread identifier when available
- `summarizer`
- `canonical_pointers`
- `known_omissions`
- `unresolved_uncertainty`

Then provide these sections:

1. `DECISIONS` - current decisions and supersessions.
2. `EVIDENCE` - material claims, exact labels, identifiers, and pointers.
3. `MUTATIONS` - completed changes, targets, writer, and readback status.
4. `BLOCKERS` - exact failure class and remaining exit gate.
5. `APPROVALS` - granted, denied, exhausted, and still-required approvals.
6. `CLEANUP` - completed and pending residual checks.
7. `NEXT` - the first genuinely open frontier and exact safe next actions.

Finish with `LOSS CHECK`:

- confirm that approvals and denials were preserved;
- confirm that exact decision-critical identifiers survived;
- list retained negative findings and unresolved tool evidence;
- confirm secret and personal-data redaction;
- confirm project-scope isolation;
- state explicitly that the packet is not evidence and does not grant new
  authority.

If the source context is too incomplete to satisfy the loss check, produce the
best safe packet, mark the affected item `NOT VERIFIED` or `BLOCKED`, and name
the exact missing source instead of inventing or silently dropping it.
