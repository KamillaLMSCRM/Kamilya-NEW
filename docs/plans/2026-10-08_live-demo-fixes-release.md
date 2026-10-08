# Live demo fixes — release 0.11.42

Owner request2026-10-08: fix course-PIN programme Start/404 mismatch and publish
with three existing demo corrections. Root owns shared contracts, source/Git,
release decision and live acceptance. Independent reviewer is read-only;
persistent Test Runner owns its exact test ledger append; Release Runner owns
only digest-bound CT137 bridge execution after Root acceptance.

1. Implement four scoped fixes from clean origin/master8e22e8a76ac76c487e9c4212896a786021c66f4b;
   preserve unrelated dirty worktrees. DONE.
2. Focused API/UI tests, mixed-course negatives, ordinary-account control,
   full web suite, quality/types/lint/build and independent review. DONE;
   exact CI37780905461 all7SUCCESS/4194PASS, full web942PASS.
3. Fresh production identities, rollback, schema0178, flags and capacity; exact
   source/tag/CI/artifacts; no-migration release evidence gate. DONE; exact42
   d415fd39f6bb41524d294b8528589ea337d49118, predeployGO independently accepted.
4. Protected API/threeworker rollout followed by CT137 bridge; preserve enabled
   flags and existing billing/resources, landing and retained QA. DONE;
   protected backend37781702081 SUCCESS; native bridgeRELEASE_OK, no cleanup.
5. Independent runtime readback and live PIN/own-course, quiz, mobile and audience
   regression; document exact outcomes, no reset of completed training.
   Root four-flow acceptance and independent runtime readback DONE;
   Test Runner ordinary-account browser controls DONE: retained completed student
   courses100% RU/KK, methodologist programme list/detail/audience1learner and
   reload persistence independently PASS. Mobile390x844 remains Root-owned proof;
   runner backend lacks that capability. Final acceptance is bounded to four fixes.

Stop on identity/hash drift, missing rollback, capacity/CI/test failure, unknown
mutation outcome or scope expansion. Retained QA83552ce6-8058-4561-abe3-cfbda14e030a
only for business smoke; no customer data, new tenants, email or credential reset.
Current authorised release scope does not include voice or antivirus.

Candidate41/7f3c489a is retained as BLOCKED, not deployed: fresh Next.js audit
and a test-only self-enrollment route error. Successor42 keeps the same bounded
product scope, updates Next.js15.5.27 and fixes the synthetic assignment test.
