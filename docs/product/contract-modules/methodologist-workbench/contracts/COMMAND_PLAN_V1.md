# COMMAND-PLAN V1 — frozen pure foundation contract

Status: Accepted for local foundation by root, 2026-10-01. Product authority:
owner's stepwise-work approval, not provider/data/production authority.
Changes require a versioned addendum/V2; keep V1. Parent epic remains Draft.

## Trust boundary and interface

`IntentCandidate` is untrusted model output: allowlisted action and nonempty
bounded instruction only. No actor, tenant, IDs, approval, SQL, provider or
execution control. The instruction may contain entity/date hints, but is never
executed or treated as a system instruction. All unknown fields are rejected.

`PlanSnapshot` is constructed ONLY by a future trusted server resolver, not
accepted from HTTP or LLM. It binds plan UUID, positive revision, authenticated
actor/tenant UUIDs, timezone-aware expiry, and **one** fully resolved operation:

- `create_course_draft`: versioned source references + generation instruction.
- `propose_course_edit`: exact course snapshot + instruction + source references.
- `publish_course`: exact course snapshot + fingerprint of ALL existing rule/
  assignment side effects (including canonical empty-effects digest).
- `assign_course`: exact course snapshot, canonical department UUID, audience
  version token, unique sorted explicit recipient UUIDs, aware deadline, notify
  boolean. Semantics are one-time current-members only, never a dynamic rule.

Object snapshots bind UUID and version token; token generation/ownership semantics
are future domain integration contracts, not arbitrary LLM labels. Lists are
immutable tuples; snapshots and confirmations forbid extras and are frozen.
Field/array lengths are bounded. Deadline must still be future at confirmation.

`plan_fingerprint(plan)` = SHA256 of canonical sorted-key JSON for the ENTIRE
snapshot. Contains actor/tenant/expiry/revision and all operation parameters.
Equivalent recipient order normalizes; duplicates reject. Changed instructions,
sources, course, rule effects, recipients, deadline or notification invalidate it.
This digest is an integrity comparison, **not a signature or authorization**.

`ConfirmationRequest`: plan_id + revision + fingerprint only. It refers to the
preview shown to the user. Final publish/assignment confirmation is a deliberate
UI button in V1, not a model assertion or a recognized word «да».

`evaluate_confirmation(plan, request, actor, current_fingerprint, now)` returns
an allow/deny enum without side effects. `actor` and `current_fingerprint` come
from trusted current server context, never client/model. Deny if role is not
active methodologist, tenant/actor mismatch, wrong plan/revision/digest, expired,
deadline passed, or current domain bindings differ. Require timezone-aware now.
Allow means only **pure confirmation checks passed**, NOT execution authorized,
expert review completed, entities owned, or action already performed.

## Obligations of future executor (not implemented by V1 foundation)

Persist plan with owner/tenant/expiry/status. Read it by server-bound identity;
atomically claim an unconsumed confirmed revision and recheck current snapshots,
membership, review/access/quota under domain transaction locks before mutation.
Idempotency key includes tenant/plan/revision/step; repeats return original receipt.
Stale revision cannot retry as success. Hash check alone cannot prevent TOCTOU.
Course publish idempotency keyed by course_id alone is insufficient for this seam.

Transient failure must distinguish uncommitted mutation, committed operation,
queued delivery, and completed delivery. Never replay committed generation or
enrollment creation just because a later notification failed. Side effects of
publication must be resolved and previewed or publication stops. Durable schema,
retention/recovery/migration and RLS require an accepted integration addendum.

## Negative-space contract and acceptance

No HTTP endpoint, ORM, network, provider, SQL, queue, auth-policy override, audio
handling or persistence. No change to existing domain workflows or runtime config.
Source module depends only on standard library/Pydantic. Focused public-seam tests
cover strict input, immutable/bounded plans, every fingerprint-bound field,
stale/expiry/deadline/role/tenant denial and allow without effects. This is a
contract fixture, not a live LLM/STT or end-to-end acceptance result.
