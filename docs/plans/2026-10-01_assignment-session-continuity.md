# Assignment session continuity execution plan

Owner-approved objective: restore the same personal-assignment student after reload,
release to production, and finish synthetic live acceptance. Approved by the product
owner on 2026-10-01 in the current chat. Root owns implementation/integration and
production; Test & Evidence Runner owns testing ledger; Release Runner reviews the
immutable packet. A cheap independent reviewer checks auth boundaries.

1. Freeze the bounded session contract in the versioned addendum below.
2. Execute RED regression, implement, focused GREEN and independent review.
3. Candidate full-risk tests, DEV isolation/acceptance, immutable CI/artifacts.
4. Canonical production controllers, exact runtime readback, synthetic browser
   reload/mobile/course/result acceptance. Preserve existing fixture history.
5. Transfer durable results to canonical readiness/handoff/error journal, remove
   this temporary plan. No billing/customer/DNS mutations or unrelated pruning.

Contract: ../product/contract-modules/assignment-session/SESSION_V1.md
Root write scope: named auth/access source/tests, contract, release and canonical docs.
Workers are leaf-only; no overlapping source writers. Unknown write outcomes must be
read back before retry. Failed hard gates block release, not the implementation loop.
