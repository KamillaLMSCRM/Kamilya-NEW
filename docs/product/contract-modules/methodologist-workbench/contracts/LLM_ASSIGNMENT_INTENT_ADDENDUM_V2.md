# Free-text assignment intent addendum V2

Status: Accepted for bounded implementation, 2026-10-04.
Supersedes: LLM_ASSIGNMENT_INTENT_ADDENDUM_V1.md.
Reason: source review found inconsistent historical zero-budget semantics;
do not change an existing financial rule as part of interpretation integration.
Root/module owner: root; product owner: human owner; independent reviewers as V1.
Approved by: root within the owner's existing implementation authority.

All V1 interfaces/scopes/security/verification obligations remain active EXCEPT
the proposal to change explicit zero-budget behavior and its zero-budget test.
Preserve current helper zero/None ->5000 default exactly. The stale model comment
says zero disables the gate, while current callers/helper implement default;
neither source ambiguity grants a new financial policy. No settings values change.
Fix only the proven first-INSERT budget predicate, preserving generation/default
and existing-row behavior. Test a positive small configured limit exceeded on
first insertion and concurrent reservations, rather than inventing a new meaning
for zero. Existing intent reservation1cent/rate6/60/3/timeout30s remain V1.

Owned DEV profile binds copied0039/0042 policy and0019 invoker context helper;
each transaction owns search_path, no public fallthrough, exact cleanup/public
neutrality. Synthetic provider only. Previous plan ownership checked before
provider/admission, and controlled-failure refund rebinds server-owned tenant/user
after admission commit. No general source-equivalence/production acceptance claim.

Negative space explicitly includes financial zero-budget behavior, monthly settings,
trial/course quotas and provider order. Independent review tests both zero/default
compatibility and first-row prevention. A future financial semantics change needs
its own product decision, impact contract and affected-generation verification.
