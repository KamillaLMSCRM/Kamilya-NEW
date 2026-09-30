# Continuation safety addendum V2

Status: Accepted. Approved by: Codex root, 2026-09-30.
Supersedes: CONTINUATION_ADDENDUM_V1.md.
Reason: source inspection found that native progress endpoints resolve the
canonical current occurrence even for an assignment-restricted identity.

All V1 safeguards remain active. In addition, an exact `enrollment_id` dashboard
read must compare its authorized occurrence with `current_enrollment` before
exposing continuation. A different or missing resolver result yields
`can_resume=false` and no resume URL. The read remains limited to the authorized
enrollment; it never returns the other grant. This adds at most one bounded lookup
because the input is a unique exact enrollment ID, not a per-course loop.

No progress, quiz, SCORM, course-player, access-window or credential-write contract
is changed. Assignment-specific access is not claimed to fix an occurrence-aware
player gap. Guidance tells the learner to consult their methodologist about how
to continue. An occurrence-aware player remains a separate implementation scope.

Verification: exact restricted read matched/mismatched/missing canonical result,
tenant/user-bound lookup, no other occurrence returned, no link on mismatch.
Rollback and release authority remain as defined in the epic.
