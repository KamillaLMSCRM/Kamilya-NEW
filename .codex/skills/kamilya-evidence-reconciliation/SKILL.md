---
name: kamilya-evidence-reconciliation
description: Reconcile Kamilya Git, CI, provider, deployment, database, backup, and runtime claims through exact read-only evidence. Use for release readback, production verification, security sign-off evidence, or conflicting handoffs; do not use to deploy, mutate providers, query tenant payloads, or authorize remediation.
---

# Kamilya Evidence Reconciliation

Establish what is currently proved without rerunning completed work or turning an
access gap into a claim about production. This skill is read-only by default and
never grants mutation authority.

## Preconditions

1. Resolve the absolute repository and environment in scope. Kamilya LMS defaults
   to `Kamilya-NEW`; the public landing uses the separate `kamilya-landing` repo.
2. Read the applicable `AGENTS.md` and relevant `ERRORS.md` entries. Before any
   external readback, use `docs/PROJECT-CONTEXT.md` and
   `docs/VPS_CONNECTION_GUIDE.md` as the access and topology map.
3. Record branch, exact checkout commit, upstream, and dirty/untracked state.
   Preserve unrelated work. A dirty checkout does not invalidate evidence for a
   different already-deployed exact SHA.
4. Start from exact claims and identifiers supplied by the owner or current task:
   commit SHA, CI run, provider deployment, release identity, migration revision,
   evidence artifact, time window, and environment. Do not broad-scan for unnamed
   alternatives.
5. Use Graphify only to navigate code relationships. Verify behavior in source,
   tests, migrations, provider readback, or runtime as appropriate.

## Evidence contract

Use only these labels:

- `GIT-DERIVED`: current checkout, commit, diff, ancestry, or remote Git-object
  reachability.
- `RUNTIME-DERIVED`: direct application, database, worker, network, or UI observation.
- `OWNER-CONFIRMED`: explicit current owner instruction or factual confirmation.
- `PROVIDER-CONFIRMED`: persisted CI run/artifact, deployment, or other readback
  from a named external provider.
- `GRAPH-DERIVED`: Graphify navigation or inferred relationship only.
- `INFERRED`: reasoned conclusion not directly observed.
- `NOT VERIFIED`: evidence is missing, stale, inaccessible, or not independently read.
- `BLOCKED`: a named condition prevents the required exit gate.

Use `BLOCKED` for a claim only when a named current condition prevents obtaining
evidence required by that claim's exit gate, such as `AUTHORIZATION_DENIED`, an
unavailable canonical route, or a missing required tool. Use `NOT VERIFIED` when
evidence is merely absent, stale, unsupported, or not independently read and no
concrete preventing condition has been established.

Never use `SOURCE-DERIVED`. Plans, screenshots, memory, prior chats, agent reports,
and historical handoffs are inputs, not sufficient current evidence. An unavailable
path is `NOT VERIFIED` or `BLOCKED`; it is not evidence that the remote object or
production proof does not exist.

## Readback order

Use the cheapest authoritative layer that can prove each claim. Stop when the claim
is proved; do not rerun a release, migration, restore, backup, RLS test, deployment,
or pentest merely to recreate valid evidence.

1. **Git:** prove exact commit existence, metadata, ancestry/reachability, branch or
   tag relation, and remote identity without changing the checkout.
2. **CI:** read the exact run and relevant jobs from the named CI provider and
   label the readback `PROVIDER-CONFIRMED`. Distinguish run success from the
   specific test or security gate required by the claim.
3. **Public runtime:** read health and immutable release/environment identity. HTTP
   success alone does not prove the expected executable revision.
4. **Provider:** read the exact deployment/project/service identity and status using
   token-safe APIs or an existing authenticated session. Provider status does not
   prove database revision or business behavior.
5. **Private runtime:** use only the canonical route. For KZ this is local to proxy
   to WireGuard to VM126; CT125 owns PostgreSQL 17, pgvector, and database backups.
   The proxy is transit infrastructure, not the application or database host.
6. **Database:** first prove target environment, host contour, database identity,
   effective runtime role, migration revision, and RLS posture. Then run only the
   minimum SELECT-only metadata or PII-free aggregate required by the claim. Never
   substitute Supabase dev/demo evidence for KZ production.
7. **Artifacts:** inspect only the exact named path and required sanitized content,
   verify signatures or hashes with the documented public material, and separately
   verify cleanup or residual absence when that is part of the exit gate. Output
   only safe metadata, hashes, signature status, timestamps, counts, and error
   classes; never reproduce payload content.

For every claim, keep the layers separate. Source proves intended behavior; CI
proves a tested revision; provider readback proves provider state; runtime proves
deployed behavior; database readback proves only the identified database contour.

Decompose compound statements such as "the release is complete" into the smallest
decision-relevant claims: exact Git object, required CI jobs, provider deployment,
public runtime identity, private worker identity, migration/database state, and
cleanup when each is part of the exit gate. Verify and label every component
separately; one successful layer cannot close the compound statement.

## Secret and data boundary

- Load only current authorized `.env` values into process memory when required.
- Never place secret values in command arguments, URLs, process lists, shell
  history, Markdown, files, logs, or tool output.
- Print only safe identifiers, counts, statuses, timestamps, revisions, hashes,
  error classes, and masked references.
- Do not output tenant payloads, contact fields, email addresses, phone numbers,
  request bodies, raw application logs, query rows, or credentials.
- Database evidence under this skill is metadata or aggregate-only. Separate owner
  approval may authorize an exact named disposable synthetic operation outside this
  skill, but never authorizes output of payloads, contact data, secrets, or raw rows.
- Do not inspect unrelated mail, browser data, repositories, providers, databases,
  or tenants.

## Failure handling

Classify the failing layer precisely: local tool, DNS/network, authentication,
authorization, route, provider API, guest access, database identity, query, or
artifact verification. Change method only within the existing authority boundary.

After two materially identical access failures by a delegated worker, return the
node to the root with target, attempts, error classes, required authority, and safe
default. Do not guess credentials, enumerate old `.env` files, switch projects, use
console/noVNC instead of healthy canonical SSH, or weaken the evidence requirement.

## Mutation boundary

This skill may perform read-only commands and produce a report. It must not:

- edit a task graph, canonical document, source file, or evidence artifact;
- acknowledge or delete remote events;
- submit forms or create synthetic records;
- deploy, restart, roll back, migrate, restore, back up, rotate, or delete;
- change DNS, firewall, network, provider, Ads, GTM, budget, routing, or credentials;
- convert a proposed remediation into an executed action.

If a verified result makes a local documentation reconciliation appropriate, return
the exact proposed file and hunk to the root. The root performs a separate reviewed
`apply_patch`. For any external, destructive, costly, production-mutating, or
scope-expanding operation, return an exact approval gate with target, objects,
values, preservation requirements, stop condition, and rollback.

## Output

Return a compact table with one row per claim:

| Claim | Required evidence | Named layer/provider and actual readback | Label | State or exact gap |
|---|---|---|---|---|

Then report:

- `CURRENT STATUS`: `VERIFIED`, `PARTIALLY VERIFIED`, or `BLOCKED`.
- `DEPENDENCY FRONTIER`: first genuinely unclosed evidence gate.
- `COMPLETED EVIDENCE`: exact safe pointers; no raw logs or secrets.
- `NEXT SAFE ACTION`: the minimum read-only action, if one remains.
- `APPROVAL GATE`: only if the next action is outside read-only authority.
- `MUTATIONS`: explicitly state that none were performed under this skill.

Choose the overall status independently from per-claim labels:

- `VERIFIED`: every in-scope claim has the required direct evidence and no
  decision-relevant conflict remains.
- `PARTIALLY VERIFIED`: at least one decision-relevant claim is independently
  verified, while another is `NOT VERIFIED`, `BLOCKED`, stale, or conflicts with
  a different evidence layer. Name the first unresolved frontier.
- `BLOCKED`: a named condition prevents reconciliation from independently
  verifying any decision-relevant in-scope claim. Do not use this overall status
  merely because one remaining claim or the final GO/NO-GO gate is blocked.

A per-claim `BLOCKED` label therefore does not automatically make the overall
status `BLOCKED` when other claims have been verified.

Completion requires every in-scope claim to be independently verified or assigned
one exact `NOT VERIFIED`/`BLOCKED` gap. Do not strengthen a partial result into
GO, production readiness, security sign-off, or absence of data.
