# WB-LESSON-CORRECTION-APPLICATION V1.2

Status: Accepted bounded contention outcome, 2026-10-05. Root/module owner: root.

Actual isolated DEV receipt B proves one same-plan caller committed while its
peer timed out acquiring the preview row at correction_service.py:145 (55P03).
The HTTP owner already mapped this database exception to generic409; no500 was
observed. Keep all locks, NOWAIT approval prelocks, transaction-local3s/15s and
overall100s limits unchanged. Do not retry internally or extend waiting time.

On PostgreSQL55P03 during apply, roll back that caller and expose the fixed
WorkbenchConflict code correction_application_busy through HTTP409/no-store.
No SQL text, parameters or identities are reflected. Other database failures
keep their existing handling. Busy means a conflicting operation holds a lock;
it does not prove that another application succeeded. Read the owned application
receipt to reconcile. An absent receipt is not success; the caller may explicitly
resubmit the same seal after the conflicting operation completes.

Concurrent same-plan proof must allow either identical successful receipts or
one completed apply plus this exact typed busy outcome, after draining both calls.
It must then read the durable receipt and resubmit the exact seal, proving the
same response and exactly one application audit/receipt without another write or
budget charge. An arbitrary exception, two busy calls or missing durable receipt
fails the gate. Deterministic DB-held preview contention is additionally required
to prove the typed busy outcome and unchanged state on the losing caller.

Write scope: correction_application.py, correction_router.py and their focused
public service/ASGI tests; DEV driver/checks/safety tests and plan/index/journal.
No existing domain writer, migration, provider, production or UI change.
