# METHOD-WORKBENCH module index

Active epic: [EPIC V1](EPIC_V1.md), Draft overall.

| Module | Responsibility | Active mini-spec | Data owner / writer | Status |
|---|---|---|---|---|
| WORKBENCH | Untrusted intent → server-resolved plan → confirmation policy; bounded assignment receipts under addenda below | [WORKBENCH V1](modules/WORKBENCH_V1.md) | Workbench/root; pure foundation plus owned persistent assignment plans | Accepted foundation + assignment addenda; default-disabled |
| SPEECH-INTAKE | Bounded authorized audio → editable transcript, no business execution | [SPEECH-INTAKE V1](modules/SPEECH_INTAKE_V1.md) | Speech/root; no storage now | Draft / benchmark gate |

Active shared contract: [COMMAND-PLAN V1](contracts/COMMAND_PLAN_V1.md).
Bounded local assignment integration:
[ASSIGNMENT-EXECUTION addendum V1](contracts/ASSIGNMENT_EXECUTION_ADDENDUM_V1.md).
Owned-plan reload and isolated notification validation:
[ASSIGNMENT-RELOAD-VALIDATION addendum V1](contracts/ASSIGNMENT_RELOAD_VALIDATION_ADDENDUM_V1.md).
Never-activated learner preparation validation:
[ASSIGNMENT-INVITATION-VALIDATION addendum V1](contracts/ASSIGNMENT_INVITATION_VALIDATION_ADDENDUM_V1.md).
Organization interleavings and bounded metadata preflight:
[ASSIGNMENT-ORGANIZATION-ISOLATION addendum V1](contracts/ASSIGNMENT_ORGANIZATION_ISOLATION_VALIDATION_ADDENDUM_V1.md).
Invitation isolation remediation:
[INVITATION-TOKEN-RLS impact V1](contracts/INVITATION_TOKEN_RLS_IMPACT_ADDENDUM_V1.md).
Owner-confirmed metadata retention durations:
[RETENTION policy V1](contracts/RETENTION_POLICY_V1.md).
Bounded timestamp/cleanup implementation, local176 + isolated DEV64 accepted;
public activation/scheduling still gated:
[RETENTION implementation V1](contracts/RETENTION_IMPLEMENTATION_ADDENDUM_V1.md).
Acceptance: [critical journeys](acceptance/CRITICAL_JOURNEYS_V1.md).
Read-only catalog/source-body bindings, full neighbor equivalence NOT_VERIFIED:
[NEIGHBOR-CATALOG validation V1](contracts/NEIGHBOR_CATALOG_VALIDATION_ADDENDUM_V1.md).
Execution sequence/progress: [plan](../../../plans/2026-10-01_ai-driven-methodologist.md).

The original foundation remains pure. The accepted assignment addenda add
default-disabled API/UI and persistence, validated only in an owned isolated
Supabase DEV schema so far; public migration/deployment and voice remain gated.
