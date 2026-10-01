# WORKBENCH mini-spec V1

## Identity

METHOD-WORKBENCH / WORKBENCH. Template V2, document V1, supersedes none.
Status: Accepted **pure foundation only**, 2026-10-01. Approved by root under
owner's stepwise local-development authority. Root/module owner: root; product
owner: human owner; reviewer: workbench_inventory read-only leaf.
Change control: proposal → root impact review → versioned addendum/V2; material
scope/billing/data/production changes need owner decision. Preserve V1.

## Responsibility / non-responsibilities [Core]

Concentrate the policy separating an AI suggestion from an exact human-confirmed
server plan. Do not own course/editor/assignment business rules, speech, auth,
provider configuration or execution. User-visible contribution later: precise
preview and reliable result; foundation has no new UI.

## External interface and inputs/outputs [Core]

[COMMAND-PLAN V1](../contracts/COMMAND_PLAN_V1.md) defines exact fields and
obligations. `IntentCandidate` → future resolver; `PlanSnapshot` → canonical
fingerprint; `ConfirmationRequest` + trusted actor/current snapshot/aware now →
`ConfirmationDecision`. One action per snapshot. Pure bounded local operations,
no network/performance dependencies. Inputs contain instructions, entity IDs and
recipient IDs (sensitive); never log payloads. Output is digest or safe reason.

## Data ownership / invariants [Core]

Workbenches own in-memory frozen plans; root writes source. No DB records now,
no migration or retention. Future persisted plans require tenant/owner/RLS/FORCE
RLS addendum before any write. Context originates from server, not model output.
Pydantic validation is NOT proof of tenant ownership. Active role only;
admin/superadmin capability union denied. Exact versions/recipients/deadline/
notifications bind confirmation. No runtime domain side effects.

## State machine / errors [Core]

| Current | Event | Result | Guard | Effect |
|---|---|---|---|---|
| Untrusted payload | Validate | Candidate / validation error | Allowed action, bounded instruction, no extras | None |
| Server plan | Fingerprint | Digest | Fully typed/bounded parameters | None |
| Preview | Confirmation check | Accepted / deny reason | Role/context/identity/revision/digests/expiry/deadline | None |

Validation errors are permanent until input changes; stale/expired plans require
new preview, not automatic retry. Role/context errors require correct session.
This pure evaluation is repeatable, not an idempotent executor or consumed token.

## Idempotency / concurrency [Extended]

Deterministic digest; repeated calls do not mutate anything. Future execution
claim/lock/receipt rules are in COMMAND-PLAN. Execution/replay safety is unproven
until transactional integration. No concurrency guarantee from hash alone.

## Dependencies / forbidden effects / impact [Extended]

Only Pydantic and Python standard library. Tests exercise the same public seam.
No adapters or registry needed. Forbidden: existing domain imports, tables,
providers, routes, queue tasks, credentials, network and billing actions.
Existing-module changes: Not applicable to foundation, only NEW module/tests;
future integration matrix in epic needs frozen addenda first.

## Security/privacy / observability [Core / Extended]

Reject extra authority fields. Frozen models contain immutable nested tuples.
Never authorize from candidate text. Server role/context fields are trusted-call
inputs only. No logging in foundation; later metrics only counts/reason codes,
sanitized correlation IDs, no text/audio/PII. Rate limits belong to future routes.

## Verification / implementation packet [Core]

| Scope | Evidence |
|---|---|
| Unit/interface/contract fixtures | `scripts/dev/run_api_pytest.ps1 tests/unit/test_methodologist_workbench_plan_contract.py -q` |
| Quality | Canonical Python Ruff/Mypy on owned module + quality baseline wrapper |
| DB/neighbor/integration | Not applicable to unwired pure foundation; mandatory when integrated |
| Negative space | Diff scope and dependency/AST graph check |

Read scope: this epic, existing schemas and source inventory. Write scope:
`app/modules/methodologist_workbench/{__init__,plan_contract}.py`, its owned unit
test, epic docs, temporary execution plan and backlog link. Forbidden all other
source/runtime/provider/DB writes. Stop if domain import/mutation needed. Handoff
five English fields with exact revision/tests/gaps. Expected map:
plan_contract → standard library/Pydantic; test → plan_contract.

## Rollout / Ready / Done [Extended / Core]

No runtime hook or dependency install: foundation rollback is reverting owned
files. Integration feature flag/persistence rollout requires addendum. Foundation
Ready: accepted narrow contract/write set/tests/owners and impact negative space.
Foundation Done: focused tests/quality/review/diff and expected dependencies pass.
Epic Done is separate: integrated critical journeys, exact release and live flow.
