# WB-LESSON-CORRECTION-APPLICATION-DEV V1.4

Status: Accepted root-owned fixture correction, 2026-10-05.

Preserve D:19 checks, peak3, cleanup/public-neutrality true, failure
fk_workflow_access_credentials_wrong_state. Source0147 has the immediate unique
partial index uq_workflow_access_active_item(work_item_id) WHERE revoked_at IS
NULL. The probe copied an existing active credential and requested another active
one for the same item; it is not a valid FK-only insertion fixture. Do not drop,
weaken, defer or replace that index or any production rule.

The credential probe overrides token_hash and sets a fixed revoked_at timestamp,
so it is a valid historical credential while still referencing the same locked
work-item parent. Build the same11 probe definitions once; before first application
execute each via ordinary runtime context, require one inserted row and rollback.
This early fixture preflight must pass before the expensive race matrix. During
the held-parent batch all11 still require55P03; after release all11 plus the move
must insert/update one row and rollback. Reuse a single connection, never context
or transaction state, and preserve the maximum3 cap. No added persistent rows,
email, auth/key activation, product/migration/timeouts or public/provider change.

Failure SQLSTATE may follow max3 explicit cause or exception-context links, never
messages, SQL or parameters. New freeze/receipt E; preserve A/B/C/D. Fixture
preflight is a required extra check, not a substitute for held-parent proof.
Record actual monotonic driver elapsed seconds including cleanup/disposal; this
is a run duration, not a matched productivity, token, quota or cost comparison.
Independent review additionally requires unlock failure not to mask an earlier
probe/apply failure: always drain the task, then prioritize original probe, task,
finally unlock error. Public driver cleanup-seam regressions cover each outcome.
