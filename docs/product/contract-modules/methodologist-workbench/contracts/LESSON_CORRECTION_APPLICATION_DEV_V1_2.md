# WB-LESSON-CORRECTION-APPLICATION-DEV V1.2

Status: Accepted root-owned diagnostic successor, 2026-10-05.

Preserve failed runtime A, its frozen files, SQLSTATE55P03, cleanup and public
neutrality. Do not relax service timeouts, assertions or acceptance requirements.
Driver same-plan concurrency must drain both tasks before cleanup even when one
fails. Record only per-task completion/failure class and SQLSTATE, and a bounded
allowlist of application-owner source file/line pointers. Never record SQL text,
parameters, exception messages, fixture identities, credentials or row content.
Use a fresh frozen successor receipt for one isolated diagnostic run. Application
and migration source remain unchanged; a product fix requires its own impact
addendum after identifying the actual failing statement.
