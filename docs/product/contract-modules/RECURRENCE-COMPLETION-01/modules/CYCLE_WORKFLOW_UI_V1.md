# Canonical cycle workflow UI V1

Status: Accepted

- Responsibility: on `/learning-cycles`, show latest/history occurrences,
  original/effective deadlines, deadline events and a reason-required override.
- Non-responsibilities: assignment-rule redesign, notification provider setup,
  certificate editing, source actuality decisions.
- Users: methodologist; tenant admin and learner do not receive this editor.
- Interface: only the versioned participant-deadline HTTP contract.
- States: loading, empty, ready, saving, recoverable error, terminal occurrence.
- Invariants: never imply that an override rewrites completion or a sent
  reminder; do not expose raw IDs as primary labels; RU/KK/EN parity; desktop
  and 375px mobile usable.
- Verification: focused RTL/helper tests, typecheck, lint, production build and
  browser critical journey.
- Write scope: learning-cycles page/helpers/locales/tests. Stop if a shared API
  contract or unrelated sidebar/navigation change is required.
