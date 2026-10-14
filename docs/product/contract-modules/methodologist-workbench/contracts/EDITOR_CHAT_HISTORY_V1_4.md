# Editor chat history V1.4 — exact public response oracle

Accepted by Root2026-10-14 before test-only correction. Amends V1.1's compatible
history_eligible response addition; runtime behavior and all prior guards unchanged.
DEV CI38519657164 directly reproduced the public integration failure: its exact
old JSON oracle omitted history_eligible=False for a scope refusal. Root owns
tests/integration/test_ai_assistant_public_policy.py's exact expected response,
adding that field while retaining full equality, status200 and no-provider assertion.
No subset assertion, skip, timeout change or DB/RBAC/migration change. Require
fresh exact-sha CI to execute this producer/consumer contract and existing gates.
Workstation local PostgreSQL remains prohibited; CI ephemeral DB contour unchanged.
