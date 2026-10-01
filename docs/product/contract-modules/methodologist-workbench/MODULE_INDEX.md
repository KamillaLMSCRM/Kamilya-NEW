# METHOD-WORKBENCH module index

Active epic: [EPIC V1](EPIC_V1.md), Draft overall.

| Module | Responsibility | Active mini-spec | Data owner / writer | Status |
|---|---|---|---|---|
| WORKBENCH | Untrusted intent → server-resolved plan → confirmation policy; later execution receipts | [WORKBENCH V1](modules/WORKBENCH_V1.md) | Workbench/root; in-memory only now | Accepted foundation only |
| SPEECH-INTAKE | Bounded authorized audio → editable transcript, no business execution | [SPEECH-INTAKE V1](modules/SPEECH_INTAKE_V1.md) | Speech/root; no storage now | Draft / benchmark gate |

Active shared contract: [COMMAND-PLAN V1](contracts/COMMAND_PLAN_V1.md).
Bounded local assignment integration:
[ASSIGNMENT-EXECUTION addendum V1](contracts/ASSIGNMENT_EXECUTION_ADDENDUM_V1.md).
Acceptance: [critical journeys](acceptance/CRITICAL_JOURNEYS_V1.md).
Execution sequence/progress: [plan](../../../plans/2026-10-01_ai-driven-methodologist.md).

Neither module is wired into HTTP, DB, queues or frontend by the foundation.
