# Assignment invitation preparation validation addendum V1

Status: Accepted by root for bounded local/synthetic DEV validation, 2026-10-01,
under owner's "продолжай". Extends the assignment execution and reload addenda;
predecessors remain immutable. Product owner: user. Integration/DEV writer: root.
Independent local acceptance: Test & Evidence Runner. Leaf source review only.

## Objective / interface / ownership

Prove that existing one-time assignment to an active student without a configured
login prepares activation on the exact existing identity, atomically with
enrollment, access policy, notification outbox and workbench receipt. This does
not activate an account, send an OTP/email, accept an invitation or issue a JWT.
No runtime application interface or business rule changes. The existing
`enroll_users` -> `prepare_user_invitation(reuse_valid=True)` interface remains
authoritative. `notify=false` must not prepare activation or a notification.

Owner allowed writes: owned gate script/tests, this contract, module index and
canonical plan/backlog/handoff/changelog/error evidence. No enrollment/invitation/
auth/worker/provider/config/migration changes. Only root may run the DEV gate.

## Exact synthetic DEV expansion / negative space

Reuse the canonical owner/runtime Supabase DEV URLs, non-bypass runtime role,
random validated `workbench_<12hex>` schema and exact cleanup procedure. Copy
definitions only for existing `user_invitations` and `tenant_settings` into the
owned schema in addition to the previously named tables; never copy rows, public
FKs, triggers or delivery functions. Synthetic student has status active and
is_active true but no password/Telegram/verified email login; use `.invalid` email.

Owned transaction search_path excludes public (`owned, pg_catalog`), so a missing
dependency fails instead of falling through to public data. Verify required
unqualified table resolution before fixture/application mutation. Accepted enqueue
body matching, fixed owned search_path, outbox ACL/FORCE RLS and no delivery/recovery
interfaces remain mandatory. Neighbor table clones are NOT production RLS/FK/
trigger equivalence; that gate stays open. Tokens remain only in ephemeral owned
database rows: never select, print or save activation URL/token/email payloads.

## Behavioral verification

- Preview has an access warning but creates no invitation/enrollment/outbox.
- Confirm then rollback leaves all these rows absent and plan ready/receipt null.
- Successful notify=true confirm prepares exactly one pending student invitation
  bound to the original user_id and invited_by, using synthetic tenant expiry;
  does not activate the account, create another user, deliver or increment attempts.
- A second course assignment to the same never-activated identity reuses the valid
  invitation; expired pending invitation is superseded on a later assignment.
- Replay of each succeeded plan returns stored receipt and no dispatch IDs or new
  invitation; owned GET returns the same receipt.
- notify=false for a different never-activated synthetic student creates assignment
  but no invitation/outbox. Existing activated-account/manual-overlap checks remain.

Focused database-free guard and invitation/enrollment neighbor tests, isolated real
PostgreSQL transactions, independent source review and exact frozen-candidate local
acceptance are required. No full-suite/build repeat without a changed runtime source.

## Stop / cleanup / retention / rollout

Missing table/function, wrong identity, source/live enqueue drift, unexpected public
resolution, token exposure, failed atomicity or new dependency stops the gate. Root
fixes only owned validation; business-source defect needs accepted impact expansion.
Drop only the exact generated owned schema, independently verify absence and public
revision/table inventory neutrality. Tokens disappear with schema cleanup; no broad
prune, public migration, tenant/customer/QA-stand mutation or billable resource.

Flags remain off. Persistent workbench retention values await the user's separate
choice; this addendum does not authorize automatic deletion of real plans/receipts.
Browser, full neighbor RLS/org interleavings, delivery and production stay gated.
