# Manager attention — active implementation index

Current status, 2026-09-05. The accepted EPIC/mini-specs remain design history;
this index tracks implementation and release evidence separately.

| Module | Active design | Implementation | Remaining acceptance |
|---|---|---|---|
| R1 | training-deadline-read-model_V1 + review addendum | local + Supabase DEV reporting verified | release/runtime UI readback |
| R2a | recurring-reminder-delivery_V1 + implementation, UI acceptance, login-schema and V2 SMTP addenda | backend, methodologist UI and corrected migration 0152; existing SMTP supported with one reservation; disabled by default | full legacy migration/RLS parity, deployed worker/timer/live-recipient acceptance |
| R2b | plan only | not implemented | overdue steps, assigned-owner escalation |
| R3–R5 | plan only | not implemented | manager actions, weak-topic analytics, onboarding |

Implementation records and agent acceptance are in
`../../plans/2026-09-05-manager-attention-implementation-plan.md`.
Canonical operational behavior: `../../PROJECT_INTERNAL_DOCUMENTATION.md`,
section R2a. No production authority is conveyed by this index.
