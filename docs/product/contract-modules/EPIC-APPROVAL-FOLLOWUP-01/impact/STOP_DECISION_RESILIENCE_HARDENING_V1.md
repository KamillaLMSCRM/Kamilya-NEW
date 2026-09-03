# Stop decision: approval follow-up resilience hardening V1

## Trigger

Independent review found that the first implementation could strand a delivery
in `accepted`, consume a deadline without creating a delivery, rely only on
Python for secret-free content, expose same-tenant rows to a query missing its
recipient predicate, and render an old notification response after auth change.

## Root-owner decision

Production release stopped. The accepted business objective and roles remain
unchanged. Root owner approved a bounded invariant hardening packet:

- persisted five-minute claim lease and explicit terminal exhaustion;
- fail-closed deadline materialization;
- additive migration `0151` with safe context/path checks and recipient RLS;
- authenticated `app.user_id` transaction context;
- auth-identity keyed frontend state and unknown-kind non-actionability;
- executable DB-backed and rendered UI regression tests.

Already applied revision `0150` is preserved. No provider plan, billing,
recipient policy, PIN lifecycle or unrelated module is changed.

## Verification required before release resumes

Remote DEV must read back `0151 (head)` and pass tenant/user/trigger/unsafe-data
tests. Frontend rendered tests, full web suite/build, risk-based backend tests,
CI and post-change Graphify comparison must pass. Production remains blocked
until those gates and exact release-plane identities are available.
