# Manager attention — active implementation index

Current status, 2026-09-24. The accepted EPIC/mini-specs remain design history;
this index tracks implementation and release evidence separately.

| Module | Active design | Implementation | Remaining acceptance |
|---|---|---|---|
| R1 | training-deadline-read-model_V1 + review addendum | local + Supabase DEV reporting verified | release/runtime UI readback |
| R2a | recurring-reminder-delivery_V1 + implementation, UI acceptance, login-schema and V2 SMTP addenda | backend, methodologist UI and corrected migration 0152; existing SMTP supported with one reservation; disabled by default | full legacy migration/RLS parity, deployed worker/timer/live-recipient acceptance |
| R2b | plan only | not implemented | overdue steps, assigned-owner escalation |
| R3 action center | `modules/learning-action-center_V1.md` | local API/UI complete; disposable Supabase DEV migration and RLS acceptance passed | deployed browser and release acceptance |
| R4 weak-topic analytics | Learning Insights V1 + `modules/learning-action-center_V1.md` | immutable analytics, privacy threshold and current-occurrence isolation locally accepted | deployed browser and release acceptance |
| R5 onboarding | plan only | not implemented | onboarding slice |

Implementation records and agent acceptance are in
`../../plans/2026-09-05-manager-attention-implementation-plan.md`.
Canonical operational behavior: `../../PROJECT_INTERNAL_DOCUMENTATION.md`,
section R2a. No production authority is conveyed by this index.
