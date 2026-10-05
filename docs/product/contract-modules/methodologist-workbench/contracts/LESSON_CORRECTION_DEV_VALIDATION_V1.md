# WB-LESSON-CORRECTION-DEV-VALIDATION V1

Accepted root/module-owner validation impact contract, 2026-10-05.
Owner continuation authorizes the next isolated Supabase DEV gate, not a public
migration, provider activation, production release, apply endpoint or UI change.
Preserves PREVIEW V1/V1.1/V1.2/V1.3 and FOUNDATION V1.

## Scope and ownership

Root owns `scripts/ops/workbench_correction_dev_gate.py`, integration and actual
DEV execution. A narrow delegated writer may own only
`scripts/ops/workbench_correction_dev_checks.py`; root owns its acceptance.
Safety regressions live in `scripts/tests/test_workbench_correction_dev_gate.py`.
Documentation may update the workbench plan/index and append truthful evidence.
Reuse existing document-gate canonical config, context, migration seam, public
snapshot, runtime-role verification and evidence sanitizer without changing them.

Only the canonical .env path is read, never credential values in output. Both
owner/runtime URLs must validate against the canonical Supabase DEV project;
runtime must be nonsuperuser and non-BYPASSRLS. Existing approved resources only;
no billing, grants to global roles, new instances or public migrations.

## Disposable database contour

Generate a fresh `workbench_<12 lowercase hex>` schema internally. Reject every
other name. Search path is exactly owned schema plus pg_catalog, restored on each
runtime transaction including service commits. No public fallback.

Clone structure only from these exact public neighbors: tenants, users,
user_roles, documents, courses, modules, lessons, content_blocks, quizzes,
questions, quiz_choices, scorm_packages, course_approval_policies,
course_approval_revisions, tenant_settings, tenant_llm_usage. Never copy rows.
Reject sequence-dependent cloned defaults. Synthetic neighbor RLS is a fixture,
not proof of equivalence to public policies/triggers. Apply real migration 0176
with its existing Alembic Operations seam to the empty new table. This does not
claim a full empty-database migration-chain test.

Two synthetic tenants, owned/sibling/foreign methodologists and synthetic source
bytes are confined to that schema. All owner mutations qualify the owned schema;
no login/password/email/OTP/provider/queue/filesystem business-data mutations.
Runtime checks use actual lms_app credentials and real resolver, parser, quality,
budget, preview foundation and service transactions. Stub only external storage
bytes and configured LLM invocation. Real-model RU/KK semantics and real login
remain separate gates. Keep at most three DB connections simultaneously.

## Required checks and truthful result

Prove success/read, same-key replay without another invocation or charge,
concurrent same-key admission, digest collision, zero budget denial without a
committed claim, failed generation closure/refund, owned role-loss ready denial
and failed closure/refund, foreign actor/tenant and absent-context denial,
column ACL and immutable-state/time rejection. Prove non-target lesson/module/
block/quiz/source/approval changes invalidate pending/ready results; prove month
guard behavior without changing any public clock or configuration. Exercise
populated downgrade refusal, empty downgrade and re-upgrade.

Every check has a bounded timeout and neutral sanitized label. SQL exceptions
are reduced to class/SQLSTATE, never SQL, parameters, URLs or traceback. Preserve
each failed run receipt; a failure stops acceptance and requires an exact repair
and successor run, never weakening sanitization or pretending a stub is live AI.

Record pre/post public revision and table inventory. These prove public schema
neutrality, not arbitrary public data equivalence. Ownership starts only upon a
successful CREATE SCHEMA and is tied to its transaction: uncommitted creation
rolls back; committed owned creation must always be dropped, even if cloning or
migration fails. Never drop a preexisting/colliding schema. Cleanup requires a
fresh connection proving pg_namespace absence and unchanged public snapshot.
Cleanup or readback failure is FAIL regardless of other results.

PASS means isolated preview runtime validation only. It is not release GO:
apply atomicity/UI, crash reconciliation, semantic quality and deployment gates
remain mandatory before their respective activation.
