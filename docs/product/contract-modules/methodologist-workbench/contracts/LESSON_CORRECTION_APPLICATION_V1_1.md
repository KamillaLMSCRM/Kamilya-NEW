# WB-LESSON-CORRECTION-APPLICATION V1.1

Status: Accepted local addendum, 2026-10-05. Root/module owner: root.
Preserves V1; independent review identified opposite approval-owner lock orders.

## Bounded concurrency correction

Existing cancellation/resend can lock a request before its revision, while
supersession locks revision before request. Application must not wait for an
approval row while holding another approval row. Before any business write,
prelock all owned policies, revisions, their requests/work items and the work
items' credentials with FOR UPDATE NOWAIT in deterministic ID order. Include
inactive rows as conservative coverage. Reacquisition by the existing owner
is then local/reentrant. Busy rows abort and roll back; no automatic retry or
lock-order changes to existing approval writers. Actual concurrent sessions,
immediate parent FKs and insert/move phantoms remain mandatory DEV gates.

Write impact: correction_application.py and focused tests only; no existing
approval/lesson/audit owner signature or implementation change.

## Commit uncertainty and historical outcomes

The V1 rollback guarantee applies before a successful database commit. If the
commit succeeds but its acknowledgment is lost, the response must not claim
success or assert rollback erased the committed write. Read the owned receipt
to reconcile; retry the same seal returns that receipt without another write.
One application audit/receipt is required; approval supersession may append its
own existing audit. Receipt review labels are historical required-review labels,
not a guarantee that later authorized edits/reviews never happened. No global
direct-editor concurrency certification is added.

Local acceptance: contention refusal before write, approval artifact invalidation,
unchanged history, precommit rollback and durable lost-ack receipt recovery.
Source/fake-DB proof is not a substitute for actual PostgreSQL race acceptance.
