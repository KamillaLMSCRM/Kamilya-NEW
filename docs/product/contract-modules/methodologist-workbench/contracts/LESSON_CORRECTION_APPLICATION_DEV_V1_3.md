# WB-LESSON-CORRECTION-APPLICATION-DEV V1.3

Status: Accepted root-owned harness correction, 2026-10-05.

Preserve runtime C:19 checks passed, peak3, cleanup/public neutrality true, final
WorkbenchConflict while the test-owned blocking advisory pause outlived the
unchanged application3s lock limit. Product source remains exactly frozen C.

The owned BEFORE UPDATE test trigger must signal readiness with its own granted
transaction advisory key, then poll pg_try_advisory_xact_lock for the owner-held
release key with pg_sleep(0.05). This is a controlled fixture pause, not a blocking
lock acquisition or a wall-time-only proof. Observe the granted readiness key in
pg_locks before each contention batch; the real application still owns the actual
course/tree locks. Its unchanged15s statement and100s overall limits bound the
pause. Never alter service/database timeouts to keep the fixture alive.

Create the movable probe before pausing. During each rival transaction combine
ordinary tenant/user/false-superadmin context and unchanged250ms lock_timeout
into one parameter-bound set_config query; the runtime begin listener still
sets exactly the owned schema/pg_catalog on every transaction. No public context,
global setting or role grant. All probes must still fail55P03 while held and
execute successfully after release followed by rollback. If the original probe
fails, release and drain the apply task without masking that original failure.
Sanitized diagnostics may also extract SQLSTATE from a fixed exception cause;
no SQL/message/parameter payload. Use a new freeze/receipt D, never rewrite C.
