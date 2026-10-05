# WB-LESSON-CORRECTION-PREVIEW V1.1

Accepted local addendum, 2026-10-05, root/module owner; same owner-approved
preview scope. Preserves V1 except the terminal failure eligibility below.

An already admitted owned pending record may transition to failed after the
actor loses active methodologist eligibility. The UPDATE policy still requires
the exact tenant AND actor; only failed closure is allowed without eligibility.
Ready still requires current active eligibility. The immutable-state trigger,
column ACL and state CHECK forbid attaching a proposal/fingerprint to failure,
changing ownership/context or rewriting a terminal result. This is not a new
login, role union, impersonation or bypass path. The in-flight request can then
atomically close failure and refund its optimistic estimate once. A new request
and every public read continue to require ordinary active methodologist access.

No other V1 interface, billing, source, apply, retention or rollout rule changes.
Verify lost-role ready denial, owned failure/refund and foreign closure denial
in isolated DEV before runtime activation. Local fakes/static checks alone do
not prove this RLS behavior.
