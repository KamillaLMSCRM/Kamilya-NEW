# Workbench plan and receipt retention V1

Status: OWNER-CONFIRMED policy, 2026-10-01: owner selected exact proposal and said
"ок". Implementation/public application/scheduling remain NOT_IMPLEMENTED.
Root owns implementation and verification; users owns unrelated invitation data.

- Ready preview is executable for15minutes from creation (existing behavior).
- Delete unexecuted ready plans24hours AFTER their expires_at timestamp.
- Keep succeeded command receipts90days from successful execution, then delete
  their workbench-owned record. Execution time must be unambiguously recorded;
  do not use preview creation time as a substitute.
- Delete only workbench plan/snapshot/preview/receipt state, not enrollments,
  courses, progress, certificates, evidence, invitation or learning history.
- Snapshots contain recipient identifiers/labels; bounded retention prevents
  indefinite accumulation. No audio/document/transcript retention is approved.
- A removed/expired locator must be Not found/expired; confirming it must never
  reconstruct or execute a command. Required deletion/retry/duplicate negative
  regression and exact tenant/purge boundaries precede any cleanup activation.
- No schedule, production delete, public migration, bypass privilege, role/grant,
  worker/billing mutation or unbounded cleanup follows from this policy alone.
  Cleanup implementation needs its bounded contract, migration/ACL gates and
  exact rollout; feature flags remain OFF until those and other readiness gates.

This accepts durations, not a blanket data-retention/legal claim. Existing
learning-history retention policies and supported tenant purge remain unchanged.
